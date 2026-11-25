#!/usr/bin/env python3
"""periods — 多期对比与异常波动检测。

    python scripts/periods.py compare -i 两期数据.json
    python scripts/periods.py demo

对付的是「本期 vs 上期」：
    变动额、变动率、按绝对额排序、超过阈值的异常项、新增/消失的科目。

纯算术。它不说「这个变动是好是坏」，只说「这一项动得反常，值得看一眼」。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
DEFAULT_THRESHOLD = 0.30  # 变动率超过 30% 视为异常


@dataclasses.dataclass
class Change:
    code: str
    name: str
    before: float | None
    after: float | None
    delta: float
    rate: float | None      # None 表示上期为 0，无法算变动率
    status: str             # normal | abnormal | new | gone
    note: str = ""


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def to_map(accounts: list[dict[str, Any]]) -> dict[str, tuple[str, float]]:
    result: dict[str, tuple[str, float]] = {}
    for account in accounts:
        code = str(account.get("code") or account.get("科目编码") or "").strip()
        if not code:
            continue
        name = str(account.get("name") or account.get("科目名称") or code)
        result[code] = (name, num(account.get("closing", account.get("余额"))))
    return result


def compare(
    before: dict[str, tuple[str, float]],
    after: dict[str, tuple[str, float]],
    *,
    threshold: float,
    min_amount: float,
) -> list[Change]:
    changes: list[Change] = []
    for code in sorted(set(before) | set(after)):
        old = before.get(code)
        new = after.get(code)
        name = (new or old or (code, 0.0))[0]
        old_value = old[1] if old else None
        new_value = new[1] if new else None

        if old is None:
            changes.append(Change(code, name, None, new_value, new_value or 0.0, None, "new", "上期没有这个科目"))
            continue
        if new is None:
            changes.append(Change(code, name, old_value, None, -(old_value or 0.0), None, "gone", "本期没有这个科目"))
            continue

        delta = (new_value or 0.0) - (old_value or 0.0)
        if abs(old_value or 0.0) < 1e-9:
            rate = None
            status = "normal" if abs(delta) < min_amount else "abnormal"
            note = "上期余额为 0，只能看变动额"
        else:
            rate = delta / abs(old_value or 1.0)
            status = "abnormal" if abs(rate) >= threshold and abs(delta) >= min_amount else "normal"
            note = ""
        changes.append(Change(code, name, old_value, new_value, delta, rate, status, note))
    return changes


def render(changes: list[Change], meta: dict[str, Any], threshold: float, min_amount: float) -> str:
    abnormal = [c for c in changes if c.status == "abnormal"]
    new_items = [c for c in changes if c.status == "new"]
    gone_items = [c for c in changes if c.status == "gone"]
    top = sorted(changes, key=lambda c: -abs(c.delta))[:10]

    lines = [
        "# 多期对比",
        "",
        f"- 上期：{meta.get('period_a') or '—'} · 本期：{meta.get('period_b') or '—'}",
        f"- 科目 {len(changes)} 个 · **异常 {len(abnormal)}** · 新增 {len(new_items)} · 消失 {len(gone_items)}",
        f"- 判定标准：变动率 ≥ {threshold:.0%} 且变动额 ≥ {min_amount:,.2f}",
        "",
    ]

    if abnormal:
        lines.extend(["## 变动异常", "", "| 科目 | 上期 | 本期 | 变动额 | 变动率 |", "|---|---|---|---|---|"])
        for item in sorted(abnormal, key=lambda c: -abs(c.delta)):
            rate = "—" if item.rate is None else f"{item.rate:+.1%}"
            lines.append(
                f"| {item.code} {item.name} | {item.before:,.2f} | {item.after:,.2f} | "
                f"{item.delta:+,.2f} | {rate} |"
            )
        lines.append("")

    if top:
        lines.extend(["## 变动金额最大的十项", "", "| 科目 | 变动额 |", "|---|---|"])
        for item in top:
            lines.append(f"| {item.code} {item.name} | {item.delta:+,.2f} |")
        lines.append("")

    if new_items:
        lines.extend(["## 本期新增科目", ""])
        for item in new_items[:10]:
            lines.append(f"- {item.code} {item.name}：{item.after:,.2f}")
        lines.append("")

    if gone_items:
        lines.extend(["## 本期消失科目", ""])
        for item in gone_items[:10]:
            lines.append(f"- {item.code} {item.name}：上期 {item.before:,.2f}")
        lines.append("")

    lines.extend([
        "---",
        "",
        "> 只算变动，不判断好坏。变动大可能是业务增长，也可能是记错、重复入账或漏记。",
        "> 判定标准（阈值和金额下限）可调，默认 30% 且变动额不低于 1000 元。",
        "",
    ])
    return "\n".join(lines)


def cmd_compare(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2

    before = to_map(data.get("accounts_a") or data.get("上期") or [])
    after = to_map(data.get("accounts_b") or data.get("本期") or [])
    if not before and not after:
        print("error: 两期都没有科目数据", file=sys.stderr)
        return 2

    threshold = float(data.get("threshold") or DEFAULT_THRESHOLD)
    min_amount = float(data.get("min_amount") or 1000.0)
    changes = compare(before, after, threshold=threshold, min_amount=min_amount)
    meta = {"period_a": data.get("period_a"), "period_b": data.get("period_b")}

    if args.json:
        print(json.dumps({
            "version": VERSION,
            "changes": [dataclasses.asdict(c) for c in changes],
            "abnormal": sum(1 for c in changes if c.status == "abnormal"),
        }, ensure_ascii=False, indent=2))
    else:
        print(render(changes, meta, threshold, min_amount))
    return 1 if any(c.status == "abnormal" for c in changes) else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "period_a": "2026-09",
        "period_b": "2026-10",
        "accounts_a": [
            {"code": "6602", "name": "管理费用", "closing": 50000},
            {"code": "6001", "name": "主营业务收入", "closing": 3000000},
            {"code": "1122", "name": "应收账款", "closing": 400000},
            {"code": "1403", "name": "原材料", "closing": 200000},
        ],
        "accounts_b": [
            {"code": "6602", "name": "管理费用", "closing": 200000},
            {"code": "6001", "name": "主营业务收入", "closing": 3050000},
            {"code": "1122", "name": "应收账款", "closing": 420000},
            {"code": "1403", "name": "原材料", "closing": 210000},
            {"code": "6601", "name": "销售费用", "closing": 80000},
        ],
    }
    before = to_map(data["accounts_a"])
    after = to_map(data["accounts_b"])
    changes = compare(before, after, threshold=DEFAULT_THRESHOLD, min_amount=1000.0)
    print(render(changes, data, DEFAULT_THRESHOLD, 1000.0))
    print("（管理费用涨 300% 应被标出；销售费用是本期新增）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="periods.py", description="多期对比与异常波动")
    parser.add_argument("--version", action="version", version=f"periods {VERSION}")
    sub = parser.add_subparsers(dest="command")
    compare_cmd = sub.add_parser("compare", help="比较两期科目余额")
    compare_cmd.add_argument("-i", "--input", required=True)
    compare_cmd.add_argument("--json", action="store_true")
    compare_cmd.set_defaults(func=cmd_compare)
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
