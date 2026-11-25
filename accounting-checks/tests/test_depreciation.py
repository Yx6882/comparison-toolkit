"""Tests for depreciation. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import depreciation as dp  # noqa: E402


def base(**overrides) -> dict:
    data = {
        "method": "straight_line",
        "original_cost": 120000,
        "residual_value": 6000,
        "useful_life_years": 5,
        "start_period": "2026-01",
    }
    data.update(overrides)
    return data


def total(data: dict) -> float:
    schedule, _issues = dp.build_schedule(data)
    return round(sum(item.amount for item in schedule), 2)


class TestStraightLine(unittest.TestCase):
    def test_total_equals_cost_minus_residual(self):
        self.assertAlmostEqual(total(base()), 114000.0, places=2)

    def test_monthly_amount(self):
        schedule, _ = dp.build_schedule(base())
        self.assertEqual(len(schedule), 60)
        self.assertAlmostEqual(schedule[0].amount, 1900.0, places=2)

    def test_ending_net_equals_residual(self):
        schedule, _ = dp.build_schedule(base())
        self.assertAlmostEqual(schedule[-1].net_book, 6000.0, places=2)

    def test_first_period_starts_next_month(self):
        schedule, _ = dp.build_schedule(base(start_period="2026-01"))
        self.assertEqual(schedule[0].period, "2026-02", "当月增加当月不提")


class TestMethods(unittest.TestCase):
    def test_double_declining_total(self):
        self.assertAlmostEqual(total(base(method="double_declining")), 114000.0, places=2)

    def test_double_declining_front_loaded(self):
        schedule, _ = dp.build_schedule(base(method="double_declining"))
        self.assertGreater(schedule[0].amount, schedule[-1].amount, "双倍递减应前高后低")

    def test_sum_of_years_total(self):
        self.assertAlmostEqual(total(base(method="sum_of_years")), 114000.0, places=2)

    def test_sum_of_years_front_loaded(self):
        schedule, _ = dp.build_schedule(base(method="sum_of_years"))
        self.assertGreater(schedule[0].amount, schedule[-1].amount)

    def test_units_of_production(self):
        data = base(method="units_of_production")
        data.pop("useful_life_years")
        data["work_units"] = {"total": 10000, "per_period": [1000, 2000, 3000]}
        schedule, _ = dp.build_schedule(data)
        self.assertEqual(len(schedule), 3)
        self.assertAlmostEqual(sum(p.amount for p in schedule), 114000.0 * 0.6, places=2)


class TestDisposal(unittest.TestCase):
    def test_partial_disposal_stops(self):
        schedule, _ = dp.build_schedule(base(disposal_period="2027-06"))
        self.assertEqual(schedule[-1].period, "2027-06", "处置当月照提，次月停提")
        self.assertEqual(len(schedule), 17)  # 2026-02 到 2027-06

    def test_disposal_before_start(self):
        _schedule, issues = dp.build_schedule(base(disposal_period="2025-12"))
        self.assertTrue(any("早于" in issue for issue in issues))


class TestValidation(unittest.TestCase):
    def test_residual_cannot_exceed_cost(self):
        _schedule, issues = dp.build_schedule(base(residual_value=200000))
        self.assertTrue(issues)

    def test_zero_life_rejected(self):
        _schedule, issues = dp.build_schedule(base(useful_life_years=0))
        self.assertTrue(issues)

    def test_bad_start_period(self):
        _schedule, issues = dp.build_schedule(base(start_period="明年"))
        self.assertTrue(any("起算期间" in issue for issue in issues))

    def test_unknown_method(self):
        _schedule, issues = dp.build_schedule(base(method="magic"))
        self.assertTrue(any("未知" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
