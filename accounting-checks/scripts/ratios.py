#!/usr/bin/env python3
"""ratios — 财务比率分析。纯除法，不做判断。

    python scripts/ratios.py calc -i 报表.json
    python scripts/ratios.py demo

参考值是**通用参考区间**，不是行业标准。不同行业、不同规模差异极大，
例如零售业流动比率 1.0 可能正常，重资产制造业要 2.0 以上。
所以输出只标「偏离」，不下结论。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"

# (名称, 分子字段, 分母字段, 通用参考下限, 上限, 说明)
RATIOS = [
    ("流动比率", ("balance_sheet", "current_assets"), ("balance_sheet", "current_liabilities"),
     None, 2.0, "短期偿债能力，过低风险高，过高说明资产闲置"),
    ("速动比率", ("balance_sheet", "quick_assets"), ("balance_sheet", "current_liabilities"),
     None, 1.0, "剔除存货后的短期偿债能力"),
    ("资产负债率", ("balance_sheet", "total_liabilities"), ("balance_sheet", "total_assets"),
     40.0, 60.0, "长期偿债能力与财务杠杆"),
    ("毛利率", ("income_statement", "gross_profit"), ("income_statement", "revenue"),
     None, None, "产品竞争力，行业间差异极大"),
    ("净利率", ("income_statement", "net_profit"), ("income_statement", "revenue"),
     None, None, "最终盈利能力"),
    ("净资产收益率 ROE", ("income_statement", "net_profit"), ("balance_sheet", "total_equity"),
     None, None, "股东回报水平"),
    ("总资产报酬率 ROA", ("income_statement", "net_profit"), ("balance_sheet", "total_assets"),
     None, None, "资产使用效率"),
    ("应收账款周转率", ("income_statement", "revenue"), ("balance_sheet", "receivables"),
     None, None, "一年周转次数，越高回款越快"),
    ("存货周转率", ("income_statement", "cost_of_sales"), ("balance_sheet", "inventory"),
     None, None, "一年周转次数，越高存货压力越小"),
]


@dataclasses.dataclass
class Ratio:
    name: str
    value: float | None
    unit: str
    low: float | None
    high: float | None
    verdict: str
    note: str


def pull(data: dict[str, Any], path: tuple[str, str]) -> float | None:
    section = data.get(path[0]) or {}
    if not isinstance(section, dict):
        return None
    value = section.get(path[1])
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute(data: dict[str, Any]) -> list[Ratio]:
    results: list[Ratio] = []
    for name, numerator_path, denominator_path, low, high, note in RATIOS:
        numerator = pull(data, numerator_path)
        denominator = pull(data, denominator_path)
        if numerator is None or denominator is None or abs(denominator) < 1e-9:
            results.append(Ratio(name, None, "", low, high, "缺少数据", note))
            continue
        value = numerator / denominator
        is_percent = name in {"毛利率", "净利率", "净资产收益率 ROE", "总资产报酬率 ROA", "资产负债率"}
        unit = "%" if is_percent else "倍"
        display = value * 100 if is_percent else value
        verdict = "—"
        if low is not None and display < low:
            verdict = "偏低"
        elif high is not None and display > high:
            verdict = "偏高"
        elif low is not None or high is not None:
            verdict = "正常"
        results.append(Ratio(name, display, unit, low, high, verdict, note))
    return results


def render(results: list[Ratio]) -> str:
    lines = [
        "# 财务比率",
        "",
        "| 比率 | 数值 | 通用参考 | 提示 |",
        "|---|---|---|---|",
    ]
    for ratio in results:
        if ratio.value is None:
            value_text = "—"
        else:
            value_text = f"{ratio.value:.2f}{ratio.unit}"
        if ratio.low is not None and ratio.high is not None:
            if ratio.unit == "%":
                reference = f"{ratio.low:.0f}%–{ratio.high:.0f}%"
            else:
                reference = f"{ratio.low:.2f}–{ratio.high:.2f}"
        elif ratio.high is not None:
            reference = f"≤ {ratio.high:.0f}%" if ratio.unit == "%" else f"≤ {ratio.high:.2f}"
        else:
            reference = "无通用值"
        lines.append(f"| {ratio.name} | {value_text} | {reference} | {ratio.verdict} |")
    lines.extend(
        [
            "",
            "## 参考值说明",
            "",
            "表中的「通用参考」是教科书常见区间，**不是行业标准**。实际判断要看：",
            "",
            "- 行业（零售和重资产的合理区间差一倍）",
            "- 企业规模与生命周期（成长期和成熟期不同）",
            "- 历史趋势（比单期数值更有意义）",
            "",
            "工具只负责算，偏离不代表有问题。",
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
    results = compute(data)
    if args.json:
        print(json.dumps({"version": VERSION, "ratios": [dataclasses.asdict(r) for r in results]},
                         ensure_ascii=False, indent=2))
    else:
        print(render(results))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "balance_sheet": {
            "current_assets": 800000, "quick_assets": 500000, "current_liabilities": 400000,
            "total_assets": 5000000, "total_liabilities": 2000000, "total_equity": 3000000,
            "receivables": 300000, "inventory": 300000,
        },
        "income_statement": {
            "revenue": 4000000, "cost_of_sales": 2800000,
            "gross_profit": 1200000, "net_profit": 500000,
        },
    }
    print(render(compute(data)))
    print("（示例数据：营收 400 万、净利 50 万、总资产 500 万）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ratios.py", description="财务比率分析")
    parser.add_argument("--version", action="version", version=f"ratios {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份报表 JSON")
    calc.add_argument("-i", "--input", required=True)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(func=cmd_calc)
    demo = sub.add_parser("demo", help="跑一个内置示例")
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
