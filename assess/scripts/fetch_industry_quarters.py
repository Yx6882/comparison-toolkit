#!/usr/bin/env python3
"""fetch_industry_quarters — 抓多个季报期，看行业毛利率的年内变化。

    python scripts/fetch_industry_quarters.py --write

**重要口径**：季报是**累计数**（Q3 = 前三季度合计），所以 Q3 的毛利率是
前三季度的综合，不是第三季度单季。用来看「年内走势」可以，不能当严格季节性。

产出 data/industry-quarters.json。
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
OUTPUT = DATA_DIR / "industry-quarters.json"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://data.eastmoney.com/",
}

QUARTERS: list[tuple[str, str]] = [
    ("2026-03-31", "2026Q1"),
    ("2026-06-30", "2026H1"),
    ("2026-09-30", "2026Q1-Q3"),
]
MIN_SAMPLE = 5


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


def fetch_period(report_date: str, page_size: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 1
    pages = 1
    while page <= pages:
        data = fetch({
            "reportName": "RPT_LICO_FN_CPD",
            "columns": "SECUCODE,SECURITY_NAME_ABBR,BOARD_NAME,XSMLL,TOTAL_OPERATE_INCOME",
            "pageNumber": str(page),
            "pageSize": str(page_size),
            "sortColumns": "SECURITY_CODE",
            "sortTypes": "1",
            "filter": f"(REPORTDATE='{report_date}')",
        })
        if not data:
            print(f"    第 {page} 页失败", file=sys.stderr)
            break
        result = data.get("result") or {}
        batch = result.get("data") or []
        pages = result.get("pages") or 1
        rows.extend(batch)
        page += 1
        time.sleep(0.4)
    return rows


def median_of(values: list[float]) -> float | None:
    if len(values) < MIN_SAMPLE:
        return None
    return round(statistics.median(values), 2)


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    parser = argparse.ArgumentParser(description="抓季报期，看年内毛利率走势")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--page-size", type=int, default=2000)
    parser.add_argument("--version", action="version", version=f"fetch_industry_quarters {VERSION}")
    args = parser.parse_args(argv)

    period_data: dict[str, dict[str, Any]] = {}
    for report_date, label in QUARTERS:
        print(f"抓取 {label}（{report_date}）...")
        rows = fetch_period(report_date, args.page_size)
        print(f"  {len(rows)} 家")
        buckets: dict[str, list[float]] = {}
        for row in rows:
            board = str(row.get("BOARD_NAME") or "").strip()
            gross = row.get("XSMLL")
            if not board or not isinstance(gross, (int, float)) or isinstance(gross, bool):
                continue
            buckets.setdefault(board, []).append(float(gross))
        industries: dict[str, float] = {}
        for board, values in buckets.items():
            med = median_of(values)
            if med is not None:
                industries[board] = med
        period_data[label] = {
            "report_date": report_date,
            "companies": len(rows),
            "industries": industries,
        }
        print(f"  有效行业 {len(industries)} 个")

    print("\n计算年内走势...")
    labels = [label for _date, label in QUARTERS]
    pattern: dict[str, Any] = {}
    boards = set()
    for label in labels:
        boards.update(period_data[label]["industries"].keys())
    for board in boards:
        series = []
        for label in labels:
            value = period_data[label]["industries"].get(board)
            if value is not None:
                series.append({"period": label, "median": value})
        if len(series) >= 2:
            first = series[0]["median"]
            last = series[-1]["median"]
            pattern[board] = {
                "series": series,
                "change": round(last - first, 2),
                "direction": "上升" if last > first + 0.5 else ("下降" if last < first - 0.5 else "持平"),
            }
    print(f"  有对比的行业 {len(pattern)} 个")

    rising = sum(1 for v in pattern.values() if v["direction"] == "上升")
    falling = sum(1 for v in pattern.values() if v["direction"] == "下降")
    print(f"  年内上升 {rising}，下降 {falling}")

    if args.dry_run:
        print("\n变化最大的 5 个：")
        for board, info in sorted(pattern.items(), key=lambda kv: -abs(kv[1]["change"]))[:5]:
            series = " → ".join(f"{s['median']}%" for s in info["series"])
            print(f"  {board:<16} {series}  {info['change']:+.2f}pp")
        return 0

    if not args.write:
        parser.print_help()
        return 1

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": VERSION,
        "source": "东方财富 RPT_LICO_FN_CPD",
        "periods": period_data,
        "pattern": pattern,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "caveat": (
            "季报是累计口径：Q3 的毛利率是前三季度综合，不是第三季度单季。"
            "所以这里的「年内走势」是被平均过的，看不出真正的淡旺季波动。"
        ),
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n已写入 {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
