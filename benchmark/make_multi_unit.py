"""编一个多方表决的单位陷阱：三份报价，一份写「元」、两份写「千元」。

12000 元 = 12 千元 = 12 千元。如果表决前不归一化，三个值会被判成
「各说各话（无共识）」——而真实结论应该是「A 和 B 一致，C 离群」。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases" / "multi-unit"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
(ROOT / "input").mkdir(parents=True, exist_ok=True)

header = ["物料号", "单价", "单位", "数量"]
rows = {
    "报价A.csv": [("M-1001", "12000", "元", "2")],
    "报价B.csv": [("M-1001", "12", "千元", "2")],
    "报价C.csv": [("M-1001", "13", "千元", "2")],  # 13000 元，离群
}
for name, data in rows.items():
    with (ROOT / "input" / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(data)

expected = {
    "name": "多方表决 · 单位混用（元 vs 千元）",
    "tool": "multi",
    "argv": ["multi", "{input}/报价A.csv", "{input}/报价B.csv", "{input}/报价C.csv", "--key", "物料号", "-o", "{out}"],
    "report": "{out}/reconcile-multi.json",
    "must_find": ["M-1001|多数"],
    "must_not_report": ["M-1001|无共识"],
    "notes": (
        "A 报 12000 元、B 报 12 千元，两者相等；C 报 13 千元（=13000 元）应判离群。"
        "如果不看「单位」列，12000 / 12 / 13 三个数各不相同，会被误判成无共识。"
    ),
}
(ROOT / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("multi-unit case built")
for name, data in rows.items():
    print(f"  {name}: {data[0][1]} {data[0][2]}")
