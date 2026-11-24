"""Tests for assess. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import assess as az  # noqa: E402

HEALTH = ROOT / "rubrics" / "health-metabolic.json"
CAREER = ROOT / "rubrics" / "career-pm.json"
BUDGET = ROOT / "rubrics" / "budget-50-30-20.json"


class TestRubrics(unittest.TestCase):
    def test_all_three_load(self):
        for path in (HEALTH, CAREER, BUDGET):
            rubric = az.load_rubric(path)
            self.assertTrue(rubric.items, path)
            self.assertTrue(rubric.disclaimer, f"{path} needs a disclaimer")

    def test_aliases_resolve(self):
        rubric = az.load_rubric(HEALTH)
        self.assertEqual(rubric.find_item("总胆固醇").key, "tc")
        self.assertEqual(rubric.find_item("TC").key, "tc")
        self.assertEqual(rubric.find_item("高压").key, "sbp")

    def test_unknown_item(self):
        self.assertIsNone(az.load_rubric(HEALTH).find_item("不存在的指标"))


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.rubric = az.load_rubric(HEALTH)

    def test_tc_levels(self):
        tc = self.rubric.find_item("tc")
        self.assertEqual(az.classify_range(tc, 4.8)[0], "合适")
        self.assertEqual(az.classify_range(tc, 5.8)[0], "边缘升高")
        self.assertEqual(az.classify_range(tc, 6.42)[0], "升高")

    def test_boundary_belongs_to_next_level(self):
        """区间是左闭右开：落在界值上归下一级（指南写的是 TC <5.2 合适）。"""
        tc = self.rubric.find_item("tc")
        self.assertEqual(az.classify_range(tc, 5.19)[0], "合适")
        self.assertEqual(az.classify_range(tc, 5.2)[0], "边缘升高", "5.2 正好在界上，应归下一级")
        self.assertEqual(az.classify_range(tc, 6.2)[0], "升高")
        glu = self.rubric.find_item("glucose")
        self.assertEqual(az.classify_range(glu, 6.1)[0], "空腹血糖受损")
        uric = self.rubric.find_item("uric")
        self.assertEqual(az.classify_range(uric, 420)[0], "偏高")

    def test_glucose_impaired(self):
        glu = self.rubric.find_item("glucose")
        level, _ref, severity = az.classify_range(glu, 6.35)
        self.assertEqual(level, "空腹血糖受损")
        self.assertEqual(severity, "关注")

    def test_sbp_see_doctor(self):
        sbp = self.rubric.find_item("sbp")
        level, _ref, severity = az.classify_range(sbp, 142)
        self.assertEqual(severity, "建议就医")

    def test_reference_text(self):
        tc = self.rubric.find_item("tc")
        self.assertIn("5.2", az.classify_range(tc, 5.8)[1])


class TestAssess(unittest.TestCase):
    def test_health_photo_values(self):
        rubric = az.load_rubric(HEALTH)
        values = {"总胆固醇": 6.42, "甘油三酯": 2.85, "低密度脂蛋白": 4.31,
                  "高密度脂蛋白": 0.86, "空腹血糖": 6.35, "尿酸": 486, "收缩压": 142}
        results = az.assess(rubric, values)
        verdict, reason = az.overall_level(results, rubric)
        self.assertEqual(verdict, "建议尽快就医复核")
        self.assertIn("收缩压", reason)
        missing = [r for r in results if r.missing]
        self.assertEqual([r.key for r in missing], ["hba1c"])

    def test_health_normal(self):
        rubric = az.load_rubric(HEALTH)
        values = {"总胆固醇": 4.2, "甘油三酯": 1.0, "低密度脂蛋白": 2.5, "空腹血糖": 5.0}
        results = az.assess(rubric, values)
        verdict, _reason = az.overall_level(results, rubric)
        self.assertEqual(verdict, "各项在参考范围内")

    def test_career_shortfall(self):
        rubric = az.load_rubric(CAREER)
        values = {"用户研究": 2, "需求分析": 3, "数据分析": 2, "项目管理": 4,
                  "商业理解": 2, "技术理解": 3, "表达沟通": 3}
        results = az.assess(rubric, values)
        user_research = next(r for r in results if r.key == "用户研究")
        self.assertEqual(user_research.level, "短板")
        self.assertAlmostEqual(user_research.priority, 2 * 0.18, places=6)
        verdict, reason = az.overall_level(results, rubric)
        self.assertEqual(verdict, "有明确差距")
        self.assertIn("用户研究", reason)

    def test_budget_ratio(self):
        rubric = az.load_rubric(BUDGET)
        values = {"必要支出": 8200, "生活享受": 4300, "储蓄投资": 2500, "收入": 15000}
        results = az.assess(rubric, values)
        necessary = next(r for r in results if r.key == "必要支出")
        self.assertAlmostEqual(necessary.value or 0, 54.7, places=0)
        self.assertEqual(necessary.level, "略超")
        save = next(r for r in results if r.key == "储蓄投资")
        self.assertEqual(save.level, "略低")

    def test_budget_missing_denominator(self):
        rubric = az.load_rubric(BUDGET)
        results = az.assess(rubric, {"必要支出": 8200})
        necessary = next(r for r in results if r.key == "必要支出")
        self.assertTrue(necessary.missing)
        self.assertIn("收入", necessary.advice)


class TestCli(unittest.TestCase):
    def test_run_writes_report_and_xlsx(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = az.main([
                "run", "--rubric", str(HEALTH),
                "--kv", "总胆固醇=6.42,收缩压=142",
                "-o", tmp,
            ])
            self.assertEqual(code, 0)
            self.assertTrue((Path(tmp) / "health-metabolic.md").exists())
            self.assertTrue((Path(tmp) / "assess-health-metabolic.xlsx").exists())

    def test_fail_on_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = az.main([
                "run", "--rubric", str(HEALTH), "--kv", "收缩压=150", "-o", tmp, "--fail-on", "建议就医",
            ])
            self.assertEqual(code, 1)

    def test_rubric_by_id(self):
        rubric = az.load_rubric(az.resolve_rubric("career-pm"))
        self.assertEqual(rubric.id, "career-pm")


if __name__ == "__main__":
    unittest.main()
