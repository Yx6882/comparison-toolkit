#!/usr/bin/env python3
"""inventory — 存货计价。三种方法，纯算术。

    python scripts/inventory.py calc -i 收发存.json
    python scripts/inventory.py demo

三种方法：
    先进先出 FIFO      先入库的先出，逐批结转成本
    月末一次加权平均    全月平均单价 = 期初金额 + 本月入库金额 ÷ 总数量，月终一次结转
    移动加权平均        每次入库后重算单价，出库按当时单价结转
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
TOLERANCE = 0.01
METHODS = {
    "fifo": "先进先出",
    "weighted_average": "月末一次加权平均",
    "moving_average": "移动加权平均",
}


@dataclasses.dataclass
class Movement:
    date: str
    kind: str  # in | out
    qty: float
    unit_cost: float = 0.0
    amount: float = 0.0
    note: str = ""


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def normalize(data: dict[str, Any]) -> list[Movement]:
    out: list[Movement] = []
    for record in data.get("records") or []:
        kind = str(record.get("type") or record.get("kind") or "").lower()
        if kind in {"in", "入库", "收", "采购"}:
            kind = "in"
        elif kind in {"out", "出库", "发", "销售"}:
            kind = "out"
        else:
            continue
        out.append(
            Movement(
                date=str(record.get("date") or ""),
                kind=kind,
                qty=num(record.get("qty")),
                unit_cost=num(record.get("unit_cost")),
            )
        )
    return out


def run_fifo(records: list[Movement], opening: float, opening_qty: float) -> tuple[list[Movement], float, float, list[str]]:
    issues: list[str] = []
    layers: list[list[float]] = []  # [qty, unit_cost]
    if opening_qty > 0 and opening > 0:
        layers.append([opening_qty, opening / opening_qty])
    issued: list[Movement] = []
    for record in records:
        if record.kind == "in":
            if record.qty <= 0:
                issues.append(f"{record.date} 入库数量非正：{record.qty}")
                continue
            layers.append([record.qty, record.unit_cost])
        else:
            remaining = record.qty
            cost = 0.0
            while remaining > 1e-9 and layers:
                qty, unit = layers[0]
                take = min(qty, remaining)
                cost += take * unit
                remaining -= take
                if qty - take <= 1e-9:
                    layers.pop(0)
                else:
                    layers[0][0] = qty - take
            if remaining > 1e-9:
                issues.append(f"{record.date} 出库 {record.qty} 超过库存，缺 {remaining:g}")
            issued.append(Movement(record.date, "out", record.qty, cost / record.qty if record.qty else 0, cost))
    ending_qty = sum(layer[0] for layer in layers)
    ending_amount = sum(layer[0] * layer[1] for layer in layers)
    return issued, ending_qty, ending_amount, issues


def run_weighted_average(records: list[Movement], opening: float, opening_qty: float) -> tuple[list[Movement], float, float, list[str]]:
    issues: list[str] = []
    in_qty = sum(r.qty for r in records if r.kind == "in")
    in_amount = sum(r.qty * r.unit_cost for r in records if r.kind == "in")
    out_qty = sum(r.qty for r in records if r.kind == "out")
    total_qty = opening_qty + in_qty
    if total_qty <= 0:
        return [], 0.0, 0.0, ["没有期初和入库，无法计算加权平均单价"]
    if out_qty > total_qty + 1e-9:
        issues.append(f"发出数量 {out_qty:g} 超过可发数量 {total_qty:g}")
    unit = (opening + in_amount) / total_qty
    issued = [Movement(r.date, "out", r.qty, unit, r.qty * unit) for r in records if r.kind == "out"]
    ending_qty = total_qty - out_qty
    ending_amount = ending_qty * unit
    return issued, ending_qty, ending_amount, issues


def run_moving_average(records: list[Movement], opening: float, opening_qty: float) -> tuple[list[Movement], float, float, list[str]]:
    issues: list[str] = []
    qty = opening_qty
    amount = opening
    issued: list[Movement] = []
    for record in records:
        if record.kind == "in":
            qty += record.qty
            amount += record.qty * record.unit_cost
        else:
            if qty <= 1e-9:
                issues.append(f"{record.date} 库存为 0 却发生出库 {record.qty:g}")
                continue
            if record.qty > qty + 1e-9:
                issues.append(f"{record.date} 出库 {record.qty:g} 超过库存 {qty:g}")
            unit = amount / qty
            take = min(record.qty, qty)
            cost = take * unit
            qty -= take
            amount -= cost
            issued.append(Movement(record.date, "out", record.qty, unit, cost))
    return issued, qty, amount, issues


def calculate(data: dict[str, Any]) -> tuple[list[Movement], float, float, list[str], str]:
    method = str(data.get("method") or "fifo").lower()
    opening = num(data.get("opening_amount"))
    opening_qty = num(data.get("opening_qty"))
    records = normalize(data)
    if not records:
        return [], opening_qty, opening, ["没有收发记录"], method
    if method == "fifo":
        issued, qty, amount, issues = run_fifo(records, opening, opening_qty)
    elif method == "weighted_average":
        issued, qty, amount, issues = run_weighted_average(records, opening, opening_qty)
    elif method == "moving_average":
        issued, qty, amount, issues = run_moving_average(records, opening, opening_qty)
    else:
        return [], 0.0, 0.0, [f"未知计价方法：{method}"], method
    return issued, qty, amount, issues, method


def render(issued: list[Movement], qty: float, amount: float, issues: list[str], method: str) -> str:
    lines = [
        "# 存货计价",
        "",
        f"- 方法：{METHODS.get(method, method)}",
        f"- 期末数量 {qty:,.2f} · 期末金额 {amount:,.2f}"
        + (f" · 单位成本 {amount / qty:,.4f}" if qty > 1e-9 else ""),
        "",
    ]
    if issues:
        lines.extend(["## 检查提示", ""] + [f"- {issue}" for issue in issues] + [""])
    if issued:
        lines.extend(["| 日期 | 出库数量 | 单位成本 | 出库金额 |", "|---|---|---|---|"])
        for item in issued:
            lines.append(f"| {item.date} | {item.qty:,.2f} | {item.unit_cost:,.4f} | {item.amount:,.2f} |")
        lines.extend(["", f"发出成本合计 **{sum(i.amount for i in issued):,.2f}**", ""])
    lines.extend(
        [
            "---",
            "",
            "> 只按给定数据算成本，不判断计价方法的选用是否恰当。",
            "> 三种方法在物价波动时结果不同，选哪种要符合企业会计政策并一贯使用。",
            "",
        ]
    )
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
    issued, qty, amount, issues, method = calculate(data)
    if args.json:
        print(json.dumps({
            "version": VERSION, "method": method,
            "issued": [dataclasses.asdict(i) for i in issued],
            "ending_qty": round(qty, 4), "ending_amount": round(amount, 2),
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(issued, qty, amount, issues, method))
    return 1 if issues else 0


def cmd_demo(args: argparse.Namespace) -> int:
    print("# 存货计价示例")
    print()
    base = {
        "records": [
            {"date": "2026-01-05", "type": "in", "qty": 100, "unit_cost": 10},
            {"date": "2026-01-10", "type": "out", "qty": 30},
            {"date": "2026-01-15", "type": "in", "qty": 100, "unit_cost": 12},
            {"date": "2026-01-20", "type": "out", "qty": 80},
        ]
    }
    print("场景：1/5 入库 100@10，1/10 出 30，1/15 入库 100@12，1/20 出 80\n")
    for method in ("fifo", "weighted_average", "moving_average"):
        data = dict(base, method=method)
        issued, qty, amount, issues, _ = calculate(data)
        issued_total = sum(i.amount for i in issued)
        print(f"=== {METHODS[method]} ===")
        print(f"  发出成本 {issued_total:,.2f} · 期末 {qty:g} 件 / {amount:,.2f} 元")
        if issues:
            print(f"  提示：{issues}")
        print()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="inventory.py", description="存货计价")
    parser.add_argument("--version", action="version", version=f"inventory {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份收发存 JSON")
    calc.add_argument("-i", "--input", required=True)
    calc.add_argument("--json", action="store_true")
    calc.set_defaults(func=cmd_calc)
    demo = sub.add_parser("demo", help="跑三种方法的示例")
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
