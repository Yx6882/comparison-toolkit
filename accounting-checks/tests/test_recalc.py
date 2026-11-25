"""Tests for independent statement recalculation. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import recalc as rc  # noqa: E402


def accounts() -> list[dict]:
    return [
        {"code": "1001", "closing": 5000},
        {"code": "1002", "closing": 795000},
        {"code": "1122", "closing": 320000},
        {"code": "1231", "closing": 20000},
        {"code": "1403", "closing": 300000},
        {"code": "1601", "closing": 2000000},
        {"code": "1602", "closing": 400000},
        {"code": "2202", "closing": 600000},
        {"code": "2211", "closing": 200000},
        {"code": "4001", "closing": 1500000},
        {"code": "4103", "closing": 500000},
        {"code": "6001", "closing": 4000000},
        {"code": "6401", "closing": 2800000},
        {"code": "6602", "closing": 600000},
        {"code": "6801", "closing": 100000},
    ]


def data(**overrides) -> dict:
    payload = {"accounts": accounts(), "reported": {}}
    payload.update(overrides)
    return payload


def computed_map(payload: dict) -> dict[str, float]:
    balances = rc.build_balances(payload)
    result = rc.compute_section(balances, rc.BALANCE_SHEET, payload.get("mapping"))
    result.update(rc.compute_section(balances, rc.INCOME_STATEMENT, payload.get("mapping")))
    return rc.derive(result)


class TestComputation(unittest.TestCase):
    def test_cash(self):
        self.assertAlmostEqual(computed_map(data())["货币资金"], 800000.0, places=2)

    def test_receivables_net_of_provision(self):
        self.assertAlmostEqual(computed_map(data())["应收账款"], 300000.0, places=2)

    def test_fixed_assets_net_of_depreciation(self):
        self.assertAlmostEqual(computed_map(data())["固定资产"], 1600000.0, places=2)

    def test_liabilities_are_positive(self):
        """负债在报表里是正数列示，不该被取反成负数。"""
        self.assertAlmostEqual(computed_map(data())["应付账款"], 600000.0, places=2)

    def test_equity_positive(self):
        self.assertAlmostEqual(computed_map(data())["实收资本"], 1500000.0, places=2)

    def test_derived_profit(self):
        result = computed_map(data())
        self.assertAlmostEqual(result["营业利润"], 600000.0, places=2)  # 4000000-2800000-600000
        self.assertAlmostEqual(result["净利润"], 500000.0, places=2)

    def test_assets_total(self):
        result = computed_map(data())
        self.assertAlmostEqual(result["资产总计"], 3000000.0, places=2)  # 800k+300k+300k+1600k


class TestCompare(unittest.TestCase):
    def test_all_matching(self):
        payload = data(reported={
            "货币资金": 800000, "应收账款": 300000, "固定资产": 1600000,
            "应付账款": 600000, "净利润": 500000,
        })
        lines, _issues = rc.run(payload)
        self.assertTrue(all(line.status == "ok" for line in lines))

    def test_mismatch_detected(self):
        payload = data(reported={"货币资金": 800100})
        lines, _issues = rc.run(payload)
        bad = [line for line in lines if line.status == "mismatch"]
        self.assertEqual(len(bad), 1)
        self.assertAlmostEqual(bad[0].gap, 100.0, places=2)

    def test_unlisted_items_skipped(self):
        """报表没列的项目不该算成缺项。"""
        payload = data(reported={"货币资金": 800000})
        lines, _issues = rc.run(payload)
        self.assertEqual([line.name for line in lines], ["货币资金"])

    def test_reported_only_item_marked_no_data(self):
        payload = data(reported={"递延所得税资产": 12345})
        lines, _issues = rc.run(payload)
        self.assertTrue(any(line.status == "no-data" for line in lines))

    def test_mapping_override(self):
        payload = data(mapping={"货币资金": [["9999", 1]]})
        payload["accounts"].append({"code": "9999", "closing": 123456})
        self.assertAlmostEqual(computed_map(payload)["货币资金"], 123456.0, places=2)


class TestValidation(unittest.TestCase):
    def test_no_accounts(self):
        lines, issues = rc.run({"accounts": [], "reported": {}})
        self.assertEqual(lines, [])
        self.assertTrue(issues)


if __name__ == "__main__":
    unittest.main()
