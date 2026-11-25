"""Tests for indirect-method cash flow. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import cashflow as cf  # noqa: E402


def base(**overrides) -> dict:
    data = {
        "income_statement": {"net_profit": 500000},
        "non_cash": {"depreciation": 100000, "amortization": 20000, "impairment": 30000},
        "working_capital": {
            "receivables_change": 50000,
            "inventory_change": -30000,
            "payables_change": 40000,
        },
    }
    data.update(overrides)
    return data


class TestCalculation(unittest.TestCase):
    def test_operating_cash_flow(self):
        result, issues = cf.calculate(base())
        # 500000 + 100000 + 20000 + 30000 - 50000 + 30000 + 40000
        self.assertAlmostEqual(result.operating_cash_flow, 670000.0, places=2)
        self.assertEqual(issues, [])

    def test_inventory_decrease_adds_back(self):
        result, _ = cf.calculate(base())
        line = next(item for item in result.lines if "存货" in item.label)
        self.assertGreater(line.amount, 0, "存货减少应显示为对现金流的正影响")

    def test_receivables_increase_subtracts(self):
        result, _ = cf.calculate(base())
        line = next(item for item in result.lines if "应收" in item.label)
        self.assertLess(line.amount, 0)

    def test_payables_increase_adds(self):
        result, _ = cf.calculate(base())
        line = next(item for item in result.lines if "应付" in item.label)
        self.assertGreater(line.amount, 0)

    def test_disposal_gain_subtracted(self):
        data = base()
        data["non_cash"]["gain_on_disposal"] = 10000
        result, _ = cf.calculate(data)
        self.assertAlmostEqual(result.operating_cash_flow, 660000.0, places=2)

    def test_scrapping_loss_added(self):
        data = base()
        data["non_cash"]["loss_on_scrapping"] = 5000
        result, _ = cf.calculate(data)
        self.assertAlmostEqual(result.operating_cash_flow, 675000.0, places=2)


class TestReportedComparison(unittest.TestCase):
    def test_matching(self):
        data = base(reported_operating_cash_flow=670000)
        result, issues = cf.calculate(data)
        self.assertEqual(result.gap, 0.0)
        self.assertEqual(issues, [])

    def test_mismatch_reported(self):
        data = base(reported_operating_cash_flow=700000)
        result, issues = cf.calculate(data)
        self.assertAlmostEqual(result.gap, 30000.0, places=2)
        self.assertTrue(issues)

    def test_tolerance_is_one_cent(self):
        data = base(reported_operating_cash_flow=670000.01)
        result, issues = cf.calculate(data)
        self.assertEqual(issues, [], "一分钱以内不算差异")

    def test_no_reported_value(self):
        result, issues = cf.calculate(base())
        self.assertIsNone(result.reported)
        self.assertEqual(issues, [])


class TestValidation(unittest.TestCase):
    def test_missing_net_profit(self):
        result, issues = cf.calculate({"non_cash": {}})
        self.assertIsNone(result)
        self.assertTrue(issues)


if __name__ == "__main__":
    unittest.main()
