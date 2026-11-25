"""Tests for bank-statement one-to-many matching. `python -m unittest discover -s tests -v`"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import bank as bk  # noqa: E402


def payload(targets, transactions, tolerance=1.0, max_size=6) -> dict:
    return {
        "tolerance": tolerance,
        "max_size": max_size,
        "targets": [{"id": i, "amount": a} for i, a in targets],
        "transactions": [{"id": i, "amount": a} for i, a in transactions],
    }


class TestSingleMatch(unittest.TestCase):
    def test_exact_single(self):
        matches, missed, _, _amb = bk.match_all(payload([("A", 1000)], [("T1", 1000)]))
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].combination, ["T1"])
        self.assertEqual(missed, [])

    def test_tolerance_covers_fee(self):
        matches, _missed, _, _amb = bk.match_all(payload([("A", 1000)], [("T1", 999)]))
        self.assertEqual(matches[0].combination, ["T1"])

    def test_outside_tolerance(self):
        matches, missed, _, _amb = bk.match_all(payload([("A", 1000)], [("T1", 900)]))
        self.assertEqual(matches, [])
        self.assertEqual(len(missed), 1)


class TestCombination(unittest.TestCase):
    def test_three_transactions(self):
        matches, _missed, _, _amb = bk.match_all(
            payload([("A", 10000)], [("T1", 3000), ("T2", 2000), ("T3", 5000)])
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(set(matches[0].combination), {"T1", "T2", "T3"})

    def test_max_size_respected(self):
        matches, _missed, _, _amb = bk.match_all(
            payload([("A", 100)], [("T1", 25), ("T2", 25), ("T3", 25), ("T4", 25), ("T5", 25)], max_size=3)
        )
        self.assertEqual(matches, [], "超过 max_size 的组合不该报")

    def test_combination_not_reusing_transaction(self):
        matches, _missed, _, _amb = bk.match_all(
            payload([("A", 200), ("B", 200)], [("T1", 100), ("T2", 100)])
        )
        used = [name for match in matches for name in match.combination]
        self.assertEqual(len(used), len(set(used)), "同一笔流水不能被两条记录共用")


class TestPriority(unittest.TestCase):
    def test_single_match_wins_over_combination(self):
        """回归测试：单笔 6800 属于 B，不能被 A 的组合搜索抢走。"""
        matches, missed, _, _amb = bk.match_all(
            payload(
                [("A", 10000), ("B", 6800)],
                [("T1", 3000), ("T2", 2000), ("T3", 5000), ("T4", 6800), ("T5", 1200)],
            )
        )
        by_target = {match.target: match.combination for match in matches}
        self.assertEqual(by_target["B"], ["T4"], "B 必须拿到单笔 T4")
        self.assertEqual(set(by_target["A"]), {"T1", "T2", "T3"}, "A 应该用三笔凑")
        self.assertEqual(missed, [])

    def test_unmatched_target_reported(self):
        _matches, missed, _, _amb = bk.match_all(payload([("A", 99999)], [("T1", 100)]))
        self.assertEqual([t["id"] for t in missed], ["A"])


class TestAmbiguity(unittest.TestCase):
    """同额多笔：结论不能取决于输入顺序。"""

    def test_two_targets_one_transaction_is_ambiguous(self):
        matches, _missed, _, ambiguities = bk.match_all(
            payload([("A-001", 1000), ("A-002", 1000)], [("T1", 1000)])
        )
        self.assertEqual(matches, [], "同额多笔不能硬配")
        self.assertEqual(len(ambiguities), 1)
        self.assertEqual(set(ambiguities[0].targets), {"A-001", "A-002"})
        self.assertEqual(ambiguities[0].amount, 1000.0)

    def test_order_does_not_change_conclusion(self):
        """验收要求：调换两笔账簿顺序，结论必须一致。"""
        first = payload([("A-001", 1000), ("A-002", 1000)], [("T1", 1000)])
        second = payload([("A-002", 1000), ("A-001", 1000)], [("T1", 1000)])
        m1, _, _, a1 = bk.match_all(first)
        m2, _, _, a2 = bk.match_all(second)
        self.assertEqual([m.target for m in m1], [m.target for m in m2])
        self.assertEqual([sorted(a.targets) for a in a1], [sorted(a.targets) for a in a2])

    def test_equal_counts_still_match(self):
        """两笔账簿对两笔流水，数量对等，可以一一配对。"""
        matches, _missed, _, ambiguities = bk.match_all(
            payload([("A-001", 1000), ("A-002", 1000)], [("T1", 1000), ("T2", 1000)])
        )
        self.assertEqual(len(matches), 2)
        self.assertEqual(ambiguities, [])

    def test_more_transactions_than_targets(self):
        matches, _missed, _, ambiguities = bk.match_all(
            payload([("A-001", 1000)], [("T1", 1000), ("T2", 1000)])
        )
        self.assertEqual(matches, [])
        self.assertEqual(len(ambiguities), 1)

    def test_ambiguous_items_not_double_counted(self):
        _m, missed, _, ambiguities = bk.match_all(
            payload([("A-001", 1000), ("A-002", 1000)], [("T1", 1000)])
        )
        self.assertEqual(missed, [], "歧义组不该同时出现在未匹配里")
        self.assertEqual(len(ambiguities), 1)


class TestCentsPrecision(unittest.TestCase):
    def test_cent_level(self):
        matches, _missed, _, _amb = bk.match_all(
            payload([("A", 100.01)], [("T1", 50.00), ("T2", 50.01)], tolerance=0.0)
        )
        self.assertEqual(len(matches), 1, "一分钱精度内应能匹配")

    def test_no_float_drift(self):
        """0.1 + 0.2 这类浮点误差不能导致误判。"""
        matches, _missed, _, _amb = bk.match_all(
            payload([("A", 0.3)], [("T1", 0.1), ("T2", 0.2)], tolerance=0.0)
        )
        self.assertEqual(len(matches), 1)


if __name__ == "__main__":
    unittest.main()
