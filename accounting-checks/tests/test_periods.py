"""Tests for multi-period comparison. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import periods as pd  # noqa: E402


def maps(before: dict, after: dict):
    def to_map(data: dict) -> dict:
        return {code: (code, value) for code, value in data.items()}

    return to_map(before), to_map(after)


def run(before: dict, after: dict, **kwargs):
    b, a = maps(before, after)
    return pd.compare(b, a, threshold=kwargs.get("threshold", 0.30), min_amount=kwargs.get("min_amount", 1000.0))


class TestClassification(unittest.TestCase):
    def test_normal_change(self):
        changes = run({"6602": 100000}, {"6602": 110000})
        self.assertEqual(changes[0].status, "normal")

    def test_abnormal_by_rate(self):
        changes = run({"6602": 50000}, {"6602": 200000})
        self.assertEqual(changes[0].status, "abnormal")
        self.assertAlmostEqual(changes[0].rate, 3.0, places=4)

    def test_small_amount_not_abnormal(self):
        """变动率很大但金额很小，不该报异常。"""
        changes = run({"9999": 10}, {"9999": 100})
        self.assertEqual(changes[0].status, "normal")

    def test_new_account(self):
        changes = run({"6602": 1000}, {"6602": 1000, "6601": 80000})
        new = [c for c in changes if c.status == "new"]
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].code, "6601")

    def test_gone_account(self):
        changes = run({"6602": 1000, "6601": 50000}, {"6602": 1000})
        gone = [c for c in changes if c.status == "gone"]
        self.assertEqual(len(gone), 1)
        self.assertEqual(gone[0].delta, -50000.0)

    def test_zero_base_cannot_compute_rate(self):
        changes = run({"1122": 0}, {"1122": 50000})
        self.assertIsNone(changes[0].rate)
        self.assertEqual(changes[0].status, "abnormal")

    def test_decrease_marked(self):
        changes = run({"1122": 400000}, {"1122": 200000})
        self.assertAlmostEqual(changes[0].delta, -200000.0, places=2)
        self.assertLess(changes[0].rate or 0, 0)

    def test_threshold_configurable(self):
        changes = run({"6602": 100000}, {"6602": 120000}, threshold=0.10)
        self.assertEqual(changes[0].status, "abnormal")

    def test_no_change(self):
        changes = run({"6602": 100000}, {"6602": 100000})
        self.assertEqual(changes[0].status, "normal")
        self.assertAlmostEqual(changes[0].delta, 0.0, places=2)


class TestCli(unittest.TestCase):
    def test_missing_file(self):
        self.assertEqual(pd.main(["compare", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
