"""Tests for reconcile. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile as rc  # noqa: E402


class TestNormalisation(unittest.TestCase):
    def test_strip_and_lower(self):
        self.assertEqual(rc.normalize("  贵州 茅台 "), "贵州茅台")
        self.assertEqual(rc.normalize("M-1001"), "m-1001")

    def test_punctuation_removed(self):
        self.assertEqual(rc.normalize("第一条：甲方，乙方。"), "第一条甲方乙方")

    def test_fullwidth_digits(self):
        self.assertEqual(rc.normalize("１２３"), "123")


class TestNumbers(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(rc.parse_number(100), (100.0, "none"))
        self.assertEqual(rc.parse_number("100"), (100.0, "none"))

    def test_unit_conversion(self):
        self.assertEqual(rc.parse_number("6.2kg"), (6200.0, "mass"))
        self.assertEqual(rc.parse_number("6200 g"), (6200.0, "mass"))

    def test_percent(self):
        self.assertEqual(rc.parse_number("1.2%"), (1.2, "percent"))

    def test_prose_is_not_numeric(self):
        self.assertIsNone(rc.parse_number("合同总金额为人民币 120,000 元，含税。"))

    def test_thousands_separator(self):
        self.assertEqual(rc.parse_number("120,000"), (120000.0, "none"))


class TestNumericTokens(unittest.TestCase):
    def test_dates(self):
        tokens = rc.extract_numeric_tokens("乙方应于 2026 年 12 月 31 日前完成交付。")
        self.assertIn("2026年12月31日", tokens)

    def test_amounts(self):
        tokens = rc.extract_numeric_tokens("合同总金额为人民币 120,000 元，含税。")
        self.assertIn("120000", tokens)

    def test_months(self):
        self.assertIn("12", rc.extract_numeric_tokens("质保期为验收合格后 12 个月。"))


class TestKeySelection(unittest.TestCase):
    def test_code_beats_name(self):
        table = rc.table_from_rows(
            "t",
            [
                ["代码", "名称", "价格"],
                ["600519", "贵州茅台", "1680"],
                ["000001", "平安银行", "11.85"],
            ],
        )
        key, _score = rc.pick_key_column(table)
        self.assertEqual(key, "代码")

    def test_material_code(self):
        table = rc.table_from_rows(
            "t",
            [
                ["物料号", "名称", "单价"],
                ["M-1001", "电源", "12000"],
                ["M-1002", "导线", "500"],
            ],
        )
        key, _score = rc.pick_key_column(table)
        self.assertEqual(key, "物料号")

    def test_no_hint_falls_back_to_unique(self):
        table = rc.table_from_rows(
            "t",
            [
                ["a", "b"],
                ["x1", "1"],
                ["x2", "2"],
            ],
        )
        key, _score = rc.pick_key_column(table)
        self.assertIn(key, {"a", "b"})


class TestAlignment(unittest.TestCase):
    def _entity(self, key: str, text: str) -> rc.Entity:
        return rc.Entity(key=rc.normalize(key), attrs={"内容": text}, ref="段1", raw=text, kind="block")

    def test_exact_match(self):
        left = [self._entity("第一条 甲", "第一条 甲")]
        right = [self._entity("第一条 甲", "第一条 甲")]
        matched, only_l, only_r, fuzzy = rc.align_entities(left, right)
        self.assertEqual(len(matched), 1)
        self.assertEqual(fuzzy, [])

    def test_fuzzy_match_on_rewrite(self):
        left = [self._entity("第一条 甲方委托乙方完成设备安装调试工作", "第一条 甲方委托乙方完成设备安装调试工作")]
        right = [self._entity("第一条 甲方委托乙方完成设备安装调试及培训工作", "第一条 甲方委托乙方完成设备安装调试及培训工作")]
        matched, only_l, only_r, fuzzy = rc.align_entities(left, right)
        self.assertEqual(len(matched), 1)
        self.assertEqual(len(fuzzy), 1)
        self.assertEqual(only_l, [])

    def test_unrelated_stays_unmatched(self):
        left = [self._entity("甲方委托安装", "甲方委托安装")]
        right = [self._entity("违约金按日计算", "违约金按日计算")]
        matched, only_l, only_r, _fuzzy = rc.align_entities(left, right)
        self.assertEqual(matched, [])
        self.assertEqual(len(only_l), 1)
        self.assertEqual(len(only_r), 1)


class TestComparison(unittest.TestCase):
    def test_numeric_change(self):
        diff = rc.compare_values("单价", "12000", "11800", tolerance=0.01)
        self.assertIsNotNone(diff)
        self.assertEqual(diff.kind, "value")

    def test_within_tolerance_is_quiet(self):
        self.assertIsNone(rc.compare_values("单价", "12000", "12010", tolerance=0.01))

    def test_percent_uses_points(self):
        diff = rc.compare_values("涨跌幅", "1.2%", "0.9%", tolerance=0.01)
        self.assertIsNotNone(diff)
        self.assertEqual(diff.delta_unit, "pp")
        self.assertAlmostEqual(diff.delta, -0.3, places=6)

    def test_unit_equivalence(self):
        self.assertIsNone(rc.compare_values("重量", "6.2kg", "6200g", tolerance=0.01))

    def test_text_similarity(self):
        diff = rc.compare_values("内容", "甲方委托安装", "甲方委托调试", tolerance=0.01)
        self.assertIsNotNone(diff)
        self.assertEqual(diff.kind, "text")


class TestEndToEnd(unittest.TestCase):
    def test_three_demo_pairs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            rc.build_demo(root)
            out = Path(tmp) / "out"

            stock = rc.run_pair(root / "今日股价.xlsx", root / "昨日股价.xlsx", out=out, quiet=True)
            self.assertEqual(stock["mode"], "record")
            self.assertEqual(stock["diffs"], 12)  # 10 value + 1 only-left + 1 only-right
            self.assertIn("代码", stock["report"], "auto key should be the stock code")

            material = rc.run_pair(root / "物料A.xlsx", root / "物料B.xlsx", out=out, quiet=True)
            kinds = [d.kind for d in material["diff_items"]]
            self.assertEqual(kinds.count("value"), 4)  # 单价 + 金额，两组
            self.assertIn("only_left", kinds)
            self.assertIn("only_right", kinds)

            contract = rc.run_pair(root / "合同A.docx", root / "合同B.docx", out=out, quiet=True)
            self.assertEqual(contract["mode"], "text")
            values = [d for d in contract["diff_items"] if d.kind == "value"]
            self.assertEqual(len(values), 3, [d.left + "->" + d.right for d in values])
            joined = " ".join(f"{d.left}->{d.right}" for d in values)
            self.assertIn("120000", joined)
            self.assertIn("2026年12月31日", joined)
            self.assertIn("12", joined)
            self.assertTrue((out / "reconcile-diff.xlsx").exists())

    def test_reports_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            rc.build_demo(root)
            out = Path(tmp) / "reports"
            rc.run_pair(root / "合同A.docx", root / "合同B.docx", out=out, quiet=True)
            reports = list(out.glob("*.md"))
            self.assertEqual(len(reports), 1)
            text = reports[0].read_text(encoding="utf-8")
            self.assertIn("数字 / 日期", text)
            self.assertIn("仅右侧存在", text)


class TestSkillFile(unittest.TestCase):
    def test_frontmatter(self):
        import re

        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---", 2)[1]
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
        desc = re.search(r"^description:\s*(.+)$", front, re.M)
        self.assertIsNotNone(name)
        self.assertIsNotNone(desc)
        assert name and desc
        self.assertRegex(name.group(1), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(desc.group(1)), 1024)


if __name__ == "__main__":
    unittest.main()
