#!/usr/bin/env python3
"""recalc — 从科目余额表独立重算三大表，与导出报表对比。

    python scripts/recalc.py check -i 报表.json
    python scripts/recalc.py demo

用途：系统（用友/金蝶/任何 ERP）导出的报表，**是不是真的由科目余额算出来的**？
如果有公式被改过、或者报表被手工调过，重算结果就会对不上。

内置的是《企业会计准则》的通用科目-报表映射，科目编码按 1001/1122/2202 这类标准码。
如果企业用了自定义编码，用 `"mapping"` 字段覆盖。
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

# 报表项目 = 若干科目余额的加减。
# 余额按「该科目正常方向」记为正数（资产在借、负债在贷），所以负债类也取 +1。
# 只有备抵科目（累计折旧、累计摊销、坏账准备）才减：它们是资产的抵减项。
BALANCE_SHEET: dict[str, list[tuple[str, float]]] = {
    "货币资金": [("1001", 1), ("1002", 1), ("1012", 1)],
    "应收账款": [("1122", 1), ("1231", -1)],
    "其他应收款": [("1221", 1)],
    "存货": [("1401", 1), ("1403", 1), ("1405", 1), ("1406", 1)],
    "固定资产": [("1601", 1), ("1602", -1)],
    "在建工程": [("1604", 1)],
    "无形资产": [("1701", 1), ("1702", -1)],
    "应付账款": [("2202", 1)],
    "应付职工薪酬": [("2211", 1)],
    "应交税费": [("2221", 1)],
    "其他应付款": [("2241", 1)],
    "实收资本": [("4001", 1)],
    "资本公积": [("4002", 1)],
    "盈余公积": [("4101", 1)],
    "未分配利润": [("4103", 1), ("4104", 1)],
}

INCOME_STATEMENT: dict[str, list[tuple[str, float]]] = {
    "营业收入": [("6001", 1), ("6051", 1)],
    "营业成本": [("6401", 1), ("6402", 1)],
    "税金及附加": [("6403", 1)],
    "销售费用": [("6601", 1)],
    "管理费用": [("6602", 1)],
    "财务费用": [("6603", 1)],
    "营业外收入": [("6301", 1)],
    "营业外支出": [("6711", 1)],
    "所得税费用": [("6801", 1)],
}

DERIVED = {
    "营业利润": ["营业收入", "营业成本", "税金及附加", "销售费用", "管理费用", "财务费用"],
    "利润总额": ["营业利润", "营业外收入", "营业外支出"],
    "净利润": ["利润总额", "所得税费用"],
    "资产总计": ["货币资金", "应收账款", "其他应收款", "存货", "固定资产", "在建工程", "无形资产"],
    "负债合计": ["应付账款", "应付职工薪酬", "应交税费", "其他应付款"],
    "所有者权益合计": ["实收资本", "资本公积", "盈余公积", "未分配利润"],
    "负债和所有者权益总计": ["负债合计", "所有者权益合计"],
}


@dataclasses.dataclass
class Line:
    name: str
    computed: float | None
    reported: float | None
    gap: float | None
    status: str  # ok | mismatch | missing | no-data


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_balances(data: dict[str, Any]) -> dict[str, float]:
    """科目编码 -> 期末余额（按借贷方向统一成「正数表示该科目应有余额」）。"""
    balances: dict[str, float] = {}
    for account in data.get("accounts") or []:
        code = str(account.get("code") or "").strip()
        if not code:
            continue
        balances[code] = num(account.get("closing", account.get("balance")))
    return balances


def compute_section(
    balances: dict[str, float],
    rules: dict[str, list[tuple[str, float]]],
    mapping: dict[str, list[list[Any]]] | None,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for name, formula in rules.items():
        override = (mapping or {}).get(name)
        if override:
            total = 0.0
            for code, sign in override:
                total += float(sign) * balances.get(str(code), 0.0)
            result[name] = round(total, 2)
            continue
        total = 0.0
        for code, sign in formula:
            total += sign * balances.get(code, 0.0)
        result[name] = round(total, 2)
    return result


def derive(results: dict[str, float]) -> dict[str, float]:
    out = dict(results)
    for name, parts in DERIVED.items():
        if name in out:
            continue
        if not all(part in out for part in parts):
            continue
        if name in {"营业利润"}:
            value = out["营业收入"] - out["营业成本"] - out["税金及附加"] - out["销售费用"] - out["管理费用"] - out["财务费用"]
        elif name in {"利润总额"}:
            value = out["营业利润"] + out["营业外收入"] - out["营业外支出"]
        elif name in {"净利润"}:
            value = out["利润总额"] - out["所得税费用"]
        elif name in {"资产总计"}:
            value = sum(out[part] for part in parts)
        elif name in {"负债合计"}:
            value = sum(out[part] for part in parts)
        elif name in {"所有者权益合计"}:
            value = sum(out[part] for part in parts)
        elif name in {"负债和所有者权益总计"}:
            value = out["负债合计"] + out["所有者权益合计"]
        else:
            value = sum(out[part] for part in parts)
        out[name] = round(value, 2)
    return out


def compare(
    computed: dict[str, float],
    reported: dict[str, float],
) -> list[Line]:
    lines: list[Line] = []
    for name, value in computed.items():
        actual = reported.get(name)
        if actual is None:
            # 报表没列这个项目（比如零余额不列示）——不算差异，跳过
            continue
        gap = round(num(actual) - value, 2)
        status = "ok" if abs(gap) <= TOLERANCE else "mismatch"
        lines.append(Line(name, value, num(actual), gap, status))
    for name, value in reported.items():
        if name not in computed:
            lines.append(Line(name, None, num(value), None, "no-data"))
    return lines


def run(data: dict[str, Any]) -> tuple[list[Line], list[str]]:
    issues: list[str] = []
    balances = build_balances(data)
    if not balances:
        return [], ["没有科目余额数据（accounts 为空）"]
    mapping = data.get("mapping") or {}
    computed = compute_section(balances, BALANCE_SHEET, mapping)
    computed.update(compute_section(balances, INCOME_STATEMENT, mapping))
    computed = derive(computed)

    reported = data.get("reported") or {}
    lines = compare(computed, reported)
    if not reported:
        issues.append("没有提供「导出报表数」，只输出重算结果")
    return lines, issues


def render(lines: list[Line], issues: list[str]) -> str:
    ok = sum(1 for line in lines if line.status == "ok")
    bad = sum(1 for line in lines if line.status == "mismatch")
    unknown = sum(1 for line in lines if line.status == "no-data")
    lines_out = [
        "# 报表独立重算",
        "",
        "从科目余额表按标准公式重算，再和导出报表逐项对比。",
        "",
        f"**一致 {ok} · 不符 {bad}**" + (f" · 无法重算 {unknown}" if unknown else ""),
        "",
    ]
    if issues:
        lines_out.extend(["## 提示", ""] + [f"- {issue}" for issue in issues] + [""])
    if lines:
        lines_out.extend(["| 项目 | 重算 | 报表 | 差异 | 状态 |", "|---|---|---|---|---|"])
        mark = {"ok": "✓", "mismatch": "✗", "missing": "—", "no-data": "?"}
        for line in lines:
            computed = "—" if line.computed is None else f"{line.computed:,.2f}"
            reported = "—" if line.reported is None else f"{line.reported:,.2f}"
            gap = "—" if line.gap is None else f"{line.gap:,.2f}"
            lines_out.append(f"| {line.name} | {computed} | {reported} | {gap} | {mark[line.status]} |")
        lines_out.append("")
    lines_out.extend([
        "---",
        "",
        "> 公式是按《企业会计准则》通用科目编码写的（1001/1122/2202…）。",
        "> 企业用自定义科目编码时，用 `mapping` 字段覆盖，否则重算结果没有意义。",
        "> 差异不一定是错：可能是报表做了重分类、合并列示，或科目映射与本工具不同。",
        "> 报表里没列的项目（如零余额）不参与对比，不会算成缺项。",
        "",
    ])
    return "\n".join(lines_out)


def cmd_check(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    lines, issues = run(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "lines": [dataclasses.asdict(line) for line in lines],
            "issues": issues,
        }, ensure_ascii=False, indent=2))
    else:
        print(render(lines, issues))
    return 1 if any(line.status == "mismatch" for line in lines) else 0


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "accounts": [
            {"code": "1001", "closing": 5000},
            {"code": "1002", "closing": 795000},
            {"code": "1122", "closing": 320000},
            {"code": "1231", "closing": 20000},
            {"code": "1403", "closing": 300000},
            {"code": "1601", "closing": 2000000},
            {"code": "1602", "closing": 400000},
            {"code": "2202", "closing": 600000},
            {"code": "2211", "closing": 200000},
            {"code": "2221", "closing": 50000},
            {"code": "4001", "closing": 1500000},
            {"code": "4101", "closing": 100000},
            {"code": "4103", "closing": 500000},
            {"code": "4104", "closing": 50000},
            {"code": "6001", "closing": 4000000},
            {"code": "6401", "closing": 2800000},
            {"code": "6602", "closing": 600000},
            {"code": "6801", "closing": 100000},
        ],
        "reported": {
            "货币资金": 800000,
            "应收账款": 300000,   # 重算 320000-20000=300000，正确
            "存货": 300000,
            "固定资产": 1600000,
            "应付账款": 600000,
            "实收资本": 1500000,
            "营业收入": 4000000,
            "净利润": 500000,
            "资产总计": 4000100,   # 故意错 100
        },
    }
    lines, issues = run(data)
    print(render(lines, issues))
    print("（示例：应收账款重算对得上；资产总计故意差 100）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recalc.py", description="报表独立重算")
    parser.add_argument("--version", action="version", version=f"recalc {VERSION}")
    sub = parser.add_subparsers(dest="command")
    check = sub.add_parser("check", help="重算并对比一份报表 JSON")
    check.add_argument("-i", "--input", required=True)
    check.add_argument("--json", action="store_true")
    check.set_defaults(func=cmd_check)
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
