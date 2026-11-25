"""Tests for inventory costing. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import inventory as inv  # noqa: E402


def records() -> dict:
    return {
        "records": [
            {"date": "2026-01-05", "type": "in", "qty": 100, "unit_cost": 10},
            {"date": "2026-01-10", "type": "out", "qty": 30},
            {"date": "2026-01-15", "type": "in", "qty": 100, "unit_cost": 12},
            {"date": "2026-01-20", "type": "out", "qty": 80},
        ]
    }


class TestFifo(unittest.TestCase):
    def test_issued_cost(self):
        _issued, _qty, _amount, issues, _method = inv.calculate(dict(records(), method="fifo"))
        self.assertEqual(issues, [])
        data = dict(records(), method="fifo")
        issued, _qty, _amount, _issues, _ = inv.calculate(data)
        self.assertAlmostEqual(sum(i.amount for i in issued), 1120.0, places=2)

    def test_ending_inventory(self):
        issued, qty, amount, _issues, _ = inv.calculate(dict(records(), method="fifo"))
        self.assertEqual(qty, 90)
        self.assertAlmostEqual(amount, 1080.0, places=2, msg="剩 90 件 @12")

    def test_out_exceeds_stock(self):
        data = {"method": "fifo", "records": [
            {"date": "2026-01-01", "type": "in", "qty": 10, "unit_cost": 5},
            {"date": "2026-01-02", "type": "out", "qty": 20},
        ]}
        _issued, _qty, _amount, issues, _ = inv.calculate(data)
        self.assertTrue(any("超过库存" in issue for issue in issues))


class TestWeightedAverage(unittest.TestCase):
    def test_month_end_average(self):
        _issued, qty, amount, issues, _ = inv.calculate(dict(records(), method="weighted_average"))
        self.assertEqual(issues, [])
        issued, qty, amount, _issues, _ = inv.calculate(dict(records(), method="weighted_average"))
        self.assertAlmostEqual(sum(i.amount for i in issued), 1210.0, places=2)
        self.assertAlmostEqual(amount, 990.0, places=2)
        self.assertEqual(qty, 90)

    def test_with_opening(self):
        data = dict(records(), method="weighted_average")
        data["opening_qty"] = 100
        data["opening_amount"] = 900
        _issued, qty, amount, issues, _ = inv.calculate(data)
        self.assertEqual(issues, [])
        # 总数量 300，总金额 900+2200=3100，单价 10.3333，发出 110 → 1136.67
        issued, _q, _a, _i, _ = inv.calculate(data)
        self.assertAlmostEqual(sum(i.amount for i in issued), 1136.67, places=1)


class TestMovingAverage(unittest.TestCase):
    def test_moving_average(self):
        issued, qty, amount, issues, _ = inv.calculate(dict(records(), method="moving_average"))
        self.assertEqual(issues, [])
        self.assertAlmostEqual(sum(i.amount for i in issued), 1194.12, places=1)
        self.assertAlmostEqual(amount, 1005.88, places=1)
        self.assertEqual(qty, 90)

    def test_three_methods_differ(self):
        totals = {}
        for method in ("fifo", "weighted_average", "moving_average"):
            issued, _q, _a, _i, _m = inv.calculate(dict(records(), method=method))
            totals[method] = round(sum(i.amount for i in issued), 2)
        self.assertEqual(len(set(totals.values())), 3, f"三种方法应给出三种结果：{totals}")


class TestValidation(unittest.TestCase):
    def test_no_records(self):
        _i, _q, _a, issues, _m = inv.calculate({"method": "fifo", "records": []})
        self.assertTrue(any("没有收发记录" in issue for issue in issues))

    def test_unknown_method(self):
        _i, _q, _a, issues, _m = inv.calculate(dict(records(), method="magic"))
        self.assertTrue(any("未知" in issue for issue in issues))

    def test_out_with_zero_stock(self):
        data = {"method": "moving_average", "records": [
            {"date": "2026-01-01", "type": "out", "qty": 5},
        ]}
        _i, _q, _a, issues, _m = inv.calculate(data)
        self.assertTrue(any("库存为 0" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
