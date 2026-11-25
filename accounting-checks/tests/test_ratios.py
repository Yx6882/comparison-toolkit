"""Tests for financial ratios. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ratios as rt  # noqa: E402


def sample() -> dict:
    return {
        "balance_sheet": {
            "current_assets": 800000, "quick_assets": 500000, "current_liabilities": 400000,
            "total_assets": 5000000, "total_liabilities": 2000000, "total_equity": 3000000,
            "receivables": 300000, "inventory": 300000,
        },
        "income_statement": {
            "revenue": 4000000, "cost_of_sales": 2800000,
            "gross_profit": 1200000, "net_profit": 500000,
        },
    }


def by_name(results: list[rt.Ratio]) -> dict[str, rt.Ratio]:
    return {ratio.name: ratio for ratio in results}


class TestValues(unittest.TestCase):
    def test_current_ratio(self):
        ratio = by_name(rt.compute(sample()))["流动比率"]
        self.assertAlmostEqual(ratio.value, 2.0, places=4)
        self.assertEqual(ratio.unit, "倍")

    def test_debt_ratio_percent(self):
        ratio = by_name(rt.compute(sample()))["资产负债率"]
        self.assertAlmostEqual(ratio.value, 40.0, places=4)
        self.assertEqual(ratio.unit, "%")

    def test_gross_margin(self):
        ratio = by_name(rt.compute(sample()))["毛利率"]
        self.assertAlmostEqual(ratio.value, 30.0, places=4)

    def test_roe(self):
        ratio = by_name(rt.compute(sample()))["净资产收益率 ROE"]
        self.assertAlmostEqual(ratio.value, 16.6667, places=3)

    def test_turnover(self):
        ratio = by_name(rt.compute(sample()))["应收账款周转率"]
        self.assertAlmostEqual(ratio.value, 13.3333, places=3)


class TestVerdict(unittest.TestCase):
    def test_debt_ratio_at_lower_bound_is_normal(self):
        """回归测试：40% 正好在下限，以前被误判成「偏高」（单位写成了 0.40）。"""
        ratio = by_name(rt.compute(sample()))["资产负债率"]
        self.assertEqual(ratio.verdict, "正常")

    def test_debt_ratio_above_upper(self):
        data = sample()
        data["balance_sheet"]["total_liabilities"] = 4000000
        ratio = by_name(rt.compute(data))["资产负债率"]
        self.assertEqual(ratio.verdict, "偏高")

    def test_current_ratio_over_reference(self):
        data = sample()
        data["balance_sheet"]["current_assets"] = 1000000
        ratio = by_name(rt.compute(data))["流动比率"]
        self.assertEqual(ratio.verdict, "偏高")


class TestMissing(unittest.TestCase):
    def test_missing_section(self):
        data = {"balance_sheet": {"current_assets": 100, "current_liabilities": 50}}
        results = by_name(rt.compute(data))
        self.assertIsNone(results["毛利率"].value)
        self.assertAlmostEqual(results["流动比率"].value, 2.0, places=4)

    def test_zero_denominator(self):
        data = sample()
        data["balance_sheet"]["current_liabilities"] = 0
        self.assertIsNone(by_name(rt.compute(data))["流动比率"].value)

    def test_negative_denominator_is_computed(self):
        """所有者权益为负时 ROE 仍然算得出来，只是符号为负。"""
        data = sample()
        data["balance_sheet"]["total_equity"] = -1000000
        ratio = by_name(rt.compute(data))["净资产收益率 ROE"]
        self.assertIsNotNone(ratio.value)
        self.assertLess(ratio.value, 0)


class TestCli(unittest.TestCase):
    def test_calc_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(sample()), encoding="utf-8")
            self.assertEqual(rt.main(["calc", "-i", str(path)]), 0)

    def test_missing_file(self):
        self.assertEqual(rt.main(["calc", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
