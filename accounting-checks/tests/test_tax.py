"""Tests for the tax calculator. `python -m unittest discover -s tests -v`

重点：验证「只算金额」的边界——不做筹划、留抵不缴税、附加税随增值税联动。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import tax as tx  # noqa: E402


def vat_data(**overrides) -> dict:
    data = {"vat": {"output_tax": 520000, "input_tax": 380000, "input_transfer_out": 5000}}
    data.update(overrides)
    return data


def amounts(result: tx.Result, name: str) -> float:
    return round(sum(line.amount for line in result.lines if line.name == name), 2)


class TestVat(unittest.TestCase):
    def test_basic(self):
        result = tx.calculate(vat_data())
        self.assertAlmostEqual(amounts(result, "增值税"), 145000.0, places=2)

    def test_transfer_out_increases(self):
        data = {"vat": {"output_tax": 100000, "input_tax": 100000, "input_transfer_out": 8000}}
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "增值税"), 8000.0, places=2)

    def test_credit_carry_forward_reduces(self):
        data = {"vat": {"output_tax": 100000, "input_tax": 60000, "carry_forward": 20000}}
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "增值税"), 20000.0, places=2)

    def test_input_exceeds_output_is_credit_not_tax(self):
        data = {"vat": {"output_tax": 100000, "input_tax": 150000}}
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "增值税"), 0.0, places=2)
        self.assertTrue(any("留抵" in note for note in result.notes))


class TestSurcharges(unittest.TestCase):
    def test_default_rates(self):
        result = tx.calculate(vat_data())
        # 145000 × (7% + 3% + 2%) = 17400
        self.assertAlmostEqual(amounts(result, "附加税"), 17400.0, places=2)

    def test_city_rate_configurable(self):
        data = vat_data(surcharges={"city_rate": 0.05})
        result = tx.calculate(data)
        # 145000 × (5% + 3% + 2%) = 14500
        self.assertAlmostEqual(amounts(result, "附加税"), 14500.0, places=2)

    def test_zero_vat_means_zero_surcharge(self):
        data = {"vat": {"output_tax": 100000, "input_tax": 150000}, "surcharges": {}}
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "附加税"), 0.0, places=2)

    def test_surcharges_can_be_disabled(self):
        data = {"vat": {"output_tax": 100000, "input_tax": 0}, "surcharges": False}
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "附加税"), 0.0, places=2)

    def test_surcharges_default_when_omitted(self):
        """没提供 surcharges 字段时，按默认税率计算（附加税是法定随增值税计征的）。"""
        result = tx.calculate({"vat": {"output_tax": 100000, "input_tax": 0}})
        self.assertAlmostEqual(amounts(result, "附加税"), 12000.0, places=2)


class TestIncomeTax(unittest.TestCase):
    def test_adjustments(self):
        data = {
            "income_tax": {
                "accounting_profit": 500000,
                "adjustments": [
                    {"item": "业务招待费超支", "amount": 20000},
                    {"item": "研发费用加计扣除", "amount": -150000},
                ],
                "rate": 0.25,
            }
        }
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "企业所得税"), 92500.0, places=2)

    def test_loss_carryforward(self):
        data = {
            "income_tax": {
                "accounting_profit": 100000,
                "loss_carryforward": 80000,
                "rate": 0.25,
            }
        }
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "企业所得税"), 5000.0, places=2)

    def test_negative_taxable_income(self):
        data = {
            "income_tax": {
                "accounting_profit": 50000,
                "adjustments": [{"item": "超支", "amount": -100000}],
                "rate": 0.25,
            }
        }
        result = tx.calculate(data)
        self.assertAlmostEqual(amounts(result, "企业所得税"), 0.0, places=2)
        self.assertTrue(any("亏损" in note for note in result.notes))


class TestTotal(unittest.TestCase):
    def test_total_sums_three_taxes(self):
        data = {
            "vat": {"output_tax": 520000, "input_tax": 380000, "input_transfer_out": 5000},
            "income_tax": {"accounting_profit": 500000, "rate": 0.25},
        }
        result = tx.calculate(data)
        expected = 145000 + 17400 + 125000
        self.assertAlmostEqual(result.total, expected, places=2)


class TestBoundary(unittest.TestCase):
    def test_no_data(self):
        result = tx.calculate({})
        self.assertEqual(result.total, 0.0)
        self.assertTrue(any("没有提供" in note for note in result.notes))

    def test_output_mentions_not_advice(self):
        report = tx.render(tx.calculate(vat_data()))
        self.assertIn("不是税务顾问", report)
        self.assertIn("以税务机关认定", report)


if __name__ == "__main__":
    unittest.main()
