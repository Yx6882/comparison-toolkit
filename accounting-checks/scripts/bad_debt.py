#!/usr/bin/env python3
"""bad_debt — 应收账款账龄分析与坏账准备计提。

    python scripts/bad_debt.py calc -i 应收.json
    python scripts/bad_debt.py demo

按账龄分组，乘以各组的计提比例，算出应计提的坏账准备，
再和账上已有的准备对比，得出补提或冲回金额。

只做金额计算。计提比例是会计估计，工具不判断比例是否合理。
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
DATE_RE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")


@dataclasses.dataclass
class Bucket:
    label: str
    amount: float
    rate: float
    provision: float


@dataclasses.dataclass
class Result:
    buckets: list[Bucket]
    total_receivable: float
    required_provision: float
    existing_provision: float
    adjustment: float  # 正数=补提，负数=冲回


def parse_date(text: Any) -> tuple[int, int, int] | None:
    match = DATE_RE.search(str(text or ""))
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.groups())  # type: ignore[return-value]
    except ValueError:
        return None


def days_between(start: tuple[int, int, int], end: tuple[int, int, int]) -> int:
    import datetime as dt

    a = dt.date(*start)
    b = dt.date(*end)
    return (b - a).days


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def calculate(data: dict[str, Any]) -> tuple[Result | None, list[str]]:
    issues: list[str] = []
    as_of = parse_date(data.get("as_of"))
    if as_of is None:
        return None, ["缺少或无法解析 as_of 日期（YYYY-MM-DD）"]

    rules = data.get("buckets") or [
        {"max_days": 30, "rate": 0.05},
        {"max_days": 90, "rate": 0.10},
        {"max_days": 180, "rate": 0.30},
        {"max_days": 365, "rate": 0.50},
        {"max_days": None, "rate": 1.00},
    ]
    prepared: list[tuple[float | None, float]] = []
    for rule in rules:
        max_days = rule.get("max_days")
        prepared.append((None if max_days is None else float(max_days), num(rule.get("rate"))))
    prepared.sort(key=lambda item: (item[0] is None, item[0] if item[0] is not None else 0))

    buckets: list[Bucket] = []
    for index, (max_days, rate) in enumerate(prepared):
        previous = prepared[index - 1][0] if index else None
        if max_days is None:
            label = f"> {previous:.0f} 天" if previous is not None else "全部"
        elif previous is None:
            label = f"≤ {max_days:.0f} 天"
        else:
            # 左开右闭：上一档上限 +1 到本档上限，避免「90–180」不知道 91 天算哪档
            label = f"{previous + 1:.0f}–{max_days:.0f} 天"
        buckets.append(Bucket(label, 0.0, rate, 0.0))

    total = 0.0
    for item in data.get("receivables") or []:
        amount = num(item.get("amount"))
        due = parse_date(item.get("due_date") or item.get("invoice_date"))
        if due is None:
            issues.append(f"客户 {item.get('customer') or '?'} 缺少到期日，已跳过")
            continue
        if amount <= 0:
            issues.append(f"客户 {item.get('customer') or '?'} 金额非正（{amount}），已跳过")
            continue
        age = days_between(due, as_of)
        if age < 0:
            issues.append(f"客户 {item.get('customer') or '?'} 到期日在 as_of 之后，账龄按 0 计")
            age = 0
        total += amount
        for bucket, (max_days, _rate) in zip(buckets, prepared):
            if max_days is None or age <= max_days:
                bucket.amount += amount
                break

    for bucket in buckets:
        bucket.provision = round(bucket.amount * bucket.rate, 2)

    required = round(sum(bucket.provision for bucket in buckets), 2)
    existing = num(data.get("existing_provision"))
    return (
        Result(
            buckets=buckets,
            total_receivable=round(total, 2),
            required_provision=required,
            existing_provision=existing,
            adjustment=round(required - existing, 2),
        ),
        issues,
    )


def render(result: Result | None, issues: list[str]) -> str:
    lines = ["# 坏账准备计提", ""]
    if issues:
        lines.extend(["## 检查提示", ""] + [f"- {issue}" for issue in issues] + [""])
    if not result:
        return "\n".join(lines)

    lines.extend([
        f"- 应收账款合计 **{result.total_receivable:,.2f}**",
        "",
        "| 账龄 | 金额 | 计提比例 | 应计提 |",
        "|---|---|---|---|",
    ])
    for bucket in result.buckets:
        if bucket.amount == 0 and bucket.provision == 0:
            continue
        lines.append(f"| {bucket.label} | {bucket.amount:,.2f} | {bucket.rate:.0%} | {bucket.provision:,.2f} |")

    lines.extend([
        "",
        f"- 应计提坏账准备 **{result.required_provision:,.2f}**",
        f"- 账面已有 **{result.existing_provision:,.2f}**",
    ])
    if abs(result.adjustment) < 0.01:
        lines.append("- 无需调整")
    elif result.adjustment > 0:
        lines.extend([
            f"- **需补提 {result.adjustment:,.2f}**",
            "",
            "```",
            f"借：信用减值损失        {result.adjustment:,.2f}",
            f"    贷：坏账准备          {result.adjustment:,.2f}",
            "```",
        ])
    else:
        lines.extend([
            f"- **需冲回 {-result.adjustment:,.2f}**",
            "",
            "```",
            f"借：坏账准备            {-result.adjustment:,.2f}",
            f"    贷：信用减值损失      {-result.adjustment:,.2f}",
            "```",
        ])

    lines.extend([
        "",
        "---",
        "",
        "> 只按给定账龄和比例计算金额。计提比例是会计估计，工具不判断其合理性。",
        "> 分录方向按《企业会计准则第 22 号》的常规处理，实际以企业会计政策为准。",
        "",
    ])
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
    result, issues = calculate(data)
    if args.json:
        payload = {"version": VERSION, "issues": issues}
        if result:
            payload["result"] = {
                "buckets": [dataclasses.asdict(b) for b in result.buckets],
                "total_receivable": result.total_receivable,
                "required_provision": result.required_provision,
                "existing_provision": result.existing_provision,
                "adjustment": result.adjustment,
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render(result, issues))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "as_of": "2026-10-31",
        "existing_provision": 3000,
        "receivables": [
            {"customer": "甲公司", "amount": 50000, "due_date": "2026-10-15"},
            {"customer": "乙公司", "amount": 30000, "due_date": "2026-08-01"},
            {"customer": "丙公司", "amount": 20000, "due_date": "2026-03-01"},
            {"customer": "丁公司", "amount": 10000, "due_date": "2025-06-01"},
        ],
    }
    result, issues = calculate(data)
    print(render(result, issues))
    print("（账龄：甲 16 天 / 乙 91 天 / 丙 244 天 / 丁 517 天）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bad_debt.py", description="坏账准备账龄分析")
    parser.add_argument("--version", action="version", version=f"bad_debt {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份应收 JSON")
    calc.add_argument("-i", "--input", required=True)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(func=cmd_calc)
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
