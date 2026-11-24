"""Tests for fix suggestions and safe apply. `python -m unittest discover -s tests -v`

Rules under test:
  1. patch 只生成建议，不动任何文件
  2. apply 只在「当前值 == 补丁原值」时才改（防止改错行）
  3. apply 只接受 CSV；xlsx/docx/pptx 直接拒绝
  4. 原文件永远不被修改
"""

from __future__ import annotations

import contextlib
import csv
import io
import json
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


def write_report(path: Path, diffs: list[dict], left: str = "A.csv", right: str = "B.csv") -> Path:
    path.write_text(
        json.dumps({"version": "x", "left": left, "right": right, "diffs": diffs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestBuildPatches(unittest.TestCase):
    def test_value_patch_is_low_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = write_report(root / "r.json", [
                {"kind": "value", "key": "M-1", "field": "单价", "left": "100", "right": "120"},
            ])
            patches = rc.build_patches(report)
            self.assertEqual(len(patches), 1)
            self.assertEqual(patches[0].risk, "low")
            self.assertEqual(patches[0].old, "120")
            self.assertEqual(patches[0].new, "100")
            self.assertEqual(patches[0].basis, "A.csv")

    def test_text_is_medium(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = write_report(root / "r.json", [
                {"kind": "text", "key": "k", "field": "文字表述", "left": "甲", "right": "乙"},
            ])
            self.assertEqual(rc.build_patches(report)[0].risk, "medium")

    def test_presence_diff_is_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = write_report(root / "r.json", [
                {"kind": "only_left", "key": "M-9", "field": "仅左侧存在"},
                {"kind": "only_right", "key": "M-8", "field": "仅右侧存在"},
            ])
            risks = {patch.risk for patch in rc.build_patches(report)}
            self.assertEqual(risks, {"high"})

    def test_missing_report(self):
        with self.assertRaises(SystemExit):
            rc.build_patches(Path("不存在.json"))

    def test_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{oops", encoding="utf-8")
            with self.assertRaises(SystemExit):
                rc.load_diff_json(path)


class TestApply(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.target = write_csv(
            self.root / "target.csv",
            [("M-1", "120", "2"), ("M-2", "500", "4")],
            ["物料号", "单价", "数量"],
        )
        self.patch = self.root / "fix-patch.csv"
        with self.patch.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["文件", "键", "字段", "原值", "建议值", "依据", "风险", "类型", "备注"])
            writer.writerow(["target.csv", "M-1", "单价", "120", "100", "A.csv", "low", "value", ""])
            writer.writerow(["target.csv", "M-2", "数量", "4", "6", "A.csv", "low", "value", ""])

    def tearDown(self):
        self.tmp.cleanup()

    def test_apply_replaces_and_keeps_original(self):
        before = self.target.read_bytes()
        result = quiet(rc.main, [
            "apply", "--patch", str(self.patch), "--target", str(self.target),
            "--key", "物料号", "-o", str(self.root / "out"),
        ])
        self.assertEqual(result, 0)
        self.assertEqual(self.target.read_bytes(), before, "原文件必须不变")
        fixed = self.root / "out" / "target.fixed.csv"
        rows = list(csv.reader(fixed.open(encoding="utf-8-sig")))
        self.assertEqual(rows[1][1], "100")
        self.assertEqual(rows[2][2], "6")

    def test_value_mismatch_is_skipped(self):
        with self.patch.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["文件", "键", "字段", "原值", "建议值", "依据", "风险", "类型", "备注"])
            writer.writerow(["target.csv", "M-1", "单价", "999", "100", "A.csv", "low", "value", ""])
        result = rc.apply_csv_patches(self.target, rc.load_patch_csv(self.patch), key_column="物料号", out=self.root / "o2")
        self.assertEqual(result["applied"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_high_risk_not_applied(self):
        with self.patch.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["文件", "键", "字段", "原值", "建议值", "依据", "风险", "类型", "备注"])
            writer.writerow(["target.csv", "M-1", "单价", "120", "100", "A.csv", "high", "only_left", ""])
        result = rc.apply_csv_patches(self.target, rc.load_patch_csv(self.patch), key_column="物料号", out=self.root / "o3")
        self.assertEqual(result["applied"], 0)

    def test_missing_key_column_fails(self):
        with self.assertRaises(SystemExit):
            rc.apply_csv_patches(self.target, rc.load_patch_csv(self.patch), key_column="不存在", out=self.root / "o4")

    def test_non_csv_target_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "a.xlsx"
            from openpyxl import Workbook

            Workbook().save(path)
            code = quiet(rc.main, [
                "apply", "--patch", str(self.patch), "--target", str(path), "--key", "物料号",
                "-o", str(root / "o"),
            ])
            self.assertEqual(code, 2)


class TestLoop(unittest.TestCase):
    def test_diff_patch_apply_rediff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = ["物料号", "单价"]
            base = write_csv(root / "base.csv", [("M-1", "100"), ("M-2", "500")], header)
            target = write_csv(root / "target.csv", [("M-1", "120"), ("M-2", "500")], header)

            quiet(rc.run_pair, base, target, out=root / "step1", key="物料号")
            report = next((root / "step1").glob("*.json"))
            patches = rc.build_patches(report)
            self.assertEqual(len(patches), 1)
            md, csv_path = rc.write_patches(root / "patches", patches)
            self.assertTrue(md.exists() and csv_path.exists())

            quiet(rc.main, [
                "apply", "--patch", str(csv_path), "--target", str(target),
                "--key", "物料号", "-o", str(root / "fixed"),
            ])
            fixed = root / "fixed" / "target.fixed.csv"
            result = quiet(rc.run_pair, base, fixed, out=root / "step2", key="物料号")
            self.assertEqual(result["diffs"], 0, "修完再对照应该没有差异")


if __name__ == "__main__":
    unittest.main()
