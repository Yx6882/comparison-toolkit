"""Tests for chart-of-accounts roll-forward. `python -m unittest discover -s tests -v`

注意：单科目只检查「期初+借-贷=期末」；「发生额平衡」是全表恒等式，
必须用一套完整的平衡科目来测，不能用单个科目。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger as lg  # noqa: E402


def account(code="1001", direction="借", opening=1000, debit=500, credit=200, closing=1300) -> dict:
    return {"code": code, "name": "测试科目", "direction": direction,
            "opening": opening, "debit": debit, "credit": credit, "closing": closing}


def balanced_set(**overrides) -> list[dict]:
    """一借一贷、发生额和余额都平的完整科目集。

    借方期初 1000 = 贷方期初 1000；本期借 500 = 贷 500；
    期末借方 1300 = 期末贷方 1300（贷方向：1000 + 500 − 200）。
    """
    a = account("1001", "借", opening=1000, debit=500, credit=200, closing=1300)
    b = account("2001", "贷", opening=1000, debit=200, credit=500, closing=1300)
    if "a" in overrides:
        a.update(overrides["a"])
    if "b" in overrides:
        b.update(overrides["b"])
    return [a, b]


def rules(issues: list[lg.Issue]) -> set[str]:
    return {issue.rule for issue in issues}


class TestSingleAccount(unittest.TestCase):
    """单科目只测滚算关系，不碰全局平衡。"""

    def test_debit_side_ok(self):
        self.assertEqual(lg.check_account(account()), [])

    def test_credit_side_ok(self):
        self.assertEqual(lg.check_account(account(direction="贷", opening=2000, debit=300, credit=500, closing=2200)), [])

    def test_debit_side_broken(self):
        self.assertIn("余额勾稽", rules(lg.check_account(account(closing=1301))))

    def test_credit_side_broken(self):
        self.assertIn("余额勾稽", rules(lg.check_account(account(direction="贷", closing=999))))

    def test_bad_direction(self):
        self.assertIn("余额方向", rules(lg.check_account(account(direction="平"))))

    def test_negative_amounts_flagged(self):
        self.assertIn("负数发生额", rules(lg.check_account(account(debit=-100, closing=700))))


class TestTotals(unittest.TestCase):
    def test_balanced_set_is_clean(self):
        self.assertEqual(lg.run_checks({"accounts": balanced_set()}), [])

    def test_debit_credit_total_mismatch(self):
        accounts = balanced_set(b={"credit": 400, "closing": 900})  # 贷方少 100
        issues = lg.run_checks({"accounts": accounts})
        self.assertIn("发生额不平", rules(issues))

    def test_closing_imbalance(self):
        accounts = balanced_set()
        accounts.append(account("3001", "贷", opening=100, debit=0, credit=0, closing=100))
        self.assertIn("期末不平", rules(lg.run_checks({"accounts": accounts})))

    def test_opening_imbalance(self):
        accounts = balanced_set(a={"opening": 1200, "closing": 1500})
        self.assertIn("期初不平", rules(lg.run_checks({"accounts": accounts})))


class TestCli(unittest.TestCase):
    def _write(self, tmp: str, payload: dict) -> Path:
        path = Path(tmp) / "l.json"
        path.write_text(json.dumps({"accounts": payload, "version": 1}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_broken_exits_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = balanced_set(a={"closing": 999})
            self.assertEqual(lg.main(["check", "-i", str(self._write(tmp, broken))]), 1)

    def test_clean_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(lg.main(["check", "-i", str(self._write(tmp, balanced_set()))]), 0)

    def test_missing_file(self):
        self.assertEqual(lg.main(["check", "-i", "不存在.json"]), 2)


if __name__ == "__main__":
    unittest.main()
