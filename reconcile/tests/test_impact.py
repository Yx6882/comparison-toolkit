"""Tests for impact ranking. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile as rc  # noqa: E402


def entity(key: str, attrs: dict[str, str]) -> rc.Entity:
    return rc.Entity(key=rc.normalize(key), attrs=attrs, ref="行2", raw=key, kind="row")


class TestDetection(unittest.TestCase):
    def test_money_fields(self):
        for name in ("单价", "总金额", "价格", "费用", "amount", "Cost"):
            self.assertTrue(rc.looks_money(name), name)
        for name in ("名称", "型号", "备注"):
            self.assertFalse(rc.looks_money(name), name)

    def test_quantity_fields(self):
        for name in ("数量", "件数", "qty", "Quantity"):
            self.assertTrue(rc.looks_quantity(name), name)
        self.assertFalse(rc.looks_quantity("单价"))

    def test_pick_quantity(self):
        self.assertEqual(rc.pick_quantity({"单价": "100", "数量": "3"}), 3.0)
        self.assertIsNone(rc.pick_quantity({"单价": "100"}))


class TestImpact(unittest.TestCase):
    def test_price_change_multiplied_by_quantity(self):
        left = entity("M-1", {"单价": "100", "数量": "3"})
        right = entity("M-1", {"单价": "120", "数量": "3"})
        diffs = rc.compare_entities([(left, right)], [], [])
        price = next(d for d in diffs if d.field == "单价")
        self.assertAlmostEqual(price.impact or 0, 60.0, places=2)

    def test_no_quantity_defaults_to_one(self):
        left = entity("M-1", {"单价": "100"})
        right = entity("M-1", {"单价": "150"})
        diffs = rc.compare_entities([(left, right)], [], [])
        price = next(d for d in diffs if d.field == "单价")
        self.assertAlmostEqual(price.impact or 0, 50.0, places=2)

    def test_non_money_field_has_no_impact(self):
        left = entity("M-1", {"名称": "电源", "数量": "3"})
        right = entity("M-1", {"名称": "导线", "数量": "3"})
        diffs = rc.compare_entities([(left, right)], [], [])
        name_diff = next(d for d in diffs if d.field == "名称")
        self.assertIsNone(name_diff.impact)

    def test_report_ranks_by_impact(self):
        left = entity("M-1", {"单价": "100", "数量": "1"})
        right = entity("M-1", {"单价": "110", "数量": "1"})
        left2 = entity("M-2", {"单价": "5000", "数量": "10"})
        right2 = entity("M-2", {"单价": "5000", "数量": "10"})
        diffs = rc.compare_entities([(left, right), (left2, right2)], [], [])
        report = rc.render_report(
            Path("a.xlsx"), Path("b.xlsx"), "record", {"key": "物料号"}, {"key": "物料号"},
            diffs, matched_count=2, fuzzy_pairs=[],
        )
        self.assertIn("优先看这些", report)
        self.assertIn("10.00", report)

    def test_no_impact_section_when_nothing_money(self):
        left = entity("K-1", {"名称": "甲"})
        right = entity("K-1", {"名称": "乙"})
        diffs = rc.compare_entities([(left, right)], [], [])
        report = rc.render_report(
            Path("a.md"), Path("b.md"), "text", {}, {}, diffs, matched_count=1, fuzzy_pairs=[],
        )
        self.assertNotIn("优先看这些", report)


if __name__ == "__main__":
    unittest.main()
