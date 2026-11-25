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


# ---------------------------------------------------------------------------
# 敏感性分析：哪个变量最影响净利
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Sensitivity:
    name: str
    change_desc: str
    delta_net: float
    elasticity: float  # 净利变化 / 净利基数


def analyze_sensitivity(data: dict[str, Any], step: float = 0.10) -> list[Sensitivity]:
    """每个变量单独变动 step，看月净利变化多少。

    净利对这些变量越敏感，做决策时就越要先盯它。
    """
    base = compute_payback(data)
    if base.monthly_net == 0:
        return []
    revenue = base.monthly_revenue
    variable_rate = num(data.get("variable_cost_rate"))
    fixed = base.monthly_fixed
    denom = abs(base.monthly_net)

    rows = [
        Sensitivity(
            "月收入", f"+{step:.0%}",
            revenue * step * (1 - variable_rate),
            revenue * step * (1 - variable_rate) / denom,
        ),
        Sensitivity(
            "变动成本率", f"+{step:.0%}",
            -revenue * variable_rate * step,
            -revenue * variable_rate * step / denom,
        ),
        Sensitivity(
            "固定成本", f"+{step:.0%}",
            -fixed * step,
            -fixed * step / denom,
        ),
    ]
    rows.sort(key=lambda r: -abs(r.delta_net))
    return rows


# ---------------------------------------------------------------------------
# 淡旺季：按月份系数推算全年现金流
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class MonthRow:
    month: int
    factor: float
    revenue: float
    net: float
    cumulative: float


def analyze_seasonal(data: dict[str, Any]) -> tuple[list[MonthRow], float, int, float] | None:
    """输入 12 个月的收入系数（相对平均值），算全年现金流曲线。"""
    factors = data.get("monthly_factors") or []
    if len(factors) != 12:
        return None
    revenue = num(data.get("monthly_revenue"))
    variable_rate = num(data.get("variable_cost_rate"))
    fixed = num(data.get("monthly_fixed_cost"))

    rows: list[MonthRow] = []
    cumulative = 0.0
    for index, raw in enumerate(factors):
        factor = num(raw)
        month_revenue = revenue * factor
        net = month_revenue * (1 - variable_rate) - fixed
        cumulative += net
        rows.append(MonthRow(index + 1, factor, month_revenue, net, cumulative))

    lowest = min(rows, key=lambda r: r.cumulative)
    return rows, cumulative, lowest.month, lowest.cumulative


# ---------------------------------------------------------------------------
# 平台抽成：算「看起来赚钱、实际不赚」的真实毛利
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class PlatformResult:
    price: float
    take_home: float
    commission: float
    promotion: float
    shipping: float
    cost: float
    net_profit: float
    net_margin: float
    note: str = ""


def analyze_platform(data: dict[str, Any]) -> PlatformResult | None:
    """平台抽成后的真实利润。

    关键：佣金按成交额扣，推广费按曝光/点击扣，**退货订单的推广费通常不退**。
    所以退货率高的时候，实际毛利会被吃掉得比想象中多。
    """
    spec = data.get("platform")
    if not spec:
        return None
    price = num(spec.get("price"))
    cost = num(spec.get("product_cost"))
    commission_rate = num(spec.get("commission_rate"))
    promotion_rate = num(spec.get("promotion_rate"))
    shipping = num(spec.get("shipping"))
    return_rate = num(spec.get("return_rate"))

    commission = price * commission_rate
    promotion = price * promotion_rate
    # 未退货订单的毛利
    gross_per_order = price - commission - promotion - cost - shipping
    # 退货订单：佣金一般可退，推广费不退，物流要付两趟（去+回）
    loss_per_return = promotion + shipping * 2
    valid = 1 - return_rate
    net_per_gmv = valid * gross_per_order + return_rate * (-loss_per_return)
    net_margin = net_per_gmv / price if price else 0.0

    note = ""
    if return_rate >= 0.2:
        note = f"退货率 {return_rate:.0%}，退货的推广费不退还，实际利润被吃掉很多"
    elif net_per_gmv <= 0:
        note = "按当前费率，每卖一件都在亏——涨价或砍推广费之前别放量"

    return PlatformResult(
        price=price,
        take_home=price - commission - promotion,
        commission=commission,
        promotion=promotion,
        shipping=shipping,
        cost=cost,
        net_profit=net_per_gmv,
        net_margin=net_margin,
        note=note,
    )


