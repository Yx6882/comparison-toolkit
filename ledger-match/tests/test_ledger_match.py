"""Tests for ledger_match. Stdlib + openpyxl: `python -m unittest discover -s tests -v`."""

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

import ledger_match as lm  # noqa: E402


def line(amount: float, row: int = 2, sheet: str = "明细") -> lm.Line:
    return lm.Line(sheet=sheet, row=row, raw=str(amount), amount=amount)


class TestMoney(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(lm.parse_money(2000), 2000.0)
        self.assertEqual(lm.parse_money(2000.5), 2000.5)

    def test_formatted(self):
        self.assertEqual(lm.parse_money("2,000.00"), 2000.0)
        self.assertEqual(lm.parse_money("¥2000"), 2000.0)
        self.assertEqual(lm.parse_money("2000 元"), 2000.0)

    def test_accounting_negative(self):
        self.assertEqual(lm.parse_money("(500)"), -500.0)
        self.assertEqual(lm.parse_money("（500）"), -500.0)

    def test_junk(self):
        for value in (None, "", "-", "N/A", "无"):
            self.assertIsNone(lm.parse_money(value))


class TestCombinations(unittest.TestCase):
    def test_four_five_hundreds(self):
        pool = [line(500, row) for row in range(2, 6)] + [line(1200, 6)]
        solutions = lm.find_combinations(2000, pool, tolerance=0.01, max_items=12, max_solutions=4)
        self.assertTrue(any(len(s) == 4 for s in solutions))
        for solution in solutions:
            self.assertAlmostEqual(sum(item.amount for item in solution), 2000.0, places=2)

    def test_ambiguity_is_reported(self):
        pool = [line(500, 2), line(500, 3), line(500, 4), line(500, 5), line(1200, 6), line(800, 7)]
        solutions = lm.find_combinations(2000, pool, tolerance=0.01, max_items=12, max_solutions=6)
        self.assertGreaterEqual(len(solutions), 2, "1200+800 and 4x500 are both valid")

    def test_tolerance_absorbs_rounding(self):
        pool = [line(1999.99, 2)]
        self.assertTrue(lm.find_combinations(2000, pool, tolerance=0.01, max_items=12, max_solutions=2))

    def test_no_solution(self):
        self.assertEqual(
            lm.find_combinations(999, [line(500, 2)], tolerance=0.01, max_items=12, max_solutions=2), []
        )

    def test_negative_lines_ignored(self):
        pool = [line(500, 2), line(-500, 3)]
        solutions = lm.find_combinations(500, pool, tolerance=0.01, max_items=12, max_solutions=2)
        self.assertEqual(len(solutions), 1)
        self.assertEqual(solutions[0][0].row, 2)


class TestReconcile(unittest.TestCase):
    def test_greedy_assignment_uses_each_line_once(self):
        summaries = [line(2000, sheet="汇总"), line(1200, sheet="汇总")]
        details = [line(500, 2), line(500, 3), line(500, 4), line(500, 5), line(1200, 6)]
        matches, leftover = lm.reconcile(summaries, details)
        self.assertEqual(matches[0].status, "matched")
        self.assertEqual(len(matches[0].lines), 4)
        self.assertEqual(matches[1].status, "matched")
        self.assertEqual(len(matches[1].lines), 1)
        self.assertEqual(leftover, [])

    def test_unmatched_total(self):
        matches, _ = lm.reconcile([line(999, sheet="汇总")], [line(500, 2)])
        self.assertEqual(matches[0].status, "unmatched")

    def test_ambiguous_total_keeps_alternatives(self):
        summaries = [line(2000, sheet="汇总")]
        details = [line(500, 2), line(500, 3), line(500, 4), line(500, 5), line(1200, 6), line(800, 7)]
        matches, _ = lm.reconcile(summaries, details)
        self.assertEqual(matches[0].status, "ambiguous")
        self.assertTrue(matches[0].alternatives)


class TestSpreadsheet(unittest.TestCase):
    def test_read_percent_signs_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            from openpyxl import Workbook

            path = Path(tmp) / "s.xlsx"
            wb = Workbook()
            ws = wb.active
            ws.append(["客户", "总价"])
            ws.append(["A", 2000])
            ws.append(["B", "1,500.00"])
            ws.append(["C", "¥888"])
            wb.save(path)

            lines = lm.read_sheet(path, "总价", label_column="客户")
            self.assertEqual([l.amount for l in lines], [2000.0, 1500.0, 888.0])
            self.assertEqual(lines[0].label, "A")

    def test_demo_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "demo"
            lm.build_demo(root)
            buffer = io.StringIO()
            namespace = type(
                "Args",
                (),
                {
                    "summary": str(root / "汇总表.xlsx"),
                    "detail": str(root / "明细表.xlsx"),
                    "summary_col": "总价",
                    "detail_col": "金额",
                    "summary_sheet": None,
                    "detail_sheet": None,
                    "summary_label": "客户",
                    "detail_label": "单号",
                    "tolerance": 0.01,
                    "max_items": 12,
                    "out": str(root / "report"),
                    "fail_on_unmatched": False,
                },
            )()
            with contextlib.redirect_stdout(buffer):
                code = lm.run_match(namespace)
            self.assertEqual(code, 0)
            output = buffer.getvalue()
            self.assertIn("500.00 + 500.00 + 500.00 + 500.00", output)
            self.assertIn("找不到组合", output)
            payload = json.loads((root / "report" / "ledger-match.json").read_text(encoding="utf-8"))
            statuses = [m["status"] for m in payload["matches"]]
            self.assertIn("matched", statuses)
            self.assertIn("unmatched", statuses)


if __name__ == "__main__":
    unittest.main()
