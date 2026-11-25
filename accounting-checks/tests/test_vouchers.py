"""Tests for voucher compliance checks. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import vouchers as vc  # noqa: E402


def balanced(no: str = "记-001", date: str = "2026-10-05", summary: str = "采购") -> dict:
    return {
        "no": no, "date": date, "summary": summary,
        "lines": [
            {"account": "1403", "debit": 1000, "credit": 0},
            {"account": "1002", "debit": 0, "credit": 1000},
        ],
    }


def data(*vouchers: dict, start: str = "2026-10-01", end: str = "2026-10-31") -> dict:
    return {"period": {"start": start, "end": end}, "vouchers": list(vouchers)}


def rules(issues: list[vc.Issue]) -> set[str]:
    return {issue.rule for issue in issues}


class TestPerVoucher(unittest.TestCase):
    def test_balanced_is_clean(self):
        self.assertEqual(vc.run_checks(data(balanced())), [])

    def test_unbalanced(self):
        voucher = balanced()
        voucher["lines"][1]["credit"] = 950
        issues = vc.run_checks(data(voucher))
        self.assertIn("借贷平衡", rules(issues))
        self.assertTrue(any("50.00" in issue.detail for issue in issues))

    def test_single_line(self):
        voucher = {"no": "记-001", "date": "2026-10-05", "summary": "x",
                   "lines": [{"account": "1403", "debit": 100, "credit": 0}]}
        self.assertIn("行数", rules(vc.run_checks(data(voucher))))

    def test_debit_and_credit_on_same_line(self):
        voucher = balanced()
        voucher["lines"][0]["credit"] = 500
        self.assertIn("借贷同填", rules(vc.run_checks(data(voucher))))

    def test_zero_amount_line(self):
        voucher = balanced()
        voucher["lines"].append({"account": "9999", "debit": 0, "credit": 0})
        self.assertIn("零金额", rules(vc.run_checks(data(voucher))))

    def test_empty_summary(self):
        self.assertIn("摘要", rules(vc.run_checks(data(balanced(summary="  ")))))

    def test_cross_period_before(self):
        self.assertIn("跨期", rules(vc.run_checks(data(balanced(date="2026-09-30")))))

    def test_cross_period_after(self):
        self.assertIn("跨期", rules(vc.run_checks(data(balanced(date="2026-11-01")))))

    def test_bad_date_format(self):
        self.assertIn("日期", rules(vc.run_checks(data(balanced(date="十月五日")))))

    def test_red_letter_negative_allowed(self):
        """红字凭证是负数，但借贷仍然平衡——不该被规则误伤。"""
        voucher = {"no": "记-002", "date": "2026-10-06", "summary": "红字冲销",
                   "lines": [{"account": "1403", "debit": -500, "credit": 0},
                             {"account": "1002", "debit": 0, "credit": -500}]}
        self.assertEqual(vc.run_checks(data(balanced(), voucher)), [])


class TestNumbering(unittest.TestCase):
    def test_duplicate_number(self):
        issues = vc.run_checks(data(balanced("记-001"), balanced("记-001", date="2026-10-06")))
        self.assertIn("凭证号重复", rules(issues))

    def test_gap_detected(self):
        issues = vc.run_checks(data(balanced("记-001"), balanced("记-004", date="2026-10-06")))
        self.assertIn("凭证号跳号", rules(issues))

    def test_continuous_numbers_clean(self):
        issues = vc.run_checks(data(
            balanced("记-001"), balanced("记-002", date="2026-10-06"),
            balanced("记-003", date="2026-10-07"),
        ))
        self.assertNotIn("凭证号跳号", rules(issues))

    def test_unparsable_numbers_are_skipped(self):
        issues = vc.run_checks(data(balanced("A"), balanced("B", date="2026-10-06")))
        self.assertNotIn("凭证号跳号", rules(issues))


class TestCli(unittest.TestCase):
    def _write(self, tmp: str, payload: dict) -> Path:
        path = Path(tmp) / "v.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_high_issue_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            voucher = balanced()
            voucher["lines"][1]["credit"] = 900
            self.assertEqual(vc.main(["check", "-i", str(self._write(tmp, data(voucher)))]), 1)

    def test_clean_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(vc.main(["check", "-i", str(self._write(tmp, data(balanced())))]), 0)

    def test_missing_file(self):
        self.assertEqual(vc.main(["check", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
