#!/usr/bin/env python3
"""trend — 跨期趋势：这一期的差异，下一期还在不在。

    python scripts/trend.py run --prev 上期.json --curr 本期.json
    python scripts/trend.py run --prev 上期/ --curr 本期/          # 自动找 reconcile-*.json
    python scripts/trend.py demo

对账真正的价值不在「这一期差了多少」，而在「同一批差异是不是一直存在」：

    已解决  = 上期有、本期无
    新增    = 上期无、本期有
    持续    = 两期都有；严重度上升记「恶化」
    已变化  = 两期都有但数值变了

差异的身份 = `类型 | 键 | 字段`。同一个键的同一个字段，跨期才算「同一件事」。
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclasses.dataclass
class Item:
    identity: str
    kind: str
    key: str
    field: str
    severity: str
    left: str = ""
    right: str = ""
    delta: float | None = None
    note: str = ""


@dataclasses.dataclass
class Delta:
    status: str  # resolved | new | persistent | worsened
    item: Item
    prev: Item | None = None


def load_report(path: Path) -> dict[str, Any]:
    if path.is_dir():
        candidates = sorted(path.glob("*.json"))
        if not candidates:
            raise SystemExit(f"{path}: 目录里没有 json 报告")
        # 选最新的一个
        path = max(candidates, key=lambda p: p.stat().st_mtime)
    if not path.exists():
        raise SystemExit(f"报告不存在：{path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: 不是合法 JSON（{exc}）")


def identity_key(text: str) -> str:
    """Normalise a key before comparing across periods.

    两期报告可能来自不同数据源：`M-1001` 和 `m-1001` 是同一个物料。
    如果不归一化，同一个持续两期的问题会被判成「上期解决 + 本期新增」。
    """
    return re.sub(r"[\s_\-]+", "", str(text or "")).lower()


def to_items(report: dict[str, Any]) -> list[Item]:
    raw = report.get("diffs") or report.get("items") or []
    items: list[Item] = []
    for entry in raw:
        kind = str(entry.get("kind") or entry.get("type") or "diff")
        key = str(entry.get("key") or entry.get("label") or "")
        field = str(entry.get("field") or entry.get("label") or "")
        identity = f"{identity_key(kind)}|{identity_key(key)}|{identity_key(field)}"
        items.append(
            Item(
                identity=identity,
                kind=kind,
                key=key,
                field=field,
                severity=str(entry.get("severity") or "medium"),
                left=str(entry.get("left") or ""),
                right=str(entry.get("right") or ""),
                delta=entry.get("delta"),
                note=str(entry.get("note") or ""),
            )
        )
    return items


def compare_periods(prev: list[Item], curr: list[Item]) -> list[Delta]:
    prev_by_id: dict[str, Item] = {}
    for item in prev:
        prev_by_id.setdefault(item.identity, item)
    curr_by_id: dict[str, Item] = {}
    for item in curr:
        curr_by_id.setdefault(item.identity, item)

    deltas: list[Delta] = []
    for identity, item in curr_by_id.items():
        before = prev_by_id.get(identity)
        if before is None:
            deltas.append(Delta("new", item))
            continue
        if SEVERITY_RANK.get(item.severity, 1) > SEVERITY_RANK.get(before.severity, 1):
            deltas.append(Delta("worsened", item, before))
        else:
            deltas.append(Delta("persistent", item, before))
    for identity, item in prev_by_id.items():
        if identity not in curr_by_id:
            deltas.append(Delta("resolved", item, prev=item))
    order = {"worsened": 0, "new": 1, "persistent": 2, "resolved": 3}
    deltas.sort(key=lambda delta: (order.get(delta.status, 9), delta.item.key))
    return deltas


def render(deltas: list[Delta], prev_path: Path, curr_path: Path, prev_meta: dict[str, Any], curr_meta: dict[str, Any]) -> str:
    counts = {status: sum(1 for d in deltas if d.status == status) for status in ("new", "worsened", "persistent", "resolved")}
    lines = [
        "# 跨期趋势",
        "",
        f"- 上期：`{prev_path}`" + (f"（{prev_meta.get('generated_at', '')}）" if prev_meta.get("generated_at") else ""),
        f"- 本期：`{curr_path}`" + (f"（{curr_meta.get('generated_at', '')}）" if curr_meta.get("generated_at") else ""),
        f"- 生成时间：{dt.datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"**新增 {counts['new']} · 恶化 {counts['worsened']} · 持续 {counts['persistent']} · 已解决 {counts['resolved']}**",
        "",
        "> 差异的身份 = `类型 | 键 | 字段`。只有同一身份跨期才算「同一件事」。",
        "",
    ]

    def section(title: str, status: str, note: str = "") -> None:
        items = [d for d in deltas if d.status == status]
        if not items:
            return
        lines.extend([f"## {title}（{len(items)}）", ""])
        if note:
            lines.extend([note, ""])
        lines.append("| 键 | 字段 | 上期 | 本期 | 严重度 |")
        lines.append("|---|---|---|---|---|")
        for delta in items:
            def show(left: str, right: str) -> str:
                left, right = (left or "").strip(), (right or "").strip()
                if left and right and left != right:
                    return f"{left} → {right}"
                return left or right or "—"

            before = show(delta.prev.left, delta.prev.right) if delta.prev else "—"
            after = "—" if status == "resolved" else show(delta.item.left, delta.item.right)
            lines.append(f"| {delta.item.key} | {delta.item.field} | {before} | {after} | {delta.item.severity} |")
        lines.append("")

    section("新增", "new", "这些是本期才出现的，先确认是不是真的新问题。")
    section("恶化", "worsened", "同一件事，本期更严重了。")
    section("持续", "persistent", "两期都在。持续越久，越可能是流程问题而不是笔误。")
    section("已解决", "resolved", "上期有、本期没了。")

    if counts["new"] == 0 and counts["worsened"] == 0 and counts["persistent"] == 0:
        lines.extend(["## 结论", "", "本期没有发现新的差异，上期的问题也已清零。", ""])
    elif counts["persistent"] >= 3:
        lines.extend(
            [
                "## 结论",
                "",
                f"有 {counts['persistent']} 项连续两期没解决——建议查流程，而不是逐条改。",
                "",
            ]
        )

    lines.extend(
        [
            "---",
            "",
            "> 趋势只比较「差异的身份」，不判断业务对错。",
            "> 两期必须来自同一类对照（同一对文件/同一张凭证表），否则键对不上。",
            "",
        ]
    )
    return "\n".join(lines)


def run_trend(prev_path: Path, curr_path: Path, out: Path) -> dict[str, Any]:
    prev_report = load_report(prev_path)
    curr_report = load_report(curr_path)
    prev_items = to_items(prev_report)
    curr_items = to_items(curr_report)
    if not prev_items and not curr_items:
        raise SystemExit("两期报告都没有差异条目，无法比较趋势")
    deltas = compare_periods(prev_items, curr_items)
    report = render(deltas, prev_path, curr_path, prev_report, curr_report)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "trend.md"
    target.write_text(report, encoding="utf-8")
    counts = {status: sum(1 for d in deltas if d.status == status) for status in ("new", "worsened", "persistent", "resolved")}
    (out / "trend.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "prev": str(prev_path),
                "curr": str(curr_path),
                "counts": counts,
                "deltas": [
                    {
                        "status": delta.status,
                        "key": delta.item.key,
                        "field": delta.item.field,
                        "severity": delta.item.severity,
                    }
                    for delta in deltas
                ],
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"新增 {counts['new']} · 恶化 {counts['worsened']} · 持续 {counts['persistent']} · 已解决 {counts['resolved']}")
    print(f"report: {target}")
    return {"deltas": deltas, "report": report, "counts": counts}


def build_demo(target: Path) -> tuple[Path, Path]:
    target.mkdir(parents=True, exist_ok=True)
    prev = {
        "version": "x", "mode": "record", "generated_at": "2026-10-01T09:00:00+08:00",
        "diffs": [
            {"kind": "value", "key": "M-1001", "field": "单价", "left": "12000", "right": "11800", "severity": "high"},
            {"kind": "value", "key": "M-1002", "field": "单价", "left": "500", "right": "520", "severity": "high"},
            {"kind": "only_left", "key": "M-1004", "field": "仅左侧存在", "severity": "medium"},
            {"kind": "text", "key": "合同条款3", "field": "文字表述", "severity": "medium"},
        ],
    }
    curr = {
        "version": "x", "mode": "record", "generated_at": "2026-11-01T09:00:00+08:00",
        "diffs": [
            {"kind": "value", "key": "M-1001", "field": "单价", "left": "11800", "right": "11500", "severity": "high"},
            {"kind": "only_left", "key": "M-1004", "field": "仅左侧存在", "severity": "medium"},
            {"kind": "value", "key": "M-1009", "field": "金额", "left": "900", "right": "1200", "severity": "high"},
            {"kind": "text", "key": "合同条款5", "field": "文字表述", "severity": "low"},
        ],
    }
    prev_path = target / "prev.json"
    curr_path = target / "curr.json"
    prev_path.write_text(json.dumps(prev, ensure_ascii=False, indent=2), encoding="utf-8")
    curr_path.write_text(json.dumps(curr, ensure_ascii=False, indent=2), encoding="utf-8")
    return prev_path, curr_path


def cmd_demo(args: argparse.Namespace) -> int:
    root = Path(args.out or "trend-demo")
    prev_path, curr_path = build_demo(root)
    result = run_trend(prev_path, curr_path, root / "out")
    print(result["report"][:1200])
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    run_trend(Path(args.prev), Path(args.curr), Path(args.out or "trend-out"))
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    prev = [Item("value|A|价格", "value", "A", "价格", "high", left="10")]
    curr = [
        Item("value|A|价格", "value", "A", "价格", "high", left="12"),
        Item("value|B|价格", "value", "B", "价格", "high", left="20"),
    ]
    deltas = compare_periods(prev, curr)
    statuses = {d.status for d in deltas}
    checks = [
        ("新增被识别", any(d.status == "new" and d.item.key == "B" for d in deltas)),
        ("持续被识别", any(d.status == "persistent" and d.item.key == "A" for d in deltas)),
        ("没有误报已解决", not any(d.status == "resolved" for d in deltas)),
    ]
    prev2 = [Item("value|C|价格", "value", "C", "价格", "medium")]
    deltas2 = compare_periods(prev2, [])
    checks.append(("已解决被识别", deltas2 and deltas2[0].status == "resolved"))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trend.py", description="跨期趋势：差异的收敛跟踪")
    parser.add_argument("--version", action="version", version=f"trend {VERSION}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="比较两期报告")
    run.add_argument("--prev", required=True)
    run.add_argument("--curr", required=True)
    run.add_argument("-o", "--out", default="")
    run.set_defaults(func=cmd_run)

    demo = sub.add_parser("demo", help="造两期样例并跑")
    demo.add_argument("-o", "--out", default="")
    demo.set_defaults(func=cmd_demo)

    selftest = sub.add_parser("selftest", help="内置自检")
    selftest.set_defaults(func=cmd_selftest)
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
