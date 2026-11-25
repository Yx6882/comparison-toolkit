#!/usr/bin/env python3
"""tax — 税额计算器。只算金额，不做筹划。

    python scripts/tax.py calc -i 数据.json
    python scripts/tax.py demo

算三种：

    增值税    销项税额 − 进项税额 + 进项转出 − 留抵
    附加税    实缴增值税 ×（城建税 + 教育费附加 + 地方教育附加）
    企业所得税（会计利润 ± 纳税调整 − 弥补亏损）× 税率

**这是计算器，不是税务顾问。** 它不算「怎么少交」，只算「按这些数字该交多少」。
税率、征收率、优惠条件都按输入值处理，实际适用必须以税务机关认定为准。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"

DEFAULT_SURCHARGE = {
    "city_rate": 0.07,        # 城建税（市区）
    "edu_rate": 0.03,         # 教育费附加
    "local_edu_rate": 0.02,   # 地方教育附加
}


@dataclasses.dataclass
class TaxLine:
    name: str
    detail: str
    amount: float


@dataclasses.dataclass
class Result:
    lines: list[TaxLine]
    total: float
    notes: list[str]


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calc_vat(data: dict[str, Any], notes: list[str]) -> tuple[float, float, list[TaxLine]]:
    """Return (payable, credit_carry_forward, lines)."""
    vat = data.get("vat") or {}
    output = num(vat.get("output_tax"))
    incoming = num(vat.get("input_tax"))
    transfer_out = num(vat.get("input_transfer_out"))
    credit = num(vat.get("carry_forward"))

    if not data.get("vat"):
        return 0.0, 0.0, []

    net = output - incoming + transfer_out - credit
    lines = [
        TaxLine("增值税", f"销项 {output:,.2f} − 进项 {incoming:,.2f}", 0.0),
    ]
    if transfer_out:
        lines.append(TaxLine("增值税", f"进项转出 +{transfer_out:,.2f}", 0.0))
    if credit:
        lines.append(TaxLine("增值税", f"上期留抵 −{credit:,.2f}", 0.0))

    if net <= 0:
        notes.append(f"本期增值税留抵 {-net:,.2f}，无需缴纳，结转下期")
        lines.append(TaxLine("增值税", "本期应纳税额", 0.0))
        return 0.0, -net, lines

    lines.append(TaxLine("增值税", "本期应纳税额", round(net, 2)))
    return round(net, 2), 0.0, lines


def calc_surcharges(data: dict[str, Any], vat_payable: float, notes: list[str]) -> list[TaxLine]:
    # 附加税是随增值税法定计征的，默认就算；要关掉必须显式 "surcharges": false
    if data.get("surcharges") is False:
        return []
    if not data.get("vat"):
        return []
    rates = dict(DEFAULT_SURCHARGE)
    spec = data.get("surcharges")
    if isinstance(spec, dict):
        rates.update({k: num(v, rates[k]) for k, v in spec.items()})
    if vat_payable <= 0:
        notes.append("增值税为零或留抵，附加税计税依据为零")
        return [TaxLine("附加税", "增值税为 0，附加税为 0", 0.0)]

    lines = []
    for key, label in (
        ("city_rate", "城市维护建设税"),
        ("edu_rate", "教育费附加"),
        ("local_edu_rate", "地方教育附加"),
    ):
        amount = round(vat_payable * rates[key], 2)
        lines.append(TaxLine("附加税", f"{label} {rates[key]:.0%}", amount))
    return lines


def calc_income_tax(data: dict[str, Any], notes: list[str]) -> tuple[float, list[TaxLine]]:
    spec = data.get("income_tax")
    if not spec:
        return 0.0, []

    profit = num(spec.get("accounting_profit"))
    rate = num(spec.get("rate"), 0.25)
    loss = num(spec.get("loss_carryforward"))

    additions = 0.0
    deductions = 0.0
    lines = [TaxLine("企业所得税", f"会计利润 {profit:,.2f}", 0.0)]
    for item in spec.get("adjustments") or []:
        amount = num(item.get("amount"))
        label = str(item.get("item") or "调整项")
        if amount >= 0:
            additions += amount
            lines.append(TaxLine("企业所得税", f"调增：{label} +{amount:,.2f}", 0.0))
        else:
            deductions += -amount
            lines.append(TaxLine("企业所得税", f"调减：{label} −{-amount:,.2f}", 0.0))

    taxable = profit + additions - deductions - loss
    if loss:
        lines.append(TaxLine("企业所得税", f"弥补以前年度亏损 −{loss:,.2f}", 0.0))

    if taxable <= 0:
        notes.append(f"应纳税所得额 {-taxable:,.2f}（亏损），本期不缴企业所得税")
        lines.append(TaxLine("企业所得税", "本期应纳税额", 0.0))
        return 0.0, lines

    tax = round(taxable * rate, 2)
    lines.append(TaxLine("企业所得税", f"应纳税所得额 {taxable:,.2f} × {rate:.0%}", tax))
    return tax, lines


def calculate(data: dict[str, Any]) -> Result:
    notes: list[str] = []
    vat_payable, credit, vat_lines = calc_vat(data, notes)
    surcharge_lines = calc_surcharges(data, vat_payable, notes)
    income_tax, income_lines = calc_income_tax(data, notes)

    lines = vat_lines + surcharge_lines + income_lines
    total = round(vat_payable + sum(line.amount for line in surcharge_lines if line.amount) + income_tax, 2)
    if not lines:
        notes.append("没有提供任何税种数据")
    return Result(lines, total, notes)


def render(result: Result) -> str:
    lines = ["# 税额计算", ""]
    if result.lines:
        lines.extend(["| 税种 | 明细 | 金额 |", "|---|---|---|"])
        for line in result.lines:
            amount = f"{line.amount:,.2f}" if line.amount else "—"
            lines.append(f"| {line.name} | {line.detail} | {amount} |")
        lines.extend(["", f"**本期应缴合计 {result.total:,.2f}**", ""])

    if result.notes:
        lines.extend(["## 说明", ""] + [f"- {note}" for note in result.notes] + [""])

    lines.extend([
        "---",
        "",
        "> **这是计算器，不是税务顾问。** 只算「按这些数字该交多少」，不算「怎么少交」。",
        "> 税率、征收率、优惠条件按输入值处理；实际适用以税务机关认定和最新政策为准。",
        "> 附加税默认按市区 7% + 教育费附加 3% + 地方教育附加 2%，可按实际地区修改。",
        "> 纳税申报前请由税务师或主管税务机关复核。",
        "",
    ])
    return "\n".join(lines)


def cmd_calc(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    result = calculate(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "lines": [dataclasses.asdict(line) for line in result.lines],
            "total": result.total,
            "notes": result.notes,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(result))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "period": "2026-10",
        "vat": {"output_tax": 520000, "input_tax": 380000, "input_transfer_out": 5000},
        "surcharges": {"city_rate": 0.07},
        "income_tax": {
            "accounting_profit": 500000,
            "adjustments": [
                {"item": "业务招待费超支", "amount": 20000},
                {"item": "研发费用加计扣除", "amount": -150000},
            ],
            "rate": 0.25,
        },
    }
    print(render(calculate(data)))
    print("（增值税 145,000；附加税按 12% 计 17,400；所得税 92,500）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tax.py", description="税额计算器")
    parser.add_argument("--version", action="version", version=f"tax {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份数据")
    calc.add_argument("-i", "--input", required=True)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(func=cmd_calc)
    demo = sub.add_parser("demo", help="跑一个示例")
    demo.set_defaults(func=cmd_demo)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
