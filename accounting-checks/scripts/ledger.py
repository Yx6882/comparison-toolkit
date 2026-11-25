#!/usr/bin/env python3
"""ledger — 科目余额表勾稽。纯加减，不做判断。

    python scripts/ledger.py check -i 科目余额表.json
    python scripts/ledger.py demo

检查四件事：
    1. 单科目：期初 + 借方 − 贷方 = 期末（借贷方向不同，公式镜像）
    2. 期初余额合计：借方余额合计 = 贷方余额合计
    3. 本期发生额：借方合计 = 贷方合计
    4. 期末余额合计：借方余额合计 = 贷方余额合计
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
class Issue:
    target: str
    level: str
    rule: str
    detail: str


def num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def signed_balance(amount: float, direction: str) -> float:
    """借方余额记正、贷方余额记负，用于试算平衡。"""
    return amount if direction == "借" else -amount


def check_account(account: dict[str, Any]) -> list[Issue]:
    code = str(account.get("code") or account.get("科目编码") or "?")
    name = str(account.get("name") or account.get("科目名称") or "")
    label = f"{code} {name}".strip()

    opening = num(account.get("opening"))
    debit = num(account.get("debit"))
    credit = num(account.get("credit"))
    closing = num(account.get("closing"))
    direction = str(account.get("direction") or "借").strip()

    issues: list[Issue] = []
    if direction == "借":
        expected = opening + debit - credit
    elif direction == "贷":
        expected = opening + credit - debit
    else:
        issues.append(Issue(label, "high", "余额方向", f"方向只能是「借」或「贷」，实际 {direction!r}"))
        return issues

    gap = closing - expected
    if abs(gap) > TOLERANCE:
        issues.append(
            Issue(
                label, "high", "余额勾稽",
                f"期初 {opening:,.2f} + 借 {debit:,.2f} − 贷 {credit:,.2f} = {expected:,.2f}，"
                f"表列期末 {closing:,.2f}，差 {gap:,.2f}",
            )
        )
    if debit < 0 or credit < 0:
        issues.append(Issue(label, "medium", "负数发生额", "红字冲销应有专门标识，检查是否漏标注"))
    return issues


def check_totals(accounts: list[dict[str, Any]]) -> list[Issue]:
    issues: list[Issue] = []

    opening_signed = 0.0
    debit_total = 0.0
    credit_total = 0.0
    closing_signed = 0.0
    for account in accounts:
        direction = str(account.get("direction") or "借").strip()
        opening_signed += signed_balance(num(account.get("opening")), direction)
        closing_signed += signed_balance(num(account.get("closing")), direction)
        debit_total += num(account.get("debit"))
        credit_total += num(account.get("credit"))

    if abs(credit_total - debit_total) > TOLERANCE:
        issues.append(
            Issue("本期发生额", "high", "发生额不平",
                  f"借方 {debit_total:,.2f} ≠ 贷方 {credit_total:,.2f}，差 {debit_total - credit_total:,.2f}")
        )
    if abs(opening_signed) > TOLERANCE:
        issues.append(
            Issue("期初余额", "high", "期初不平", f"借方余额合计 − 贷方余额合计 = {opening_signed:,.2f}，应为 0")
        )
    if abs(closing_signed) > TOLERANCE:
        issues.append(
            Issue("期末余额", "high", "期末不平", f"借方余额合计 − 贷方余额合计 = {closing_signed:,.2f}，应为 0")
        )
    return issues


def run_checks(data: dict[str, Any]) -> list[Issue]:
    accounts = data.get("accounts") or data.get("科目") or []
    issues: list[Issue] = []
    for account in accounts:
        issues.extend(check_account(account))
    issues.extend(check_totals(accounts))
    return issues


def render(issues: list[Issue], count: int) -> str:
    high = sum(1 for issue in issues if issue.level == "high")
    lines = ["# 科目余额表勾稽", "", f"- 科目 {count} 个", ""]
    if not issues:
        lines.extend(["✓ 单科目滚算、发生额、余额合计全部平", ""])
    else:
        lines.append("| 科目 | 级别 | 规则 | 详情 |")
        lines.append("|---|---|---|---|")
        for issue in sorted(issues, key=lambda item: item.level != "high"):
            lines.append(f"| {issue.target} | {'高' if issue.level == 'high' else '中'} | {issue.rule} | {issue.detail} |")
        lines.append("")
        lines.append(f"高 {high} 项")
    lines.extend(["", "> 只校验加减关系。科目使用是否恰当、余额是否合理，不在检查范围。", ""])
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
    accounts = data.get("accounts") or []
    issues = run_checks(data)
    if args.json:
        print(json.dumps({"version": VERSION, "accounts": len(accounts),
                          "issues": [dataclasses.asdict(i) for i in issues]}, ensure_ascii=False, indent=2))
    else:
        print(render(issues, len(accounts)))
    return 1 if any(issue.level == "high" for issue in issues) else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "accounts": [
            {"code": "1001", "name": "库存现金", "direction": "借",
             "opening": 5000, "debit": 12000, "credit": 8000, "closing": 9000},
            {"code": "1002", "name": "银行存款", "direction": "借",
             "opening": 100000, "debit": 50000, "credit": 30000, "closing": 120000},
            {"code": "2001", "name": "应付账款", "direction": "贷",
             "opening": 60000, "debit": 20000, "credit": 45000, "closing": 85000},
            {"code": "4001", "name": "实收资本", "direction": "贷",
             "opening": 45000, "debit": 0, "credit": 0, "closing": 44000},  # 期末错 1000
        ]
    }
    issues = run_checks(data)
    print(render(issues, len(data["accounts"])))
    print("（示例故意让 4001 期末错 1,000，并让期末余额不平）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ledger.py", description="科目余额表勾稽")
    parser.add_argument("--version", action="version", version=f"ledger {VERSION}")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="检查一份科目余额表 JSON")
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
