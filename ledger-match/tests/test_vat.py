"""Tests for the VAT trio: reconcile / export / mark.

`python -m unittest discover -s tests -v`

Fixture is deliberately tiny and hand-computable:

    凭证:  13%=130  9%=95  6%=60  1%=10  5%=2.14      合计 297.14
    发票:  13%=130  9%=90  6%=60  1%=10  + 一张 8.3% 异常发票税额 83   合计 373

    预期差异：9% 多 5.00 · 5% 多 2.14 · 异常少 83.00 · 总差 -75.86
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vat_export as ve  # noqa: E402
import vat_mark as vm  # noqa: E402
import vat_reconcile as vr  # noqa: E402

VOUCHER_ROWS = [
    ("测试公司", "记账凭证 1", "13%税率", 130),
    ("测试公司", "记账凭证 2", "9%税率", 95),
    ("测试公司", "记账凭证 3", "6%税率", 60),
    ("测试公司", "记账凭证 4", "1%税率", 10),
    ("测试公司", "记账凭证 5", "5%税率", 2.14),
]

INVOICE_ROWS = [
    # 序号, 勾选, 数电号, 代码, 号码, 日期, 金额, 税额, 有效税额, 购买方, 销售方
    ("1", "是", "", "", "", "2026-11-01", 1000, 130, 130, "", "供应商A"),
    ("2", "是", "", "", "", "2026-11-02", 1000, 90, 90, "", "供应商B"),
    ("3", "是", "", "", "", "2026-11-03", 1000, 60, 60, "", "供应商C"),
    ("4", "是", "", "", "", "2026-11-04", 1000, 10, 10, "", "供应商D"),
    ("5", "是", "", "", "", "2026-11-05", 1000, 83, 83, "", "供应商E"),
]


def build_fixture(root: Path) -> tuple[Path, Path]:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "凭证明细"
    ws.append(["单位", "凭证编号", "总摘要", "分录摘要", "科目编码", "科目名称", "管理对象", "主辅标志", "借方金额"])
    for row in VOUCHER_ROWS:
        ws.append([row[0], row[1], "", "", "", "", row[2], "主", row[3]])
    voucher = root / "凭证明细.xlsx"
    wb.save(voucher)

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    ws.append([
        "序号", "是否勾选*", "数电发票号码", "发票代码", "发票号码", "开票日期*",
        "金额*", "票面税额*", "有效抵扣税额*", "购买方识别号*", "销售方纳税人名称",
        "销售方纳税人识别号", "发票来源", "票种*", "发票状态",
    ])
    for row in INVOICE_ROWS:
        ws.append([row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], "", "", "数电发票（增值税专用发票）", "正常"])
    invoice = root / "发票.xlsx"
    wb.save(invoice)
    return voucher, invoice


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestParsing(unittest.TestCase):
    def test_num(self):
        self.assertEqual(vr.num(2000), 2000.0)
        self.assertEqual(vr.num("2,000.00"), 2000.0)
        self.assertEqual(vr.num("¥1,234.5"), 1234.5)
        self.assertEqual(vr.num(None), 0.0)
        self.assertEqual(vr.num("abc"), 0.0)

    def test_classify_standard_rates(self):
        for rate in (1, 3, 5, 6, 9, 13):
            self.assertEqual(vr.classify(float(rate)), f"{rate:g}%")

    def test_classify_within_tolerance(self):
        self.assertEqual(vr.classify(9.0), "9%")
        self.assertEqual(vr.classify(9.1), "9%")

    def test_classify_off_standard(self):
        self.assertEqual(vr.classify(8.3), "异常")
        self.assertEqual(vr.classify(8.65), "异常")
        self.assertEqual(vr.classify(5.82), "异常")

    def test_find_col(self):
        header = ["序号", "金额*", "票面税额*"]
        self.assertEqual(vr.find_col(header, "金额"), 1)
        self.assertEqual(vr.find_col(header, "税额"), 2)
        with self.assertRaises(SystemExit):
            vr.find_col(header, "不存在")

    def test_find_optional(self):
        header = ["序号", "金额*"]
        self.assertIsNone(vr.find_optional(header, "税额"))


class TestCombine(unittest.TestCase):
    def test_exact_combination(self):
        items = [("a", 1000.0), ("b", 500.0), ("c", 500.0), ("d", 300.0)]
        combos = vr.combine(1000.0, items)
        self.assertTrue(any(len(c) == 2 and abs(sum(x[1] for x in c) - 1000) < 0.01 for c in combos))

    def test_no_combination(self):
        self.assertEqual(vr.combine(999.0, [("a", 100.0), ("b", 200.0)]), [])


class TestReconcileEndToEnd(unittest.TestCase):
    def test_rate_diff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            data = ve.analyze(voucher, invoice)
            labels = data["voucher_by_label"]
            by_rate = data["by_rate"]
            self.assertAlmostEqual(labels["9%"], 95.0, places=2)
            self.assertAlmostEqual(by_rate["9%"]["tax"], 90.0, places=2)
            self.assertAlmostEqual(labels["5%"], 2.14, places=2)
            self.assertAlmostEqual(by_rate["异常"]["tax"], 83.0, places=2)

    def test_report_and_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            out = root / "out"
            code = quiet(
                vr.main,
                ["--voucher", str(voucher), "--invoice", str(invoice), "--out", str(out), "--json"],
            )
            self.assertEqual(code, 0)
            report = (out / "vat-reconcile.md").read_text(encoding="utf-8")
            self.assertIn("9%", report)
            self.assertIn("异常", report)
            payload = json.loads((out / "vat-reconcile.json").read_text(encoding="utf-8"))
            self.assertAlmostEqual(payload["voucher_total"], 297.14, places=2)
            self.assertAlmostEqual(payload["invoice_total"], 373.0, places=2)
            self.assertAlmostEqual(payload["voucher_total"] - payload["invoice_total"], -75.86, places=2)

    def test_missing_columns_fail_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            from openpyxl import Workbook

            path = root / "坏表.xlsx"
            wb = Workbook()
            wb.active.append(["随便", "什么"])
            wb.active.append(["a", "b"])
            wb.save(path)
            with self.assertRaises(SystemExit):
                vr.load_rows(path) if False else vr.find_col(["随便", "什么"], "金额")


class TestExport(unittest.TestCase):
    def test_workbook_has_all_sheets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            data = ve.analyze(voucher, invoice)
            target = root / "核对表.xlsx"
            ve.build_workbook(data, target)
            self.assertTrue(target.exists())
            from openpyxl import load_workbook

            wb = load_workbook(str(target))
            self.assertEqual(
                wb.sheetnames,
                ["汇总", "疑点1_5%", "疑点2_异常税率", "疑点3_9%差异", "按票种", "全部发票", "全部凭证"],
            )
            summary = wb["汇总"]
            values = {
                summary.cell(row=row, column=1).value: summary.cell(row=row, column=2).value
                for row in range(6, 10)
            }
            self.assertAlmostEqual(values["凭证进项税额合计"], 297.14, places=2)
            self.assertAlmostEqual(values["发票税额合计"], 373.0, places=2)

    def test_odd_rate_sheet_lists_invoice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            data = ve.analyze(voucher, invoice)
            target = root / "核对表.xlsx"
            ve.build_workbook(data, target)
            from openpyxl import load_workbook

            ws = load_workbook(str(target))["疑点2_异常税率"]
            dates = [ws.cell(row=row, column=1).value for row in range(6, 12)]
            self.assertIn("2026-11-05", dates)


class TestRedInvoice(unittest.TestCase):
    """红字（负数）发票必须计入合计，且按绝对税率归类。"""

    def _build(self, root: Path) -> tuple[Path, Path]:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(["单位", "凭证编号", "总摘要", "分录摘要", "科目编码", "科目名称", "管理对象", "主辅标志", "借方金额"])
        ws.append(["测试公司", "记账凭证 1", "", "", "", "", "13%税率", "主", 1300])
        voucher = root / "v.xlsx"
        wb.save(voucher)

        wb = Workbook()
        ws = wb.active
        ws.append([
            "序号", "是否勾选*", "数电发票号码", "发票代码", "发票号码", "开票日期*",
            "金额*", "票面税额*", "有效抵扣税额*", "购买方识别号*", "销售方纳税人名称",
        ])
        ws.append(["1", "是", "", "", "", "2026-11-01", 10000, 1300, 1300, "", "供应商A"])
        ws.append(["2", "是", "", "", "", "2026-11-02", -384.62, -50, -50, "", "供应商A"])  # 红字冲销
        invoice = root / "i.xlsx"
        wb.save(invoice)
        return voucher, invoice

    def test_red_invoice_is_counted_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = self._build(root)
            data = ve.analyze(voucher, invoice)
            by_rate = data["by_rate"]
            self.assertAlmostEqual(by_rate["13%"]["tax"], 1250.0, places=2, msg="红字必须冲减 13% 合计")
            self.assertEqual(by_rate["13%"]["n"], 2)
            self.assertNotIn("异常", by_rate, "绝对值仍是 13%，不该归为异常税率")
            self.assertEqual(len(data["invoices"]), 2, "红字发票不能被丢掉")


class TestRedInvoiceClassify(unittest.TestCase):
    def test_negative_rate_maps_to_absolute(self):
        self.assertEqual(vr.classify(-13.0), "13%")
        self.assertEqual(vr.classify(-9.0), "9%")
        self.assertEqual(vr.classify(13.0), "13%")


class TestMark(unittest.TestCase):
    def test_marks_odd_rate_and_five_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            out = root / "marked"
            code = quiet(vm.main, ["--voucher", str(voucher), "--invoice", str(invoice), "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertTrue((out / "抵扣勾选增值税发票信息_已标注.xlsx").exists())
            self.assertTrue((out / "凭证明细_已标注.xlsx").exists())

            from openpyxl import load_workbook

            wb = load_workbook(str(out / "抵扣勾选增值税发票信息_已标注.xlsx"))
            ws = wb.worksheets[0]
            red_rows = [
                row for row in range(2, ws.max_row + 1)
                if ws.cell(row=row, column=3).fill.fgColor.rgb == "00FFC7CE"
            ]
            self.assertEqual(len(red_rows), 1, "只有那张 8.3% 的发票应该标红")
            note = ws.cell(row=red_rows[0], column=ws.max_column).value
            self.assertIn("不在标准值", note)

            wb2 = load_workbook(str(out / "凭证明细_已标注.xlsx"))
            ws2 = wb2.worksheets[0]
            red_vouchers = [
                row for row in range(2, ws2.max_row + 1)
                if ws2.cell(row=row, column=3).fill.fgColor.rgb == "00FFC7CE"
            ]
            self.assertEqual(len(red_vouchers), 1, "只有 5% 那行应该标红")

    def test_original_files_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            voucher, invoice = build_fixture(root)
            before = (voucher.stat().st_size, invoice.stat().st_size)
            quiet(vm.main, ["--voucher", str(voucher), "--invoice", str(invoice), "--out", str(root / "m")])
            after = (voucher.stat().st_size, invoice.stat().st_size)
            self.assertEqual(before, after)
            from openpyxl import load_workbook

            wb = load_workbook(str(invoice))
            self.assertNotIn("勾稽标记", [c.value for c in wb.worksheets[0][1]])


if __name__ == "__main__":
    unittest.main()
