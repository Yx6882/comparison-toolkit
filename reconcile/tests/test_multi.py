"""Tests for multi-source consensus voting. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile as rc  # noqa: E402


def write_csv(path: Path, rows: list[tuple[str, ...]], header: list[str]) -> Path:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)
    return path


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestVote(unittest.TestCase):
    def test_unanimous(self):
        vote = rc.vote_field("K", "f", {"a": "100", "b": "100", "c": "100"})
        self.assertEqual(vote.consensus, "unanimous")
        self.assertEqual(vote.outliers, [])

    def test_majority(self):
        vote = rc.vote_field("K", "f", {"a": "100", "b": "100", "c": "120"})
        self.assertEqual(vote.consensus, "majority")
        self.assertEqual(vote.outliers, ["c"])
        self.assertEqual(vote.majority_value, "100")

    def test_split(self):
        vote = rc.vote_field("K", "f", {"a": "1", "b": "2", "c": "3"})
        self.assertEqual(vote.consensus, "split")
        self.assertEqual(len(vote.outliers), 3)

    def test_missing_source_ignored(self):
        vote = rc.vote_field("K", "f", {"a": "100", "b": "", "c": "100"})
        self.assertEqual(vote.consensus, "unanimous")
        self.assertEqual(vote.missing, ["b"])

    def test_units_normalise(self):
        vote = rc.vote_field("K", "f", {"a": "6.2kg", "b": "6200 g", "c": "6.2 kg"})
        self.assertEqual(vote.consensus, "unanimous", "单位换算后应视为一致")

    def test_thousands_separator_normalises(self):
        vote = rc.vote_field("K", "f", {"a": "1,200", "b": "1200", "c": "1200.00"})
        self.assertEqual(vote.consensus, "unanimous")

    def test_text_case_insensitive(self):
        vote = rc.vote_field("K", "f", {"a": "Approved", "b": "approved", "c": "APPROVED"})
        self.assertEqual(vote.consensus, "unanimous")


class TestMultiCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        header = ["物料号", "单价", "数量"]
        self.a = write_csv(self.root / "a.csv", [("M-1", "100", "2"), ("M-2", "50", "4")], header)
        self.b = write_csv(self.root / "b.csv", [("M-1", "100", "2"), ("M-2", "60", "4")], header)
        self.c = write_csv(self.root / "c.csv", [("M-1", "120", "2"), ("M-2", "70", "5")], header)

    def tearDown(self):
        self.tmp.cleanup()

    def test_vote_counts(self):
        votes, stats = rc.multi_compare([self.a, self.b, self.c])
        self.assertEqual(stats["keys"], 2)
        self.assertEqual(stats["unanimous"], 1)   # M-1 数量
        self.assertEqual(stats["majority"], 2)    # M-1 单价、M-2 数量(5 vs 4,4)
        self.assertEqual(stats["split"], 1)       # M-2 单价 50/60/70

    def test_outlier_identified(self):
        votes, _stats = rc.multi_compare([self.a, self.b, self.c])
        m1_price = next(v for v in votes if v.key == "M-1" and v.field == "单价")
        self.assertEqual(m1_price.consensus, "majority")
        self.assertEqual(m1_price.outliers, ["c"])

    def test_needs_three_files(self):
        with self.assertRaises(SystemExit):
            quiet(rc.multi_compare, [self.a, self.b])

    def test_missing_file(self):
        with self.assertRaises(SystemExit):
            quiet(rc.multi_compare, [self.a, self.b, self.root / "不存在.csv"])

    def test_no_common_keys(self):
        other = write_csv(self.root / "x.csv", [("Z-9", "1", "1")], ["物料号", "单价", "数量"])
        with self.assertRaises(SystemExit):
            quiet(rc.multi_compare, [self.a, self.b, other])

    def test_report_and_excel(self):
        out = self.root / "out"
        result = quiet(rc.run_multi, [self.a, self.b, self.c], out=out, key="物料号")
        self.assertTrue((out / "reconcile-multi.md").exists())
        self.assertTrue((out / "reconcile-multi.xlsx").exists())
        report = (out / "reconcile-multi.md").read_text(encoding="utf-8")
        self.assertIn("多数不等于正确", report)
        self.assertIn("M-1", report, "键应显示原始大小写")
        self.assertIn("## 无共识", report)

    def test_field_filter(self):
        votes, stats = rc.multi_compare([self.a, self.b, self.c], fields=["单价"])
        self.assertEqual(stats["fields"], ["单价"])
        self.assertTrue(all(vote.field == "单价" for vote in votes))


class TestUnitColumn(unittest.TestCase):
    """报价单常把单位放在单独一列：12000 元 与 12 千元 是同一个价。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_money_unit_column_is_normalised(self):
        header = ["物料号", "单价", "单位"]
        a = write_csv(self.root / "a.csv", [("M-1", "12000", "元")], header)
        b = write_csv(self.root / "b.csv", [("M-1", "12", "千元")], header)
        c = write_csv(self.root / "c.csv", [("M-1", "13", "千元")], header)
        votes, _stats = rc.multi_compare([a, b, c])
        price = next(vote for vote in votes if vote.field == "单价")
        self.assertEqual(price.consensus, "majority", "12000 元 与 12 千元 应视为一致")
        self.assertEqual(price.outliers, ["c"])

    def test_quantity_does_not_inherit_money_unit(self):
        header = ["物料号", "单价", "单位", "数量"]
        a = write_csv(self.root / "a.csv", [("M-1", "12000", "元", "2")], header)
        b = write_csv(self.root / "b.csv", [("M-1", "12", "千元", "2")], header)
        c = write_csv(self.root / "c.csv", [("M-1", "12", "千元", "2")], header)
        votes, _stats = rc.multi_compare([a, b, c])
        quantity = next(vote for vote in votes if vote.field == "数量")
        self.assertEqual(quantity.consensus, "unanimous", "数量不能被拼上「元」单位")

    def test_unit_column_not_voted_on(self):
        header = ["物料号", "单价", "单位"]
        a = write_csv(self.root / "a.csv", [("M-1", "12000", "元")], header)
        b = write_csv(self.root / "b.csv", [("M-1", "12", "千元")], header)
        c = write_csv(self.root / "c.csv", [("M-1", "12", "千元")], header)
        votes, _stats = rc.multi_compare([a, b, c])
        self.assertNotIn("单位", {vote.field for vote in votes}, "单位列决定口径，不该参与表决")


class TestCliMulti(unittest.TestCase):
    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = ["物料号", "单价"]
            a = write_csv(root / "a.csv", [("M-1", "100")], header)
            b = write_csv(root / "b.csv", [("M-1", "100")], header)
            c = write_csv(root / "c.csv", [("M-1", "120")], header)
            code = quiet(rc.main, ["multi", str(a), str(b), str(c), "--key", "物料号", "-o", str(root / "out")])
            self.assertEqual(code, 0)
            self.assertTrue((root / "out" / "reconcile-multi.md").exists())


if __name__ == "__main__":
    unittest.main()
