#!/usr/bin/env python3
"""gen_industry_rubrics — 从行业参数表批量生成 assess 的 rubric。

    python scripts/gen_industry_rubrics.py --list
    python scripts/gen_industry_rubrics.py --write

参数表在 INDUSTRIES 里，一行一个行业。生成器负责套模板，
保证 110 个行业的结构、免责声明、建议写法完全一致。

**参数是「行业常见区间」的经验值，不是官方统计。** 每个生成的 rubric
都带这段说明，使用时必须按自己的情况校准。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

VERSION = "0.1.0"
RUBRIC_DIR = Path(__file__).resolve().parents[1] / "rubrics" / "industry"

# 指标模板：按行业组选不同的指标集
PROFILES: dict[str, list[str]] = {
    # 吃客流、看毛利和租金——餐饮零售美业健身
    "footfall": ["gross_margin", "net_margin", "rent_ratio", "labour_ratio"],
    # 看人效和回款——软件设计咨询广告
    "knowledge": ["gross_margin", "net_margin", "labour_ratio", "receivable_days"],
    # 看周转和账期——制造贸易物流
    "flow": ["gross_margin", "net_margin", "inventory_days", "receivable_days"],
    # 看成交和获客——中介服务
    "deal": ["gross_margin", "net_margin", "labour_ratio", "receivable_days"],
}

# (key, 名称, 分组, profile, 毛利率%区间, 净利率%区间, 备注)
INDUSTRIES: list[tuple[str, str, str, str, tuple, tuple, str]] = [
    # ---------------- 餐饮
    ("restaurant-full", "正餐", "餐饮", "footfall", (55, 65), (8, 15), "看翻台率和桌均消费"),
    ("restaurant-fast", "快餐", "餐饮", "footfall", (50, 60), (8, 14), "出餐速度和商圈流量是关键"),
    ("restaurant-hotpot", "火锅", "餐饮", "footfall", (55, 65), (10, 18), "锅底和菜品毛利差异大"),
    ("cafe", "咖啡店", "餐饮", "footfall", (60, 75), (5, 15), "连锁 vs 独立差异极大"),
    ("tea-shop", "茶饮店", "餐饮", "footfall", (55, 70), (8, 18), "看重原料成本和出杯速度"),
    ("bakery", "烘焙店", "餐饮", "footfall", (50, 65), (6, 14), "损耗率往往比毛利更致命"),
    ("street-food", "小吃店", "餐饮", "footfall", (50, 65), (10, 20), "低租金高翻台是核心"),
    ("catering", "团餐/食堂", "餐饮", "footfall", (20, 35), (5, 10), "薄利靠规模和稳定客源"),
    # ---------------- 零售
    ("convenience", "便利店", "零售", "footfall", (20, 30), (3, 8), "靠周转和坪效，不是高毛利"),
    ("supermarket", "超市", "零售", "footfall", (15, 25), (2, 6), "生鲜损耗是关键变量"),
    ("apparel-retail", "服装零售", "零售", "footfall", (40, 60), (8, 18), "库存周转比毛利更重要"),
    ("cosmetics-retail", "美妆零售", "零售", "footfall", (30, 50), (6, 15), "品牌溢价和试用装成本"),
    ("baby-retail", "母婴零售", "零售", "footfall", (25, 40), (5, 12), "复购和会员是核心"),
    ("digital-retail", "数码零售", "零售", "footfall", (10, 20), (2, 6), "价格透明，靠服务和配件"),
    ("home-retail", "家居零售", "零售", "footfall", (30, 50), (6, 15), "客单价高、转化慢"),
    ("pharmacy", "药店", "零售", "footfall", (25, 40), (5, 12), "处方药和保健品毛利不同"),
    # ---------------- 电商
    ("ecom-platform", "电商平台店", "电商", "flow", (30, 55), (5, 15), "平台扣点和推广费要算进成本"),
    ("ecom-standalone", "独立站", "电商", "flow", (50, 70), (10, 25), "获客成本波动大"),
    ("ecom-live", "直播带货", "电商", "flow", (20, 40), (3, 10), "坑位费和退货率影响大"),
    ("ecom-supply", "电商供货", "电商", "flow", (10, 25), (3, 8), "薄利走量，回款周期长"),
    # ---------------- 教育培训
    ("edu-academic", "学科培训", "教育", "knowledge", (50, 65), (15, 30), "政策和合规成本占比高"),
    ("edu-hobby", "兴趣班", "教育", "knowledge", (50, 65), (15, 30), "续班率是核心指标"),
    ("edu-adult", "成人培训", "教育", "knowledge", (55, 70), (15, 30), "获客成本决定生死"),
    ("edu-study-abroad", "留学中介", "教育", "deal", (60, 80), (20, 40), "服务周期长，退费风险"),
    ("edu-online", "在线教育", "教育", "knowledge", (60, 80), (10, 30), "技术投入摊薄是关键"),
    # ---------------- 医疗
    ("clinic", "综合诊所", "医疗", "knowledge", (40, 60), (10, 25), "合规和质控成本不能省"),
    ("dental", "口腔诊所", "医疗", "knowledge", (50, 70), (15, 30), "设备和耗材占比高"),
    ("aesthetic-med", "医美机构", "医疗", "knowledge", (55, 75), (15, 35), "获客成本和合规是两大变量"),
    ("rehab", "康复中心", "医疗", "knowledge", (45, 65), (10, 25), "治疗师人效是关键"),
    ("tcm", "中医馆", "医疗", "knowledge", (45, 65), (10, 25), "饮片成本和名医资源"),
    # ---------------- 美业
    ("beauty-salon", "美容院", "美业", "footfall", (60, 80), (15, 30), "预付卡模式要盯现金流"),
    ("hair-salon", "美发店", "美业", "footfall", (55, 75), (10, 25), "发型师提成和客流"),
    ("nail-salon", "美甲店", "美业", "footfall", (60, 80), (15, 30), "耗材成本低，主要看客流"),
    ("skin-care", "皮肤管理", "美业", "footfall", (60, 80), (15, 30), "仪器投入和复购"),
    # ---------------- 健身
    ("gym", "健身房", "健身", "footfall", (60, 80), (10, 25), "预售模式要盯现金流"),
    ("yoga", "瑜伽馆", "健身", "footfall", (60, 80), (15, 30), "小班课人效和续卡率"),
    ("pt-studio", "私教工作室", "健身", "footfall", (60, 80), (15, 30), "教练提成占比高"),
    ("swim", "游泳馆", "健身", "footfall", (50, 70), (10, 25), "水处理成本和大班容量"),
    # ---------------- 宠物
    ("pet-shop", "宠物店", "宠物", "footfall", (35, 55), (8, 18), "商品和服务毛利差异大"),
    ("pet-hospital", "宠物医院", "宠物", "knowledge", (50, 70), (15, 30), "设备和药品成本"),
    ("pet-grooming", "宠物美容", "宠物", "footfall", (55, 75), (15, 30), "人工和耗材占比"),
    # ---------------- 汽车
    ("auto-repair", "汽车维修", "汽车", "knowledge", (45, 65), (10, 25), "配件毛利和工时费分开算"),
    ("auto-beauty", "汽车美容", "汽车", "footfall", (60, 80), (15, 30), "耗材低，主要看客流"),
    ("auto-sales", "汽车销售", "汽车", "flow", (5, 12), (1, 4), "整车毛利率很低，靠金融和保险"),
    ("auto-rental", "汽车租赁", "汽车", "flow", (40, 60), (10, 25), "车辆折旧和空置率"),
    # ---------------- 装修
    ("home-decoration", "家装", "装修", "flow", (20, 35), (5, 12), "工期延误和增项是主要风险"),
    ("commercial-decoration", "工装", "装修", "flow", (15, 30), (4, 10), "垫资和回款周期长"),
    ("soft-furnishing", "软装", "装修", "flow", (30, 50), (8, 18), "定制周期和退货率"),
    # ---------------- 设计
    ("graphic-design", "平面设计", "设计", "knowledge", (60, 80), (20, 40), "人效和返工率"),
    ("interior-design", "室内设计", "设计", "knowledge", (50, 70), (15, 30), "设计费 vs 工程提成"),
    ("industrial-design", "工业设计", "设计", "knowledge", (55, 75), (15, 30), "项目周期长，人力投入大"),
    ("ui-ux", "UI/UX 设计", "设计", "knowledge", (60, 85), (20, 40), "按项目还是按人天"),
    # ---------------- 软件开发
    ("saas", "SaaS 产品", "软件", "knowledge", (70, 90), (15, 40), "订阅收入和获客成本"),
    ("software-outsourcing", "软件外包", "软件", "knowledge", (30, 50), (8, 18), "人天定价和延期风险"),
    ("mini-program", "小程序开发", "软件", "knowledge", (50, 70), (15, 30), "交付快，售后成本要算"),
    ("game-dev", "游戏开发", "软件", "knowledge", (60, 85), (10, 40), "研发周期长，成败波动大"),
    ("app-dev", "App 开发", "软件", "knowledge", (50, 75), (15, 35), "上架和维护成本"),
    # ---------------- IT 服务
    ("it-ops", "IT 运维", "IT服务", "knowledge", (40, 60), (10, 20), "服务费和硬件转售"),
    ("it-integration", "系统集成", "IT服务", "flow", (15, 30), (4, 10), "硬件占比高，毛利被摊薄"),
    ("data-service", "数据服务", "IT服务", "knowledge", (50, 70), (15, 30), "数据合规是前提"),
    # ---------------- 制造
    ("machinery", "机械制造", "制造", "flow", (20, 35), (5, 12), "设备折旧和订单周期"),
    ("electronics", "电子制造", "制造", "flow", (15, 30), (3, 10), "物料占比高，缺料影响大"),
    ("garment-making", "服装制造", "制造", "flow", (15, 30), (4, 10), "订单波动和库存"),
    ("food-processing", "食品加工", "制造", "flow", (20, 35), (5, 12), "保质期和损耗"),
    ("chemical", "化工", "制造", "flow", (15, 30), (4, 10), "环保和安全投入"),
    ("furniture-making", "家具制造", "制造", "flow", (25, 40), (6, 15), "定制周期和板材损耗"),
    ("packaging", "包装印刷", "制造", "flow", (20, 35), (5, 12), "起订量和设计费"),
    # ---------------- 物流
    ("express", "快递网点", "物流", "flow", (15, 30), (3, 8), "派费和人效"),
    ("warehousing", "仓储", "物流", "flow", (30, 50), (8, 18), "面积利用率和周转"),
    ("freight", "货运", "物流", "flow", (15, 30), (4, 10), "油价和空驶率"),
    ("cold-chain", "冷链", "物流", "flow", (25, 45), (6, 15), "电费和损耗"),
    # ---------------- 贸易
    ("foreign-trade", "外贸", "贸易", "flow", (10, 25), (3, 10), "汇率和账期"),
    ("wholesale", "内贸批发", "贸易", "flow", (8, 20), (2, 8), "薄利走量，资金占用大"),
    ("import", "进口贸易", "贸易", "flow", (15, 30), (4, 12), "关税和汇率"),
    # ---------------- 农业
    ("planting", "种植", "农业", "flow", (20, 45), (5, 20), "看天吃饭，季节性强"),
    ("breeding", "养殖", "农业", "flow", (15, 35), (4, 15), "疫病和饲料成本"),
    ("farm-processing", "农产品加工", "农业", "flow", (15, 30), (4, 10), "原料价格波动"),
    # ---------------- 建筑
    ("construction", "建筑施工", "建筑", "flow", (8, 20), (2, 8), "垫资和回款是最大风险"),
    ("design-institute", "设计院", "建筑", "knowledge", (40, 60), (10, 20), "人效和项目周期"),
    ("supervision", "工程监理", "建筑", "deal", (30, 50), (8, 18), "按项目收费，人力密集"),
    # ---------------- 咨询
    ("management-consulting", "管理咨询", "咨询", "knowledge", (50, 75), (15, 35), "人效和项目周期"),
    ("tax-consulting", "财税咨询", "咨询", "knowledge", (50, 75), (15, 35), "合规责任重"),
    ("legal", "法律服务", "咨询", "knowledge", (60, 85), (20, 40), "人效极高，规模化难"),
    ("hr-consulting", "人力资源咨询", "咨询", "deal", (50, 70), (15, 30), "招聘和培训两块"),
    # ---------------- 广告传媒
    ("ad-planning", "广告策划", "广告", "knowledge", (50, 70), (15, 30), "创意价值和返工"),
    ("ad-media", "广告投放", "广告", "flow", (10, 25), (3, 8), "媒介返点和账期"),
    ("content-creation", "内容制作", "广告", "knowledge", (55, 75), (15, 30), "设备折旧和人力"),
    ("self-media", "自媒体", "传媒", "knowledge", (70, 90), (20, 50), "平台分成和广告"),
    ("short-video", "短视频制作", "传媒", "knowledge", (50, 75), (15, 35), "流量和商单"),
    ("live-stream", "直播运营", "传媒", "flow", (20, 40), (5, 15), "坑位费和投流"),
    ("publishing", "出版", "传媒", "flow", (30, 50), (8, 18), "印量和库存"),
    # ---------------- 娱乐
    ("ktv", "KTV", "娱乐", "footfall", (60, 85), (15, 30), "包房利用率和酒水"),
    ("escape-room", "剧本杀/密室", "娱乐", "footfall", (60, 85), (15, 30), "内容更新成本和复购"),
    ("cinema", "影院", "娱乐", "footfall", (50, 70), (5, 15), "票房分账和卖品"),
    # ---------------- 旅游
    ("travel-agency", "旅行社", "旅游", "deal", (10, 25), (3, 10), "团费和返点"),
    ("homestay", "民宿", "旅游", "footfall", (50, 75), (15, 35), "入住率和季节波动"),
    ("scenic", "景区", "旅游", "footfall", (40, 65), (10, 25), "门票和二次消费"),
    # ---------------- 酒店
    ("hotel-economy", "经济型酒店", "酒店", "footfall", (30, 50), (10, 20), "出租率和房价指数"),
    ("hotel-mid", "中高端酒店", "酒店", "footfall", (40, 60), (12, 25), "服务成本和出租率"),
    # ---------------- 租赁
    ("equipment-rental", "设备租赁", "租赁", "flow", (50, 70), (15, 30), "设备利用率和折旧"),
    ("venue-rental", "场地租赁", "租赁", "footfall", (60, 85), (20, 40), "场地利用率和维护"),
    # ---------------- 中介
    ("real-estate-agent", "房产中介", "中介", "deal", (60, 85), (20, 40), "成交周期和佣金率"),
    ("matchmaking", "婚恋中介", "中介", "deal", (60, 85), (20, 40), "获客成本和退费"),
    ("headhunting", "猎头", "中介", "deal", (70, 90), (20, 40), "成单周期长"),
    # ---------------- 金融
    ("insurance-agent", "保险代理", "金融", "deal", (30, 50), (10, 25), "佣金率和续期"),
    ("loan-broker", "贷款中介", "金融", "deal", (50, 80), (20, 40), "合规是前提"),
    ("wealth-management", "财富管理", "金融", "knowledge", (50, 80), (15, 35), "持牌要求"),
    # ---------------- 环保能源
    ("recycling", "再生资源回收", "环保", "flow", (10, 25), (3, 8), "价格波动和合规"),
    ("environmental", "环保治理", "环保", "flow", (20, 35), (5, 12), "项目周期长"),
    ("solar-install", "光伏安装", "能源", "flow", (15, 30), (4, 12), "政策和并网"),
    ("ev-charging", "充电桩运营", "能源", "flow", (30, 50), (8, 20), "利用率和电价"),
    # ---------------- 安防
    ("security-install", "安防监控工程", "安防", "flow", (15, 30), (5, 12), "硬件占比高"),
    # ---------------- 维修
    ("appliance-repair", "家电维修", "维修", "knowledge", (50, 70), (15, 30), "配件和上门费"),
    ("phone-repair", "手机维修", "维修", "footfall", (40, 70), (10, 25), "配件价格透明"),
    # ---------------- 家政
    ("cleaning", "保洁", "家政", "deal", (30, 50), (8, 18), "人效和复购"),
    ("maternity", "月嫂服务", "家政", "deal", (40, 60), (12, 25), "人稀缺，培训成本"),
    ("nanny", "保姆中介", "家政", "deal", (30, 50), (10, 20), "匹配成功率和留存"),
    # ---------------- 养老
    ("elderly-care", "养老机构", "养老", "knowledge", (30, 50), (5, 15), "人工占比高，审批严格"),
    ("home-care", "居家养老", "养老", "deal", (30, 50), (8, 18), "服务半径和人效"),
    # ---------------- 其他
    ("fitness-equipment", "健身器材销售", "零售", "flow", (30, 50), (8, 18), "安装和售后成本"),
    ("postpartum", "月子中心", "母婴", "footfall", (50, 70), (15, 30), "入住率和护理成本"),
    ("wedding", "婚庆策划", "婚庆", "deal", (40, 60), (12, 25), "季节性和单场执行"),
    ("funeral", "殡葬服务", "殡葬", "deal", (40, 65), (15, 30), "地域性强，合规要求高"),
]


def build_rubric(entry: tuple) -> dict[str, Any]:
    key, name, group, profile, gross, net, note = entry
    indicator_names = {
        "gross_margin": ("毛利率", "%", gross),
        "net_margin": ("净利率", "%", net),
        "rent_ratio": ("租售比", "%", (10, 20)),
        "labour_ratio": ("人力成本占比", "%", (15, 30)),
        "inventory_days": ("库存周转天数", "天", (30, 60)),
        "receivable_days": ("应收账款周转天数", "天", (30, 90)),
    }
    # 指标方向很重要：
    #   毛利率/净利率 → 越高越好（偏低要关注）
    #   租金/人力占比 → 成本项，两端都可能有问题（太低可能不够用，太高挤压利润）
    #   周转天数       → 时间项，越短越好（偏慢要关注）
    COST_RATIOS = {"rent_ratio", "labour_ratio"}
    TIME_RATIOS = {"inventory_days", "receivable_days"}

    items = []
    for code in PROFILES[profile]:
        label, unit, (low, high) = indicator_names[code]
        if code in COST_RATIOS:
            ranges = [
                {"max": low, "level": "偏低", "severity": "注意"},
                {"max": high, "level": "正常", "severity": "正常"},
                {"max": None, "level": "偏高", "severity": "注意"},
            ]
            advice = {
                "偏低": f"{label}低于{group}常见区间。可能是投入不足（人手/场地），也可能是效率高，先确认。",
                "正常": f"{label}在{group}常见区间内。",
                "偏高": f"{label}高于{group}常见区间，直接挤压利润。这是{group}最常见的成本失控点。",
            }
        elif code in TIME_RATIOS:
            ranges = [
                {"max": low, "level": "偏快", "severity": "正常"},
                {"max": high, "level": "正常", "severity": "正常"},
                {"max": None, "level": "偏慢", "severity": "注意"},
            ]
            advice = {
                "偏快": f"{label}快于{group}常见区间，资金效率好。",
                "正常": f"{label}在{group}常见区间内。",
                "偏慢": f"{label}慢于{group}常见区间，意味着现金占用加重。",
            }
        else:
            ranges = [
                {"max": low, "level": "偏低", "severity": "注意"},
                {"max": high, "level": "正常", "severity": "正常"},
                {"max": None, "level": "偏高", "severity": "正常"},
            ]
            advice = {
                "偏低": f"{label}低于{group}常见区间。先确认统计口径（含不含税、算没算全成本）。",
                "正常": f"{label}在{group}常见区间内。",
                "偏高": f"{label}高于{group}常见区间。注意高{label}如果是靠低周转换来的，未必是好事。",
            }
        items.append({
            "key": code,
            "name": label,
            "unit": unit,
            "aliases": [label],
            "kind": "range",
            "ranges": ranges,
            "advice": advice,
        })
    return {
        "id": f"industry-{key}",
        "title": f"{group} · {name}",
        "kind": "business",
        "tier": "general",
        "source": (
            f"参考{group}行业的常见经营区间经验值，不是官方统计。"
            f"同一指标在不同城市、规模、客群下差异很大——{note}。"
        ),
        "disclaimer": (
            "本表只按你填的数字对照常见区间，不构成经营建议。"
            "区间是经验值，请用自己过去 6-12 个月的实际情况校准后再参考。"
        ),
        "items": items,
    }


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="从行业参数表生成 rubric")
    parser.add_argument("--list", action="store_true", help="列出所有行业")
    parser.add_argument("--write", action="store_true", help="生成 JSON 到 rubrics/industry/")
    parser.add_argument("--version", action="version", version=f"gen_industry_rubrics {VERSION}")
    args = parser.parse_args(argv)

    if args.list:
        groups: dict[str, list[str]] = {}
        for entry in INDUSTRIES:
            groups.setdefault(entry[2], []).append(entry[1])
        print(f"共 {len(INDUSTRIES)} 个行业，{len(groups)} 个分组：\n")
        for group, names in groups.items():
            print(f"{group}（{len(names)}）：{'、'.join(names)}")
        return 0

    if args.write:
        RUBRIC_DIR.mkdir(parents=True, exist_ok=True)
        written = 0
        for entry in INDUSTRIES:
            rubric = build_rubric(entry)
            target = RUBRIC_DIR / f"{rubric['id']}.json"
            target.write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            written += 1
        print(f"已生成 {written} 个行业 rubric -> {RUBRIC_DIR}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