# ---------------------------------------------------------------------------
# 用工成本：工资之外，社保公积金才是大头
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class LaborResult:
    headcount: float
    wage_total: float
    insurance: float
    housing_fund: float
    total: float
    per_head: float
    overhead_ratio: float


DEFAULT_INSURANCE_RATES = {
    "pension": 0.16,        # 养老（企业部分）
    "medical": 0.08,        # 医疗（企业部分，各地差异大）
    "unemployment": 0.005,  # 失业
    "injury": 0.004,        # 工伤（按行业浮动）
    "maternity": 0.008,     # 生育（部分地区已并入医疗）
}


def analyze_labor(data: dict[str, Any]) -> LaborResult | None:
    """实际用工成本 = 工资 + 社保（企业部分）+ 公积金。

    费率各地差异大，默认值只是常见值，必须用当地标准覆盖。
    """
    spec = data.get("labor")
    if not spec:
        return None
    headcount = num(spec.get("headcount"))
    wage = num(spec.get("monthly_wage"))
    base = num(spec.get("insurance_base")) or wage
    rates = dict(DEFAULT_INSURANCE_RATES)
    rates.update(spec.get("insurance_rates") or {})
    fund_rate = num(spec.get("housing_fund_rate"))

    if headcount <= 0 or wage <= 0:
        return None

    wage_total = headcount * wage
    insurance = headcount * base * sum(rates.values())
    housing_fund = headcount * base * fund_rate
    total = wage_total + insurance + housing_fund
    return LaborResult(
        headcount=headcount,
        wage_total=wage_total,
        insurance=insurance,
        housing_fund=housing_fund,
        total=total,
        per_head=total / headcount,
        overhead_ratio=(total - wage_total) / wage_total if wage_total else 0.0,
    )


# ---------------------------------------------------------------------------
# 多店对比
# ---------------------------------------------------------------------------


def compare_stores(data: dict[str, Any]) -> list[tuple[str, Payback]]:
    rows = []
    for store in data.get("stores") or []:
        name = str(store.get("name") or f"店{len(rows) + 1}")
        rows.append((name, compute_payback(store)))
    return rows


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


def render_sensitivity(rows: list[Sensitivity], data: dict[str, Any], step: float) -> str:
    base = compute_payback(data)
    lines = [
        "# 敏感性分析",
        "",
        f"基准月净利 {base.monthly_net:,.0f}。每个变量单独变动 {step:.0%}，看净利变化：",
        "",
        "| 变量 | 变动 | 净利变化 | 敏感度 |",
        "|---|---|---|---|",
    ]
    for row in rows:
        lines.append(f"| {row.name} | {row.change_desc} | {row.delta_net:+,.0f} | {row.elasticity:+.2f} |")
    lines.append("")
    if rows:
        top = rows[0]
        lines.extend([
            f"**最敏感的是「{top.name}」**——净利对它的变化反应最大，",
            "管好这一项，比同时盯三个都有效。",
            "",
        ])
        if abs(base.monthly_net) < 1:
            lines.append("> 基准净利接近 0，敏感度数值会异常放大，仅供相对比较。")
            lines.append("")
    lines.extend([
        "---",
        "",
        "> 单变量分析：每次只动一个，不考虑变量之间的联动。",
        "> 真实情况里收入和成本往往同时变化，参见压力测试的双杀场景。",
        "",
    ])
    return "\n".join(lines)


