"""Tests for exchange. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import exchange as ex  # noqa: E402


def make_data(*, hours_old: float = 0.1, single_point: bool = False) -> dict:
    fetched = (dt.datetime.now().astimezone() - dt.timedelta(hours=hours_old)).isoformat(timespec="seconds")
    return {
        "meta": {"fetched_at": fetched, "source": "test", "warning": ""},
        "items": {
            "铜": {
                "name": "铜", "symbol": "nf_CU0", "market": "沪铜连续", "last": 80000.0,
                "low": 80000.0 if single_point else 78000.0,
                "high": 80000.0 if single_point else 82000.0,
                "prev_settle": 79000.0, "as_of": "2026-11-25", "source": "test",
            },
            "铝": {
                "name": "铝", "symbol": "nf_AL0", "market": "沪铝连续", "last": 20000.0,
                "low": 20000.0 if single_point else 19500.0,
                "high": 20000.0 if single_point else 20500.0,
                "prev_settle": 19900.0, "as_of": "2026-11-25", "source": "test",
            },
        },
    }


class TestUnits(unittest.TestCase):
    def test_ton_to_jin(self):
        self.assertEqual(ex.per_unit(20000, "斤"), 10.0)

    def test_ton_to_kg(self):
        self.assertEqual(ex.per_unit(20000, "公斤"), 20.0)

    def test_unknown_unit(self):
        with self.assertRaises(SystemExit):
            ex.per_unit(20000, "石")


class TestConvert(unittest.TestCase):
    def test_mid_value(self):
        result = ex.convert(make_data(), "铜", "铝", 1, "斤")
        self.assertAlmostEqual(result.mid, 4.0, places=6)

    def test_range_brackets_mid(self):
        result = ex.convert(make_data(), "铜", "铝", 1, "斤")
        self.assertLess(result.low, result.mid)
        self.assertGreater(result.high, result.mid)

    def test_range_values(self):
        # 最不利：铜取低 78000、铝取高 20500 → 3.80；最有利：铜高 82000、铝低 19500 → 4.21
        result = ex.convert(make_data(), "铜", "铝", 1, "斤")
        self.assertAlmostEqual(result.low, 78000 / 20500, places=6)
        self.assertAlmostEqual(result.high, 82000 / 19500, places=6)

    def test_quantity_scales(self):
        one = ex.convert(make_data(), "铜", "铝", 1, "斤")
        ten = ex.convert(make_data(), "铜", "铝", 10, "斤")
        self.assertAlmostEqual(ten.mid, one.mid * 10, places=6)

    def test_unknown_material(self):
        with self.assertRaises(SystemExit):
            ex.convert(make_data(), "铜", "黄金", 1, "斤")

    def test_stale_data_flagged(self):
        result = ex.convert(make_data(hours_old=24), "铜", "铝", 1, "斤")
        statuses = dict(result.checks)
        self.assertIn("⚠", statuses["行情时效"])

    def test_fresh_data_ok(self):
        result = ex.convert(make_data(hours_old=0.5), "铜", "铝", 1, "斤")
        statuses = dict(result.checks)
        self.assertIn("✅", statuses["行情时效"])

    def test_single_point_flagged(self):
        result = ex.convert(make_data(single_point=True), "铜", "铝", 1, "斤")
        statuses = dict(result.checks)
        self.assertIn("⚠", statuses["价格区间"])

    def test_trading_cost_always_flagged(self):
        result = ex.convert(make_data(), "铜", "铝", 1, "斤")
        statuses = dict(result.checks)
        self.assertIn("⚠", statuses["交易成本"])
        self.assertIn("⚠", statuses["价格性质"])

    def test_single_source_flagged(self):
        result = ex.convert(make_data(), "铜", "铝", 1, "斤")
        self.assertIn("只有单源", dict(result.checks)["多源交叉"])

    def test_cross_source_agrees(self):
        data = make_data()
        data["items"]["铜"]["cross"] = {
            "source": "东方财富", "price": 79900.0, "market": "沪铜主连", "spread_pct": 0.13,
        }
        result = ex.convert(data, "铜", "铝", 1, "斤")
        self.assertIn("✅", dict(result.checks)["多源交叉"])

    def test_cross_source_conflict(self):
        data = make_data()
        data["items"]["铜"]["cross"] = {
            "source": "东方财富", "price": 76000.0, "market": "沪铜主连", "spread_pct": 5.0,
        }
        result = ex.convert(data, "铜", "铝", 1, "斤")
        self.assertIn("疑似数据错位", dict(result.checks)["多源交叉"])

    def test_cross_source_minor_drift(self):
        data = make_data()
        data["items"]["铜"]["cross"] = {
            "source": "东方财富", "price": 79000.0, "market": "沪铜主连", "spread_pct": 1.25,
        }
        result = ex.convert(data, "铜", "铝", 1, "斤")
        self.assertIn("口径不同", dict(result.checks)["多源交叉"])


class TestReport(unittest.TestCase):
    def test_report_contains_manual_check(self):
        data = make_data()
        result = ex.convert(data, "铜", "铝", 1, "斤")
        report = ex.render(result, data)
        self.assertIn("请以当日实际报价人工核对", report)
        self.assertIn("⚠ 未计交易成本", report)
        self.assertIn("4.00", report)
        self.assertIn("公式", report)

    def test_report_states_source(self):
        data = make_data()
        report = ex.render(ex.convert(data, "铜", "铝", 1, "斤"), data)
        self.assertIn("新浪财经", report) if "新浪" in data["meta"]["source"] else self.assertIn("test", report)


class TestSelfTest(unittest.TestCase):
    def test_builtin(self):
        self.assertEqual(ex.main(["selftest"]), 0)


if __name__ == "__main__":
    unittest.main()
