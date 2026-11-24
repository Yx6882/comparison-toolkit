#!/usr/bin/env python3
"""ledger_match — explain a summary ledger with a detail ledger.

One sheet says "2000". Another sheet says "500, 500, 500, 500". Are they the
same money? Usually yes, but the honest answer is a *set* of candidates, because
2000 can also be 1200+800 or 1000+500+500. This tool finds the combinations,
prefers the explanation with the fewest lines, and reports the ambiguity
instead of hiding it.

    python scripts/ledger_match.py demo
    python scripts/ledger_match.py match --summary 汇总.xlsx --detail 明细.xlsx \
        --summary-col 总价 --detail-col 金额

Standard library + openpyxl. No network.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "0.1.0"
MONEY_RE = re.compile(r"[-+]?\d[\d,，]*(?:\.\d+)?")
NEGATIVE_MARKERS = {"退款", "冲红", "折让", "credit", "refund"}

# ---------------------------------------------------------------------------
# Reading spreadsheets
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Line:
    sheet: str
    row: int
    raw: str
    amount: float
    label: str = ""

    @property
    def ref(self) -> str:
        return f"{self.sheet}!行{self.row}"


def parse_money(value: Any) -> float | None:
    """Accept 2000, '2,000.00', '¥2000', '(500)' (= -500), '2000 元'."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "—", "/", "N/A", "n/a", "无"}:
        return None
    negative = text.startswith("(") and text.endswith(")") or text.startswith("（")
    for marker in NEGATIVE_MARKERS:
        if marker in text.lower():
            negative = True
    cleaned = re.sub(r"[¥￥$€\s元人民币]", "", text).strip("()（）")
    match = MONEY_RE.search(cleaned)
    if not match:
        return None
    number = float(match.group(0).replace(",", "").replace("，", ""))
    return -number if negative else number


def resolve_column(header: Sequence[Any], spec: str) -> int:
    """Column can be a header name, a letter (C), or a 1-based index."""
    wanted = spec.strip()
    for index, cell in enumerate(header):
        if cell is not None and str(cell).strip() == wanted:
            return index
    if re.fullmatch(r"[A-Za-z]{1,3}", wanted):
        total = 0
        for char in wanted.upper():
            total = total * 26 + (ord(char) - 64)
        return total - 1
    if wanted.isdigit():
        return int(wanted) - 1
    raise SystemExit(f"column {spec!r} not found in header {[str(c) for c in header]}")


def read_sheet(
    path: Path,
    column: str,
    *,
    sheet: str | None = None,
    label_column: str | None = None,
    header_row: int = 1,
) -> list[Line]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit("openpyxl is required (pip install openpyxl)")

    wb = load_workbook(str(path), read_only=True, data_only=True)
    if sheet:
        if sheet not in wb.sheetnames:
            raise SystemExit(f"sheet {sheet!r} not found; available: {wb.sheetnames}")
        worksheets = [wb[sheet]]
    else:
        worksheets = list(wb.worksheets)

    lines: list[Line] = []
    for ws in worksheets:
        rows = list(ws.iter_rows(values_only=True))
        if len(rows) < header_row:
            continue
        header = rows[header_row - 1]
        col_index = resolve_column(header, column)
        label_index = None
        if label_column:
            try:
                label_index = resolve_column(header, label_column)
            except SystemExit:
                label_index = 0 if col_index != 0 else None
        for offset, row in enumerate(rows[header_row:], start=header_row + 1):
            if col_index >= len(row):
                continue
            amount = parse_money(row[col_index])
            if amount is None:
                continue
            label = ""
            if label_index is not None and label_index < len(row) and row[label_index] is not None:
                label = str(row[label_index]).strip()
            lines.append(
                Line(sheet=ws.title, row=offset, raw=str(row[col_index]), amount=amount, label=label)
            )
    wb.close()
    return lines


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Match:
    total: Line
    lines: list[Line]
    status: str  # matched | ambiguous | unmatched
    alternatives: list[list[Line]] = dataclasses.field(default_factory=list)

    @property
    def explained(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)


