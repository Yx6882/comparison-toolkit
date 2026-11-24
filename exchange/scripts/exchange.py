#!/usr/bin/env python3
"""exchange — 物物等值换算：一斤铜换多少斤铝，多少钱换多少度电。

    python scripts/exchange.py fetch
    python scripts/exchange.py convert --from 铜 --to 铝 --quantity 1 --unit 斤
    python scripts/exchange.py list

严谨性约定（这是本工具的全部价值）：
  1. 每个价格都带来源、抓取时间、当日高低区间，不存单点
  2. 结论给区间，不给一个数
  3. 数据过期 / 只有单点 / 未计入交易成本时，表格里逐行写「⚠ 需人工核对」
  4. 计算过程全部打印，允许你手算复核
  5. 明确区分「期货价」「现货价」「实物成交价」，不混用
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "prices.json"
SINA = "https://hq.sinajs.cn/list={symbols}"
EASTMONEY = "https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f58,f60"

# 上期所/大商所连续合约代码 -> (品种名, 东方财富 secid)；均为 元/吨
SYMBOLS: dict[str, tuple[str, str]] = {
    "nf_CU0": ("铜", "113.CUM"),
    "nf_AL0": ("铝", "113.ALM"),
    "nf_ZN0": ("锌", "113.ZNM"),
    "nf_PB0": ("铅", "113.PBM"),
    "nf_NI0": ("镍", "113.NIM"),
    "nf_RB0": ("螺纹钢", "113.RBM"),
    "nf_C0": ("玉米", "114.CM"),
    "nf_M0": ("豆粕", "114.MM"),
}

CROSS_OK = 0.5      # 两源偏差 ≤0.5% 视为一致
CROSS_WARN = 2.0    # 0.5%–2% 提示标的差异；>2% 视为疑似冲突

UNIT_PER_TON = {"吨": 1, "公斤": 1000, "kg": 1000, "千克": 1000, "斤": 2000, "克": 1_000_000}

STALE_HOURS = 12  # 期货行情用日内数据，超过 12 小时就提示重抓


@dataclasses.dataclass
class Quote:
    name: str
    symbol: str
    market: str
    last: float
    low: float
    high: float
    prev_settle: float | None
    as_of: str
    fetched_at: str
    source: str = "新浪财经期货实时行情"
    confidence: str = "高（交易所连续合约）"
    note: str = ""
    cross: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_quotes() -> dict[str, Any]:
    url = SINA.format(symbols=",".join(SYMBOLS))
    request = urllib.request.Request(
        url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("gbk", errors="replace")

    quotes: list[Quote] = []
    for line in raw.splitlines():
        match = re.search(r"hq_str_(nf_[A-Z0-9]+)=\"([^\"]*)\"", line)
        if not match:
            continue
        symbol, payload = match.group(1), match.group(2)
        fields = payload.split(",")
        if len(fields) < 18 or not fields[8]:
            continue
        name = SYMBOLS.get(symbol, (fields[0], ""))[0]
        try:
            last = float(fields[8])
            high = float(fields[3])
            low = float(fields[4])
            prev_settle = float(fields[10]) if fields[10] not in {"", "0.000"} else None
        except ValueError:
            continue
        if last <= 0:
            continue
        quotes.append(
            Quote(
                name=name,
                symbol=symbol,
                market=(fields[0] if fields[0].startswith(fields[15]) else f"{fields[15]}{fields[0]}")
                if len(fields) > 15 and fields[15]
                else fields[0],
                last=last,
                low=low or last,
                high=high or last,
                prev_settle=prev_settle,
                as_of=fields[17] if len(fields) > 17 else "",
                fetched_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                note="期货连续合约价，不等于实物成交价（有升贴水）",
            )
        )

    if not quotes:
        raise SystemExit("没有解析到任何行情，可能是接口变了或网络不通")

    # ---- 第二来源：东方财富（主连合约）----
    eastmoney = fetch_eastmoney()
    for quote in quotes:
        cross = eastmoney.get(quote.name)
        if not cross or not cross.get("price"):
            continue
        spread = abs(quote.last - cross["price"]) / quote.last * 100 if quote.last else 0.0
        quote.cross = {
            "source": "东方财富",
            "price": cross["price"],
            "market": cross.get("market", ""),
            "prev": cross.get("prev"),
            "spread_pct": round(spread, 4),
        }
        quote.note = "新浪为连续合约、东财为主连合约，两者口径略有差异"

    payload = {
        "meta": {
            "fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": "新浪财经 hq.sinajs.cn（主源）+ 东方财富 push2（交叉验证）",
            "unit": "元/吨",
            "cross_ok": CROSS_OK,
            "cross_warn": CROSS_WARN,
            "warning": "期货价≠现货成交价；实物交易还有升贴水、加工费、运费、成色折价",
        },
        "items": {quote.name: dataclasses.asdict(quote) for quote in quotes},
    }
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def fetch_eastmoney() -> dict[str, dict[str, Any]]:
    """Same-day closing/last price from a second vendor, for cross-checking."""
    out: dict[str, dict[str, Any]] = {}
    for _symbol, (name, secid) in SYMBOLS.items():
        if not secid:
            continue
        try:
            request = urllib.request.Request(
                EASTMONEY.format(secid=secid), headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except Exception:
            continue
        data = payload.get("data")
        if not data:
            continue
        try:
            price = float(data.get("f43"))
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out[name] = {"price": price, "market": str(data.get("f58") or ""), "prev": data.get("f60")}
    return out


def load_data() -> dict[str, Any]:
    if not DATA.exists():
        raise SystemExit(f"还没有行情数据，先运行：python scripts/exchange.py fetch（{DATA}）")
    return json.loads(DATA.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Convert
# ---------------------------------------------------------------------------


def age_hours(fetched_at: str) -> float | None:
    try:
        then = dt.datetime.fromisoformat(fetched_at)
    except ValueError:
        return None
    now = dt.datetime.now().astimezone()
    return (now - then).total_seconds() / 3600


def per_unit(price_per_ton: float, unit: str) -> float:
    factor = UNIT_PER_TON.get(unit)
    if factor is None:
        raise SystemExit(f"不支持的单位：{unit}（可用：{', '.join(UNIT_PER_TON)}）")
    return price_per_ton / factor


@dataclasses.dataclass
class ConvertResult:
    from_name: str
    to_name: str
    quantity: float
    unit: str
    mid: float
    low: float
    high: float
    from_quote: dict[str, Any]
    to_quote: dict[str, Any]
    checks: list[tuple[str, str]]  # (项目, 状态)


def convert(data: dict[str, Any], from_name: str, to_name: str, quantity: float, unit: str) -> ConvertResult:
    items = data["items"]
    for name in (from_name, to_name):
        if name not in items:
            raise SystemExit(f"没有「{name}」的行情，可用：{', '.join(items)}")
    left, right = items[from_name], items[to_name]

    mid = quantity * per_unit(left["last"], unit) / per_unit(right["last"], unit)
    # 最不利：左低右高；最有利：左高右低
    low = quantity * per_unit(left["low"] or left["last"], unit) / per_unit(right["high"] or right["last"], unit)
    high = quantity * per_unit(left["high"] or left["last"], unit) / per_unit(right["low"] or right["last"], unit)

    checks: list[tuple[str, str]] = []
    hours = age_hours(data["meta"].get("fetched_at", ""))
    if hours is None:
        checks.append(("行情时效", "❓ 无法判断抓取时间，请人工核对"))
    elif hours > STALE_HOURS:
        checks.append(("行情时效", f"⚠ 数据已 {hours:.0f} 小时，请先 fetch 更新"))
    else:
        checks.append(("行情时效", f"✅ 抓取于 {hours:.1f} 小时前"))

    if (left.get("high") or 0) <= (left.get("low") or 0):
        checks.append(("价格区间", "⚠ 只有单点价，未取到当日高低"))
    else:
        checks.append(("价格区间", "✅ 已用当日高低点"))

    checks.append(("价格性质", "⚠ 期货价≠实物成交价，含升贴水差异，请人工核对"))
    checks.append(("交易成本", "⚠ 未计入加工费、运费、成色折价、批量折扣"))

    cross = left.get("cross")
    if cross:
        spread = float(cross.get("spread_pct") or 0.0)
        detail = f"新浪 {fmt(left['last'])} / 东财 {fmt(cross.get('price', 0))}（偏差 {spread:.2f}%）"
        if spread <= CROSS_OK:
            checks.append(("多源交叉", f"✅ {detail}"))
        elif spread <= CROSS_WARN:
            checks.append(("多源交叉", f"⚠ {detail}；连续合约与主连合约口径不同，确认标的"))
        else:
            checks.append(("多源交叉", f"⚠ {detail}；疑似数据错位，请人工核对"))
    else:
        checks.append(("多源交叉", "❓ 只有单源，未做交叉验证"))
    if left.get("symbol") in SYMBOLS and right.get("symbol") in SYMBOLS:
        checks.append(("标的匹配", "✅ 同一数据源、同为交易所连续合约"))
    else:
        checks.append(("标的匹配", "❓ 标的来源不同，请人工确认"))

    return ConvertResult(
        from_name=from_name,
        to_name=to_name,
        quantity=quantity,
        unit=unit,
        mid=mid,
        low=min(low, high),
        high=max(low, high),
        from_quote=left,
        to_quote=right,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def fmt(value: float) -> str:
    return f"{value:,.2f}"


def render(result: ConvertResult, data: dict[str, Any]) -> str:
    left, right = result.from_quote, result.to_quote
    unit = result.unit
    lines = [
        f"# 换算：{result.quantity:g} {unit}{result.from_name} ⇄ {result.to_name}",
        "",
        f"## 结论：约 **{fmt(result.mid)} {unit}**",
        "",
        f"按当日行情区间，结果在 **{fmt(result.low)} – {fmt(result.high)} {unit}** 之间。",
        "",
        "> 这是「等值」换算，不是成交价。实际换货还要看升贴水、加工费、成色和批量，"
        "**请以当日实际报价人工核对后再做决定**。",
        "",
        "## 计算过程（可手算复核）",
        "",
        "| 项目 | 数值 | 当日区间 | 来源 | 数据时间 | 核对状态 |",
        "|---|---|---|---|---|---|",
    ]
    for quote, label in ((left, result.from_name), (right, result.to_name)):
        lines.append(
            f"| {label}（{quote['market']}） | {fmt(quote['last'])} 元/吨 "
            f"| {fmt(quote['low'])} – {fmt(quote['high'])} "
            f"| {quote.get('source', '')} | {quote.get('as_of', '')} | ✅ 交易所行情 |"
        )
    cross = left.get("cross")
    if cross:
        spread = float(cross.get("spread_pct") or 0.0)
        mark = "✅ 两源一致" if spread <= CROSS_OK else ("⚠ 口径差异" if spread <= CROSS_WARN else "⚠ 疑似冲突")
        lines.append(
            f"| 交叉验证（{result.from_name}） | 新浪 {fmt(left['last'])} / "
            f"东财 {fmt(cross.get('price', 0))}（{cross.get('market', '')}） "
            f"| 偏差 {spread:.2f}% | 东方财富 | — | {mark} |"
        )
    else:
        lines.append(f"| 交叉验证（{result.from_name}） | 只有单源 | — | — | — | ❓ 未验证 |")
    lines.extend(
        [
            f"| 换算 | {fmt(per_unit(left['last'], unit))} 元/{unit} ÷ "
            f"{fmt(per_unit(right['last'], unit))} 元/{unit} = {fmt(result.mid)} {unit} | "
            f"{fmt(result.low)} – {fmt(result.high)} {unit} | 计算 | — | ⚠ 未计交易成本 |",
            "",
            "公式：",
            "",
            "```",
            f"{result.quantity:g} {unit}{result.from_name} × 单价({result.from_name}) ÷ 单价({result.to_name})"
            f" = {fmt(result.mid)} {unit}{result.to_name}",
            "```",
            "",
            "## 风险与人工核对项",
            "",
            "| 检查项 | 状态 |",
            "|---|---|",
        ]
    )
    for name, status in result.checks:
        lines.append(f"| {name} | {status} |")
    lines.extend(
        [
            "",
            "## 还需要人工确认的",
            "",
            "- **实物成色**：铜 99.95% 与废铜、铝锭与铝型材，价格能差 10–30%",
            "- **升贴水**：期货价 + 升贴水才是现货提货价，不同地区不同",
            "- **交易方式**：按重量还是按件、过磅误差、运费谁承担",
            "- **税费**：是否含税、能否开票",
            "",
            "---",
            "",
            f"> 数据来源：{data['meta'].get('source', '')} · 抓取于 {data['meta'].get('fetched_at', '')}",
            f"> {data['meta'].get('warning', '')}",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_fetch(args: argparse.Namespace) -> int:
    data = fetch_quotes()
    print(f"抓取 {len(data['items'])} 个品种 -> {DATA}")
    for name, quote in data["items"].items():
        cross = quote.get("cross")
        extra = ""
        if cross:
            extra = f"  | 东财 {fmt(cross['price'])} 偏差 {cross['spread_pct']:.2f}%"
        else:
            extra = "  | 东财 未取到"
        print(f"  {name:<6} {quote['market']:<10} {fmt(quote['last']):>12} 元/吨  "
              f"[{fmt(quote['low'])} – {fmt(quote['high'])}]{extra}")
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    data = load_data()
    result = convert(data, args.from_name, args.to_name, args.quantity, args.unit)
    report = render(result, data)
    print(report)
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"{args.from_name}换{args.to_name}.md"
        target.write_text(report, encoding="utf-8")
        print(f"report: {target}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    try:
        data = load_data()
    except SystemExit as exc:
        print(str(exc))
        return 2
    hours = age_hours(data["meta"].get("fetched_at", ""))
    stamp = f"（{hours:.1f} 小时前）" if hours is not None else ""
    print(f"行情{stamp}，单位 元/吨：")
    for name, quote in data["items"].items():
        print(f"  {name:<6} {fmt(quote['last']):>12}  [{fmt(quote['low'])} – {fmt(quote['high'])}]  {quote['market']}")
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("1 吨 = 2000 斤", UNIT_PER_TON["斤"] == 2000))
    checks.append(("每斤价 = 元/吨 ÷ 2000", abs(per_unit(20000, "斤") - 10) < 1e-9))
    data = {
        "meta": {"fetched_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "source": "selftest"},
        "items": {
            "铜": {"name": "铜", "symbol": "nf_CU0", "market": "沪铜连续", "last": 80000.0,
                   "low": 78000.0, "high": 82000.0, "prev_settle": 79000.0, "as_of": "2026-11-25"},
            "铝": {"name": "铝", "symbol": "nf_AL0", "market": "沪铝连续", "last": 20000.0,
                   "low": 19500.0, "high": 20500.0, "prev_settle": 19900.0, "as_of": "2026-11-25"},
        },
    }
    result = convert(data, "铜", "铝", 1, "斤")
    checks.append(("80000/20000 = 4.0", abs(result.mid - 4.0) < 1e-9))
    checks.append(("区间下限 < 中值", result.low < result.mid))
    checks.append(("区间上限 > 中值", result.high > result.mid))
    checks.append(("含交易成本提醒", any("交易成本" in name for name, _ in result.checks)))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exchange.py", description="物物等值换算，带来源与风险标注")
    parser.add_argument("--version", action="version", version=f"exchange {VERSION}")
    sub = parser.add_subparsers(dest="command")

    fetch = sub.add_parser("fetch", help="抓取最新行情")
    fetch.set_defaults(func=cmd_fetch)

    convert_parser = sub.add_parser("convert", help="换算")
    convert_parser.add_argument("--from", dest="from_name", required=True)
    convert_parser.add_argument("--to", dest="to_name", required=True)
    convert_parser.add_argument("--quantity", type=float, default=1.0)
    convert_parser.add_argument("--unit", default="斤")
    convert_parser.add_argument("-o", "--out", default="")
    convert_parser.set_defaults(func=cmd_convert)

    listing = sub.add_parser("list", help="列出已抓取品种")
    listing.set_defaults(func=cmd_list)

    selftest = sub.add_parser("selftest", help="内置自检")
    selftest.set_defaults(func=cmd_selftest)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
