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


class TestSensitivity(unittest.TestCase):
    def test_three_variables(self):
        rows = bs.analyze_sensitivity(base())
        self.assertEqual(len(rows), 3)
        self.assertEqual({r.name for r in rows}, {"月收入", "变动成本率", "固定成本"})

    def test_revenue_positive_impact(self):
        rows = {r.name: r for r in bs.analyze_sensitivity(base())}
        self.assertGreater(rows["月收入"].delta_net, 0)

    def test_costs_negative_impact(self):
        rows = {r.name: r for r in bs.analyze_sensitivity(base())}
        self.assertLess(rows["变动成本率"].delta_net, 0)
        self.assertLess(rows["固定成本"].delta_net, 0)

    def test_sorted_by_absolute_impact(self):
        rows = bs.analyze_sensitivity(base())
        values = [abs(r.delta_net) for r in rows]
        self.assertEqual(values, sorted(values, reverse=True))

    def test_zero_net_returns_empty(self):
        zero = base(monthly_revenue=83333.333, monthly_fixed_cost=50000)
        rows = bs.analyze_sensitivity(zero)
        self.assertIsInstance(rows, list)


class TestSeasonal(unittest.TestCase):
    def test_requires_twelve_factors(self):
        self.assertIsNone(bs.analyze_seasonal(base(monthly_factors=[1, 2, 3])))

    def test_twelve_months(self):
        result = bs.analyze_seasonal(base(monthly_factors=[1.0] * 12))
        rows, _total, _lm, _lv = result
        self.assertEqual(len(rows), 12)

    def test_flat_year_matches_monthly(self):
        result = bs.analyze_seasonal(base(monthly_factors=[1.0] * 12))
        _rows, total, _lm, _lv = result
        self.assertAlmostEqual(total, 22000 * 12, places=2)

    def test_lowest_month_detected(self):
        factors = [0.5, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
        result = bs.analyze_seasonal(base(monthly_factors=factors))
        _rows, _total, lowest_month, lowest_value = result
        self.assertIn(lowest_month, (1, 2))
        self.assertLess(lowest_value, 0)


class TestPlatform(unittest.TestCase):
    def platform(self, **overrides) -> dict:
        spec = {
            "price": 100, "product_cost": 35, "commission_rate": 0.06,
            "promotion_rate": 0.18, "shipping": 6, "return_rate": 0.15,
        }
        spec.update(overrides)
        return {"platform": spec}

    def test_no_platform_returns_none(self):
        self.assertIsNone(bs.analyze_platform(base()))

    def test_net_profit_with_returns(self):
        result = bs.analyze_platform(self.platform())
        # 0.85×(100-6-18-35-6) + 0.15×(-(18+12)) = 29.75 - 4.5 = 25.25
        self.assertAlmostEqual(result.net_profit, 25.25, places=2)

    def test_zero_returns(self):
        result = bs.analyze_platform(self.platform(return_rate=0.0))
        self.assertAlmostEqual(result.net_profit, 100 - 6 - 18 - 35 - 6, places=2)

    def test_high_return_rate_flagged(self):
        result = bs.analyze_platform(self.platform(return_rate=0.25))
        self.assertIn("退货", result.note)

    def test_losing_money_flagged(self):
        result = bs.analyze_platform(self.platform(promotion_rate=0.5))
        self.assertLess(result.net_profit, 0)
        self.assertTrue(result.note)


class TestLabor(unittest.TestCase):
    def labor(self, **overrides) -> dict:
        spec = {"headcount": 5, "monthly_wage": 6000, "insurance_base": 6000,
                "housing_fund_rate": 0.07}
        spec.update(overrides)
        return {"labor": spec}

    def test_no_labor_returns_none(self):
        self.assertIsNone(bs.analyze_labor(base()))

    def test_total_cost(self):
        result = bs.analyze_labor(self.labor())
        # 工资 30000 + 社保 5×6000×0.257 + 公积金 5×6000×0.07
        expected = 30000 + 5 * 6000 * 0.257 + 5 * 6000 * 0.07
        self.assertAlmostEqual(result.total, expected, places=2)

    def test_overhead_ratio(self):
        result = bs.analyze_labor(self.labor())
        self.assertGreater(result.overhead_ratio, 0.2)
        self.assertLess(result.overhead_ratio, 0.4)

    def test_custom_rates(self):
        low = bs.analyze_labor(self.labor(insurance_rates={"pension": 0.08}))
        high = bs.analyze_labor(self.labor())
        self.assertLess(low.insurance, high.insurance)

    def test_zero_headcount(self):
        self.assertIsNone(bs.analyze_labor(self.labor(headcount=0)))


class TestCompare(unittest.TestCase):
    def test_compare_two_stores(self):
        data = {"stores": [
            {"name": "A", "investment": 500000, "monthly_revenue": 120000,
             "variable_cost_rate": 0.40, "monthly_fixed_cost": 50000},
            {"name": "B", "investment": 300000, "monthly_revenue": 80000,
             "variable_cost_rate": 0.45, "monthly_fixed_cost": 30000},
        ]}
        rows = bs.compare_stores(data)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "A")

    def test_empty_stores(self):
        self.assertEqual(bs.compare_stores({}), [])

    def test_unnamed_store_gets_label(self):
        data = {"stores": [{"investment": 100000, "monthly_revenue": 50000,
                            "variable_cost_rate": 0.40, "monthly_fixed_cost": 20000}]}
        rows = bs.compare_stores(data)
        self.assertEqual(rows[0][0], "店1")


class TestCli(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(bs.main(["payback", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
