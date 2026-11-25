"""编一个 impact 的误报陷阱：变更记录里提到旧值，不该算「待更新」。

真实业务里，变更记录表会写「内孔 原值 Ø32 → 新值 Ø36」。
如果工具看到 32 就当 stale，它会把变更说明本身报成待整改项——用户点开一看是废话，
以后就不信这个清单了。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases" / "impact-change-log"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
(ROOT / "input").mkdir(parents=True, exist_ok=True)

files = {
    # 已改好的规格书
    "设计说明.md": "| 项目 | 取值 |\n|---|---|\n| 内孔 | Ø36 |\n| 环外径 | Ø112 |\n",
    # 变更记录：同时出现旧值和新值，这是历史说明
    "变更记录.md": (
        "# 变更记录 V2\n\n"
        "| 项目 | 原值 | 新值 | 说明 |\n|---|---|---|---|\n"
        "| 内孔 | Ø32 | Ø36 | 配合新轴承，壁厚保持 |\n"
    ),
    # 真的还没改
    "供应商图纸.md": "- 内孔：Ø32\n- 其余同标准件\n",
    # 带公差的旧值
    "工艺卡.md": "- 内孔 Ø32±0.05，精车后铰孔\n",
    # 近似写法的旧值
    "装配说明.md": "- 内孔约 Ø32，按 H7 配合\n",
}
for name, content in files.items():
    (ROOT / "input" / name).write_text(content, encoding="utf-8")

expected = {
    "name": "变更影响 · 变更记录不该算待更新（编造陷阱）",
    "tool": "impact",
    "argv": ["impact", "-d", "{input}", "--param", "内孔", "--old", "32", "--new", "36", "-o", "{out}"],
    "report": "{out}/change-impact.json",
    "must_find": ["供应商图纸.md|stale", "工艺卡.md|stale"],
    "must_not_report": ["变更记录.md|stale"],
    "notes": (
        "变更记录表里同时写了旧值 Ø32 和新值 Ø36，那是历史说明，不该报 stale。"
        "真正的待更新项是供应商图纸（Ø32）、工艺卡（Ø32±0.05）、装配说明（约 Ø32）。"
    ),
}
(ROOT / "expected.json").write_text(json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("impact-change-log case built")
for name in files:
    print(f"  {name}")
