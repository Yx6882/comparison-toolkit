"""Tests for bad-debt aging. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bad_debt as bd  # noqa: E402


def base(**overrides) -> dict:
    data = {
        "as_of": "2026-10-31",
        "existing_provision": 3000,
        "receivables": [
            {"customer": "甲", "amount": 50000, "due_date": "2026-10-15"},   # 16 天
            {"customer": "乙", "amount": 30000, "due_date": "2026-08-01"},   # 91 天
            {"customer": "丙", "amount": 20000, "due_date": "2026-03-01"},   # 244 天
            {"customer": "丁", "amount": 10000, "due_date": "2025-06-01"},   # 517 天
        ],
    }
    data.update(overrides)
    return data


class TestBuckets(unittest.TestCase):
    def test_total_receivable(self):
        result, _issues = bd.calculate(base())
        self.assertAlmostEqual(result.total_receivable, 110000.0, places=2)

    def test_required_provision(self):
        result, _issues = bd.calculate(base())
        # 50000×5% + 30000×30% + 20000×50% + 10000×100%
        self.assertAlmostEqual(result.required_provision, 31500.0, places=2)

    def test_adjustment_is_shortfall(self):
        result, _issues = bd.calculate(base())
        self.assertAlmostEqual(result.adjustment, 28500.0, places=2)

    def test_existing_larger_means_reversal(self):
        result, _issues = bd.calculate(base(existing_provision=40000))
        self.assertLess(result.adjustment, 0)
        self.assertAlmostEqual(result.adjustment, -8500.0, places=2)

    def test_labels_are_left_open(self):
        result, _issues = bd.calculate(base())
        labels = [bucket.label for bucket in result.buckets if bucket.amount > 0]
        self.assertIn("91–180 天", labels, "91 天应落在 91–180 而不是 90–180")
        self.assertIn("181–365 天", labels)


class TestEdgeCases(unittest.TestCase):
    def test_missing_due_date_skipped(self):
        data = base()
        data["receivables"].append({"customer": "戊", "amount": 5000})
        _result, issues = bd.calculate(data)
        self.assertTrue(any("到期日" in issue for issue in issues))

    def test_future_due_date_clamped(self):
        data = {"as_of": "2026-10-31", "receivables": [
            {"customer": "己", "amount": 1000, "due_date": "2026-12-01"},
        ]}
        _result, issues = bd.calculate(data)
        self.assertTrue(any("之后" in issue for issue in issues))

    def test_negative_amount_skipped(self):
        data = base()
        data["receivables"].append({"customer": "庚", "amount": -100, "due_date": "2026-01-01"})
        _result, issues = bd.calculate(data)
        self.assertTrue(any("金额非正" in issue for issue in issues))

    def test_missing_as_of(self):
        result, issues = bd.calculate({"receivables": []})
        self.assertIsNone(result)
        self.assertTrue(issues)

    def test_custom_buckets(self):
        data = base(buckets=[
            {"max_days": 60, "rate": 0.02},
            {"max_days": None, "rate": 0.20},
        ])
        result, _issues = bd.calculate(data)
        self.assertEqual(len(result.buckets), 2)
        # 16 天和 91 天都在 ≤60？不，91 > 60 → 第二档
        self.assertAlmostEqual(result.buckets[0].amount, 50000.0, places=2)
        self.assertAlmostEqual(result.buckets[1].amount, 60000.0, places=2)


if __name__ == "__main__":
    unittest.main()