def render_seasonal(rows: list[MonthRow], total: float, lowest_month: int, lowest_value: float) -> str:
    lines = [
        "# 全年现金流（淡旺季）",
        "",
        "| 月份 | 系数 | 收入 | 月净利 | 累计 |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.month} 月 | {row.factor:.2f} | {row.revenue:,.0f} | "
            f"{row.net:,.0f} | {row.cumulative:,.0f} |"
        )
    lines.extend([
        "",
        f"- 全年净现金流：**{total:,.0f}**",
        f"- 累计最低点出现在 **{lowest_month} 月：{lowest_value:,.0f}**",
        "",
    ])
    if lowest_value < 0:
        lines.extend([
            f"> ⚠ 第 {lowest_month} 月前累计会跌到 {lowest_value:,.0f}，",
            f"> 这个数就是你在旺季到来前必须准备的现金。",
            "",
        ])
    lines.extend([
        "---",
        "",
        "> 系数是各月收入相对全年平均的倍数（1.0 = 平均）。",
        "> 用它看全年现金曲线，尤其是淡季的谷底能不能扛住。",
        "",
    ])
    return "\n".join(lines)


def render_platform(result: PlatformResult) -> str:
    lines = [
        "# 平台抽成后的真实利润",
        "",
        "| 项目 | 金额 |",
        "|---|---|",
        f"| 售价 | {result.price:,.2f} |",
        f"| 平台佣金 | −{result.commission:,.2f} |",
        f"| 推广费 | −{result.promotion:,.2f} |",
        f"| 商品成本 | −{result.cost:,.2f} |",
        f"| 物流 | −{result.shipping:,.2f} |",
        f"| **单件净利（含退货影响）** | **{result.net_profit:+,.2f}** |",
        f"| **净利率** | **{result.net_margin:+.1%}** |",
        "",
    ]
    if result.note:
        lines.extend([f"> ⚠ {result.note}", ""])
    lines.extend([
        "---",
        "",
        "> 算法：未退货订单按「售价 − 佣金 − 推广 − 成本 − 物流」计；",
        "> 退货订单按「推广费不退 + 物流双程」计损失。",
        "> 不同平台的退货规则不同，实际以平台协议为准。",
        "",
    ])
    return "\n".join(lines)


def render_labor(result: LaborResult) -> str:
    lines = [
        "# 用工成本",
        "",
        "| 项目 | 金额/月 |",
        "|---|---|",
        f"| 工资（{result.headcount:.0f} 人） | {result.wage_total:,.0f} |",
        f"| 社保（企业部分） | {result.insurance:,.0f} |",
        f"| 公积金 | {result.housing_fund:,.0f} |",
        f"| **实际用工成本** | **{result.total:,.0f}** |",
        f"| 人均成本 | {result.per_head:,.0f} |",
        f"| 附加成本占工资比 | {result.overhead_ratio:.1%} |",
        "",
        "---",
        "",
        "> 工资之外还有社保和公积金，通常额外 20%–35%。",
        "> 费率各地差异极大，默认值是常见值，**必须用当地标准覆盖**。",
        "> 实际申报以当地社保经办机构口径为准。",
        "",
    ]
    return "\n".join(lines)


def render_compare(rows: list[tuple[str, Payback]]) -> str:
    lines = [
        "# 多店对比",
        "",
        "| 店铺 | 月收入 | 月净利 | 回本周期 | 保本月收入 |",
        "|---|---|---|---|---|",
    ]
    for name, payback in rows:
        payback_text = f"{payback.payback_months:.1f} 个月" if payback.payback_months else "无法回本"
        breakeven = f"{payback.breakeven_revenue:,.0f}" if payback.breakeven_revenue else "—"
        lines.append(
            f"| {name} | {payback.monthly_revenue:,.0f} | {payback.monthly_net:,.0f} | "
            f"{payback_text} | {breakeven} |"
        )
    lines.append("")
    viable = [(n, p) for n, p in rows if p.payback_months is not None]
    if viable:
        best = min(viable, key=lambda item: item[1].payback_months or 9999)
        lines.extend([f"**回本最快：{best[0]}**（{best[1].payback_months:.1f} 个月）", ""])
    lines.extend([
        "---",
        "",
        "> 只比数值，不考虑店铺的商圈、租约、团队差异。",
        "",
    ])
    return "\n".join(lines)


