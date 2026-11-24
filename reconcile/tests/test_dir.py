"""Tests for directory mode. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import reconcile as rc  # noqa: E402


def make_tree(root: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def quiet(func, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return func(*args, **kwargs)


class TestDirCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.left = root / "left"
        self.right = root / "right"
        make_tree(self.left, {
            "相同.md": "一模一样\n".encode("utf-8"),
            "修改.md": "第一行\n第二行\n".encode("utf-8"),
            "仅左.txt": "只有左边有\n".encode("utf-8"),
            "二进制.bin": b"\x00\x01\x02",
            "__pycache__/忽略.pyc": b"junk",
        })
        make_tree(self.right, {
            "相同.md": "一模一样\n".encode("utf-8"),
            "修改.md": "第一行\n改过的第二行\n".encode("utf-8"),
            "仅右.txt": "只有右边有\n".encode("utf-8"),
            "二进制.bin": b"\x00\x01\x03",
            "__pycache__/忽略.pyc": b"different junk",
        })

    def tearDown(self):
        self.tmp.cleanup()

    def test_statuses(self):
        entries = rc.compare_dirs(self.left, self.right, exclude=set(rc.DEFAULT_EXCLUDE), content=False, max_content=0)
        by_rel = {entry.rel: entry for entry in entries}
        self.assertEqual(by_rel["相同.md"].status, "same")
        self.assertEqual(by_rel["修改.md"].status, "modified")
        self.assertEqual(by_rel["仅左.txt"].status, "only_left")
        self.assertEqual(by_rel["仅右.txt"].status, "only_right")
        self.assertNotIn("__pycache__/忽略.pyc", by_rel, "排除规则必须生效")

    def test_binary_only_reports_hash_change(self):
        entries = rc.compare_dirs(self.left, self.right, exclude=set(rc.DEFAULT_EXCLUDE), content=True, max_content=10)
        binary = next(entry for entry in entries if entry.rel == "二进制.bin")
        self.assertEqual(binary.status, "modified")
        self.assertEqual(binary.diffs, None)
        self.assertIn("二进制", binary.note)

    def test_content_mode_counts_diffs(self):
        entries = rc.compare_dirs(self.left, self.right, exclude=set(rc.DEFAULT_EXCLUDE), content=True, max_content=10)
        changed = next(entry for entry in entries if entry.rel == "修改.md")
        self.assertIsNotNone(changed.diffs)
        self.assertGreaterEqual(changed.diffs or 0, 1)

    def test_max_content_limits_work(self):
        entries = rc.compare_dirs(self.left, self.right, exclude=set(rc.DEFAULT_EXCLUDE), content=True, max_content=0)
        changed = next(entry for entry in entries if entry.rel == "修改.md")
        self.assertIsNone(changed.diffs, "max_content=0 时不应做内容级对照")

    def test_ignore_pattern_extra(self):
        entries = rc.compare_dirs(self.left, self.right, exclude=set(rc.DEFAULT_EXCLUDE) | {"*.md"}, content=False, max_content=0)
        # 通配符形式不是本实现的语义，目录名才会被排除；这里验证不会崩
        self.assertTrue(entries)

    def test_report_and_excel(self):
        out = Path(self.tmp.name) / "out"
        result = quiet(rc.run_dir, self.left, self.right, out=out, exclude=set(rc.DEFAULT_EXCLUDE), content=False, max_content=0)
        self.assertTrue((out / "reconcile-dir.md").exists())
        self.assertTrue((out / "reconcile-dir.xlsx").exists())
        report = (out / "reconcile-dir.md").read_text(encoding="utf-8")
        self.assertIn("仅左侧存在", report)
        self.assertIn("内容已修改", report)
        self.assertIn("SHA-256", report)
        self.assertEqual(len(result["entries"]), 5)

    def test_empty_dirs_fail_loudly(self):
        empty_left = Path(self.tmp.name) / "empty_l"
        empty_right = Path(self.tmp.name) / "empty_r"
        empty_left.mkdir()
        empty_right.mkdir()
        with self.assertRaises(SystemExit):
            quiet(rc.run_dir, empty_left, empty_right, out=Path(self.tmp.name) / "o", exclude=set(), content=False, max_content=0)

    def test_not_a_directory(self):
        file_path = Path(self.tmp.name) / "file.txt"
        file_path.write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            quiet(rc.run_dir, file_path, self.right, out=Path(self.tmp.name) / "o2", exclude=set(), content=False, max_content=0)

    def test_identical_trees(self):
        same = Path(self.tmp.name) / "same"
        make_tree(same, {"相同.md": "一模一样\n".encode("utf-8")})
        result = quiet(rc.run_dir, same, same, out=Path(self.tmp.name) / "o3", exclude=set(), content=False, max_content=0)
        self.assertTrue(all(entry.status == "same" for entry in result["entries"]))
        self.assertIn("完全一致", result["report"])


class TestRename(unittest.TestCase):
    """改名（内容哈希一致、路径变了）不能报成「删了一个、加了一个」。"""

    def test_rename_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left, right = root / "l", root / "r"
            make_tree(left, {"图A.png": b"\x89PNG-fake-bytes"})
            make_tree(right, {"图A_v2.png": b"\x89PNG-fake-bytes"})
            entries = rc.compare_dirs(left, right, exclude=set(), content=False, max_content=0)
            old = next(entry for entry in entries if entry.rel == "图A.png")
            new = next(entry for entry in entries if entry.rel == "图A_v2.png")
            self.assertEqual(old.status, "renamed")
            self.assertEqual(new.status, "renamed")
            self.assertIn("图A_v2.png", old.note)

    def test_rename_not_confused_with_real_delete_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left, right = root / "l", root / "r"
            make_tree(left, {"删掉.txt": b"old"})
            make_tree(right, {"新增.txt": b"new"})
            entries = rc.compare_dirs(left, right, exclude=set(), content=False, max_content=0)
            self.assertEqual({entry.status for entry in entries}, {"only_left", "only_right"})

    def test_duplicate_content_pairs_one_to_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left, right = root / "l", root / "r"
            make_tree(left, {"a.txt": b"same", "b.txt": b"same"})
            make_tree(right, {"c.txt": b"same"})
            entries = rc.compare_dirs(left, right, exclude=set(), content=False, max_content=0)
            renamed = [entry for entry in entries if entry.status == "renamed"]
            self.assertEqual(len(renamed), 2, "一个改名对 = 左右各一条")
            leftovers = [entry for entry in entries if entry.status == "only_left"]
            self.assertEqual(len(leftovers), 1, "多出来的那个仍是仅左侧")


class TestCliDir(unittest.TestCase):
    def test_cli_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            left, right = root / "l", root / "r"
            make_tree(left, {"a.md": b"one\n"})
            make_tree(right, {"a.md": b"two\n"})
            code = quiet(rc.main, ["dir", str(left), str(right), "-o", str(root / "out")])
            self.assertEqual(code, 0)
            self.assertTrue((root / "out" / "reconcile-dir.md").exists())


if __name__ == "__main__":
    unittest.main()
