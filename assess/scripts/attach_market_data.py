#!/usr/bin/env python3
"""attach_market_data — 把上市公司真实财务数据接到行业规则上。

    python scripts/attach_market_data.py --report     # 只看匹配情况
    python scripts/attach_market_data.py --write      # 写进 rubric

做法：在 rubric 里加一个 `market_data` 字段，记录 A 股对应行业的
真实中位数和样本数。**不替换经验区间**，两个数并列显示——

因为上市公司和中小企业的差异可能很大（软件上市公司净利率 -3%，
而一个 3 人外包团队可能活得很滋润）。让用户看到两个数，自己判断。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parents[1]
RUBRIC_DIR = ROOT / "rubrics" / "industry"
MARKET_FILE = ROOT.parent / "data" / "industry-financials.json"
HISTORY_FILE = ROOT.parent / "data" / "industry-history.json"

# 我们的行业 key -> 东财（申万二级）行业名。没有对应关系的留空。
MAPPING: dict[str, str] = {
    # 餐饮
    "restaurant-full": "酒店餐饮",
    "restaurant-fast": "酒店餐饮",
    "restaurant-hotpot": "酒店餐饮",
    "cafe": "酒店餐饮",
    "tea-shop": "酒店餐饮",
    "bakery": "食品加工",
    "catering": "酒店餐饮",
    # 零售
    "convenience": "",
    "supermarket": "百货",
    "apparel-retail": "服装家纺",
    "cosmetics-retail": "化妆品",
    "baby-retail": "",
    "digital-retail": "",
    "home-retail": "家居用品",
    "pharmacy": "医药商业",
    # 电商
    "ecom-platform": "互联网电商",
    "ecom-standalone": "互联网电商",
    "ecom-live": "互联网电商",
    "ecom-supply": "互联网电商",
    # 教育
    "edu-academic": "教育",
    "edu-hobby": "教育",
    "edu-adult": "教育",
    "edu-study-abroad": "",
    "edu-online": "教育",
    # 医疗
    "clinic": "医疗服务",
    "dental": "医疗服务",
    "aesthetic-med": "医疗服务",
    "rehab": "医疗服务",
    "tcm": "中药Ⅱ",
    # 美业
    "beauty-salon": "医疗美容",
    "hair-salon": "",
    "nail-salon": "",
    "skin-care": "医疗美容",
    # 健身
    "gym": "",
    "yoga": "",
    "pt-studio": "",
    "swim": "",
    # 宠物
    "pet-shop": "",
    "pet-hospital": "",
    "pet-grooming": "",
    # 汽车
    "auto-repair": "汽车服务",
    "auto-beauty": "汽车服务",
    "auto-sales": "汽车经销商",
    "auto-rental": "汽车服务",
    # 装修
    "home-decoration": "装修装饰Ⅱ",
    "commercial-decoration": "装修装饰Ⅱ",
    "soft-furnishing": "家居用品",
    # 设计
    "graphic-design": "专业服务",
    "interior-design": "装修装饰Ⅱ",
    "industrial-design": "专业服务",
    "ui-ux": "软件开发",
    # 软件
    "saas": "软件开发",
    "software-outsourcing": "软件开发",
    "mini-program": "软件开发",
    "game-dev": "游戏Ⅱ",
    "app-dev": "软件开发",
    # IT
    "it-ops": "IT服务Ⅱ",
    "it-integration": "IT服务Ⅱ",
    "data-service": "IT服务Ⅱ",
    # 制造
    "machinery": "通用设备",
    "electronics": "半导体",
    "garment-making": "服装家纺",
    "food-processing": "食品加工",
    "chemical": "化学制品",
    "furniture-making": "家居用品",
    "packaging": "包装印刷",
    # 物流
    "express": "物流",
    "warehousing": "物流",
    "freight": "物流",
    "cold-chain": "物流",
    # 贸易
    "foreign-trade": "贸易Ⅱ",
    "wholesale": "贸易Ⅱ",
    "import": "贸易Ⅱ",
    # 农业
    "planting": "种植业",
    "breeding": "养殖业",
    "farm-processing": "农产品加工",
    # 建筑
    "construction": "房屋建设Ⅱ",
    "design-institute": "工程咨询服务",
    "supervision": "工程咨询服务",
    # 咨询
    "management-consulting": "专业服务",
    "tax-consulting": "专业服务",
    "legal": "专业服务",
    "hr-consulting": "专业服务",
    # 广告传媒
    "ad-planning": "广告营销",
    "ad-media": "广告营销",
    "content-creation": "影视院线",
    "self-media": "出版",
    "short-video": "影视院线",
    "live-stream": "互联网电商",
    "publishing": "出版",
    # 娱乐
    "ktv": "酒店餐饮",
    "escape-room": "游戏Ⅱ",
    "cinema": "影视院线",
    # 旅游
    "travel-agency": "旅游及景区",
    "homestay": "酒店餐饮",
    "scenic": "旅游及景区",
    # 酒店
    "hotel-economy": "酒店餐饮",
    "hotel-mid": "酒店餐饮",
    # 租赁
    "equipment-rental": "",
    "venue-rental": "",
    # 中介
    "real-estate-agent": "房地产服务",
    "matchmaking": "",
    "headhunting": "专业服务",
    # 金融
    "insurance-agent": "保险Ⅱ",
    "loan-broker": "",
    "wealth-management": "多元金融",
    # 环保能源
    "recycling": "环保设备Ⅱ",
    "environmental": "环境治理",
    "solar-install": "光伏设备",
    "ev-charging": "电网设备",
    # 安防
    "security-install": "安防设备",
    # 维修
    "appliance-repair": "家电零部件Ⅱ",
    "phone-repair": "消费电子",
    # 家政
    "cleaning": "",
    "maternity": "",
    "nanny": "",
    # 养老
    "elderly-care": "",
    "home-care": "",
    # 其他
    "fitness-equipment": "体育Ⅱ",
    "postpartum": "",
    "wedding": "",
    "funeral": "",
}


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="把真实财务数据接到行业规则")
    parser.add_argument("--report", action="store_true", help="只看匹配情况")
    parser.add_argument("--write", action="store_true", help="写进 rubric 文件")
    parser.add_argument("--version", action="version", version=f"attach_market_data {VERSION}")
    args = parser.parse_args(argv)

    if not MARKET_FILE.exists():
        print(f"error: 缺少 {MARKET_FILE}，先跑 fetch_industry_data.py --write", file=sys.stderr)
        return 1
    market = json.loads(MARKET_FILE.read_text(encoding="utf-8"))
    industries = market["industries"]
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else {}

    matched: list[tuple[str, str, dict]] = []
    unmatched_key: list[str] = []
    unmatched_board: list[str] = []
    for path in sorted(RUBRIC_DIR.glob("*.json")):
        rubric = json.loads(path.read_text(encoding="utf-8"))
        key = rubric["id"].removeprefix("industry-")
        board = MAPPING.get(key, "")
        if not board:
            unmatched_key.append(key)
            continue
        data = industries.get(board)
        if not data:
            unmatched_board.append(f"{key} -> {board}")
            continue
        matched.append((key, board, data))

    print(f"能对上真实数据的行业：{len(matched)}")
    print(f"无对应板块（本就没上市公司）：{len(unmatched_key)}")
    print(f"映射的板块不在数据里：{len(unmatched_board)}")
    print()
    print("样例（真实数据 vs 我们原来的区间）：")
    for key, board, data in matched[:8]:
        gm = data["gross_margin"]
        print(f"  {key:<22} -> {board:<12} 样本{gm['count']:>4} "
              f"真实毛利率 {gm['median']:>6.2f}%（P25-P75 {gm['p25']:.1f}–{gm['p75']:.1f}%）")

    if not args.write:
        return 0

    written = 0
    for path in sorted(RUBRIC_DIR.glob("*.json")):
        rubric = json.loads(path.read_text(encoding="utf-8"))
        key = rubric["id"].removeprefix("industry-")
        board = MAPPING.get(key, "")
        data = industries.get(board) if board else None
        if not data:
            rubric.pop("market_data", None)
        else:
            gm = data["gross_margin"]
            nm = data.get("net_margin") or {}
            rubric["market_data"] = {
                "board": board,
                "source": "东方财富 RPT_LICO_FN_CPD",
                "period": market["report_period"],
                "gross_margin": {
                    "median": gm["median"], "p25": gm["p25"], "p75": gm["p75"],
                    "count": gm["count"],
                },
                **({"net_margin": {
                    "median": nm["median"], "p25": nm["p25"], "p75": nm["p75"],
                    "count": nm["count"],
                }} if nm else {}),
                "caveat": (
                    "上市公司口径，规模和规范度都高于中小企业。"
                    "样本少或行业以小微为主时，这个数仅供参考，不代表你所在市场的常态。"
                ),
            }
            # 跨期趋势：毛利率在涨还是跌
            trend = (history.get("trend") or {}).get(board)
            if trend:
                rubric["market_data"]["trend"] = {
                    "series": trend["series"],
                    "change": trend["change"],
                    "direction": trend["direction"],
                }
            # 规模差异：大中小公司的毛利率差别
            scale = (
                ((history.get("periods") or {}).get("2026 三季报") or {}).get("by_scale") or {}
            ).get(board)
            if scale:
                rubric["market_data"]["by_scale"] = {
                    tier: info["median"] for tier, info in scale.items()
                }
        path.write_text(json.dumps(rubric, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written += 1
    print(f"\n已更新 {written} 个 rubric（其中 {len(matched)} 个带真实数据）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
