"""Tests for change impact. `python -m unittest discover -s tests -v`"""

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

import spec_audit as sa  # noqa: E402


def pair(name: str, value: float, unit: str = "mm", context: str = "") -> sa.Pair:
    return sa.Pair(
        name=sa.normalize_param(name),
        display_name=name,
        value=value,
        unit=unit,
        context=context or f"{name}：{value} {unit}",
        location=f"x#{name}{value}",
    )


class TestValuesEqual(unittest.TestCase):
    def test_same_unit(self):
        self.assertTrue(sa.values_equal(32, "mm", 32, "mm"))

    def test_unit_conversion(self):
        self.assertTrue(sa.values_equal(6.2, "kg", 6200, "g"))

    def test_different_values(self):
        self.assertFalse(sa.values_equal(32, "mm", 36, "mm"))

    def test_different_dimension(self):
        self.assertFalse(sa.values_equal(32, "mm", 32, "kg"))


class TestFindImpact(unittest.TestCase):
    def setUp(self):
        self.docs = {
            "设计.md": [pair("内孔", 36, context="内孔：Ø36")],
            "汇报.md": [pair("内孔", 32, context="内孔：Ø32（待更新）"), pair("内孔", 32, context="内孔 Ø32 复制")],
            "供应商.md": [pair("内孔", 40, context="内孔 Ø40（定制）")],
            "无关.md": [pair("外径", 112)],
        }

    def test_classification(self):
        hits = sa.find_impact(self.docs, param="内孔", old_value=32, old_unit="mm", new_value=36, new_unit="mm")
        statuses = [(hit.doc, hit.status) for hit in hits]
        self.assertIn(("设计.md", "current"), statuses)
        self.assertEqual(sum(1 for hit in hits if hit.status == "stale"), 2)
        self.assertIn(("供应商.md", "other"), statuses)
        self.assertTrue(all(hit.doc != "无关.md" for hit in hits))

    def test_param_aliases(self):
        docs = {"a.md": [pair("电池容量", 512, "Wh")]}
        hits = sa.find_impact(docs, param="容量", old_value=500, old_unit="Wh", new_value=512, new_unit="Wh")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].status, "current")

    def test_no_hits(self):
        hits = sa.find_impact(self.docs, param="不存在的参数", old_value=1, old_unit="mm", new_value=2, new_unit="mm")
        self.assertEqual(hits, [])


class TestRender(unittest.TestCase):
    def test_sections(self):
        docs = {
            "a.md": [pair("内孔", 32)],
            "b.md": [pair("内孔", 36)],
            "c.md": [pair("内孔", 40)],
        }
        hits = sa.find_impact(docs, param="内孔", old_value=32, old_unit="mm", new_value=36, new_unit="mm")
        report = sa.render_impact(hits, param="内孔", old_value=32, old_unit="mm", new_value=36, new_unit="mm")
        self.assertIn("待更新", report)
        self.assertIn("其它值", report)
        self.assertIn("已更新", report)

    def test_empty_report(self):
        report = sa.render_impact([], param="内孔", old_value=32, old_unit="mm", new_value=36, new_unit="mm")
        self.assertIn("没有找到参数", report)


class TestCollectExclusion(unittest.TestCase):
    def test_output_folder_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text("内孔：Ø32\n", encoding="utf-8")
            out = root / "impact-out"
            out.mkdir()
            (out / "change-impact.md").write_text("内孔：Ø32\n", encoding="utf-8")
            docs, _ = sa.collect(root, exclude_paths=[out])
            self.assertEqual(list(docs), ["doc.md"])

    def test_without_exclusion_it_is_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "doc.md").write_text("内孔：Ø32\n", encoding="utf-8")
            out = root / "impact-out"
            out.mkdir()
            (out / "change-impact.md").write_text("内孔：Ø32\n", encoding="utf-8")
            docs, _ = sa.collect(root)
            self.assertTrue(any("change-impact.md" in key for key in docs), docs.keys())


class TestChangeLogAndApproximation(unittest.TestCase):
    def test_changelog_table_is_not_a_spec(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "变更记录.md").write_text(
                "| 项目 | 原值 | 新值 |\n|---|---|---|\n| 内孔 | Ø32 | Ø36 |\n", encoding="utf-8"
            )
            docs, _ = sa.collect(root)
            self.assertEqual(docs.get("变更记录.md") or [], [], "变更记录表记录的是历史，不该产出规格对")

    def test_normal_spec_table_still_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "规格.md").write_text(
                "| 参数 | 取值 |\n|---|---|\n| 内孔 | Ø36 |\n", encoding="utf-8"
            )
            docs, _ = sa.collect(root)
            self.assertTrue(docs.get("规格.md"), "普通规格表不能被误跳过")

    def test_approximation_suffix_stripped(self):
        self.assertEqual(sa.normalize_spec_name("内孔约"), "内孔")
        self.assertEqual(sa.normalize_spec_name("内孔大约"), "内孔")
        self.assertEqual(sa.normalize_spec_name("内孔"), "内孔")

    def test_approx_value_is_found(self):
        pairs = sa.parse_pairs("内孔约 Ø32，按 H7 配合", "x#L1")
        self.assertTrue(
            any(pair.name == "内孔" and pair.value == 32 for pair in pairs),
            f"「内孔约 Ø32」应解析成 内孔=32，实际 {[(p.name, p.value) for p in pairs]}",
        )


class TestCli(unittest.TestCase):
    def test_impact_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内孔：Ø32\n", encoding="utf-8")
            (root / "b.md").write_text("内孔：Ø36\n", encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
                code = sa.main([
                    "impact", "-d", str(root), "--param", "内孔",
                    "--old", "32", "--new", "36", "-o", str(root / "out"),
                ])
            self.assertEqual(code, 0)
            self.assertIn("待更新", buffer.getvalue())
            payload = json.loads((root / "out" / "change-impact.json").read_text(encoding="utf-8"))
            self.assertEqual(len(payload["hits"]), 2)

    def test_fail_on_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内孔：Ø32\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = sa.main([
                    "impact", "-d", str(root), "--param", "内孔",
                    "--old", "32", "--new", "36", "-o", str(root / "out"), "--fail-on-stale",
                ])
            self.assertEqual(code, 1)

    def test_bad_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.md").write_text("内孔：Ø32\n", encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = sa.main([
                    "impact", "-d", str(root), "--param", "内孔",
                    "--old", "三十二", "--new", "36", "-o", str(root / "out"),
                ])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
