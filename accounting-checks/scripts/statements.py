#!/usr/bin/env python3
"""statements — 三大报表勾稽检查。纯会计恒等式，不做任何业务或税务判断。

    python scripts/statements.py check -i 报表.json
    python scripts/statements.py check -i 报表.json --json
    python scripts/statements.py demo
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
TOLERANCE = 0.01  # 会计精确到分


@dataclasses.dataclass
class Check:
    name: str
    ok: bool | None  # None = 数据不足，跳过
    detail: str
    left: float | None = None
    right: float | None = None
    gap: float | None = None


def number(data: dict[str, Any], *path: str) -> float | None:
    """Safely pull a number from nested dict."""
    current: Any = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    try:
        return float(current)
    except (TypeError, ValueError):
        return None


def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def check_balance_sheet(data: dict[str, Any]) -> Check:
    assets = number(data, "balance_sheet", "total_assets")
    liabilities = number(data, "balance_sheet", "total_liabilities")
    equity = number(data, "balance_sheet", "total_equity")
    if assets is None or liabilities is None or equity is None:
        return Check("资产负债平衡", None, "缺少 总资产 / 总负债 / 所有者权益 之一")
    right = liabilities + equity
    gap = assets - right
    ok = abs(gap) <= TOLERANCE
    detail = f"{fmt(assets)} = {fmt(liabilities)} + {fmt(equity)}"
    if not ok:
        detail += f"，差额 {fmt(gap)}"
    return Check("资产负债平衡", ok, detail, assets, right, gap)


def check_retained_earnings(data: dict[str, Any]) -> Check:
    opening = number(data, "equity_change", "opening_retained")
    closing = number(data, "equity_change", "closing_retained")
    net_profit = number(data, "income_statement", "net_profit")
    dividends = number(data, "equity_change", "dividends") or 0.0
    adjustments = number(data, "equity_change", "prior_adjustments") or 0.0
    if opening is None or closing is None or net_profit is None:
        return Check("未分配利润滚动", None, "缺少 期初未分配 / 期末未分配 / 净利润 之一")
    expected = opening + net_profit - dividends + adjustments
    gap = closing - expected
    ok = abs(gap) <= TOLERANCE
    detail = (
        f"期初 {fmt(opening)} + 净利润 {fmt(net_profit)} − 分红 {fmt(dividends)}"
        f" + 调整 {fmt(adjustments)} = {fmt(expected)}，报表 {fmt(closing)}"
    )
    if not ok:
        detail += f"，差额 {fmt(gap)}"
    return Check("未分配利润滚动", ok, detail, expected, closing, gap)


def check_cash(data: dict[str, Any]) -> Check:
    ending = number(data, "cash_flow", "ending_cash")
    cash_bs = number(data, "balance_sheet", "cash_and_equivalents")
    if ending is None or cash_bs is None:
        return Check("现金勾稽", None, "缺少 现金流量表期末现金 或 资产负债表货币资金")
    gap = ending - cash_bs
    ok = abs(gap) <= TOLERANCE
    detail = f"现金流量表 {fmt(ending)} vs 资产负债表 {fmt(cash_bs)}"
    if not ok:
        detail += f"，差额 {fmt(gap)}"
    return Check("现金勾稽", ok, detail, ending, cash_bs, gap)


def check_profit_consistency(data: dict[str, Any]) -> Check:
    income_profit = number(data, "income_statement", "net_profit")
    equity_profit = number(data, "equity_change", "net_profit")
    if income_profit is None or equity_profit is None:
        return Check("净利润一致性", None, "缺少 利润表净利润 或 所有者权益变动表净利润")
    gap = income_profit - equity_profit
    ok = abs(gap) <= TOLERANCE
    detail = f"利润表 {fmt(income_profit)} vs 权益变动表 {fmt(equity_profit)}"
    if not ok:
        detail += f"，差额 {fmt(gap)}"
    return Check("净利润一致性", ok, detail, income_profit, equity_profit, gap)


CHECKS = [check_balance_sheet, check_retained_earnings, check_cash, check_profit_consistency]


def run_checks(data: dict[str, Any]) -> list[Check]:
    return [check(data) for check in CHECKS]


def render(checks: list[Check]) -> str:
    passed = sum(1 for c in checks if c.ok is True)
    failed = sum(1 for c in checks if c.ok is False)
    skipped = sum(1 for c in checks if c.ok is None)
    lines = ["# 报表勾稽检查", ""]
    for check in checks:
        mark = "✓" if check.ok is True else ("✗" if check.ok is False else "–")
        lines.append(f"{mark} {check.name:<16} {check.detail}")
    lines.extend(
        [
            "",
            f"{passed} 项通过 · {failed} 项不符 · {skipped} 项数据不足",
            "",
            "> 只校验会计恒等式，不判断每笔业务是否记对。",
            "> 容差 0.01 元；缺数据会标「数据不足」，不当成通过。",
            "",
        ]
    )
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
    checks = run_checks(data)
    report = render(checks)
    if args.json:
        print(
            json.dumps(
                {
                    "version": VERSION,
                    "checks": [dataclasses.asdict(c) for c in checks],
                    "passed": sum(1 for c in checks if c.ok is True),
                    "failed": sum(1 for c in checks if c.ok is False),
                    "skipped": sum(1 for c in checks if c.ok is None),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(report)
    return 1 if any(c.ok is False for c in checks) else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "balance_sheet": {
            "total_assets": 5000000,
            "total_liabilities": 2000000,
            "total_equity": 3000000,
            "cash_and_equivalents": 800000,
        },
        "income_statement": {"net_profit": 500000},
        "cash_flow": {"ending_cash": 800000},
        "equity_change": {
            "opening_retained": 2000000,
            "closing_retained": 2450000,
            "dividends": 0,
            "prior_adjustments": 0,
        },
    }
    checks = run_checks(data)
    print(render(checks))
    print("（示例故意让未分配利润差 50,000，用来展示检出效果）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="statements.py", description="三大报表勾稽检查")
    parser.add_argument("--version", action="version", version=f"statements {VERSION}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="检查一份报表 JSON")
    check.add_argument("-i", "--input", required=True)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)

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
