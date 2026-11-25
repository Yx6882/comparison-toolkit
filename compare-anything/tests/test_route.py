"""Tests for the router. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import route  # noqa: E402


def ns(**kwargs) -> "route.argparse.Namespace":
    base = dict(left=None, right=None, quantity=1.0, unit="斤", rubric=None, kv=None, input=None, out=None, key=None, task="auto")
    base.update(kwargs)
    return route.argparse.Namespace(**base)


class TestAccountingRouting(unittest.TestCase):
    def test_explicit_task(self):
        tool, reason, argv = route.classify(ns(task="bank", input="流水.json"))
        self.assertEqual(tool, "accounting")
        self.assertEqual(argv[0], "match")

    def test_filename_hint(self):
        tool, _reason, argv = route.classify(ns(input="银行流水明细.json"))
        self.assertEqual(tool, "accounting")
        self.assertEqual(argv[0], "match")

    def test_neutral_json_not_routed(self):
        tool, _reason, _argv = route.classify(ns(input="随便.json"))
        self.assertEqual(tool, "")

    def test_task_without_input_fails(self):
        tool, reason, _argv = route.classify(ns(task="ledger"))
        self.assertEqual(tool, "")
        self.assertIn("--input", reason)

    def test_media_routed_to_reconcile(self):
        with tempfile.TemporaryDirectory() as tmp:
            left, right = Path(tmp) / "a.png", Path(tmp) / "b.png"
            left.write_bytes(b"\x89PNG")
            right.write_bytes(b"\x89PNG")
            tool, reason, _argv = route.classify(ns(left=str(left), right=str(right)))
            self.assertEqual(tool, "reconcile")
            self.assertIn("媒体", reason)


class TestClassify(unittest.TestCase):
    def test_commodities(self):
        tool, reason, argv = route.classify(ns(left="铜", right="铝"))
        self.assertEqual(tool, "exchange")
        self.assertEqual(argv[:4], ["convert", "--from", "铜", "--to"])

    def test_commodity_with_other_name_is_not_exchange(self):
        tool, _reason, _argv = route.classify(ns(left="铜", right="黄金"))
        self.assertEqual(tool, "")

    def test_two_real_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            left = Path(tmp) / "a.md"
            right = Path(tmp) / "b.md"
            left.write_text("a", encoding="utf-8")
            right.write_text("b", encoding="utf-8")
            tool, _reason, argv = route.classify(ns(left=str(left), right=str(right)))
            self.assertEqual(tool, "reconcile")
            self.assertTrue(argv[1].endswith("a.md"))

    def test_missing_file_is_not_routed(self):
        tool, reason, _argv = route.classify(ns(left="不存在.docx", right="也不存在.docx"))
        self.assertEqual(tool, "reconcile")
        self.assertEqual(_argv, [])
        self.assertIn("不存在", reason)

    def test_rubric_wins(self):
        tool, _reason, argv = route.classify(ns(rubric="health-metabolic", kv="收缩压=142"))
        self.assertEqual(tool, "assess")
        self.assertIn("--kv", argv)

    def test_rubric_with_input_file(self):
        tool, _reason, argv = route.classify(ns(rubric="career-pm", input="self.json"))
        self.assertEqual(tool, "assess")
        self.assertIn("--input", argv)

    def test_unknown_inputs(self):
        tool, reason, argv = route.classify(ns(left="随便", right="什么"))
        self.assertEqual((tool, argv), ("", []))
        self.assertIn("无法判断", reason)


class TestSelftest(unittest.TestCase):
    def test_builtin(self):
        self.assertEqual(route.main(["selftest"]), 0)


class TestSkillFile(unittest.TestCase):
    def test_frontmatter(self):
        import re

        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        front = text.split("---", 2)[1]
        name = re.search(r"^name:\s*(\S+)\s*$", front, re.M)
        desc = re.search(r"^description:\s*(.+)$", front, re.M)
        self.assertIsNotNone(name)
        self.assertIsNotNone(desc)
        assert name and desc
        self.assertRegex(name.group(1), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(desc.group(1)), 1024)


if __name__ == "__main__":
    unittest.main()
