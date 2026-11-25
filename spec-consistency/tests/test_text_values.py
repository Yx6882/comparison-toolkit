"""Tests for text-value parameters (是/否/待定) and force units."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import spec_audit as sa  # noqa: E402


class TestTextValueParsing(unittest.TestCase):
    def test_table_cell_text_value(self):
        pairs = sa.parse_pairs("| 机械爪兼作磁芯 | 是 |", "x#tblr1")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].text_value, "是")
        self.assertEqual(pairs[0].name, sa.normalize_param("机械爪兼作磁芯"))

    def test_colon_text_value(self):
        pairs = sa.parse_pairs("机械爪兼作磁芯：待定", "x#L1")
        self.assertEqual([p.text_value for p in pairs], ["待定"])

    def test_numeric_line_still_parses_as_number(self):
        pairs = sa.parse_pairs("母线电压：220 kV", "x#L1")
        self.assertTrue(all(not p.text_value for p in pairs))
        self.assertTrue(any(p.unit.lower() == "kv" for p in pairs))

    def test_plain_sentence_not_captured(self):
        self.assertEqual(sa.parse_pairs("这是一个是字的句子，没有参数结构", "x#L1"), [])


class TestTextOnlyInOneDoc(unittest.TestCase):
    def test_reported_as_coverage_gap(self):
        pair = sa.Pair(
            name=sa.normalize_param("机械爪兼作磁芯"), display_name="机械爪兼作磁芯",
            value=0.0, unit="", context="机械爪兼作磁芯：是", location="a.md#tblr1",
            from_table=True, text_value="是",
        )
        findings, _stats = sa.compare({"a.md": [pair], "b.md": []})
        self.assertTrue(
            any(f.kind == "only-in-some" and f.param == sa.normalize_param("机械爪兼作磁芯") for f in findings),
            [f.kind for f in findings],
        )

    def test_contradicting_text_values_is_conflict(self):
        def pair(doc_value: str, location: str) -> sa.Pair:
            return sa.Pair(
                name=sa.normalize_param("兼作磁芯"), display_name="兼作磁芯",
                value=0.0, unit="", context=f"兼作磁芯：{doc_value}", location=location,
                from_table=True, text_value=doc_value,
            )

        findings, _stats = sa.compare({"a.md": [pair("是", "a#t1")], "b.md": [pair("否", "b#t1")]})
        self.assertTrue(any(f.kind == "conflict" and f.severity == "high" for f in findings))


class TestForceUnits(unittest.TestCase):
    def test_ton_force_is_recognised(self):
        self.assertEqual(sa.unit_dim("吨力"), "force")

    def test_ton_force_converts(self):
        base = sa.to_base(2, "吨力")
        self.assertIsNotNone(base)
        self.assertAlmostEqual(base[1], 19613.3, places=1)

    def test_newton_and_kilonewton(self):
        self.assertAlmostEqual(sa.to_base(2140, "N")[1], 2140.0, places=2)
        self.assertAlmostEqual(sa.to_base(2.14, "kN")[1], 2140.0, places=2)

    def test_ton_mass_and_ton_force_do_not_collide(self):
        self.assertEqual(sa.unit_dim("吨"), "mass")
        self.assertEqual(sa.unit_dim("吨力"), "force")


if __name__ == "__main__":
    unittest.main()
