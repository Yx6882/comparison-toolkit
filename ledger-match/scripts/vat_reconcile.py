#!/usr/bin/env python3
"""vat_reconcile — 进项税额勾稽：凭证明细 vs 抵扣勾选发票。

    python scripts/vat_reconcile.py \
        --voucher 凭证明细.xlsx --invoice 抵扣勾选发票.xlsx \
        --out reports

凭证侧按「管理对象 / 税率」分组汇总进项税额；发票侧按「税额 ÷ 金额」推断
税率后汇总。两边按税率对比，差异再用组合搜索定位到具体发票。

这个脚本只读文件、不写回，也不联网。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "0.1.0"
STD_RATES = (1.0, 3.0, 5.0, 6.0, 9.0, 13.0)
RATE_TOLERANCE = 0.15  # 税额/金额 落在标准税率 ±0.15 个百分点内视为该税率


def num(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").replace("，", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else 0.0


def load_rows(path: Path, sheet: str | None = None, header_row: int = 1) -> tuple[list[Any], list[tuple]]:
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise SystemExit("openpyxl is required (pip install openpyxl)")
    wb = load_workbook(str(path), read_only=True, data_only=True)
    if sheet and sheet in wb.sheetnames:
        ws = wb[sheet]
    else:
        ws = wb.worksheets[0]
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) < header_row:
        raise SystemExit(f"{path}: not enough rows")
    return list(rows[header_row - 1]), rows[header_row:]


def find_col(header: Sequence[Any], *keywords: str) -> int:
    for index, cell in enumerate(header):
        text = "" if cell is None else str(cell)
        if all(k in text for k in keywords):
            return index
    raise SystemExit(f"column matching {keywords} not found in header {[str(c) for c in header]}")


def find_optional(header: Sequence[Any], *keywords: str) -> int | None:
    try:
        return find_col(header, *keywords)
    except SystemExit:
        return None


def classify(rate: float) -> str:
    # 红字发票的税额是负数，税率本身仍是正税率：取绝对值再归类
    value = abs(rate)
    for std in STD_RATES:
        if abs(value - std) <= RATE_TOLERANCE:
            return f"{std:g}%"
    return "异常"


def combine(target: float, items: list[tuple[str, float]], *, limit: int = 6, tol: float = 0.01, max_solutions: int = 2) -> list[list[tuple[str, float]]]:
    """小额差异的定位：找税额合计等于 target 的发票组合。"""
    pool = sorted((it for it in items if it[1] <= abs(target) + tol), key=lambda it: -it[1])
    found: list[list[tuple[str, float]]] = []

    def walk(start: int, remaining: float, chosen: list[tuple[str, float]]) -> None:
        if len(found) >= max_solutions or len(chosen) > limit:
            return
        if chosen and abs(remaining) <= tol:
            found.append(list(chosen))
            return
        for index in range(start, len(pool)):
            ref, amount = pool[index]
            if amount > remaining + tol:
                continue
            chosen.append((ref, amount))
            walk(index + 1, remaining - amount, chosen)
            chosen.pop()
            if len(found) >= max_solutions:
                return

    walk(0, abs(target), [])
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="进项税额勾稽：凭证 vs 勾选发票")
    parser.add_argument("--voucher", required=True, help="凭证明细 xlsx")
    parser.add_argument("--invoice", required=True, help="抵扣勾选发票 xlsx")
    parser.add_argument("--voucher-sheet", default=None)
    parser.add_argument("--invoice-sheet", default=None)
    parser.add_argument("--out", default="vat-report")
    parser.add_argument("--json", action="store_true", help="同时输出 json")
    args = parser.parse_args(argv)

    # ---- 凭证侧 ----
    v_header, v_rows = load_rows(Path(args.voucher), args.voucher_sheet)
    v_amount_col = find_col(v_header, "借方")
    v_rate_col = find_col(v_header, "管理对象") if any("管理对象" in str(c) for c in v_header) else find_col(v_header, "税率")
    v_no_col = find_optional(v_header, "凭证编号")
    v_memo_col = find_optional(v_header, "摘要")

    voucher: dict[str, float] = defaultdict(float)
    voucher_count: dict[str, int] = defaultdict(int)
    voucher_rows: list[dict[str, Any]] = []
    for row in v_rows:
        if not row:
            continue
        rate_text = row[v_rate_col] if v_rate_col < len(row) else None
        if rate_text is None:
            continue
        key = str(rate_text).strip()
        amount = num(row[v_amount_col] if v_amount_col < len(row) else 0)
        voucher[key] += amount
        voucher_count[key] += 1
        voucher_rows.append(
            {
                "rate": key,
                "amount": amount,
                "voucher": str(row[v_no_col]) if v_no_col is not None and v_no_col < len(row) else "",
                "memo": str(row[v_memo_col]) if v_memo_col is not None and v_memo_col < len(row) else "",
            }
        )

    # ---- 发票侧 ----
    i_header, i_rows = load_rows(Path(args.invoice), args.invoice_sheet)
    i_amount_col = find_col(i_header, "金额")
    i_tax_col = find_col(i_header, "税额")
    i_seller_col = find_optional(i_header, "销售方")
    i_date_col = find_optional(i_header, "开票日期")
    i_number_col = find_optional(i_header, "发票号码")
    i_digital_col = find_optional(i_header, "数电发票号码")
    i_kind_col = find_optional(i_header, "票种")
    i_selected_col = find_optional(i_header, "勾选")

    invoices: list[dict[str, Any]] = []
    by_rate: dict[str, dict[str, Any]] = defaultdict(lambda: {"tax": 0.0, "amount": 0.0, "n": 0})
    odd: list[dict[str, Any]] = []
    skipped = 0
    for row in i_rows:
        if not row:
            continue
        amount = num(row[i_amount_col] if i_amount_col < len(row) else 0)
        tax = num(row[i_tax_col] if i_tax_col < len(row) else 0)
        if amount == 0:
            skipped += 1
            continue
        # 红字发票（负数）必须计入合计，否则合计会虚高、差异被吃掉。
        # 税率用绝对值推断，符号保留在税额里。
        raw_rate = tax / abs(amount) * 100 if amount else 0.0
        label = classify(raw_rate)
        kind = ""
        if i_kind_col is not None and i_kind_col < len(row) and row[i_kind_col]:
            kind = str(row[i_kind_col]).replace("数电发票（", "").replace("）", "")
        date = str(row[i_date_col])[:10] if i_date_col is not None and i_date_col < len(row) and row[i_date_col] else ""
        ref = ""
        for col in (i_number_col, i_digital_col):
            if col is not None and col < len(row) and row[col]:
                ref = str(row[col])
                break
        if not ref:
            seller = str(row[i_seller_col]) if i_seller_col is not None and i_seller_col < len(row) and row[i_seller_col] else ""
            ref = f"{seller[:12] or kind[:8]}-{date}-{amount:,.2f}"
        item = {
            "ref": ref,
            "date": date,
            "seller": str(row[i_seller_col]) if i_seller_col is not None and i_seller_col < len(row) else "",
            "amount": amount,
            "tax": tax,
            "rate": raw_rate,
            "label": label,
            "kind": kind,
            "selected": str(row[i_selected_col]) if i_selected_col is not None and i_selected_col < len(row) else "",
        }
        invoices.append(item)
        by_rate[label]["tax"] += tax
        by_rate[label]["amount"] += amount
        by_rate[label]["n"] += 1
        if label == "异常":
            odd.append(item)

    # ---- 对比 ----
    voucher_by_label: dict[str, float] = defaultdict(float)
    for key, value in voucher.items():
        match = re.search(r"(\d+(?:\.\d+)?)\s*%", key)
        label = classify(float(match.group(1))) if match else key
        voucher_by_label[label] += value

    labels = sorted(set(voucher_by_label) | set(by_rate), key=lambda lab: -voucher_by_label.get(lab, 0.0))
    lines: list[str] = []
    lines.append("# 进项税额勾稽报告")
    lines.append("")
    lines.append(f"- 凭证：`{args.voucher}`（{len(voucher_rows)} 行，合计 {sum(voucher.values()):,.2f}）")
    lines.append(f"- 发票：`{args.invoice}`（{len(invoices)} 张，税额合计 {sum(i['tax'] for i in invoices):,.2f}）")
    lines.append(f"- 税率容差：±{RATE_TOLERANCE} 个百分点；金额 <= 0 的发票跳过 {skipped} 张")
    lines.append("")
    lines.append("| 税率 | 凭证进项税额 | 发票税额 | 差异（凭证−发票） | 发票张数 |")
    lines.append("|---|---|---|---|---|")
    total_v = 0.0
    total_i = 0.0
    for label in labels:
        v = voucher_by_label.get(label, 0.0)
        i = by_rate[label]["tax"] if label in by_rate else 0.0
        total_v += v
        total_i += i
        flag = "" if abs(v - i) <= 0.01 else ("  ⚠" if abs(v - i) > 100 else "  ·")
        lines.append(f"| {label} | {v:,.2f} | {i:,.2f} | {v - i:,.2f}{flag} | {by_rate[label]['n'] if label in by_rate else 0} |")
    lines.append(f"| **合计** | **{total_v:,.2f}** | **{total_i:,.2f}** | **{total_v - total_i:,.2f}** | {len(invoices)} |")
    lines.append("")

    # ---- 差异定位 ----
    gaps = [(label, voucher_by_label.get(label, 0.0) - (by_rate[label]["tax"] if label in by_rate else 0.0)) for label in labels]
    gaps = [(label, gap) for label, gap in gaps if abs(gap) > 0.01]
    if gaps:
        lines.append("## 差异定位")
        lines.append("")
        for label, gap in gaps:
            lines.append(f"### {label} · 差异 {gap:,.2f}")
            lines.append("")
            candidates = [(inv["ref"], inv["tax"]) for inv in invoices if inv["label"] == label]
            combos = combine(gap, candidates) if abs(gap) <= 20000 else []
            if combos:
                for combo in combos[:1]:
                    detail = " + ".join(f"{ref}（{amount:,.2f}）" for ref, amount in combo)
                    lines.append(f"- 税额合计恰好等于差异的发票组合：{detail}")
                    lines.append("- 注意：凭证侧没有发票号，这只是“金额上说得通”，不等于归因")
            else:
                lines.append(f"- 同税率发票共 {len(candidates)} 张，找不到税额合计恰好为 {abs(gap):,.2f} 的组合")
            lines.append("")

    # ---- 按票种分组 ----
    kinds: dict[str, dict[str, float]] = defaultdict(lambda: {"n": 0, "amount": 0.0, "tax": 0.0})
    for inv in invoices:
        bucket = kinds[inv["kind"] or "未标注"]
        bucket["n"] += 1
        bucket["amount"] += inv["amount"]
        bucket["tax"] += inv["tax"]
    if kinds:
        lines.append("## 按票种汇总")
        lines.append("")
        lines.append("| 票种 | 张数 | 金额 | 税额 | 平均税额占比 |")
        lines.append("|---|---|---|---|---|")
        for kind, bucket in sorted(kinds.items(), key=lambda kv: -kv[1]["tax"]):
            share = bucket["tax"] / bucket["amount"] * 100 if bucket["amount"] else 0.0
            lines.append(f"| {kind} | {int(bucket['n'])} | {bucket['amount']:,.2f} | {bucket['tax']:,.2f} | {share:.2f}% |")
        lines.append("")
        lines.append("> 铁路票、行程单、通行费属于「计算抵扣」，税额按扣除率算，与专票的票面税率不是一套口径。")
        lines.append("")

    if odd:
        lines.append("## 推断税率异常的发票")
        lines.append("")
        lines.append("| 发票 | 日期 | 销售方 | 金额 | 税额 | 实际比例 |")
        lines.append("|---|---|---|---|---|---|")
        for inv in odd[:20]:
            lines.append(
                f"| {inv['ref']} | {inv['date']} | {inv['seller'][:18]} | {inv['amount']:,.2f} | {inv['tax']:,.2f} | {inv['rate']:.2f}% |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("> 凭证侧只有「税率 + 金额」，没有发票号，所以只能对到税率级；差异定位是启发式的，需人工核对。")
    lines.append("")

    report = "\n".join(lines)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "vat-reconcile.md").write_text(report, encoding="utf-8")
    if args.json:
        (out / "vat-reconcile.json").write_text(
            json.dumps(
                {
                    "voucher_total": round(total_v, 2),
                    "invoice_total": round(total_i, 2),
                    "by_rate": [
                        {
                            "rate": label,
                            "voucher": round(voucher_by_label.get(label, 0.0), 2),
                            "invoice": round(by_rate[label]["tax"] if label in by_rate else 0.0, 2),
                            "gap": round(voucher_by_label.get(label, 0.0) - (by_rate[label]["tax"] if label in by_rate else 0.0), 2),
                            "invoices": by_rate[label]["n"] if label in by_rate else 0,
                        }
                        for label in labels
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    print(report)
    print(f"report: {out / 'vat-reconcile.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
