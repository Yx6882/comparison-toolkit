#!/usr/bin/env python3
"""business — 开店经营测算：回本周期、保本点、压力测试、城市系数。

    python scripts/business.py payback -i 数据.json
    python scripts/business.py stress  -i 数据.json
    python scripts/business.py demo

全部是算术。数据由你填，工具只负责算——不编任何行业数据。

四个能力：
    回本周期    投资 ÷ 月净利
    保本点      固定成本 ÷ (1 − 变动成本率)
    压力测试    收入下滑 / 成本上涨 / 两者叠加，还撑不撑得住
    城市系数    用城市收入水平相对全国的比值，估算成本和客单价差异
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"

# 全国城镇人均可支配收入基准（2023 年，国家统计局）。
# 这个数只用于「城市系数」的相对换算，绝对值请以最新公报为准。
NATIONAL_INCOME_BASELINE = 39218.0


@dataclasses.dataclass
class Payback:
    monthly_revenue: float
    monthly_variable: float
    monthly_fixed: float
    monthly_gross: float
    monthly_net: float
    payback_months: float | None
    breakeven_revenue: float | None
    note: str = ""


@dataclasses.dataclass
class Scenario:
    name: str
    revenue: float
    fixed: float
    net: float
    payback_months: float | None
    status: str


@dataclasses.dataclass
class RampMonth:
    month: int
    revenue_ratio: float
    revenue: float
    net: float
    cumulative: float


@dataclasses.dataclass
class LeaseCheck:
    lease_months: float
    payback_months: float
    profitable_months: float
    verdict: str
    note: str


def compute_ramp(data: dict[str, Any]) -> tuple[list[RampMonth], float, float] | None:
    """开业爬坡期：收入从首月的 start_ratio 线性恢复到 100%。

    返回 (逐月明细, 累计净现金流, 需要准备的最低现金)。
    开店最容易死在这一段——不是不赚钱，是撑不到赚钱。
    """
    months = int(num(data.get("ramp_months")))
    if months <= 0:
        return None
    start_ratio = num(data.get("ramp_start_ratio")) or 0.5
    revenue = num(data.get("monthly_revenue"))
    variable = num(data.get("variable_cost_rate"))
    fixed = num(data.get("monthly_fixed_cost"))

    rows: list[RampMonth] = []
    cumulative = 0.0
    lowest = 0.0
    for index in range(months):
        # 第 1 个月是 start_ratio，最后一个月到 100%
        progress = index / max(months - 1, 1) if months > 1 else 1.0
        ratio = start_ratio + (1 - start_ratio) * progress
        month_revenue = revenue * ratio
        net = month_revenue * (1 - variable) - fixed
        cumulative += net
        lowest = min(lowest, cumulative)
        rows.append(RampMonth(index + 1, ratio, month_revenue, net, cumulative))

    # 最低点就是需要准备的现金（负数表示要垫多少）
    return rows, cumulative, abs(lowest)


def check_lease(data: dict[str, Any], payback: Payback) -> LeaseCheck | None:
    """租约周期够不够回本——比回本周期本身更致命的判断。"""
    lease = num(data.get("lease_months"))
    if lease <= 0 or payback.payback_months is None:
        return None
    profitable = lease - payback.payback_months
    if profitable <= 0:
        verdict = "租约内回不了本"
        note = (
            f"租约 {lease:.0f} 个月，回本要 {payback.payback_months:.1f} 个月——"
            "整个租期都在还本，没有任何盈利月份。续约还要再投入。"
        )
    elif profitable < 6:
        verdict = "几乎没有盈利期"
        note = (
            f"租约 {lease:.0f} 个月，回本 {payback.payback_months:.1f} 个月，"
            f"只剩 {profitable:.1f} 个月赚钱，不够覆盖装修折旧和续约风险。"
        )
    else:
        verdict = "租约覆盖足够"
        note = f"租约内可盈利 {profitable:.1f} 个月。"
    return LeaseCheck(lease, payback.payback_months, profitable, verdict, note)


def num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def compute_payback(data: dict[str, Any]) -> Payback:
    investment = num(data.get("investment"))
    revenue = num(data.get("monthly_revenue"))
    variable_rate = num(data.get("variable_cost_rate"))
    fixed = num(data.get("monthly_fixed_cost"))

    gross = revenue * (1 - variable_rate)
    net = gross - fixed
    payback = (investment / net) if net > 0 and investment > 0 else None
    margin = (1 - variable_rate)
    breakeven = (fixed / margin) if margin > 0 else None

    note = ""
    if net <= 0:
        note = "月净利为负或为零，按当前数据永远回不了本"
    elif payback is not None and payback > 36:
        note = f"回本 {payback:.1f} 个月，超过 3 年——多数小店的租约周期都在 3 年内"

    return Payback(
        monthly_revenue=revenue,
        monthly_variable=revenue * variable_rate,
        monthly_fixed=fixed,
        monthly_gross=gross,
        monthly_net=net,
        payback_months=payback,
        breakeven_revenue=breakeven,
        note=note,
    )


def run_stress(data: dict[str, Any]) -> list[Scenario]:
    base = compute_payback(data)
    investment = num(data.get("investment"))
    revenue = base.monthly_revenue
    fixed = base.monthly_fixed
    variable_rate = num(data.get("variable_cost_rate"))

    def build(name: str, new_revenue: float, new_fixed: float) -> Scenario:
        net = new_revenue * (1 - variable_rate) - new_fixed
        payback = (investment / net) if net > 0 and investment > 0 else None
        if net <= 0:
            status = "亏损"
        elif payback is None or payback > 48:
            status = "危险"
        elif payback > 36:
            status = "吃紧"
        else:
            status = "可承受"
        return Scenario(name, new_revenue, new_fixed, net, payback, status)

    return [
        Scenario("当前", revenue, fixed, base.monthly_net, base.payback_months,
                 "亏损" if base.monthly_net <= 0 else "基准"),
        build("收入 −10%", revenue * 0.9, fixed),
        build("收入 −20%", revenue * 0.8, fixed),
        build("收入 −30%", revenue * 0.7, fixed),
        build("租金/固定成本 +20%", revenue, fixed * 1.2),
        build("收入 −20% 且 成本 +20%", revenue * 0.8, fixed * 1.2),
    ]


def city_coefficient(data: dict[str, Any]) -> dict[str, float | None]:
    """用城市收入相对全国的比值，估算成本与客单价差异。

    指数是经验假设（租金对收入更敏感），只用于「大致差多少」，
    不能当成精确值。真实租金请查当地商铺挂牌价。
    """
    city_income = num(data.get("city_disposable_income"))
    if city_income <= 0:
        return {"ratio": None, "rent": None, "labour": None, "price": None}
    ratio = city_income / NATIONAL_INCOME_BASELINE
    return {
        "ratio": ratio,
        "rent": ratio ** 1.3,      # 租金对收入更敏感
        "labour": ratio ** 1.0,    # 人力大致同比例
        "price": ratio ** 0.8,     # 客单价敏感度较低
    }


def render_payback(data: dict[str, Any], payback: Payback, scenarios: list[Scenario],
                   city: dict[str, float | None]) -> str:
    ramp = compute_ramp(data)
    lease = check_lease(data, payback)
    lines = [
        "# 开店测算",
        "",
        f"- 投资 {num(data.get('investment')):,.0f} 元",
        f"- 月收入 {payback.monthly_revenue:,.0f} · 变动成本率 {num(data.get('variable_cost_rate')):.0%}"
        f" · 月固定成本 {payback.monthly_fixed:,.0f}",
        "",
        "## 回本与保本",
        "",
        "| 项目 | 金额 |",
        "|---|---|",
        f"| 月毛利（收入 − 变动成本） | {payback.monthly_gross:,.0f} |",
        f"| 月净利（毛利 − 固定成本） | {payback.monthly_net:,.0f} |",
    ]
    if payback.payback_months is not None:
        lines.append(f"| **回本周期** | **{payback.payback_months:.1f} 个月** |")
    else:
        lines.append("| **回本周期** | **无法回本** |")
    if payback.breakeven_revenue is not None:
        lines.append(f"| 保本月收入 | {payback.breakeven_revenue:,.0f} |")
    lines.append("")
    if payback.note:
        lines.extend([f"> ⚠ {payback.note}", ""])

    if lease:
        icon = "✅" if lease.verdict == "租约覆盖足够" else "⚠"
        lines.extend([
            "## 租约够不够回本",
            "",
            f"{icon} **{lease.verdict}**",
            "",
            f"{lease.note}",
            "",
        ])

    if ramp:
        rows, total, reserve = ramp
        lines.extend([
            "## 爬坡期现金流（最容易死在这里）",
            "",
            f"假设开业首月收入为正常月份的 {rows[0].revenue_ratio:.0%}，"
            f"{len(rows)} 个月内线性恢复到 100%。",
            "",
            "| 月份 | 收入 | 月净利 | 累计 |",
            "|---|---|---|---|",
        ])
        for row in rows:
            lines.append(f"| 第 {row.month} 月 | {row.revenue:,.0f} | {row.net:,.0f} | {row.cumulative:,.0f} |")
        lines.extend([
            "",
            f"- 爬坡期累计净现金流：**{total:,.0f}**",
            f"- **需要额外准备的现金：{reserve:,.0f}**（撑过最低点）",
            "",
        ])
        if reserve > num(data.get("investment")) * 0.3:
            lines.append("> ⚠ 需要垫的钱超过投资额的 30%，很多人低估了这一块。")
            lines.append("")

    lines.extend(["## 压力测试", "", "| 场景 | 月收入 | 月净利 | 回本周期 | 判断 |",
                  "|---|---|---|---|---|"])
    for scenario in scenarios:
        if scenario.payback_months is None or scenario.payback_months > 120:
            payback_text = "无法回本"
        else:
            payback_text = f"{scenario.payback_months:.1f} 个月"
        lines.append(
            f"| {scenario.name} | {scenario.revenue:,.0f} | {scenario.net:,.0f} | "
            f"{payback_text} | {scenario.status} |"
        )
    lines.append("")

    if city.get("ratio") is not None:
        lines.extend([
            "## 城市系数（参考）",
            "",
            f"- 城市收入 / 全国基准（{NATIONAL_INCOME_BASELINE:,.0f}）= **{city['ratio']:.2f}**",
            f"- 租金约 ×{city['rent']:.2f} · 人力约 ×{city['labour']:.2f} · 客单价约 ×{city['price']:.2f}",
            "",
            "> 这是按收入水平做的**近似换算**，指数是经验假设。",
            "> 真实租金请查当地商铺挂牌价，人力请查当地社保基数和招聘薪资。",
            "",
        ])

    lines.extend([
        "---",
        "",
        "> 全部为算术：数据由你提供，工具不生成任何行业数据。",
        "> 回本周期不告诉你「值不值得做」，只告诉你「按现在的数，多久能拿回本金」。",
        "> 压力测试是单变量推演，真实经营里收入下滑往往同时伴随成本上升。",
        "",
    ])
    return "\n".join(lines)


def cmd_payback(args: argparse.Namespace) -> int:
    path = Path(args.input)
    if not path.exists():
        print(f"error: 文件不存在：{path}", file=sys.stderr)
        return 2
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return 2
    payback = compute_payback(data)
    scenarios = run_stress(data)
    city = city_coefficient(data)
    if args.json:
        print(json.dumps({
            "version": VERSION,
            "payback": dataclasses.asdict(payback),
            "scenarios": [dataclasses.asdict(s) for s in scenarios],
            "city": city,
        }, ensure_ascii=False, indent=2))
    else:
        print(render_payback(data, payback, scenarios, city))
    return 0 if payback.monthly_net > 0 else 1


def cmd_demo(args: argparse.Namespace) -> int:
    data = {
        "investment": 500000,
        "monthly_revenue": 120000,
        "variable_cost_rate": 0.40,
        "monthly_fixed_cost": 50000,
        "ramp_months": 6,
        "ramp_start_ratio": 0.4,
        "lease_months": 36,
        "city_disposable_income": 60000,
    }
    payback = compute_payback(data)
    scenarios = run_stress(data)
    city = city_coefficient(data)
    print(render_payback(data, payback, scenarios, city))
    print("（示例：投资 50 万，月收入 12 万，变动成本 40%，固定成本 5 万，")
    print("  开业首月只有四成收入、6 个月爬坡，租约 36 个月）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="business.py", description="开店测算")
    parser.add_argument("--version", action="version", version=f"business {VERSION}")
    sub = parser.add_subparsers(dest="command")
    payback = sub.add_parser("payback", help="回本周期 + 保本点 + 压力测试")
    payback.add_argument("-i", "--input", required=True)
    payback.add_argument("--json", action="store_true")
    payback.set_defaults(func=cmd_payback)
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