def find_combinations(
    target: float,
    pool: Sequence[Line],
    *,
    tolerance: float,
    max_items: int,
    max_solutions: int,
) -> list[list[Line]]:
    """All ways to reach target from pool, capped. Largest-first pruning."""
    candidates = sorted(
        (line for line in pool if line.amount > 0 and line.amount <= target + tolerance),
        key=lambda line: -line.amount,
    )
    solutions: list[list[Line]] = []

    def walk(start: int, remaining: float, chosen: list[Line]) -> None:
        if len(solutions) >= max_solutions:
            return
        if chosen and abs(remaining) <= tolerance:
            solutions.append(list(chosen))
            return
        if len(chosen) >= max_items:
            return
        for index in range(start, len(candidates)):
            line = candidates[index]
            if line.amount > remaining + tolerance:
                continue
            chosen.append(line)
            walk(index + 1, remaining - line.amount, chosen)
            chosen.pop()
            if len(solutions) >= max_solutions:
                return

    walk(0, target, [])
    return solutions


def reconcile(
    summaries: Sequence[Line],
    details: Sequence[Line],
    *,
    tolerance: float = 0.01,
    max_items: int = 12,
    max_solutions: int = 4,
) -> tuple[list[Match], list[Line]]:
    """Assign detail lines to summary totals, biggest total first.

    A greedy order plus a global pool: each detail line can only be spent once,
    which is what makes the result usable as an explanation rather than a list
    of coincidences.
    """
    remaining = list(details)
    matches: list[Match] = []
    for summary in sorted(summaries, key=lambda line: -line.amount):
        solutions = find_combinations(
            summary.amount,
            remaining,
            tolerance=tolerance,
            max_items=max_items,
            max_solutions=max_solutions,
        )
        if not solutions:
            matches.append(Match(total=summary, lines=[], status="unmatched"))
            continue
        chosen = min(solutions, key=len)  # fewest lines is the most likely story
        for line in chosen:
            remaining.remove(line)
        matches.append(
            Match(
                total=summary,
                lines=chosen,
                status="ambiguous" if len(solutions) > 1 else "matched",
                alternatives=[s for s in solutions if s is not chosen][:2],
            )
        )
    return matches, remaining


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def money(value: float) -> str:
    return f"{value:,.2f}"


def render_console(matches: Sequence[Match], leftover: Sequence[Line]) -> str:
    lines: list[str] = []
    matched = sum(1 for m in matches if m.status == "matched")
    ambiguous = sum(1 for m in matches if m.status == "ambiguous")
    unmatched = sum(1 for m in matches if m.status == "unmatched")
    lines.append(
        f"汇总 {len(matches)} 笔 · 唯一解释 {matched} · 有多种解释 {ambiguous} · 找不到来源 {unmatched}"
    )
    lines.append("")
    for match in matches:
        if match.status == "unmatched":
            lines.append(f"  {money(match.total.amount):>12}  ✗ 找不到组合  （{match.total.ref}）")
            continue
        parts = " + ".join(money(line.amount) for line in match.lines)
        flag = "?" if match.status == "ambiguous" else "="
        refs = ", ".join(line.ref.replace(match.lines[0].sheet + "!", "") for line in match.lines)
        lines.append(f"  {money(match.total.amount):>12}  {flag}  {parts}   ({refs})")
        if match.status == "ambiguous":
            for alt in match.alternatives:
                alt_parts = " + ".join(money(line.amount) for line in alt)
                lines.append(f"  {'':>12}    ? 也可解释为 {alt_parts}")
    if leftover:
        lines.append("")
        lines.append(f"未被使用的明细 {len(leftover)} 笔，合计 {money(sum(l.amount for l in leftover))}")
        for line in leftover[:10]:
            lines.append(f"  - {money(line.amount):>12}  {line.ref}")
        if len(leftover) > 10:
            lines.append(f"  … 另外 {len(leftover) - 10} 笔")
    return "\n".join(lines)


