#!/usr/bin/env python3
"""fetch_industry_history — 抓多个报告期的行业财务数据，看趋势和规模差异。

    python scripts/fetch_industry_history.py --write
    python scripts/fetch_industry_history.py --dry-run

数据源：东方财富 RPT_LICO_FN_CPD（同 fetch_industry_data，但取多个报告期）
产出 data/industry-history.json：

  periods   每个报告期、每个行业的中位数
  trend     每个行业跨期变化（毛利率涨了还是跌了）
  by_scale  按营收分档（小 <5亿 / 中 5-50亿 / 大 >50亿）看规模差异

市值字段该接口不提供，所以规模用营业收入代理——营收比市值更能反映经营体量。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

VERSION = "1.0.0"
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUTPUT = DATA_DIR / "industry-history.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

# 报告期 -> 展示名。都是完整期的数据才可比；三季报和年报的毛利率口径一致（累计口径）。
PERIODS: list[tuple[str, str]] = [
    ("2026-09-30", "2026 三季报"),
    ("2025-12-31", "2025 年报"),
    ("2024-12-31", "2024 年报"),
]

# 营收分档（元）
SCALE_TIERS: list[tuple[str, float, float]] = [
    ("小（<5 亿）", 0, 5e8),
    ("中（5–50 亿）", 5e8, 5e9),
    ("大（>50 亿）", 5e9, float("inf")),
]
MIN_SAMPLE = 3


def fetch(params: dict[str, str], retries: int = 3) -> dict[str, Any] | None:
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
    return None


def fetch_period(report_date: str, page_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages:
        data = fetch({
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECUCODE,SECURITY_NAME_ABBR,BOARD_NAME,XSMLL,"
                       "TOTAL_OPERATE_INCOME,PARENT_NETPROFIT",
            "pageNumber": str(page),
            "pageSize": str(page_size),
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "filter": f"(REPORTDATE='{report_date}')",
        })
        if not data:
            print(f"    第 {page} 页失败", file=sys.stderr)
            break
        result = data.get("result") or {}
        batch = result.get("data") or []
        pages = result.get("pages") or 1
        rows.extend(batch)
        page += 1
        time.sleep(0.4)
    return rows


def summarize(values: list[float]) -> dict[str, float] | None:
    if len(values) < MIN_SAMPLE:
        return None
    values = sorted(values)
    n = len(values)

    def pct(p: float) -> float:
        index = (n - 1) * p
        low = int(index)
        high = min(low + 1, n - 1)
        return values[low] + (values[high] - values[low]) * (index - low)

    return {
        "count": n,
        "median": round(statistics.median(values), 2),
        "p25": round(pct(0.25), 2),
        "p75": round(pct(0.75), 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="抓多期行业数据，看趋势和规模差异")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--periods", type=int, default=3, help="抓几个报告期，默认 3")
    parser.add_argument("--version", action="version", version=f"fetch_industry_history {VERSION}")
    args = parser.parse_args(argv)

    periods = PERIODS[: args.periods]
    period_data: dict[str, dict[str, Any]] = {}

    for report_date, label in periods:
        print(f"抓取 {label}（{report_date}）...")
        rows = fetch_period(report_date, args.page_size)
        print(f"  共 {len(rows)} 家")

        industries: dict[str, dict[str, list[float]]] = {}
        scale_dims: dict[str, dict[str, dict[str, list[float]]]] = {}
        for row in rows:
            board = str(row.get("BOARD_NAME") or "").strip()
            if not board:
                continue
            gross = row.get("XSMLL")
            revenue = row.get("TOTAL_OPERATE_INCOME")
            profit = row.get("PARENT_NETPROFIT")
            bucket = industries.setdefault(board, {"gross_margin": []})
            if isinstance(gross, (int, float)) and not isinstance(gross, bool):
                bucket["gross_margin"].append(float(gross))

            # 按营收分档
            if isinstance(revenue, (int, float)) and revenue and isinstance(gross, (int, float)):
                for tier_name, low, high in SCALE_TIERS:
                    if low <= float(revenue) < high:
                        scale_dims.setdefault(board, {}).setdefault(tier_name, {"gross_margin": []})
                        scale_dims[board][tier_name]["gross_margin"].append(float(gross))
                        break

        payload: dict[str, Any] = {}
        for board, metrics in industries.items():
            summary = summarize(metrics["gross_margin"])
            if summary:
                payload[board] = {"gross_margin": summary}
        by_scale: dict[str, Any] = {}
        for board, tiers in scale_dims.items():
            tier_payload = {}
            for tier, metrics in tiers.items():
                summary = summarize(metrics["gross_margin"])
                if summary:
                    tier_payload[tier] = summary
            if len(tier_payload) >= 2:
                by_scale[board] = tier_payload

        period_data[label] = {
            "report_date": report_date,
            "companies": len(rows),
            "industries": payload,
            "by_scale": by_scale,
        }
        print(f"  有效行业 {len(payload)} 个，有规模对比的 {len(by_scale)} 个")

    # 趋势：同一个行业跨期比较
    print("\n计算趋势...")
    labels = [label for _date, label in periods]
    trend: dict[str, Any] = {}
    all_boards = set()
    for label in labels:
        all_boards.update(period_data[label]["industries"].keys())
    for board in all_boards:
        series = []
        for label in labels:
            summary = period_data[label]["industries"].get(board, {}).get("gross_margin")
            if summary:
                series.append({"period": label, "median": summary["median"], "count": summary["count"]})
        if len(series) >= 2:
            first = series[-1]["median"]  # 最早一期
            last = series[0]["median"]    # 最新一期
            trend[board] = {
                "series": series,
                "change": round(last - first, 2),
                "direction": "上升" if last > first + 0.5 else ("下降" if last < first - 0.5 else "持平"),
            }
    print(f"  有跨期对比的行业 {len(trend)} 个")

    rising = [(k, v) for k, v in trend.items() if v["direction"] == "上升"]
    falling = [(k, v) for k, v in trend.items() if v["direction"] == "下降"]
    print(f"  毛利率上升 {len(rising)} 个，下降 {len(falling)} 个")

    if args.dry_run:
        print("\n样例（变化最大的 5 个行业）：")
        for board, info in sorted(trend.items(), key=lambda kv: -abs(kv[1]["change"]))[:5]:
            series = " -> ".join(f"{s['median']}%" for s in reversed(info["series"]))
            print(f"  {board:<14} {series}  变化 {info['change']:+.2f}pp")
        return 0

    if not args.write:
        parser.print_help()
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "source": "东方财富 RPT_LICO_FN_CPD",
        "periods": period_data,
        "trend": trend,
        "scale_tiers": [{"name": n, "low": lo, "high": (None if hi == float("inf") else hi)}
                        for n, lo, hi in SCALE_TIERS],
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "caveat": (
            "上市公司口径；各报告期公司数不同，趋势对比的是同行业的中位数，"
            "不是同一批公司的变化。规模用营业收入分档（该接口不提供市值）。"
        ),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入 {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
