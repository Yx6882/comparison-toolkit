#!/usr/bin/env python3
"""depreciation — 固定资产折旧计算。四种方法，纯算术。

    python scripts/depreciation.py calc -i 资产.json
    python scripts/depreciation.py demo

四种方法：
    年限平均法      (原值 − 残值) ÷ (年限 × 12)
    工作量法        (原值 − 残值) ÷ 总工作量 × 当期工作量
    双倍余额递减法  年折旧率 = 2 ÷ 年限，最后两年改直线
    年数总和法      (原值 − 残值) × 剩余年限 ÷ 年数总和

计提规则（《企业会计准则第 4 号》惯例）：
    当月增加的固定资产，当月不提，下月起计提；
    当月减少的，当月照提，下月起停提。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
TOLERANCE = 0.01
METHODS = {
    "straight_line": "年限平均法",
    "units_of_production": "工作量法",
    "double_declining": "双倍余额递减法",
    "sum_of_years": "年数总和法",
}


@dataclasses.dataclass
class Period:
    period: str          # 2026-01
    amount: float        # 本月折旧
    accumulated: float   # 累计折旧
    net_book: float      # 净值


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_ym(text: str) -> tuple[int, int] | None:
    import re

    match = re.match(r"(\d{4})[-/年]?(\d{1,2})", str(text or ""))
    if not match:
        return None
    year, month = int(match.group(1)), int(match.group(2))
    if not (1 <= month <= 12):
        return None
    return year, month


def add_month(year: int, month: int, count: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + count
    return index // 12, index % 12 + 1


def periods_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return (end[0] - start[0]) * 12 + (end[1] - start[1])


def straight_line(cost: float, residual: float, life_months: int) -> list[float]:
    if life_months <= 0:
        return []
    monthly = (cost - residual) / life_months
    return [monthly] * life_months


def units_of_production(cost: float, residual: float, total_units: float, used_units: list[float]) -> list[float]:
    if total_units <= 0:
        return []
    per_unit = (cost - residual) / total_units
    return [per_unit * units for units in used_units]


def double_declining(cost: float, residual: float, life_years: int) -> list[float]:
    """年折旧率 = 2/年限；最后两年把剩余净值减残值后平摊。"""
    if life_years <= 0:
        return []
    if life_years == 1:
        return [(cost - residual) / 12]
    rate = 2.0 / life_years
    yearly: list[float] = []
    net = cost
    for year in range(life_years):
        if year >= life_years - 2:
            break
        amount = net * rate
        yearly.append(amount)
        net -= amount
    remaining = net - residual
    tail = remaining / 2 if life_years >= 2 else remaining
    yearly.extend([tail, tail] if life_years >= 2 else [tail])
    monthly: list[float] = []
    for amount in yearly:
        monthly.extend([amount / 12] * 12)
    return monthly[: life_years * 12]


def sum_of_years(cost: float, residual: float, life_years: int) -> list[float]:
    if life_years <= 0:
        return []
    denominator = life_years * (life_years + 1) / 2
    base = cost - residual
    monthly: list[float] = []
    for year in range(life_years):
        remaining = life_years - year
        annual = base * remaining / denominator
        monthly.extend([annual / 12] * 12)
    return monthly


def build_schedule(data: dict[str, Any]) -> tuple[list[Period], list[str]]:
    issues: list[str] = []
    method = str(data.get("method") or "straight_line")
    cost = num(data.get("original_cost"))
    residual = num(data.get("residual_value"))
    start = parse_ym(data.get("start_period") or data.get("start_date"))
    if start is None:
        return [], ["起算期间无法解析（需要 YYYY-MM 或 YYYY-MM-DD）"]
    if cost <= 0:
        return [], ["原值必须大于 0"]
    if residual < 0 or residual >= cost:
        return [], ["残值必须在 [0, 原值) 之间"]

    life_years = int(num(data.get("useful_life_years"), 0))
    if method in {"straight_line", "double_declining", "sum_of_years"} and life_years <= 0:
        return [], ["使用年限必须大于 0"]

    if method == "straight_line":
        monthly = straight_line(cost, residual, life_years * 12)
    elif method == "double_declining":
        monthly = double_declining(cost, residual, life_years)
    elif method == "sum_of_years":
        monthly = sum_of_years(cost, residual, life_years)
    elif method == "units_of_production":
        work = data.get("work_units") or {}
        units = [num(item) for item in (work.get("per_period") or [])]
        monthly = units_of_production(cost, residual, num(work.get("total")), units)
    else:
        return [], [f"未知折旧方法：{method}"]

    # 当月增加不提、当月减少照提：从 start 的下一个月开始计提
    first_year, first_month = add_month(start[0], start[1], 1)
    disposal = parse_ym(data.get("disposal_period") or data.get("disposal_date"))
    limit = None
    if disposal:
        limit = periods_between((first_year, first_month), disposal) + 1  # 处置当月照提
        if limit <= 0:
            return [], ["处置期间早于起算期间，没有可计提的月份"]

    schedule: list[Period] = []
    accumulated = 0.0
    for index, amount in enumerate(monthly):
        if limit is not None and index >= limit:
            break
        year, month = add_month(first_year, first_month, index)
        accumulated += amount
        schedule.append(
            Period(f"{year:04d}-{month:02d}", round(amount, 2), round(accumulated, 2), round(cost - accumulated, 2))
        )

    total = sum(monthly)
    if abs(total - (cost - residual)) > TOLERANCE and method in {"straight_line", "sum_of_years"}:
        issues.append(f"折旧总额 {total:,.2f} 与「原值−残值」{(cost - residual):,.2f} 不等")
    return schedule, issues


def render(schedule: list[Period], issues: list[str], data: dict[str, Any]) -> str:
    method = str(data.get("method") or "straight_line")
    lines = [
        "# 折旧计算",
        "",
        f"- 原值 {num(data.get('original_cost')):,.2f} · 残值 {num(data.get('residual_value')):,.2f}",
        f"- 方法：{METHODS.get(method, method)}",
        f"- 期间数：{len(schedule)} 个月",
        "",
    ]
    if issues:
        lines.extend(["## 检查提示", ""] + [f"- {issue}" for issue in issues] + [""])
    if schedule:
        lines.extend(["| 期间 | 本月折旧 | 累计折旧 | 净值 |", "|---|---|---|---|"])
        for item in schedule[:24]:
            lines.append(f"| {item.period} | {item.amount:,.2f} | {item.accumulated:,.2f} | {item.net_book:,.2f} |")
        if len(schedule) > 24:
            lines.append(f"| … | 另 {len(schedule) - 24} 期 | | |")
        lines.extend(
            [
                "",
                f"合计折旧 **{sum(p.amount for p in schedule):,.2f}**，"
                f"期末净值 **{schedule[-1].net_book:,.2f}**",
                "",
            ]
        )
    lines.extend(
        [
            "---",
            "",
            "> 规则：当月增加的固定资产当月不提，下月起计提；当月减少的当月照提。",
            "> 只算折旧金额，不判断资产分类、使用年限和残值率是否合理。",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_calc(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    schedule, issues = build_schedule(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "method": data.get("method"),
            "periods": [dataclasses.asdict(p) for p in schedule],
            "total": round(sum(p.amount for p in schedule), 2),
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(schedule, issues, data))
    return 1 if issues else 0


def cmd_demo(args: argparse.Namespace) -> int:
    print("# 折旧计算示例")
    print()
    cases = [
        {"method": "straight_line", "original_cost": 120000, "residual_value": 6000,
         "useful_life_years": 5, "start_period": "2026-01", "note": "年限平均"},
        {"method": "double_declining", "original_cost": 120000, "residual_value": 6000,
         "useful_life_years": 5, "start_period": "2026-01", "note": "双倍余额递减"},
        {"method": "sum_of_years", "original_cost": 120000, "residual_value": 6000,
         "useful_life_years": 5, "start_period": "2026-01", "note": "年数总和"},
        {"method": "straight_line", "original_cost": 120000, "residual_value": 6000,
         "useful_life_years": 5, "start_period": "2026-01", "disposal_period": "2027-06",
         "note": "中途处置（2027-06 处置，当月照提）"},
    ]
    for case in cases:
        note = case.pop("note")
        schedule, issues = build_schedule(case)
        total = sum(p.amount for p in schedule)
        print(f"=== {note} ===")
        print(f"  {len(schedule)} 期 · 合计 {total:,.2f} · 末期净值 {schedule[-1].net_book:,.2f}"
              if schedule else f"  失败：{issues}")
        if issues:
            print(f"  提示：{issues}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="depreciation.py", description="固定资产折旧计算")
    parser.add_argument("--version", action="version", version=f"depreciation {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份资产 JSON")
    calc.add_argument("-i", "--input", required=True)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(func=cmd_calc)
    demo = sub.add_parser("demo", help="跑四种方法的示例")
    demo.set_defaults(func=cmd_demo)
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
