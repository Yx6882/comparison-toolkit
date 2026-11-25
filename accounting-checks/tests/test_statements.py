"""Tests for the three-statement tie-out. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import statements as st  # noqa: E402


def good_data() -> dict:
    return {
        "balance_sheet": {
            "total_assets": 5000000,
            "total_liabilities": 2000000,
            "total_equity": 3000000,
            "cash_and_equivalents": 800000,
        },
        "income_statement": {"net_profit": 500000},
        "cash_flow": {"ending_cash": 800000},
        "equity_change": {
            "opening_retained": 2000000,
            "closing_retained": 2500000,
            "dividends": 0,
            "prior_adjustments": 0,
        },
    }


class TestBalanceSheet(unittest.TestCase):
    def test_balanced(self):
        check = st.check_balance_sheet(good_data())
        self.assertTrue(check.ok)

    def test_unbalanced_reports_gap(self):
        data = good_data()
        data["balance_sheet"]["total_assets"] = 5000100
        check = st.check_balance_sheet(data)
        self.assertFalse(check.ok)
        self.assertAlmostEqual(check.gap, 100.0, places=2)

    def test_missing_field_is_skipped_not_passed(self):
        data = good_data()
        del data["balance_sheet"]["total_equity"]
        check = st.check_balance_sheet(data)
        self.assertIsNone(check.ok, "缺数据必须是 None，不能当成通过")

    def test_tolerance_is_one_cent(self):
        data = good_data()
        data["balance_sheet"]["total_assets"] = 5000000.01
        self.assertTrue(st.check_balance_sheet(data).ok, "一分钱以内算平")

        data["balance_sheet"]["total_assets"] = 5000000.02
        self.assertFalse(st.check_balance_sheet(data).ok, "超过一分钱要报")


class TestRetainedEarnings(unittest.TestCase):
    def test_roll_forward_ok(self):
        self.assertTrue(st.check_retained_earnings(good_data()).ok)

    def test_roll_forward_broken(self):
        data = good_data()
        data["equity_change"]["closing_retained"] = 2450000
        check = st.check_retained_earnings(data)
        self.assertFalse(check.ok)
        self.assertAlmostEqual(check.gap, -50000.0, places=2)

    def test_dividends_and_adjustments(self):
        data = good_data()
        data["equity_change"]["dividends"] = 100000
        data["equity_change"]["prior_adjustments"] = 30000
        data["equity_change"]["closing_retained"] = 2430000  # 2000000+500000-100000+30000
        self.assertTrue(st.check_retained_earnings(data).ok)

    def test_missing_net_profit_skips(self):
        data = good_data()
        del data["income_statement"]["net_profit"]
        self.assertIsNone(st.check_retained_earnings(data).ok)


class TestCash(unittest.TestCase):
    def test_cash_matches(self):
        self.assertTrue(st.check_cash(good_data()).ok)

    def test_cash_mismatch(self):
        data = good_data()
        data["cash_flow"]["ending_cash"] = 799000
        check = st.check_cash(data)
        self.assertFalse(check.ok)
        self.assertAlmostEqual(check.gap, -1000.0, places=2)


class TestProfitConsistency(unittest.TestCase):
    def test_skipped_when_only_one_source(self):
        self.assertIsNone(st.check_profit_consistency(good_data()).ok)

    def test_consistent(self):
        data = good_data()
        data["equity_change"]["net_profit"] = 500000
        self.assertTrue(st.check_profit_consistency(data).ok)

    def test_inconsistent(self):
        data = good_data()
        data["equity_change"]["net_profit"] = 480000
        check = st.check_profit_consistency(data)
        self.assertFalse(check.ok)
        self.assertAlmostEqual(check.gap, 20000.0, places=2)


class TestCli(unittest.TestCase):
    def test_exit_code_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            data = good_data()
            data["balance_sheet"]["total_assets"] = 5000100
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(st.main(["check", "-i", str(path)]), 1)

    def test_exit_code_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(good_data()), encoding="utf-8")
            self.assertEqual(st.main(["check", "-i", str(path)]), 0)

    def test_missing_file(self):
        self.assertEqual(st.main(["check", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
