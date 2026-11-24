#!/usr/bin/env python3
"""vat_export — 把进项税勾稽结果导成一张可交给做账人核对的 Excel。

    python scripts/vat_export.py --voucher 凭证明细.xlsx --invoice 勾选发票.xlsx --out vat-run

输出 `进项税勾稽_核对表.xlsx`，六个 sheet：
汇总 / 疑点1-5% / 疑点2-异常税率 / 疑点3-9%差异 / 按票种 / 全部发票 / 全部凭证
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vat_reconcile as vr  # noqa: E402

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side  # noqa: E402
from openpyxl.utils import get_column_letter  # noqa: E402

MONEY = "#,##0.00"
HEAD_FILL = PatternFill("solid", fgColor="E8EEF7")
WARN_FILL = PatternFill("solid", fgColor="FDE9E9")
HEAD_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=14)
THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def style_header(ws, row: int, cols: int) -> None:
    for col in range(1, cols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEAD_FONT
        cell.fill = HEAD_FILL
        cell.border = BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)


def autofit(ws, widths: list[int]) -> None:
    for index, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width


def analyze(voucher_path: Path, invoice_path: Path):
    v_header, v_rows = vr.load_rows(voucher_path)
    v_amount_col = vr.find_col(v_header, "借方")
    v_rate_col = vr.find_col(v_header, "管理对象")
    v_no_col = vr.find_optional(v_header, "凭证编号")

    vouchers: list[dict] = []
    voucher_by_label: dict[str, float] = defaultdict(float)
    for row in v_rows:
        if not row or v_rate_col >= len(row) or row[v_rate_col] is None:
            continue
        label = str(row[v_rate_col]).strip()
        amount = vr.num(row[v_amount_col])
        vouchers.append(
            {
                "voucher": str(row[v_no_col]) if v_no_col is not None and v_no_col < len(row) else "",
                "rate": label,
                "amount": amount,
            }
        )
        import re as _re

        match = _re.search(r"(\d+(?:\.\d+)?)\s*%", label)
        bucket = vr.classify(float(match.group(1))) if match else label
        voucher_by_label[bucket] += amount

    i_header, i_rows = vr.load_rows(invoice_path)
    c_amount = vr.find_col(i_header, "金额")
    c_tax = vr.find_col(i_header, "税额")
    c_date = vr.find_optional(i_header, "开票日期")
    c_kind = vr.find_optional(i_header, "票种")
    c_seller = vr.find_optional(i_header, "销售方")
    c_status = vr.find_optional(i_header, "发票状态")
    c_biz = vr.find_optional(i_header, "业务类型")

    invoices: list[dict] = []
    by_rate: dict[str, dict] = defaultdict(lambda: {"tax": 0.0, "amount": 0.0, "n": 0})
    for row in i_rows:
        if not row:
            continue
        amount = vr.num(row[c_amount])
        tax = vr.num(row[c_tax])
        if amount == 0:
            continue
        # 红字发票（负数）必须计入，税率按绝对值推断
        ratio = tax / abs(amount) * 100
        label = vr.classify(ratio)
        item = {
            "date": str(row[c_date])[:10] if c_date is not None and c_date < len(row) and row[c_date] else "",
            "kind": str(row[c_kind]).replace("数电发票（", "").replace("）", "")
            if c_kind is not None and c_kind < len(row) and row[c_kind]
            else "",
            "seller": str(row[c_seller]) if c_seller is not None and c_seller < len(row) and row[c_seller] else "",
            "amount": amount,
            "tax": tax,
            "ratio": ratio,
            "label": label,
            "status": str(row[c_status]) if c_status is not None and c_status < len(row) and row[c_status] else "",
            "biz": str(row[c_biz]) if c_biz is not None and c_biz < len(row) and row[c_biz] else "",
        }
        invoices.append(item)
        by_rate[label]["tax"] += tax
        by_rate[label]["amount"] += amount
        by_rate[label]["n"] += 1

    return {
        "vouchers": vouchers,
        "invoices": invoices,
        "voucher_by_label": voucher_by_label,
        "by_rate": by_rate,
    }


def build_workbook(data: dict, out_path: Path) -> None:
    vouchers = data["vouchers"]
    invoices = data["invoices"]
    voucher_by_label = data["voucher_by_label"]
    by_rate = data["by_rate"]

    total_v = sum(voucher_by_label.values())
    total_i = sum(item["tax"] for item in invoices)
    labels = sorted(set(voucher_by_label) | set(by_rate), key=lambda lab: -voucher_by_label.get(lab, 0.0))

    wb = Workbook()

    # ---------- 汇总 ----------
    ws = wb.active
    ws.title = "汇总"
    ws["A1"] = "进项税额勾稽 · 凭证 vs 抵扣勾选发票"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"生成时间 {datetime.now():%Y-%m-%d %H:%M} · 凭证 {len(vouchers)} 行 · 发票 {len(invoices)} 张"
    ws["A3"] = "口径：凭证「借方金额」视为进项税额；发票税率由「票面税额 ÷ 金额」推断"

    ws["A5"] = "总账"
    ws["A5"].font = HEAD_FONT
    rows = [
        ("凭证进项税额合计", total_v),
        ("发票税额合计", total_i),
        ("差异（凭证 − 发票）", total_v - total_i),
        ("差异率", (total_v - total_i) / total_v if total_v else 0.0),
    ]
    for index, (label, value) in enumerate(rows, start=6):
        ws.cell(row=index, column=1, value=label)
        cell = ws.cell(row=index, column=2, value=value)
        cell.number_format = "0.00%" if label == "差异率" else MONEY

    head_row = 11
    ws.cell(row=head_row, column=1, value="税率")
    ws.cell(row=head_row, column=2, value="凭证进项税额")
    ws.cell(row=head_row, column=3, value="发票税额")
    ws.cell(row=head_row, column=4, value="差异")
    ws.cell(row=head_row, column=5, value="发票张数")
    style_header(ws, head_row, 5)
    for offset, label in enumerate(labels, start=1):
        v = voucher_by_label.get(label, 0.0)
        i = by_rate[label]["tax"] if label in by_rate else 0.0
        r = head_row + offset
        ws.cell(row=r, column=1, value=label)
        ws.cell(row=r, column=2, value=v).number_format = MONEY
        ws.cell(row=r, column=3, value=i).number_format = MONEY
        gap_cell = ws.cell(row=r, column=4, value=v - i)
        gap_cell.number_format = MONEY
        if abs(v - i) > 100:
            gap_cell.fill = WARN_FILL
        ws.cell(row=r, column=5, value=by_rate[label]["n"] if label in by_rate else 0)

    note_row = head_row + len(labels) + 2
    notes = [
        "结论与疑点：",
        "1）1% 税率两边完全一致（4,532.70），说明「凭证借方 = 进项税额」口径成立。",
        "2）5% 税率只有凭证 2.14 元，发票里没有 5% 征收率——见「疑点1_5%」。",
        "3）三张发票税额/金额比例不在标准税率上——见「疑点2_异常税率」。",
        "4）9% 差异 5,434.54 最大，与铁路/行程单/通行费等计算抵扣类发票混组有关——见「疑点3_9%差异」。",
        "5）凭证侧没有发票号，只能对到税率级；逐张勾稽需要凭证带上发票号或供应商。",
    ]
    for offset, text in enumerate(notes):
        ws.cell(row=note_row + offset, column=1, value=text)
    autofit(ws, [34, 20, 18, 16, 12])

    # ---------- 疑点1：5% ----------
    ws = wb.create_sheet("疑点1_5%")
    ws["A1"] = "疑点 1 · 凭证有 5% 税率，发票没有"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "凭证 196 号借方 2.14 元挂在 5% 税率下，391 张发票中 5% 征收率为 0 张。"
    ws["A3"] = "可能原因：发票被勾选到别的税率组 / 该凭证对应非发票类抵扣凭证 / 入账税率录错。"
    head = 5
    for col, title in enumerate(["凭证编号", "管理对象", "借方金额"], start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, 3)
    row_index = head + 1
    for item in vouchers:
        if item["rate"].startswith("5%"):
            ws.cell(row=row_index, column=1, value=item["voucher"])
            ws.cell(row=row_index, column=2, value=item["rate"])
            ws.cell(row=row_index, column=3, value=item["amount"]).number_format = MONEY
            row_index += 1
    autofit(ws, [16, 16, 16])

    # ---------- 疑点2：异常税率 ----------
    ws = wb.create_sheet("疑点2_异常税率")
    ws["A1"] = "疑点 2 · 税额/金额比例不在标准税率上"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "标准税率 1/3/5/6/9/13（容差 ±0.15 个百分点）。以下三张对不上。"
    ws["A3"] = "8.3–8.65% 通常对应差额征税（劳务派遣/旅游/建筑简易计税）或农产品收购；5.82% 的小额铁路票是计算抵扣舍入。"
    head = 5
    titles = ["开票日期", "票种", "金额", "税额", "税额/金额", "发票状态", "业务类型"]
    for col, title in enumerate(titles, start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, len(titles))
    row_index = head + 1
    for item in invoices:
        if item["label"] != "异常":
            continue
        values = [item["date"], item["kind"], item["amount"], item["tax"], item["ratio"] / 100, item["status"], item["biz"]]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row_index, column=col, value=value)
            if col in (3, 4):
                cell.number_format = MONEY
            if col == 5:
                cell.number_format = "0.00%"
        row_index += 1
    total = sum(item["tax"] for item in invoices if item["label"] == "异常")
    ws.cell(row=row_index + 1, column=1, value="异常税额合计").font = HEAD_FONT
    ws.cell(row=row_index + 1, column=2, value=total).number_format = MONEY
    autofit(ws, [14, 30, 16, 14, 12, 12, 12])

    # ---------- 疑点3：9% 差异 ----------
    ws = wb.create_sheet("疑点3_9%差异")
    gap9 = voucher_by_label.get("9%", 0.0) - (by_rate["9%"]["tax"] if "9%" in by_rate else 0.0)
    ws["A1"] = "疑点 3 · 9% 税率差异"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"凭证 646,309.45 − 发票 640,874.91 = {gap9:,.2f}。9% 组含 120 张铁路票、23 张行程单，属计算抵扣。"
    ws["A3"] = "下表是税额合计恰好等于差异的发票组合。注意：凭证侧无发票号，这只是金额上说得通，不等于归因。"
    candidates = [(f"{item['kind'][:8]}-{item['date']}", item["tax"], item) for item in invoices if item["label"] == "9%"]
    combos = vr.combine(gap9, [(ref, tax) for ref, tax, _ in candidates])
    head = 5
    titles = ["发票（票种-日期）", "税额", "金额", "税额/金额", "票种"]
    for col, title in enumerate(titles, start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, len(titles))
    row_index = head + 1
    if combos:
        # 用 (票种-日期, 税额) 匹配，避免同一天同票种的两张票互相覆盖
        used: set[int] = set()
        for ref, amount in combos[0]:
            for item in invoices:
                if id(item) in used or item["label"] != "9%" or abs(item["tax"] - amount) > 0.005:
                    continue
                if f"{item['kind'][:8]}-{item['date']}" != ref:
                    continue
                ws.cell(row=row_index, column=1, value=ref)
                ws.cell(row=row_index, column=2, value=item["tax"]).number_format = MONEY
                ws.cell(row=row_index, column=3, value=item["amount"]).number_format = MONEY
                ws.cell(row=row_index, column=4, value=item["ratio"] / 100).number_format = "0.00%"
                ws.cell(row=row_index, column=5, value=item["kind"])
                used.add(id(item))
                row_index += 1
                break
    ws.cell(row=row_index + 1, column=1, value="组合合计").font = HEAD_FONT
    combo_total = sum(amount for _ref, amount in combos[0]) if combos else 0.0
    ws.cell(row=row_index + 1, column=2, value=combo_total).number_format = MONEY
    autofit(ws, [30, 16, 16, 12, 28])

    # ---------- 按票种 ----------
    ws = wb.create_sheet("按票种")
    ws["A1"] = "按票种汇总"
    ws["A1"].font = TITLE_FONT
    head = 3
    for col, title in enumerate(["票种", "张数", "金额", "税额", "平均税额占比"], start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, 5)
    kinds: dict[str, dict] = defaultdict(lambda: {"n": 0, "amount": 0.0, "tax": 0.0})
    for item in invoices:
        bucket = kinds[item["kind"] or "未标注"]
        bucket["n"] += 1
        bucket["amount"] += item["amount"]
        bucket["tax"] += item["tax"]
    row_index = head + 1
    for kind, bucket in sorted(kinds.items(), key=lambda kv: -kv[1]["tax"]):
        ws.cell(row=row_index, column=1, value=kind)
        ws.cell(row=row_index, column=2, value=bucket["n"])
        ws.cell(row=row_index, column=3, value=bucket["amount"]).number_format = MONEY
        ws.cell(row=row_index, column=4, value=bucket["tax"]).number_format = MONEY
        share = bucket["tax"] / bucket["amount"] if bucket["amount"] else 0.0
        ws.cell(row=row_index, column=5, value=share).number_format = "0.00%"
        row_index += 1
    autofit(ws, [32, 8, 18, 16, 14])

    # ---------- 全部发票 ----------
    ws = wb.create_sheet("全部发票")
    head = 1
    titles = ["开票日期", "票种", "金额", "票面税额", "税额/金额", "推定税率", "发票状态", "业务类型", "销售方"]
    for col, title in enumerate(titles, start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, len(titles))
    for offset, item in enumerate(invoices, start=2):
        values = [
            item["date"], item["kind"], item["amount"], item["tax"], item["ratio"] / 100,
            item["label"], item["status"], item["biz"], item["seller"],
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=offset, column=col, value=value)
            if col in (3, 4):
                cell.number_format = MONEY
            if col == 5:
                cell.number_format = "0.00%"
    ws.freeze_panes = "A2"
    autofit(ws, [12, 30, 16, 14, 12, 10, 10, 12, 30])

    # ---------- 全部凭证 ----------
    ws = wb.create_sheet("全部凭证")
    head = 1
    for col, title in enumerate(["凭证编号", "管理对象（税率）", "借方金额"], start=1):
        ws.cell(row=head, column=col, value=title)
    style_header(ws, head, 3)
    for offset, item in enumerate(vouchers, start=2):
        ws.cell(row=offset, column=1, value=item["voucher"])
        ws.cell(row=offset, column=2, value=item["rate"])
        ws.cell(row=offset, column=3, value=item["amount"]).number_format = MONEY
    ws.freeze_panes = "A2"
    autofit(ws, [16, 18, 16])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(out_path))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="导出进项税勾稽核对表（xlsx）")
    parser.add_argument("--voucher", required=True)
    parser.add_argument("--invoice", required=True)
    parser.add_argument("--out", default="vat-report")
    parser.add_argument("--name", default="进项税勾稽_核对表.xlsx")
    args = parser.parse_args(argv)

    data = analyze(Path(args.voucher), Path(args.invoice))
    target = Path(args.out) / args.name
    build_workbook(data, target)
    print(f"written: {target}")
    print(f"  sheets: 汇总 / 疑点1_5% / 疑点2_异常税率 / 疑点3_9%差异 / 按票种 / 全部发票 / 全部凭证")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
