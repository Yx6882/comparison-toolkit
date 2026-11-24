#!/usr/bin/env python3
"""vat_mark — 在原始表格副本上标出可疑行，不改动原文件。

    python scripts/vat_mark.py --voucher 凭证明细.xlsx --invoice 勾选发票.xlsx --out vat-run

输出两个副本：
    抵扣勾选增值税发票信息_已标注.xlsx
    凭证明细_已标注.xlsx

标色规则
    红  = 确定异常（比例不在标准税率 / 凭证 5% 无对应发票）
    黄  = 待核实（9% 差异的金额候选，不能直接归因）
每行最后一列写「勾稽标记」，说明为什么被标。
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vat_reconcile as vr  # noqa: E402
import vat_export as ve  # noqa: E402

from openpyxl import load_workbook  # noqa: E402
from openpyxl.styles import Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

RED_FILL = PatternFill("solid", fgColor="FFC7CE")
RED_FONT = Font(color="9C0006", bold=True)
YELLOW_FILL = PatternFill("solid", fgColor="FFEB9C")
YELLOW_FONT = Font(color="9C6500", bold=False)


def mark_invoice(src: Path, dst: Path, data: dict, candidates: set[tuple[str, float]]) -> tuple[int, int]:
    wb = load_workbook(str(src))
    ws = wb.worksheets[0]
    header = [cell.value for cell in ws[1]]
    c_amount = vr.find_col(header, "金额") + 1
    c_tax = vr.find_col(header, "税额") + 1
    c_date = vr.find_optional(header, "开票日期")
    c_kind = vr.find_optional(header, "票种")
    ncols = len(header)
    note_col = ncols + 1
    ws.cell(row=1, column=note_col, value="勾稽标记").font = Font(bold=True)

    red = yellow = 0
    for row in range(2, ws.max_row + 1):
        amount = vr.num(ws.cell(row=row, column=c_amount).value)
        tax = vr.num(ws.cell(row=row, column=c_tax).value)
        if amount == 0:
            continue
        # 红字发票（负数）也要标注，税率按绝对值推断
        ratio = tax / abs(amount) * 100
        label = vr.classify(ratio)
        date = ""
        if c_date is not None:
            raw_date = ws.cell(row=row, column=c_date + 1).value
            date = str(raw_date)[:10] if raw_date else ""
        kind = ""
        if c_kind is not None:
            raw_kind = ws.cell(row=row, column=c_kind + 1).value
            kind = str(raw_kind).replace("数电发票（", "").replace("）", "") if raw_kind else ""
        ref = f"{kind[:8]}-{date}"

        fill = font = None
        note = ""
        if label == "异常":
            fill, font = RED_FILL, RED_FONT
            note = f"税率 {ratio:.2f}% 不在标准值 1/3/5/6/9/13 上；疑似差额征税、农产品收购或计算抵扣舍入"
            red += 1
        elif (ref, round(tax, 2)) in candidates:
            fill, font = YELLOW_FILL, YELLOW_FONT
            note = "9% 差额 5,434.54 的金额候选；凭证侧无发票号，需人工确认是否归因"
            yellow += 1
        if not fill:
            continue
        for col in range(1, ncols + 1):
            ws.cell(row=row, column=col).fill = fill
        cell = ws.cell(row=row, column=note_col, value=note)
        cell.font = font

    ws.column_dimensions[get_column_letter(note_col)].width = 52
    ws.freeze_panes = "A2"
    wb.save(str(dst))
    return red, yellow


def mark_voucher(src: Path, dst: Path) -> int:
    wb = load_workbook(str(src))
    ws = wb.worksheets[0]
    header = [cell.value for cell in ws[1]]
    c_rate = vr.find_col(header, "管理对象") + 1
    c_amount = vr.find_col(header, "借方") + 1
    c_no = vr.find_optional(header, "凭证编号")
    ncols = len(header)
    note_col = ncols + 1
    ws.cell(row=1, column=note_col, value="勾稽标记").font = Font(bold=True)

    marked = 0
    for row in range(2, ws.max_row + 1):
        rate_text = ws.cell(row=row, column=c_rate).value
        if rate_text is None:
            continue
        label = str(rate_text).strip()
        fill = font = None
        note = ""
        if label.startswith("5%"):
            fill, font = RED_FILL, RED_FONT
            voucher_no = ""
            if c_no is not None:
                voucher_no = str(ws.cell(row=row, column=c_no + 1).value or "")
            note = f"5% 税率在 391 张勾选发票中一张都没有（凭证 {voucher_no}）；查原始单据，可能是非发票凭证或税率录错"
            marked += 1
        if not fill:
            continue
        for col in range(1, ncols + 1):
            ws.cell(row=row, column=col).fill = fill
        ws.cell(row=row, column=note_col, value=note).font = font

    ws.column_dimensions[get_column_letter(note_col)].width = 60
    ws.freeze_panes = "A2"
    wb.save(str(dst))
    return marked


def add_legend(dst_invoice: Path, marks: dict[str, int]) -> None:
    wb = load_workbook(str(dst_invoice))
    ws = wb.create_sheet("勾稽标记说明")
    ws["A1"] = "本文件由工具生成，只添加底色和说明，未改动任何原始数据"
    ws["A1"].font = Font(bold=True, size=12)
    rows = [
        ("红色", "确定异常", "发票税额/金额比例不在标准税率上，或凭证 5% 税率在发票里完全没有对应"),
        ("黄色", "待核实", "9% 差异的金额候选，凭证侧没有发票号，不能直接归因"),
        ("", "", ""),
        ("红色行数", str(marks.get("red", 0)), "发票"),
        ("黄色行数", str(marks.get("yellow", 0)), "发票"),
        ("凭证标红", str(marks.get("voucher", 0)), "行"),
    ]
    for index, (level, kind, why) in enumerate(rows, start=3):
        for col, value in enumerate((level, kind, why), start=1):
            ws.cell(row=index, column=col, value=value)
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 90
    wb.save(str(dst_invoice))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="在原始表格副本上标出可疑行")
    parser.add_argument("--voucher", required=True)
    parser.add_argument("--invoice", required=True)
    parser.add_argument("--out", default="vat-run")
    args = parser.parse_args(argv)

    data = ve.analyze(Path(args.voucher), Path(args.invoice))
    voucher_by_label = data["voucher_by_label"]
    by_rate = data["by_rate"]
    gap9 = voucher_by_label.get("9%", 0.0) - (by_rate["9%"]["tax"] if "9%" in by_rate else 0.0)
    pool = [
        (f"{item['kind'][:8]}-{item['date']}", item["tax"])
        for item in data["invoices"]
        if item["label"] == "9%"
    ]
    combos = vr.combine(gap9, pool) if abs(gap9) > 0.01 else []
    candidates = {(ref, round(amount, 2)) for ref, amount in combos[0]} if combos else set()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    invoice_dst = out / "抵扣勾选增值税发票信息_已标注.xlsx"
    voucher_dst = out / "凭证明细_已标注.xlsx"

    red, yellow = mark_invoice(Path(args.invoice), invoice_dst, data, candidates)
    voucher_marked = mark_voucher(Path(args.voucher), voucher_dst)
    add_legend(invoice_dst, {"red": red, "yellow": yellow, "voucher": voucher_marked})

    print(f"发票：红 {red} 行（异常税率）· 黄 {yellow} 行（9% 候选）")
    print(f"凭证：红 {voucher_marked} 行（5% 无对应发票）")
    print(f"发票副本：{invoice_dst}")
    print(f"凭证副本：{voucher_dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
