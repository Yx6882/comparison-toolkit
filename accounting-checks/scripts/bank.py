#!/usr/bin/env python3
"""bank — 银行流水与账面记录的一对多匹配。

    python scripts/bank.py match -i 流水.json
    python scripts/bank.py demo

场景：账上记了一笔 10,000 的应收，银行流水里是三笔 3,000 + 2,000 + 5,000。
人工勾对要翻来覆去试，机器做子集和搜索。

只做金额组合匹配。它不知道哪笔流水对应哪个客户，也不判断业务真实性。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
MAX_SOLUTIONS = 5


@dataclasses.dataclass
class Match:
    target: str
    amount: float
    combination: list[str]
    total: float
    diff: float
    ambiguous: bool = False
    candidates: list[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass
class Ambiguity:
    """金额相同、无法区分的候选组。必须人工核对，不能自动分配。"""

    amount: float
    targets: list[str]
    transactions: list[str]
    reason: str


def num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def to_cents(value: float) -> int:
    return int(round(value * 100))


def find_combinations(
    target_cents: int,
    items: list[tuple[str, int]],
    *,
    tolerance_cents: int,
    max_size: int,
    limit: int = MAX_SOLUTIONS,
) -> list[list[tuple[str, int]]]:
    """Return up to `limit` subsets whose sum is within tolerance of target."""
    items = [item for item in items if item[1] > 0]
    items.sort(key=lambda pair: -pair[1])
    results: list[list[tuple[str, int]]] = []
    chosen: list[tuple[str, int]] = []

    def walk(start: int, remaining: int) -> None:
        if len(results) >= limit:
            return
        if abs(remaining) <= tolerance_cents and chosen:
            results.append(list(chosen))
            return
        if remaining < -tolerance_cents or len(chosen) >= max_size:
            return
        for index in range(start, len(items)):
            value = items[index][1]
            if value > remaining + tolerance_cents:
                continue
            chosen.append(items[index])
            walk(index + 1, remaining - value)
            chosen.pop()
            if len(results) >= limit:
                return

    walk(0, target_cents)
    return results


def match_all(data: dict[str, Any]) -> tuple[list[Match], list[dict], list[dict], list[Ambiguity]]:
    tolerance = abs(num(data.get("tolerance")) or 0.0)
    tolerance_cents = to_cents(tolerance)
    max_size = int(data.get("max_size") or 6)

    targets = list(data.get("targets") or [])
    transactions = list(data.get("transactions") or [])

    used: set[int] = set()
    matches: list[Match] = []
    ambiguities: list[Ambiguity] = []
    pending_targets = list(targets)

    def label_of(index: int, transaction: dict[str, Any]) -> str:
        return str(transaction.get("id") or f"#{index}")

    def label_of_target(target: dict[str, Any]) -> str:
        return str(target.get("id") or "?")

    # 先找出「同额多笔」的歧义组：金额完全相同、无法从数据上区分是谁的。
    # 这类必须先标出来，否则先匹配谁完全取决于输入顺序。
    target_by_cents: dict[int, list[dict[str, Any]]] = {}
    for target in targets:
        target_by_cents.setdefault(to_cents(num(target.get("amount"))), []).append(target)
    tx_by_cents: dict[int, list[int]] = {}
    for index, transaction in enumerate(transactions):
        tx_by_cents.setdefault(to_cents(num(transaction.get("amount"))), []).append(index)

    ambiguous_target_ids: set[str] = set()
    ambiguous_tx_indexes: set[int] = set()
    for cents, group in target_by_cents.items():
        tx_group = tx_by_cents.get(cents, [])
        # 同额但数量对不上（1账对2流水、2账对1流水）→ 无法判定谁对谁，标歧义。
        # 数量相等时可以一一配对：金额都一样，配哪对哪在会计上没有差别。
        if group and tx_group and len(group) != len(tx_group):
            ambiguities.append(
                Ambiguity(
                    amount=cents / 100,
                    targets=[label_of_target(t) for t in group],
                    transactions=[label_of(i, transactions[i]) for i in tx_group],
                    reason="金额相同、笔数不一致，缺少可区分的流水号或摘要，无法自动判定对应关系",
                )
            )
            ambiguous_target_ids.update(label_of_target(t) for t in group)
            ambiguous_tx_indexes.update(tx_group)

    # 第一轮：一对一精确匹配。会计勾对也是先对单笔，避免组合搜索抢走别家的钱。
    for target in list(pending_targets):
        target_label = label_of_target(target)
        if target_label in ambiguous_target_ids:
            continue  # 歧义组留到最后统一报告，不自动分配
        amount_cents = to_cents(num(target.get("amount")))
        for index, transaction in enumerate(transactions):
            if index in used:
                continue
            if abs(to_cents(num(transaction.get("amount"))) - amount_cents) <= tolerance_cents:
                used.add(index)
                matches.append(
                    Match(
                        target=target_label,
                        amount=num(target.get("amount")),
                        combination=[label_of(index, transaction)],
                        total=num(transaction.get("amount")),
                        diff=(amount_cents - to_cents(num(transaction.get("amount")))) / 100,
                    )
                )
                pending_targets.remove(target)
                break

    # 第二轮：剩余记录做组合搜索；优先笔数少的组合
    for target in pending_targets:
        if label_of_target(target) in ambiguous_target_ids:
            continue
        amount_cents = to_cents(num(target.get("amount")))
        available = [
            (label_of(index, transaction), to_cents(num(transaction.get("amount"))))
            for index, transaction in enumerate(transactions)
            if index not in used
        ]
        combos = find_combinations(
            amount_cents, available,
            tolerance_cents=tolerance_cents, max_size=max_size,
        )
        if not combos:
            continue
        best = sorted(combos, key=lambda combo: (len(combo), abs(sum(v for _, v in combo) - amount_cents)))[0]
        total_cents = sum(item[1] for item in best)
        for name, _value in best:
            for index, transaction in enumerate(transactions):
                if label_of(index, transaction) == name:
                    used.add(index)
                    break
        matches.append(
            Match(
                target=label_of_target(target),
                amount=num(target.get("amount")),
                combination=[name for name, _ in best],
                total=total_cents / 100,
                diff=(amount_cents - total_cents) / 100,
            )
        )

    unmatched_targets = [
        target for target in targets
        if label_of_target(target) not in {match.target for match in matches}
        and label_of_target(target) not in ambiguous_target_ids
    ]
    for target in targets:
        if label_of_target(target) in ambiguous_target_ids:
            continue
        if label_of_target(target) not in {match.target for match in matches} and target not in unmatched_targets:
            unmatched_targets.append(target)
    unmatched_transactions = [
        transaction for index, transaction in enumerate(transactions)
        if index not in used and index not in ambiguous_tx_indexes
    ]
    return matches, unmatched_targets, unmatched_transactions, ambiguities


def render(data: dict[str, Any], matches: list[Match], missed_targets: list[dict],
           missed_tx: list[dict], ambiguities: list[Ambiguity]) -> str:
    targets = data.get("targets") or []
    transactions = data.get("transactions") or []
    lines = [
        "# 银行流水匹配",
        "",
        f"- 账面记录 {len(targets)} 笔 · 银行流水 {len(transactions)} 笔",
        f"- 容差 {num(data.get('tolerance')):,.2f} 元（手续费/利息）",
        "",
    ]
    if matches:
        lines.extend(["## 已匹配", "", "| 账面 | 金额 | 银行流水组合 | 合计 | 差额 |", "|---|---|---|---|---|"])
        for match in matches:
            combo = " + ".join(match.combination)
            lines.append(
                f"| {match.target} | {match.amount:,.2f} | {combo} | {match.total:,.2f} | {match.diff:,.2f} |"
            )
        lines.append("")
    if ambiguities:
        lines.extend(
            [
                "## 歧义（需人工确认）",
                "",
                "金额相同、又缺少可区分的流水号或摘要，工具**不猜**归属。",
                "",
            ]
        )
        for ambiguity in ambiguities:
            lines.append(
                f"- **{ambiguity.amount:,.2f} 元**：账面 {('、'.join(ambiguity.targets))} "
                f"↔ 流水 {('、'.join(ambiguity.transactions))}"
            )
            lines.append(f"  - {ambiguity.reason}")
        lines.append("")
    if missed_targets:
        lines.extend(["## 未匹配的账面记录", ""])
        for target in missed_targets:
            lines.append(f"- {target.get('id')} · {num(target.get('amount')):,.2f} · {target.get('desc') or ''}")
        lines.append("")
    if missed_tx:
        lines.extend(["## 未匹配的流水", ""])
        for transaction in missed_tx:
            lines.append(
                f"- {transaction.get('date') or ''} · {num(transaction.get('amount')):,.2f} · "
                f"{transaction.get('desc') or ''}"
            )
        lines.append("")
    if not matches and not missed_targets and not ambiguities:
        lines.extend(["没有需要匹配的记录", ""])
    lines.extend(
        [
            "---",
            "",
            "> 只做金额组合搜索，不判断对应关系是否正确。",
            "> 同额多笔会标成「歧义」而不是硬配——结论不该取决于输入顺序。",
            "> 组合数超过上限时只列前几组，请人工确认。",
            "",
        ]
    )
    return "\n".join(lines)


def cmd_match(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    matches, missed_targets, missed_tx, ambiguities = match_all(data)
    if args.json:
        print(json.dumps(
            {
                "version": VERSION,
                "matches": [dataclasses.asdict(m) for m in matches],
                "ambiguous": [dataclasses.asdict(a) for a in ambiguities],
                "unmatched_targets": [t.get("id") for t in missed_targets],
                "unmatched_transactions": len(missed_tx),
            },
            ensure_ascii=False, indent=2,
        ))
    else:
        print(render(data, matches, missed_targets, missed_tx, ambiguities))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "tolerance": 1.00,
        "targets": [
            {"id": "A-001", "amount": 10000, "desc": "客户甲货款"},
            {"id": "A-002", "amount": 6800, "desc": "客户乙货款"},
            {"id": "A-003", "amount": 25000, "desc": "客户丙货款（收不到）"},
        ],
        "transactions": [
            {"id": "T1", "date": "2026-10-06", "amount": 3000, "desc": "回款"},
            {"id": "T2", "date": "2026-10-07", "amount": 2000, "desc": "回款"},
            {"id": "T3", "date": "2026-10-08", "amount": 5000, "desc": "回款"},
            {"id": "T4", "date": "2026-10-09", "amount": 6800, "desc": "回款"},
            {"id": "T5", "date": "2026-10-10", "amount": 1200, "desc": "利息"},
        ],
    }
    matches, missed_targets, missed_tx, ambiguities = match_all(data)
    print(render(data, matches, missed_targets, missed_tx, ambiguities))
    print("（A-001 由三笔凑成 10000，A-002 单笔 6800，A-003 找不到组合）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bank.py", description="银行流水一对多匹配")
    parser.add_argument("--version", action="version", version=f"bank {VERSION}")
    sub = parser.add_subparsers(dest="command")
    match = sub.add_parser("match", help="匹配一份流水 JSON")
    match.add_argument("-i", "--input", required=True)
    match.add_argument("--json", action="store_true")
    match.set_defaults(func=cmd_match)
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