def render_markdown(
    summary_path: Path,
    detail_path: Path,
    matches: Sequence[Match],
    leftover: Sequence[Line],
) -> str:
    matched = sum(1 for m in matches if m.status == "matched")
    ambiguous = sum(1 for m in matches if m.status == "ambiguous")
    unmatched = sum(1 for m in matches if m.status == "unmatched")
    explained = sum(m.total.amount for m in matches if m.status != "unmatched")
    total = sum(m.total.amount for m in matches)
    lines = [
        "# 账目匹配报告",
        "",
        f"- 汇总表：`{summary_path}`",
        f"- 明细表：`{detail_path}`",
        f"- 生成时间：{dt.datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- 汇总 {len(matches)} 笔，合计 {money(total)}；已解释 {money(explained)} "
        f"（{explained / total * 100 if total else 0:.1f}%）",
        f"- 唯一解释 {matched} · 多解 {ambiguous} · 无解 {unmatched}",
        "",
        "> 组合求和可能有多解。标 `多解` 的条目给出了备选，请结合凭证号、日期或供应商确认。",
        "",
        "## 匹配结果",
        "",
        "| 汇总金额 | 来源 | 状态 |",
        "|---|---|---|",
    ]
    for match in matches:
        if match.status == "unmatched":
            lines.append(f"| {money(match.total.amount)} | — | **无解** |")
            continue
        parts = " + ".join(f"{money(line.amount)}（{line.ref}）" for line in match.lines)
        status = "多解" if match.status == "ambiguous" else "唯一"
        lines.append(f"| {money(match.total.amount)} | {parts} | {status} |")
    if leftover:
        lines.extend(["", f"## 未使用的明细（{len(leftover)} 笔）", "", "| 金额 | 位置 |", "|---|---|"])
        for line in leftover:
            lines.append(f"| {money(line.amount)} | {line.ref} |")
    lines.extend(
        [
            "",
            "---",
            "",
            "## 口径提醒",
            "",
            "- 只匹配正数金额；退款/红字需要单独处理",
            "- 容差默认 0.01，四舍五入造成的分差会被吸收",
            "- 含税/不含税混在两张表里时，先统一口径再跑",
            "- 一笔明细只能被用一次；分摊场景会显示为“无解”，需要人工拆分",
            "",
        ]
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def run_match(args: argparse.Namespace) -> int:
    summary_lines = read_sheet(
        Path(args.summary), args.summary_col, sheet=args.summary_sheet, label_column=args.summary_label
    )
    detail_lines = read_sheet(
        Path(args.detail), args.detail_col, sheet=args.detail_sheet, label_column=args.detail_label
    )
    if not summary_lines:
        print("error: no amounts found in the summary sheet", file=sys.stderr)
        return 2
    if not detail_lines:
        print("error: no amounts found in the detail sheet", file=sys.stderr)
        return 2

    matches, leftover = reconcile(
        summary_lines,
        detail_lines,
        tolerance=args.tolerance,
        max_items=args.max_items,
    )
    print(render_console(matches, leftover))

    out = Path(args.out or "ledger-report")
    out.mkdir(parents=True, exist_ok=True)
    (out / "ledger-match.md").write_text(
        render_markdown(Path(args.summary), Path(args.detail), matches, leftover), encoding="utf-8"
    )
    (out / "ledger-match.json").write_text(
        json.dumps(
            {
                "version": VERSION,
                "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                "matches": [
                    {
                        "total": dataclasses.asdict(m.total),
                        "status": m.status,
                        "lines": [dataclasses.asdict(line) for line in m.lines],
                        "alternatives": [[dataclasses.asdict(line) for line in alt] for alt in m.alternatives],
                    }
                    for m in matches
                ],
                "unused": [dataclasses.asdict(line) for line in leftover],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nreport: {out / 'ledger-match.md'}")
    if args.fail_on_unmatched and any(m.status == "unmatched" for m in matches):
        return 1
    return 0


def build_demo(target: Path) -> None:
    try:
        from openpyxl import Workbook
    except ImportError:
        raise SystemExit("demo needs openpyxl (pip install openpyxl)")
    target.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "汇总"
    ws.append(["客户", "总价"])
    ws.append(["A 公司", 2000])
    ws.append(["B 公司", 1200])
    ws.append(["C 公司", 1500])
    wb.save(target / "汇总表.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "明细"
    ws.append(["单号", "金额", "备注"])
    for index, (order, amount) in enumerate(
        [("SO-1001", 500), ("SO-1002", 500), ("SO-1003", 500), ("SO-1004", 500), ("SO-1005", 1200)],
        start=1,
    ):
        ws.append([order, amount, ""])
    wb.save(target / "明细表.xlsx")


def cmd_demo(args: argparse.Namespace) -> int:
    root = Path(args.out or "ledger-demo")
    build_demo(root)
    print(f"demo files written to {root}")
    return run_match(
        argparse.Namespace(
            summary=str(root / "汇总表.xlsx"),
            detail=str(root / "明细表.xlsx"),
            summary_col="总价",
            detail_col="金额",
            summary_sheet=None,
            detail_sheet=None,
            summary_label="客户",
            detail_label="单号",
            tolerance=0.01,
            max_items=12,
            out=str(root / "report"),
            fail_on_unmatched=False,
        )
    )


def cmd_selftest(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool]] = []
    checks.append(("parse plain int", parse_money(2000) == 2000.0))
    checks.append(("parse comma", parse_money("2,000.00") == 2000.0))
    checks.append(("parse currency", parse_money("¥2000") == 2000.0))
    checks.append(("parse accounting negative", parse_money("(500)") == -500.0))
    checks.append(("parse text", parse_money("2000 元") == 2000.0))
    checks.append(("parse junk", parse_money("N/A") is None))

    pool = [
        Line("s", 2, "500", 500.0),
        Line("s", 3, "500", 500.0),
        Line("s", 4, "500", 500.0),
        Line("s", 5, "500", 500.0),
        Line("s", 6, "1200", 1200.0),
    ]
    solutions = find_combinations(2000, pool, tolerance=0.01, max_items=12, max_solutions=4)
    checks.append(("4x500 explains 2000", any(len(s) == 4 for s in solutions)))
    checks.append(("no false 1200+x", all(abs(sum(l.amount for l in s) - 2000) <= 0.01 for s in solutions)))

    matched, leftover = reconcile(
        [Line("sum", 2, "2000", 2000.0)], pool, tolerance=0.01, max_items=12
    )
    checks.append(("reconcile counts 4 lines", len(matched[0].lines) == 4))
    checks.append(("reconcile leaves 1200", len(leftover) == 1 and leftover[0].amount == 1200))

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'}  {name}")
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ledger_match.py",
        description="Explain each summary total with a combination of detail lines.",
        epilog="examples:\n  python scripts/ledger_match.py demo\n"
        "  python scripts/ledger_match.py match --summary 汇总.xlsx --detail 明细.xlsx --summary-col 总价 --detail-col 金额",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"ledger-match {VERSION}")
    sub = parser.add_subparsers(dest="command")

    match = sub.add_parser("match", help="reconcile two ledgers")
    match.add_argument("--summary", required=True)
    match.add_argument("--detail", required=True)
    match.add_argument("--summary-col", default="金额")
    match.add_argument("--detail-col", default="金额")
    match.add_argument("--summary-sheet", default=None)
    match.add_argument("--detail-sheet", default=None)
    match.add_argument("--summary-label", default=None)
    match.add_argument("--detail-label", default=None)
    match.add_argument("--tolerance", type=float, default=0.01)
    match.add_argument("--max-items", type=int, default=12)
    match.add_argument("-o", "--out", default="")
    match.add_argument("--fail-on-unmatched", action="store_true")
    match.set_defaults(func=run_match)

    demo = sub.add_parser("demo", help="write a demo pair and reconcile it")
    demo.add_argument("-o", "--out", default="")
    demo.set_defaults(func=cmd_demo)

    selftest = sub.add_parser("selftest", help="built-in checks")
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
