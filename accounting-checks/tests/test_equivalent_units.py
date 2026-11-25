"""Tests for equivalent-units costing. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import equivalent_units as eu  # noqa: E402


def base(**overrides) -> dict:
    data = {
        "method": "weighted_average",
        "opening_wip": {"qty": 100, "material_cost": 5000, "conversion_cost": 2000},
        "current": {"material_cost": 20000, "conversion_cost": 10000},
        "completed": 400,
        "ending_wip": {"qty": 200, "material_completion": 1.0, "conversion_completion": 0.5},
    }
    data.update(overrides)
    return data


class TestEquivalentUnits(unittest.TestCase):
    def test_material_eu(self):
        result, _issues = eu.calculate(base())
        self.assertAlmostEqual(result.material_eu, 600.0, places=2)  # 400 + 200×1.0

    def test_conversion_eu(self):
        result, _issues = eu.calculate(base())
        self.assertAlmostEqual(result.conversion_eu, 500.0, places=2)  # 400 + 200×0.5

    def test_unit_costs(self):
        result, _issues = eu.calculate(base())
        self.assertAlmostEqual(result.material_unit, 25000 / 600, places=4)
        self.assertAlmostEqual(result.conversion_unit, 12000 / 500, places=4)

    def test_cost_balance(self):
        result, issues = eu.calculate(base())
        self.assertFalse(any("不平" in issue for issue in issues))
        self.assertAlmostEqual(result.finished_cost + result.ending_wip_cost, result.total_cost, places=2)

    def test_finished_cost(self):
        result, _ = eu.calculate(base())
        self.assertAlmostEqual(result.finished_cost, 400 * (25000 / 600 + 12000 / 500), places=2)

    def test_zero_completion(self):
        data = base()
        data["ending_wip"]["conversion_completion"] = 0.0
        result, _ = eu.calculate(data)
        self.assertAlmostEqual(result.conversion_eu, 400.0, places=2)


class TestValidation(unittest.TestCase):
    def test_completion_out_of_range(self):
        data = base()
        data["ending_wip"]["material_completion"] = 1.5
        _result, issues = eu.calculate(data)
        self.assertTrue(any("完工程度" in issue for issue in issues))

    def test_negative_quantity(self):
        result, issues = eu.calculate(base(completed=-1))
        self.assertIsNone(result)
        self.assertTrue(issues)

    def test_overhead_merged(self):
        data = base()
        data["current"]["overhead_cost"] = 3000
        result, issues = eu.calculate(data)
        self.assertTrue(any("制造费用" in issue for issue in issues))
        self.assertAlmostEqual(result.conversion_unit, (12000 + 3000) / 500, places=4)

    def test_unsupported_method(self):
        _result, issues = eu.calculate(base(method="fifo"))
        self.assertTrue(any("暂不支持" in issue for issue in issues))

    def test_zero_eu(self):
        data = base()
        data["completed"] = 0
        data["ending_wip"]["qty"] = 0
        result, issues = eu.calculate(data)
        self.assertIsNone(result)
        self.assertTrue(issues)


if __name__ == "__main__":
    unittest.main()
