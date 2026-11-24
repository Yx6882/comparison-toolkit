"""Tests for spec_audit. Stdlib only: `python -m unittest discover -s tests -v`."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import spec_audit  # noqa: E402


class TestUnits(unittest.TestCase):
    def test_mass_conversion(self):
        self.assertEqual(spec_audit.to_base(6.2, "kg"), ("mass", 6200.0))
        self.assertEqual(spec_audit.to_base(6200, "g"), ("mass", 6200.0))

    def test_time_conversion(self):
        self.assertEqual(spec_audit.to_base(45, "分钟"), ("time", 2700.0))
        self.assertEqual(spec_audit.to_base(1.5, "h"), ("time", 5400.0))

    def test_unknown_unit(self):
        self.assertIsNone(spec_audit.to_base(3, "个"))
        self.assertIsNone(spec_audit.to_base(3, "箱"))

    def test_dimensions_do_not_mix(self):
        percent = spec_audit.to_base(5, "%")
        money = spec_audit.to_base(5, "元")
        self.assertNotEqual(percent[0], money[0])


class TestNormalisation(unittest.TestCase):
    def test_synonyms_collapse(self):
        self.assertEqual(spec_audit.normalize_param("整机重量"), "重量")
        self.assertEqual(spec_audit.normalize_param("满载续航"), "续航时间")
        self.assertEqual(spec_audit.normalize_param("电池容量"), "容量")

    def test_case_and_space(self):
        self.assertEqual(spec_audit.normalize_param("Output  Power"), "outputpower")

    def test_noise_rejected(self):
        for name in ("第", "注", "页", ""):
            self.assertTrue(spec_audit.is_noise(name))
        self.assertFalse(spec_audit.is_noise("整机重量"))


class TestParsing(unittest.TestCase):
    def test_colon_form(self):
        pairs = spec_audit.parse_pairs("满载续航：45 分钟", "demo")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].name, "续航时间")
        self.assertEqual(pairs[0].value, 45)
        self.assertEqual(pairs[0].unit, "分钟")

    def test_space_form(self):
        pairs = spec_audit.parse_pairs("整机重量 6.2kg", "demo")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].name, "重量")
        self.assertAlmostEqual(pairs[0].value, 6.2)

    def test_bare_numbers_ignored(self):
        self.assertEqual(spec_audit.parse_pairs("共 3 个", "demo"), [])
        self.assertEqual(spec_audit.parse_pairs("第 5 页", "demo"), [])

    def test_context_preserved(self):
        pairs = spec_audit.parse_pairs("电池容量：512 Wh，符合要求", "doc#p1")
        self.assertIn("512", pairs[0].context)
        self.assertEqual(pairs[0].location, "doc#p1")

    def test_no_duplicate_from_two_regexes(self):
        pairs = spec_audit.parse_pairs("整机重量：6.2 kg", "demo")
        self.assertEqual(len(pairs), 1)


class TestComparison(unittest.TestCase):
    def _docs(self):
        return {
            "spec.docx": [spec_audit.Pair("重量", "整机重量", 6.2, "kg", "整机重量：6.2 kg", "spec.docx#t1r2")],
            "deck.pptx": [spec_audit.Pair("重量", "整机重量", 6.0, "kg", "整机重量：6.0 kg", "deck.pptx#s1")],
        }

    def test_conflict_detected(self):
        findings, stats = spec_audit.compare(self._docs())
        conflicts = [f for f in findings if f.kind == "conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0].severity, "high")
        self.assertEqual(stats["comparable"], 1)

    def test_equal_units_no_conflict(self):
        docs = {
            "a.md": [spec_audit.Pair("重量", "重量", 1, "kg", "重量：1 kg", "a")],
            "b.md": [spec_audit.Pair("重量", "重量", 1000, "g", "重量：1000 g", "b")],
        }
        findings, _ = spec_audit.compare(docs)
        self.assertFalse([f for f in findings if f.kind == "conflict"])
        self.assertTrue([f for f in findings if f.kind == "unit-inconsistent"])

    def test_within_tolerance_not_a_conflict(self):
        docs = {
            "a.md": [spec_audit.Pair("容量", "容量", 512, "Wh", "容量：512 Wh", "a")],
            "b.md": [spec_audit.Pair("容量", "容量", 511, "Wh", "容量：511 Wh", "b")],
        }
        findings, _ = spec_audit.compare(docs, tolerance=0.005)
        self.assertFalse([f for f in findings if f.kind == "conflict"])

    def test_missing_document_is_low(self):
        docs = {
            "a.md": [spec_audit.Pair("容量", "容量", 512, "Wh", "容量：512 Wh", "a")],
            "b.md": [spec_audit.Pair("重量", "重量", 6, "kg", "重量：6 kg", "b")],
        }
        findings, _ = spec_audit.compare(docs)
        kinds = {f.kind for f in findings}
        self.assertIn("only-in-some", kinds)

    def test_internal_conflict(self):
        docs = {
            "quote.xlsx": [
                spec_audit.Pair("容量", "电池容量", 500, "Wh", "电池容量：500 Wh", "q1"),
                spec_audit.Pair("容量", "电池容量", 1024, "Wh", "电池容量：1024 Wh", "q2"),
            ]
        }
        findings, _ = spec_audit.compare(docs)
        self.assertTrue([f for f in findings if f.kind == "internal-conflict"])


class TestCollections(unittest.TestCase):
    def test_demo_pack_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "material"
            spec_audit.build_demo(root)
            docs, skipped = spec_audit.collect(root)
            self.assertEqual(len(docs), 3, f"expected 3 documents with parameters, got {list(docs)}")
            findings, stats = spec_audit.compare(docs)
            high = [f for f in findings if f.kind == "conflict"]
            self.assertEqual(len(high), 3, [f.label for f in high])
            labels = {f.label for f in high}
            self.assertEqual(labels, {"电池容量", "满载续航", "整机重量"})

            names = {pair.name for pairs in docs.values() for pair in pairs}
            self.assertNotIn("px200", names, "model numbers must not be treated as parameters")

    def test_report_files_and_fail_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "material"
            spec_audit.build_demo(root)
            out = Path(tmp) / "reports"
            with contextlib.redirect_stdout(io.StringIO()):
                code = spec_audit.run_scan(root, out, fail_on="high")
            self.assertEqual(code, 1)
            self.assertTrue((out / "spec-consistency.md").exists())
            payload = json.loads((out / "spec-consistency.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["stats"]["by_severity"]["high"], 3)
            self.assertTrue(payload["findings"])

    def test_fail_on_none_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "material"
            spec_audit.build_demo(root)
            with contextlib.redirect_stdout(io.StringIO()):
                code = spec_audit.run_scan(root, Path(tmp) / "reports", fail_on="none")
            self.assertEqual(code, 0)

    def test_empty_folder_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = spec_audit.run_scan(Path(tmp), Path(tmp) / "out")
            self.assertEqual(code, 2)


class TestSkillFile(unittest.TestCase):
    def test_frontmatter(self):
        import re

        path = ROOT / "SKILL.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---", 2)[1]
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
        desc = re.search(r"^description:\s*(.+)$", front, re.M)
        self.assertIsNotNone(name)
        self.assertIsNotNone(desc)
        assert name and desc
        self.assertRegex(name.group(1), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(desc.group(1)), 1024)
        self.assertIn("license:", front)


if __name__ == "__main__":
    unittest.main()
