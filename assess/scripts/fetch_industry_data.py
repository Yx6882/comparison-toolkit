#!/usr/bin/env python3
"""fetch_industry_data — 抓 A 股上市公司数据，按行业统计真实财务分布。

    python scripts/fetch_industry_data.py --write
    python scripts/fetch_industry_data.py --dry-run

数据来源：东方财富 datacenter 公开接口 RPT_LICO_FN_CPD
  · BOARD_NAME            申万二级行业（如「银行Ⅱ」「白酒Ⅱ」「超市」）
  · XSMLL                 销售毛利率（%）
  · TOTAL_OPERATE_INCOME  营业总收入
  · PARENT_NETPROFIT      归母净利润（用它/营收算净利率）

全市场约 5800 家公司，3 页取完。产出 data/industry-financials.json。

口径：上市公司。餐饮、便利店、家政这类以小微为主的行业，上市公司样本少且规模大，
代表性有限——文件里每条都带 sample 字段，样本数太少的不该当行业标准用。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Sequence

VERSION = "1.0.0"
BASE = "https://datacenter-web.eastmoney.com/api/data/v1/get"
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUTPUT = DATA_DIR / "industry-financials.json"
REPORT_DATE = "2026-09-30"
REPORT_LABEL = "2026 三季报"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}
MIN_SAMPLE = 3


def fetch(params: dict[str, str], retries: int = 3) -> dict[str, Any] | None:
    url = BASE + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            if attempt < retries:
                time.sleep(2.0 * (attempt + 1))
    return None


def summarize(values: list[float]) -> dict[str, float] | None:
    if len(values) < MIN_SAMPLE:
        return None
    values = sorted(values)
    n = len(values)

    def pct(p: float) -> float:
        index = (n - 1) * p
        low = int(index)
        high = min(low + 1, n - 1)
        return values[low] + (values[high] - values[low]) * (index - low)

    return {
        "count": n,
        "median": round(statistics.median(values), 2),
        "p25": round(pct(0.25), 2),
        "p75": round(pct(0.75), 2),
        "min": round(values[0], 2),
        "max": round(values[-1], 2),
    }


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="抓取上市公司财务并按行业统计")
    parser.add_argument("--write", action="store_true", help="写入 data/industry-financials.json")
    parser.add_argument("--dry-run", action="store_true", help="只抓不写")
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--version", action="version", version=f"fetch_industry_data {VERSION}")
    args = parser.parse_args(argv)

    print(f"抓取 {REPORT_LABEL} 全市场数据...")
    rows: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages:
        data = fetch({
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECUCODE,SECURITY_NAME_ABBR,BOARD_NAME,XSMLL,"
                       "TOTAL_OPERATE_INCOME,PARENT_NETPROFIT",
            "pageNumber": str(page),
            "pageSize": str(args.page_size),
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "filter": f"(REPORTDATE='{REPORT_DATE}')",
        })
        if not data:
            print(f"  第 {page} 页失败", file=sys.stderr)
            break
        result = data.get("result") or {}
        batch = result.get("data") or []
        pages = result.get("pages") or 1
        rows.extend(batch)
        print(f"  第 {page}/{pages} 页：{len(batch)} 条（累计 {len(rows)}）")
        page += 1
        time.sleep(0.5)

    if not rows:
        print("error: 没抓到数据", file=sys.stderr)
        return 1

    print(f"\n按行业汇总（样本 ≥ {MIN_SAMPLE}）...")
    buckets: dict[str, dict[str, list[float]]] = {}
    skipped = 0
    for row in rows:
        board = str(row.get("BOARD_NAME") or "").strip()
        if not board:
            skipped += 1
            continue
        bucket = buckets.setdefault(board, {"gross_margin": [], "net_margin": []})
        gross = row.get("XSMLL")
        if isinstance(gross, (int, float)) and not isinstance(gross, bool):
            bucket["gross_margin"].append(float(gross))
        revenue = row.get("TOTAL_OPERATE_INCOME")
        profit = row.get("PARENT_NETPROFIT")
        if isinstance(revenue, (int, float)) and revenue and isinstance(profit, (int, float)):
            bucket["net_margin"].append(float(profit) / float(revenue) * 100)

    industries: dict[str, Any] = {}
    for board, metrics in buckets.items():
        payload: dict[str, Any] = {}
        for name, values in metrics.items():
            summary = summarize(values)
            if summary:
                payload[name] = summary
        if payload.get("gross_margin"):
            industries[board] = payload

    small = sum(1 for v in industries.values() if v["gross_margin"]["count"] < 5)
    print(f"  公司 {len(rows)} 家，无行业归属 {skipped} 家")
    print(f"  有效行业 {len(industries)} 个（其中样本 <5 的 {small} 个，参考价值有限）")

    if args.dry_run:
        print("\n样例（样本最多的 3 个行业）：")
        top = sorted(industries.items(), key=lambda kv: -kv[1]["gross_margin"]["count"])[:3]
        for name, data in top:
            gm = data["gross_margin"]
            print(f"  {name}: 样本 {gm['count']}，毛利率中位数 {gm['median']}%"
                  f"（{gm['p25']}%–{gm['p75']}%）")
        return 0

    if not args.write:
        parser.print_help()
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "source": "东方财富 datacenter 公开接口 RPT_LICO_FN_CPD",
        "report_period": REPORT_LABEL,
        "report_date": REPORT_DATE,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "company_count": len(rows),
        "industry_count": len(industries),
        "caveat": (
            "上市公司口径。餐饮、便利店、家政等以小微为主的行业，"
            "上市公司样本少且规模大，中位数不代表这些行业的中小企业。"
            "看 sample 字段，样本 <5 的行业请谨慎参考。"
        ),
        "metrics": {
            "gross_margin": "销售毛利率 XSMLL（%）",
            "net_margin": "归母净利润 / 营业总收入（%）",
        },
        "industries": industries,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入 {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
