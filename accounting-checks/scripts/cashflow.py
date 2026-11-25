#!/usr/bin/env python3
"""cashflow — 现金流量表间接法推导。

    python scripts/cashflow.py check -i 数据.json
    python scripts/cashflow.py demo

从净利润倒推经营活动现金流：

    净利润
    + 折旧、摊销、减值（非付现成本）
    − 处置收益（属于投资活动，不属于经营）
    ± 营运资本变动（应收、存货、应付）

再和实际编制的现金流量表对比，看差异在哪。
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


@dataclasses.dataclass
class Line:
    label: str
    amount: float   # 对经营活动现金流的影响额（带符号）
    kind: str       # base | add | subtract


@dataclasses.dataclass
class Result:
    lines: list[Line]
    operating_cash_flow: float
    reported: float | None
    gap: float | None


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate(data: dict[str, Any]) -> tuple[Result | None, list[str]]:
    issues: list[str] = []
    income = data.get("income_statement") or {}
    non_cash = data.get("non_cash") or {}
    working = data.get("working_capital") or {}

    net_profit = income.get("net_profit")
    if net_profit is None:
        return None, ["缺少净利润（income_statement.net_profit）"]

    lines: list[Line] = [Line("净利润", num(net_profit), "base")]
    total = num(net_profit)

    # 非付现成本：加回
    for key, label in (
        ("depreciation", "加：固定资产折旧"),
        ("amortization", "加：无形资产摊销"),
        ("impairment", "加：资产减值准备"),
        ("long_term_deferred", "加：长期待摊费用摊销"),
    ):
        value = non_cash.get(key)
        if value is None:
            continue
        lines.append(Line(label, num(value), "add"))
        total += num(value)

    # 非经营活动损益：剔除
    gain = non_cash.get("gain_on_disposal")
    if gain is not None:
        lines.append(Line("减：处置固定资产等收益", num(gain), "subtract"))
        total -= num(gain)

    loss = non_cash.get("loss_on_scrapping")
    if loss is not None:
        lines.append(Line("加：报废损失", num(loss), "add"))
        total += num(loss)

    # 营运资本变动：应收和存货增加占用现金，应付增加释放现金。
    # 注意：Line.amount 存的是「对现金流的影响」，不是科目变动本身。
    # 存货减少 30000（change=-30000）对现金流是 +30000，必须显示成加号。
    for key, label in (
        ("receivables_change", "应收项目变动"),
        ("inventory_change", "存货变动"),
    ):
        value = working.get(key)
        if value is None:
            continue
        impact = -num(value)
        lines.append(Line(label, impact, "impact"))
        total += impact

    payables = working.get("payables_change")
    if payables is not None:
        impact = num(payables)
        lines.append(Line("应付项目变动", impact, "impact"))
        total += impact

    reported = data.get("reported_operating_cash_flow")
    gap = None
    if reported is not None:
        gap = round(num(reported) - round(total, 2), 2)
        if abs(gap) > TOLERANCE:
            issues.append(f"推导值 {total:,.2f} 与报表 {num(reported):,.2f} 差 {gap:,.2f}")

    return Result(lines, round(total, 2), None if reported is None else num(reported), gap), issues


def render(result: Result | None, issues: list[str]) -> str:
    lines = ["# 现金流量表间接法推导", ""]
    if not result:
        return "\n".join(lines + ["（无法计算）"] + [f"- {i}" for i in issues])

    lines.extend(["| 项目 | 影响金额 |", "|---|---|"])
    for line in result.lines:
        if line.kind == "base":
            lines.append(f"| {line.label} | {line.amount:,.2f} |")
        elif line.kind == "impact":
            lines.append(f"| {line.label} | {line.amount:+,.2f} |")
        else:
            mark = "+" if line.kind == "add" else "−"
            lines.append(f"| {line.label} | {mark}{abs(line.amount):,.2f} |")
    lines.append(f"| **经营活动现金流量净额** | **{result.operating_cash_flow:,.2f}** |")
    lines.append("")

    if result.reported is not None:
        lines.append(f"- 报表列示：**{result.reported:,.2f}**")
        if abs(result.gap or 0) <= TOLERANCE:
            lines.append("- 结论：**推导值与报表一致**")
        else:
            lines.append(f"- 结论：**差异 {result.gap:,.2f}**，需要核对营运资本或非付现项目")
        lines.append("")

    if issues:
        lines.extend(["## 提示", ""] + [f"- {issue}" for issue in issues] + [""])

    lines.extend([
        "---",
        "",
        "> 只做公式推导，不判断现金流质量。",
        "> 差异常见来源：营运资本口径不同（含税/不含税）、其他应收应付未计入、汇兑损益。",
        "",
    ])
    return "\n".join(lines)


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    result, issues = calculate(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "lines": [dataclasses.asdict(line) for line in (result.lines if result else [])],
            "operating_cash_flow": result.operating_cash_flow if result else None,
            "reported": result.reported if result else None,
            "gap": result.gap if result else None,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(result, issues))
    return 1 if issues else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "period": "2026-10",
        "income_statement": {"net_profit": 500000},
        "non_cash": {"depreciation": 100000, "amortization": 20000, "impairment": 30000},
        "working_capital": {
            "receivables_change": 50000,   # 应收增加，占用现金
            "inventory_change": -30000,    # 存货减少，释放现金
            "payables_change": 40000,      # 应付增加，占用别人资金
        },
        "reported_operating_cash_flow": 700000,
    }
    result, issues = calculate(data)
    print(render(result, issues))
    print("（推导值 640,000，报表 700,000，差 60,000 用于展示检出效果）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cashflow.py", description="现金流量表间接法")
    parser.add_argument("--version", action="version", version=f"cashflow {VERSION}")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="推导一份数据")
    check.add_argument("-i", "--input", required=True)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
    demo = sub.add_parser("demo", help="跑一个示例")
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