def _load(path: str) -> dict[str, Any] | None:
    target = Path(path)
    if not target.exists():
        print(f"error: 文件不存在：{target}", file=sys.stderr)
        return None
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        print(f"error: 不是合法 JSON（{exc}）", file=sys.stderr)
        return None


def cmd_sens(args: argparse.Namespace) -> int:
    data = _load(args.input)
    if data is None:
        return 2
    step = num(getattr(args, "step", 0.10)) or 0.10
    rows = analyze_sensitivity(data, step)
    if not rows:
        print("error: 基准月净利为 0，无法做敏感性分析", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([dataclasses.asdict(r) for r in rows], ensure_ascii=False, indent=2))
    else:
        print(render_sensitivity(rows, data, step))
    return 0


def cmd_seasonal(args: argparse.Namespace) -> int:
    data = _load(args.input)
    if data is None:
        return 2
    result = analyze_seasonal(data)
    if result is None:
        print("error: 需要 12 个 monthly_factors（各月收入系数）", file=sys.stderr)
        return 1
    rows, total, lowest_month, lowest_value = result
    if args.json:
        print(json.dumps({
            "months": [dataclasses.asdict(r) for r in rows],
            "total": total, "lowest_month": lowest_month, "lowest_value": lowest_value,
        }, ensure_ascii=False, indent=2))
    else:
        print(render_seasonal(rows, total, lowest_month, lowest_value))
    return 0


def cmd_platform(args: argparse.Namespace) -> int:
    data = _load(args.input)
    if data is None:
        return 2
    result = analyze_platform(data)
    if result is None:
        print("error: 需要 platform 字段（price/product_cost/commission_rate 等）", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    else:
        print(render_platform(result))
    return 0 if result.net_profit > 0 else 1


def cmd_labor(args: argparse.Namespace) -> int:
    data = _load(args.input)
    if data is None:
        return 2
    result = analyze_labor(data)
    if result is None:
        print("error: 需要 labor 字段（headcount/monthly_wage）", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    else:
        print(render_labor(result))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    data = _load(args.input)
    if data is None:
        return 2
    rows = compare_stores(data)
    if not rows:
        print("error: 需要 stores 数组", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps([{"name": n, "payback": dataclasses.asdict(p)} for n, p in rows],
                         ensure_ascii=False, indent=2))
    else:
        print(render_compare(rows))
    return 0


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

    payback = sub.add_parser("payback", help="回本周期 + 保本点 + 爬坡 + 租约 + 压力测试")
    payback.add_argument("-i", "--input", required=True)
    payback.add_argument("--json", action="store_true")
    payback.set_defaults(func=cmd_payback)

    sens = sub.add_parser("sens", help="敏感性分析：哪个变量最影响净利")
    sens.add_argument("-i", "--input", required=True)
    sens.add_argument("--step", type=float, default=0.10, help="变动幅度，默认 0.10")
    sens.add_argument("--json", action="store_true")
    sens.set_defaults(func=cmd_sens)

    seasonal = sub.add_parser("seasonal", help="淡旺季全年现金流")
    seasonal.add_argument("-i", "--input", required=True)
    seasonal.add_argument("--json", action="store_true")
    seasonal.set_defaults(func=cmd_seasonal)

    platform = sub.add_parser("platform", help="平台抽成后的真实利润")
    platform.add_argument("-i", "--input", required=True)
    platform.add_argument("--json", action="store_true")
    platform.set_defaults(func=cmd_platform)

    labor = sub.add_parser("labor", help="用工成本（社保公积金）")
    labor.add_argument("-i", "--input", required=True)
    labor.add_argument("--json", action="store_true")
    labor.set_defaults(func=cmd_labor)

    compare = sub.add_parser("compare", help="多店对比")
    compare.add_argument("-i", "--input", required=True)
    compare.add_argument("--json", action="store_true")
    compare.set_defaults(func=cmd_compare)

    demo = sub.add_parser("demo", help="跑回本测算示例")
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
