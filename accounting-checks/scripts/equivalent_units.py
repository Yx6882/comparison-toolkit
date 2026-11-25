#!/usr/bin/env python3
"""equivalent_units — 约当产量法成本核算。

    python scripts/equivalent_units.py calc -i 成本.json
    python scripts/equivalent_units.py demo

加权平均法（含期初在产品成本）：

    材料约当产量 = 完工产品 + 期末在产品 × 材料完工程度
    加工约当产量 = 完工产品 + 期末在产品 × 加工完工程度
    单位成本 = (期初成本 + 本期投入) ÷ 约当产量
    完工成本 = 完工数量 × (材料单位成本 + 加工单位成本)

材料一次投入时完工程度填 1.0；分次投入按实际投料比例填。
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"

DATACLASSES_READY = True


@dataclasses.dataclass
class Result:
    material_eu: float
    conversion_eu: float
    material_unit: float
    conversion_unit: float
    finished_cost: float
    ending_wip_cost: float
    total_cost: float


def num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def calculate(data: dict[str, Any]) -> tuple[Result | None, list[str]]:
    issues: list[str] = []
    method = str(data.get("method") or "weighted_average").lower()
    if method != "weighted_average":
        issues.append(f"方法 {method} 暂不支持，只做加权平均法（含期初成本）")

    opening = data.get("opening_wip") or {}
    current = data.get("current") or {}
    ending = data.get("ending_wip") or {}

    completed = num(data.get("completed"))
    ending_qty = num(ending.get("qty"))
    material_done = num(ending.get("material_completion"), 1.0)
    conversion_done = num(ending.get("conversion_completion"), 1.0)

    if completed < 0 or ending_qty < 0:
        return None, ["完工数量和在产品数量不能为负"]
    if not (0.0 <= material_done <= 1.0):
        issues.append(f"材料完工程度应在 0~1 之间，实际 {material_done}")
    if not (0.0 <= conversion_done <= 1.0):
        issues.append(f"加工完工程度应在 0~1 之间，实际 {conversion_done}")

    opening_material = num(opening.get("material_cost"))
    opening_conversion = num(opening.get("conversion_cost"))
    current_material = num(current.get("material_cost"))
    current_conversion = num(current.get("conversion_cost"))
    if num(opening.get("overhead_cost")) or num(current.get("overhead_cost")):
        current_conversion += num(current.get("overhead_cost"))
        opening_conversion += num(opening.get("overhead_cost"))
        issues.append("制造费用已并入加工成本一起计算")

    material_total = opening_material + current_material
    conversion_total = opening_conversion + current_conversion

    material_eu = completed + ending_qty * material_done
    conversion_eu = completed + ending_qty * conversion_done
    if material_eu <= 0 or conversion_eu <= 0:
        return None, ["约当产量为 0，无法计算单位成本"]

    material_unit = material_total / material_eu
    conversion_unit = conversion_total / conversion_eu
    finished_cost = completed * (material_unit + conversion_unit)
    ending_material = ending_qty * material_done * material_unit
    ending_conversion = ending_qty * conversion_done * conversion_unit
    ending_cost = ending_material + ending_conversion
    total = material_total + conversion_total

    if abs(finished_cost + ending_cost - total) > 0.01:
        issues.append(
            f"成本分配不平：完工 {finished_cost:,.2f} + 在产 {ending_cost:,.2f} "
            f"≠ 总成本 {total:,.2f}"
        )

    return (
        Result(
            material_eu=material_eu, conversion_eu=conversion_eu,
            material_unit=material_unit, conversion_unit=conversion_unit,
            finished_cost=finished_cost, ending_wip_cost=ending_cost, total_cost=total,
        ),
        issues,
    )


def render(result: Result | None, issues: list[str], data: dict[str, Any]) -> str:
    lines = ["# 约当产量成本核算", ""]
    lines.append(f"- 完工 {num(data.get('completed')):,.0f} · "
                 f"期末在产品 {num((data.get('ending_wip') or {}).get('qty')):,.0f}")
    ending = data.get("ending_wip") or {}
    lines.append(f"- 完工程度：材料 {num(ending.get('material_completion'), 1.0):.0%} · "
                 f"加工 {num(ending.get('conversion_completion'), 1.0):.0%}")
    lines.append("")
    if issues:
        lines.extend(["## 检查提示", ""] + [f"- {issue}" for issue in issues] + [""])
    if result:
        lines.extend([
            "| 项目 | 材料 | 加工 |",
            "|---|---|---|",
            f"| 约当产量 | {result.material_eu:,.2f} | {result.conversion_eu:,.2f} |",
            f"| 单位成本 | {result.material_unit:,.4f} | {result.conversion_unit:,.4f} |",
            "",
            f"完工产品成本 **{result.finished_cost:,.2f}** · "
            f"期末在产品成本 **{result.ending_wip_cost:,.2f}** · "
            f"总成本 {result.total_cost:,.2f}",
            "",
        ])
    lines.extend([
        "---",
        "",
        "> 只按加权平均法分配成本，不判断完工程度是否估计合理。",
        "> 材料一次投入时完工程度填 1.0，分次投入按实际投料比例。",
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
    result, issues = calculate(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "result": dataclasses.asdict(result) if result else None,
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(result, issues, data))
    return 1 if issues else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "method": "weighted_average",
        "opening_wip": {"qty": 100, "material_cost": 5000, "conversion_cost": 2000},
        "current": {"material_cost": 20000, "conversion_cost": 10000},
        "completed": 400,
        "ending_wip": {"qty": 200, "material_completion": 1.0, "conversion_completion": 0.5},
    }
    result, issues = calculate(data)
    print(render(result, issues, data))
    print("（期初 100 件 + 本期投入，本月完工 400，期末 200 件完工 50%）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="equivalent_units.py", description="约当产量成本核算")
    parser.add_argument("--version", action="version", version=f"equivalent_units {VERSION}")
    sub = parser.add_subparsers(dest="command")
    calc = sub.add_parser("calc", help="计算一份成本 JSON")
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
