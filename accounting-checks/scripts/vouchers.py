#!/usr/bin/env python3
"""vouchers — 凭证合规检查。纯规则，不做会计判断。

    python scripts/vouchers.py check -i 凭证.json
    python scripts/vouchers.py check -i 凭证.json --json
    python scripts/vouchers.py demo

检查的是「凭证本身有没有毛病」：
借贷平不平、行数够不够、摘要空不空、日期在不在期间内、凭证号连不连续、
有没有一行同时记借贷、有没有零金额行。

**不检查**：这笔业务该不该这么记、科目用得对不对、金额合不合理。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
TOLERANCE = 0.01
DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
NUMBER_RE = re.compile(r"(\d+)$")


@dataclasses.dataclass
class Issue:
    voucher: str
    level: str  # high | medium | low
    rule: str
    detail: str


def parse_date(text: Any) -> tuple[int, int, int] | None:
    match = DATE_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]
    except ValueError:
        return None


def fmt_date(value: tuple[int, int, int] | None) -> str:
    if not value:
        return "—"
    return f"{value[0]:04d}-{value[1]:02d}-{value[2]:02d}"


def amount(line: dict[str, Any], side: str) -> float:
    try:
        return float(line.get(side) or 0)
    except (TypeError, ValueError):
        return 0.0


def check_voucher(voucher: dict[str, Any], period: tuple[Any, Any]) -> list[Issue]:
    issues: list[Issue] = []
    number = str(voucher.get("no") or voucher.get("number") or "?")

    lines = voucher.get("lines") or []
    if len(lines) < 2:
        issues.append(Issue(number, "high", "行数", f"只有 {len(lines)} 行，凭证至少要一借一贷"))

    debit_total = sum(amount(line, "debit") for line in lines)
    credit_total = sum(amount(line, "credit") for line in lines)
    if abs(debit_total - credit_total) > TOLERANCE:
        issues.append(
            Issue(
                number, "high", "借贷平衡",
                f"借方 {debit_total:,.2f} ≠ 贷方 {credit_total:,.2f}，差 {debit_total - credit_total:,.2f}",
            )
        )
    if not lines:
        issues.append(Issue(number, "high", "空凭证", "没有任何分录行"))

    for index, line in enumerate(lines, start=1):
        debit = amount(line, "debit")
        credit = amount(line, "credit")
        if debit and credit:
            issues.append(Issue(number, "high", "借贷同填", f"第 {index} 行同时填了借方 {debit:,.2f} 和贷方 {credit:,.2f}"))
        if not debit and not credit:
            issues.append(Issue(number, "medium", "零金额", f"第 {index} 行借贷都是 0"))

    if not str(voucher.get("summary") or "").strip():
        issues.append(Issue(number, "medium", "摘要", "摘要为空"))

    when = parse_date(voucher.get("date"))
    start, end = period
    if when is None:
        issues.append(Issue(number, "medium", "日期", f"日期无法解析：{voucher.get('date')!r}"))
    else:
        if start and when < start:
            issues.append(Issue(number, "high", "跨期", f"{fmt_date(when)} 早于期间起点 {fmt_date(start)}"))
        if end and when > end:
            issues.append(Issue(number, "high", "跨期", f"{fmt_date(when)} 晚于期间终点 {fmt_date(end)}"))

    return issues


def check_numbering(vouchers: list[dict[str, Any]]) -> list[Issue]:
    """凭证号重复或跳号。只在编号是「前缀 + 数字」时可查。"""
    issues: list[Issue] = []
    seen: dict[str, int] = {}
    parsed: list[tuple[str, int]] = []
    for voucher in vouchers:
        number = str(voucher.get("no") or voucher.get("number") or "")
        if not number:
            continue
        seen[number] = seen.get(number, 0) + 1
        match = NUMBER_RE.search(number)
        if match:
            parsed.append((number, int(match.group(1))))

    for number, count in seen.items():
        if count > 1:
            issues.append(Issue(number, "high", "凭证号重复", f"编号 {number} 出现 {count} 次"))

    if len(parsed) >= 2:
        parsed.sort(key=lambda item: item[1])
        expected = parsed[0][1]
        last_number = parsed[0][0]
        for actual_number, actual in parsed:
            if actual > expected:
                issues.append(
                    Issue(
                        actual_number, "medium", "凭证号跳号",
                        f"{last_number}（{expected - 1}）之后直接是 {actual_number}（{actual}），"
                        f"缺 {actual - expected} 个号",
                    )
                )
                expected = actual + 1
            elif actual == expected:
                expected = actual + 1
            last_number = actual_number
    return issues


def run_checks(data: dict[str, Any]) -> list[Issue]:
    period_raw = data.get("period") or {}
    start = parse_date(period_raw.get("start"))
    end = parse_date(period_raw.get("end"))
    vouchers = data.get("vouchers") or []
    issues: list[Issue] = []
    for voucher in vouchers:
        issues.extend(check_voucher(voucher, (start, end)))
    issues.extend(check_numbering(vouchers))
    return issues


def render(issues: list[Issue], voucher_count: int) -> str:
    high = sum(1 for issue in issues if issue.level == "high")
    medium = sum(1 for issue in issues if issue.level == "medium")
    lines = ["# 凭证合规检查", "", f"- 凭证 {voucher_count} 张", ""]
    if not issues:
        lines.extend(["✓ 没有发现规则类问题", ""])
    else:
        lines.append("| 凭证号 | 级别 | 规则 | 详情 |")
        lines.append("|---|---|---|---|")
        order = {"high": 0, "medium": 1, "low": 2}
        for issue in sorted(issues, key=lambda item: (order.get(item.level, 9), item.voucher)):
            mark = "高" if issue.level == "high" else ("中" if issue.level == "medium" else "低")
            lines.append(f"| {issue.voucher} | {mark} | {issue.rule} | {issue.detail} |")
        lines.append("")
        lines.append(f"高 {high} 项 · 中 {medium} 项")
    lines.extend(
        [
            "",
            "> 只检查凭证格式与内部一致性（借贷、行数、日期、编号）。",
            "> 不判断科目使用是否正确，不判断业务是否真实。",
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
    vouchers = data.get("vouchers") or []
    issues = run_checks(data)
    if args.json:
        print(json.dumps(
            {"version": VERSION, "vouchers": len(vouchers), "issues": [dataclasses.asdict(i) for i in issues]},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(render(issues, len(vouchers)))
    return 1 if any(issue.level == "high" for issue in issues) else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "period": {"start": "2026-10-01", "end": "2026-10-31"},
        "vouchers": [
            {"no": "记-001", "date": "2026-10-05", "summary": "采购原材料",
             "lines": [{"account": "1403", "debit": 10000, "credit": 0},
                       {"account": "1002", "debit": 0, "credit": 10000}]},
            {"no": "记-002", "date": "2026-10-08", "summary": "支付运费",
             "lines": [{"account": "6601", "debit": 500, "credit": 0},
                       {"account": "1002", "debit": 0, "credit": 450}]},  # 借贷不平
            {"no": "记-004", "date": "2026-11-02", "summary": "",          # 跳号 + 跨期 + 空摘要
             "lines": [{"account": "6602", "debit": 300, "credit": 0},
                       {"account": "1002", "debit": 0, "credit": 300}]},
        ],
    }
    issues = run_checks(data)
    print(render(issues, len(data["vouchers"])))
    print("（示例故意埋了三类问题：借贷不平、跳号、跨期+空摘要）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vouchers.py", description="凭证合规检查")
    parser.add_argument("--version", action="version", version=f"vouchers {VERSION}")
    sub = parser.add_subparsers(dest="command")

    check = sub.add_parser("check", help="检查一份凭证 JSON")
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
