"""编一个趋势的身份漂移陷阱：同一个差异，两期报告里的键写法不同。

真实场景：上期用 --key 物料号（M-1001），本期换了数据源，键变成小写 m-1001。
如果趋势按字符串精确比对身份，同一个持续两期的问题会被判成「上期解决了 + 本期新增」。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases" / "trend-identity"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
(ROOT / "input").mkdir(parents=True, exist_ok=True)

prev = {
    "version": "x",
    "mode": "record",
    "generated_at": "2026-10-01T09:00:00+08:00",
    "diffs": [
        {"kind": "value", "key": "M-1001", "field": "单价", "left": "12000", "right": "11800", "severity": "high"},
        {"kind": "value", "key": "M-1002", "field": "单价", "left": "500", "right": "520", "severity": "high"},
    ],
}
curr = {
    "version": "x",
    "mode": "record",
    "generated_at": "2026-11-01T09:00:00+08:00",
    "diffs": [
        # 同一个问题，只是键大小写变了
        {"kind": "value", "key": "m-1001", "field": "单价", "left": "12000", "right": "11500", "severity": "high"},
        # M-1002 已解决，不再出现
    ],
}
(ROOT / "input" / "上期.json").write_text(json.dumps(prev, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(ROOT / "input" / "本期.json").write_text(json.dumps(curr, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

expected = {
    "name": "趋势 · 键大小写不同仍是同一件事（编造陷阱）",
    "tool": "trend",
    "argv": ["run", "--prev", "{input}/上期.json", "--curr", "{input}/本期.json", "-o", "{out}"],
    "report": "{out}/trend.json",
    "must_find": ["持续 1", "已解决 1"],
    "must_not_report": ["新增 1"],
    "notes": (
        "上期 M-1001 单价差异，本期写成 m-1001 但仍是同一个物料。"
        "应判「持续 1（M-1001）+ 已解决 1（M-1002）」，不是「新增 1 + 已解决 2」。"
    ),
}
(ROOT / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("trend-identity case built")
