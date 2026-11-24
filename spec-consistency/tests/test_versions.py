"""Version-diff tests: table columns, folder revisions, changelog coverage."""

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


def pair(name: str, value: float, unit: str, variant: str = "", table: bool = True, display: str = "") -> sa.Pair:
    return sa.Pair(
        name=sa.normalize_param(name),
        display_name=display or name,
        value=value,
        unit=unit,
        context=f"{name} {value} {unit}",
        location="x#tbl" if table else "x#p1",
        variant=variant,
        from_table=table,
    )


class TestVersionedTable(unittest.TestCase):
    def test_header_detection(self):
        self.assertTrue(sa.is_version_header("CR-2"))
        self.assertTrue(sa.is_version_header("V1"))
        self.assertTrue(sa.is_version_header("版本 3"))
        self.assertFalse(sa.is_version_header("取值"))
        self.assertFalse(sa.is_version_header("说明"))

    def test_versioned_layout_emits_variant(self):
        rows = [
            ["项目", "CR-2", "CR-3"],
            ["内孔", "Ø32", "Ø36"],
            ["立柱中心距", "124", "128"],
        ]
        lines = list(sa.table_lines(rows, "t1-"))
        self.assertEqual(len(lines), 4)
        name, variant, cell = lines[0][1].split("\t")
        self.assertEqual(name, "内孔")
        self.assertEqual(variant, "CR-2")
        self.assertEqual(cell, "Ø32")

    def test_parse_pairs_handles_variant(self):
        pairs = sa.parse_pairs("内孔\tCR-2\tØ32", "doc.md#tblr2")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0].variant, "CR-2")
        self.assertEqual(pairs[0].value, 32)
        self.assertEqual(pairs[0].unit, "mm")


class TestCompare(unittest.TestCase):
    def test_changed_values(self):
        changes = sa.compare_pair_maps(
            {"立柱": pair("立柱中心距", 124, "mm")},
            {"立柱": pair("立柱中心距", 128, "mm")},
        )
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].status, "changed")
        self.assertAlmostEqual(changes[0].delta, 4 / 124, places=4)

    def test_added_and_removed(self):
        changes = sa.compare_pair_maps({}, {"新参数": pair("新参数", 1, "mm")})
        self.assertEqual(changes[0].status, "added")
        changes = sa.compare_pair_maps({"旧参数": pair("旧参数", 1, "mm")}, {})
        self.assertEqual(changes[0].status, "removed")

    def test_same_value_is_not_reported(self):
        changes = sa.compare_pair_maps(
            {"a": pair("内孔", 32, "mm")}, {"a": pair("内孔", 32, "mm")}
        )
        self.assertEqual(changes, [])

    def test_unit_difference_that_converts_is_not_a_change(self):
        changes = sa.compare_pair_maps(
            {"a": pair("重量", 6200, "g")}, {"a": pair("重量", 6.2, "kg")}
        )
        self.assertEqual(changes, [])

    def test_table_value_wins_over_prose(self):
        docs = {
            "spec.md": [
                pair("内孔", 30, "mm", table=False),
                pair("内孔", 32, "mm", table=True),
            ]
        }
        changes = sa.compare_versions(docs, "CR-2", "CR-3")
        self.assertEqual(changes, [])

    def test_compare_dirs(self):
        from_docs = {"a.md": [pair("内孔", 32, "mm")]}
        to_docs = {"b.md": [pair("内孔", 36, "mm")]}
        changes = sa.compare_dirs(from_docs, to_docs)
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0].old.value, 32)
        self.assertEqual(changes[0].new.value, 36)


class TestChangelogCoverage(unittest.TestCase):
    def test_uncovered_change_is_named(self):
        changes = [
            sa.VersionChange("立柱中心距", "立柱中心距", pair("立柱中心距", 124, "mm"), pair("立柱中心距", 128, "mm"), 0.032, "changed"),
            sa.VersionChange("膝点电流", "膝点电流", pair("膝点电流", 71, "A"), pair("膝点电流", 75, "A"), 0.056, "changed"),
        ]
        changelog = "| D-01 | 立柱中心距 124→128 | 已改 |"
        report = sa.render_version_report(changes, "CR-2", "CR-3", changelog_name="变更单.md", changelog_text=changelog)
        self.assertIn("未提及 1", report)
        self.assertIn("膝点电流", report)

    def test_column_mode_wording(self):
        report = sa.render_version_report([], "CR-2", "CR-3", column_mode=True)
        self.assertIn("两列", report)

    def test_added_hidden_by_default(self):
        changes = [sa.VersionChange("新参数", "新参数", None, pair("新参数", 1, "mm"), None, "added")]
        hidden = sa.render_version_report(changes, "CR-2", "CR-3")
        shown = sa.render_version_report(changes, "CR-2", "CR-3", show_added=True)
        self.assertIn("--show-added", hidden)
        self.assertIn("新增", shown)


class TestCli(unittest.TestCase):
    def test_versions_command_on_two_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / "old"
            new = root / "new"
            old.mkdir()
            new.mkdir()
            (old / "spec.md").write_text(
                "| 项目 | 取值 |\n|---|---|\n| 内孔 | Ø32 |\n| 立柱中心距 | 124 mm |\n",
                encoding="utf-8",
            )
            (new / "spec.md").write_text(
                "| 项目 | 取值 |\n|---|---|\n| 内孔 | Ø36 |\n| 立柱中心距 | 128 mm |\n",
                encoding="utf-8",
            )
            (root / "changelog.md").write_text("| D-01 | 立柱中心距 124→128 |", encoding="utf-8")
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(io.StringIO()):
                code = sa.main(
                    [
                        "versions",
                        "--from-dir",
                        str(old),
                        "--to-dir",
                        str(new),
                        "--changelog",
                        str(root / "changelog.md"),
                        "-o",
                        str(root / "out"),
                    ]
                )
            self.assertEqual(code, 0)
            self.assertIn("2 项变化", buffer.getvalue())
            payload = json.loads((root / "out" / "version-diff.json").read_text(encoding="utf-8"))
            labels = {c["label"] for c in payload["changes"] if c["status"] == "changed"}
            self.assertEqual(labels, {"内孔", "立柱中心距"})
            report = (root / "out" / "version-diff.md").read_text(encoding="utf-8")
            self.assertIn("未提及 1", report)


if __name__ == "__main__":
    unittest.main()
