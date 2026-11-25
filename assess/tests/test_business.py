"""Tests for business payback / stress / city coefficient. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import business as bs  # noqa: E402


def base(**overrides) -> dict:
    data = {
        "investment": 500000,
        "monthly_revenue": 120000,
        "variable_cost_rate": 0.40,
        "monthly_fixed_cost": 50000,
    }
    data.update(overrides)
    return data


class TestPayback(unittest.TestCase):
    def test_monthly_net(self):
        result = bs.compute_payback(base())
        # 120000 × 0.6 − 50000 = 22000
        self.assertAlmostEqual(result.monthly_net, 22000.0, places=2)

    def test_payback_months(self):
        result = bs.compute_payback(base())
        self.assertAlmostEqual(result.payback_months, 500000 / 22000, places=3)

    def test_breakeven_revenue(self):
        result = bs.compute_payback(base())
        self.assertAlmostEqual(result.breakeven_revenue, 50000 / 0.6, places=2)

    def test_loss_makes_payback_impossible(self):
        result = bs.compute_payback(base(monthly_revenue=70000))
        self.assertIsNone(result.payback_months)
        self.assertIn("回不了本", result.note)

    def test_variable_rate_one_hundred_percent(self):
        result = bs.compute_payback(base(variable_cost_rate=1.0))
        self.assertIsNone(result.breakeven_revenue, "变动成本率 100% 时没有保本点")

    def test_long_payback_warns(self):
        result = bs.compute_payback(base(investment=2000000))
        self.assertGreater(result.payback_months or 0, 36)
        self.assertIn("3 年", result.note)


class TestStress(unittest.TestCase):
    def test_scenarios_count(self):
        self.assertEqual(len(bs.run_stress(base())), 6)

    def test_baseline_is_first(self):
        self.assertEqual(bs.run_stress(base())[0].name, "当前")

    def test_revenue_drop_increases_payback(self):
        scenarios = {s.name: s for s in bs.run_stress(base())}
        self.assertGreater(scenarios["收入 −20%"].payback_months or 0,
                           scenarios["当前"].payback_months or 0)

    def test_double_hit_can_go_negative(self):
        scenarios = {s.name: s for s in bs.run_stress(base())}
        double = scenarios["收入 −20% 且 成本 +20%"]
        self.assertLess(double.net, 0, "双杀场景应该变成亏损")
        self.assertEqual(double.status, "亏损")

    def test_edge_still_profitable(self):
        scenarios = {s.name: s for s in bs.run_stress(base())}
        self.assertEqual(scenarios["当前"].status, "基准")


class TestCity(unittest.TestCase):
    def test_no_income_returns_none(self):
        result = bs.city_coefficient(base())
        self.assertIsNone(result["ratio"])

    def test_below_national(self):
        result = bs.city_coefficient(base(city_disposable_income=20000))
        self.assertLess(result["ratio"] or 1, 1)
        self.assertLess(result["rent"] or 1, 1)

    def test_above_national(self):
        result = bs.city_coefficient(base(city_disposable_income=80000))
        self.assertGreater(result["ratio"] or 0, 1)
        # 租金指数 1.3，应高于收入比
        self.assertGreater(result["rent"] or 0, result["ratio"] or 0)

    def test_rent_most_sensitive(self):
        result = bs.city_coefficient(base(city_disposable_income=60000))
        self.assertGreater(result["rent"] or 0, result["labour"] or 0)
        self.assertGreater(result["labour"] or 0, result["price"] or 0)

    def test_exactly_national(self):
        result = bs.city_coefficient(base(city_disposable_income=bs.NATIONAL_INCOME_BASELINE))
        self.assertAlmostEqual(result["ratio"] or 0, 1.0, places=4)


class TestRamp(unittest.TestCase):
    """爬坡期：开店最容易死的一段。"""

    def test_no_ramp_returns_none(self):
        self.assertIsNone(bs.compute_ramp(base()))

    def test_month_count(self):
        rows, _total, _reserve = bs.compute_ramp(base(ramp_months=6))
        self.assertEqual(len(rows), 6)

    def test_first_month_is_start_ratio(self):
        rows, _t, _r = bs.compute_ramp(base(ramp_months=6, ramp_start_ratio=0.4))
        self.assertAlmostEqual(rows[0].revenue_ratio, 0.4, places=4)
        self.assertAlmostEqual(rows[0].revenue, 120000 * 0.4, places=2)

    def test_last_month_is_full(self):
        rows, _t, _r = bs.compute_ramp(base(ramp_months=6, ramp_start_ratio=0.4))
        self.assertAlmostEqual(rows[-1].revenue_ratio, 1.0, places=4)

    def test_cash_reserve_positive(self):
        """爬坡期必然要先垫钱，储备金必须大于 0。"""
        _rows, _total, reserve = bs.compute_ramp(base(ramp_months=6, ramp_start_ratio=0.4))
        self.assertGreater(reserve, 0)

    def test_lower_start_needs_more_cash(self):
        _r1, _t1, low = bs.compute_ramp(base(ramp_months=6, ramp_start_ratio=0.2))
        _r2, _t2, high = bs.compute_ramp(base(ramp_months=6, ramp_start_ratio=0.7))
        self.assertGreater(low, high, "起步越低，需要垫的钱越多")

    def test_single_month_ramp(self):
        rows, _t, _r = bs.compute_ramp(base(ramp_months=1, ramp_start_ratio=0.5))
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0].revenue_ratio, 1.0, places=4)


class TestLease(unittest.TestCase):
    """租约覆盖：比回本周期本身更致命。"""

    def test_no_lease_returns_none(self):
        self.assertIsNone(bs.check_lease(base(), bs.compute_payback(base())))

    def test_lease_shorter_than_payback(self):
        payback = bs.compute_payback(base())  # 22.7 个月
        check = bs.check_lease(base(lease_months=18), payback)
        self.assertEqual(check.verdict, "租约内回不了本")
        self.assertLess(check.profitable_months, 0)

    def test_tight_lease(self):
        payback = bs.compute_payback(base())
        check = bs.check_lease(base(lease_months=25), payback)
        self.assertEqual(check.verdict, "几乎没有盈利期")

    def test_comfortable_lease(self):
        payback = bs.compute_payback(base())
        check = bs.check_lease(base(lease_months=60), payback)
        self.assertEqual(check.verdict, "租约覆盖足够")
        self.assertGreater(check.profitable_months, 30)


class TestCli(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(bs.main(["payback", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
