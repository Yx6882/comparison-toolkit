"""Tests for trend. `python -m unittest discover -s tests -v`"""

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

import trend as tr  # noqa: E402


def item(kind: str, key: str, field: str, severity: str = "high", left: str = "", right: str = "") -> tr.Item:
    return tr.Item(f"{kind}|{key}|{field}", kind, key, field, severity, left, right)


class TestComparePeriods(unittest.TestCase):
    def test_new_persistent_resolved(self):
        prev = [item("value", "A", "价格", left="10"), item("value", "B", "价格", left="20")]
        curr = [item("value", "A", "价格", left="12"), item("value", "C", "价格", left="30")]
        deltas = tr.compare_periods(prev, curr)
        statuses = {d.item.key: d.status for d in deltas}
        self.assertEqual(statuses["A"], "persistent")
        self.assertEqual(statuses["C"], "new")
        self.assertEqual(statuses["B"], "resolved")

    def test_worsened(self):
        prev = [item("value", "A", "价格", severity="medium")]
        curr = [item("value", "A", "价格", severity="high")]
        deltas = tr.compare_periods(prev, curr)
        self.assertEqual(deltas[0].status, "worsened")

    def test_identity_includes_field(self):
        prev = [item("value", "A", "单价")]
        curr = [item("value", "A", "金额")]
        deltas = tr.compare_periods(prev, curr)
        statuses = {d.status for d in deltas}
        self.assertEqual(statuses, {"new", "resolved"}, "同一个键的不同字段不能混为同一件事")

    def test_empty_periods(self):
        self.assertEqual(tr.compare_periods([], []), [])

    def test_key_case_and_separator_normalised(self):
        """两期报告来自不同数据源：M-1001 与 m-1001 是同一个物料。"""
        prev = tr.to_items({"diffs": [{"kind": "value", "key": "M-1001", "field": "单价"}]})
        curr = tr.to_items({"diffs": [{"kind": "value", "key": "m-1001", "field": "单价"}]})
        deltas = tr.compare_periods(prev, curr)
        self.assertEqual(len(deltas), 1)
        self.assertEqual(deltas[0].status, "persistent", "大小写不同不该判成解决+新增")

    def test_underscore_and_space_normalised(self):
        prev = tr.to_items({"diffs": [{"kind": "only_left", "key": "合同条款 3", "field": "存在性"}]})
        curr = tr.to_items({"diffs": [{"kind": "only_left", "key": "合同条款_3", "field": "存在性"}]})
        self.assertEqual(tr.compare_periods(prev, curr)[0].status, "persistent")


class TestLoading(unittest.TestCase):
    def test_load_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps({"diffs": [{"kind": "value", "key": "A", "field": "价格"}]}), encoding="utf-8")
            report = tr.load_report(path)
            self.assertEqual(len(tr.to_items(report)), 1)

    def test_load_directory_picks_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old.json"
            new = root / "new.json"
            old.write_text(json.dumps({"diffs": []}), encoding="utf-8")
            new.write_text(json.dumps({"diffs": [{"kind": "value", "key": "N", "field": "f"}]}), encoding="utf-8")
            import os
            import time

            os.utime(old, (time.time() - 100, time.time() - 100))
            report = tr.load_report(root)
            self.assertEqual(len(tr.to_items(report)), 1)

    def test_bad_json_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                tr.load_report(path)

    def test_missing_file_fails_loudly(self):
        with self.assertRaises(SystemExit):
            tr.load_report(Path("不存在.json"))


class TestRender(unittest.TestCase):
    def test_counts_and_sections(self):
        prev = [item("value", "A", "价格"), item("value", "B", "价格")]
        curr = [item("value", "A", "价格"), item("value", "C", "价格")]
        deltas = tr.compare_periods(prev, curr)
        report = tr.render(deltas, Path("prev.json"), Path("curr.json"), {}, {})
        self.assertIn("新增 1", report)
        self.assertIn("已解决 1", report)
        self.assertIn("## 新增", report)
        self.assertIn("## 已解决", report)

    def test_persistent_advice(self):
        prev = [item("value", k, "价格") for k in ("A", "B", "C")]
        curr = [item("value", k, "价格") for k in ("A", "B", "C")]
        report = tr.render(tr.compare_periods(prev, curr), Path("p"), Path("c"), {}, {})
        self.assertIn("连续两期没解决", report)

    def test_clean_period(self):
        report = tr.render([], Path("p"), Path("c"), {}, {})
        self.assertIn("没有发现新的差异", report)


class TestCli(unittest.TestCase):
    def test_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev, curr = tr.build_demo(Path(tmp) / "d")
            out = Path(tmp) / "out"
            with contextlib.redirect_stdout(io.StringIO()):
                result = tr.run_trend(prev, curr, out)
            self.assertEqual(result["counts"]["new"], 2)
            self.assertEqual(result["counts"]["resolved"], 2)
            self.assertEqual(result["counts"]["persistent"], 2)
            self.assertTrue((out / "trend.md").exists())

    def test_selftest(self):
        self.assertEqual(tr.main(["selftest"]), 0)


if __name__ == "__main__":
    unittest.main()
