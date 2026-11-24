"""编一个 assess 的边界值 case：所有值都正好压在界上。

真实体检报告里，数值恰好等于切点很常见（5.2、6.1、420），
而「界值归哪一级」是每个评分工具最容易搞错的地方。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases" / "assess-boundary"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
(ROOT / "input").mkdir(parents=True, exist_ok=True)

values = {
    "总胆固醇": 5.2,      # 指南：<5.2 合适，5.2–6.2 边缘升高 → 应归边缘升高
    "甘油三酯": 1.7,      # <1.7 合适 → 应归边缘升高
    "空腹血糖": 6.1,      # <6.1 正常 → 应归空腹血糖受损
    "血尿酸": 420,        # <420 正常 → 应归偏高
    "收缩压": 139,        # 120–139 正常高值（这一档本身是闭区间）
    "高密度脂蛋白": 1.0,  # 降低的界值是 1.0（方向相反）
}
(ROOT / "input" / "values.json").write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

(ROOT / "expected.json").write_text(
    json.dumps(
        {
            "name": "边界值 · 落在界上归下一级",
            "tool": "assess",
            "argv": ["run", "--rubric", "health-metabolic", "--input", "{input}/values.json", "-o", "{out}"],
            "report": "{out}/health-metabolic.json",
            "must_find": [
                "总胆固醇|边缘升高",
                "甘油三酯|边缘升高",
                "空腹血糖|空腹血糖受损",
                "血尿酸|偏高",
            ],
            "must_not_report": ["总胆固醇|合适", "空腹血糖|正常"],
            "notes": (
                "六个值全都压在切点上。指南写的是 TC <5.2 合适，所以 5.2 必须归「边缘升高」。"
                "如果工具用 value > upper 判定，5.2 会被判成「合适」——那是错的。"
            ),
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("assess-boundary case built")
for key, value in values.items():
    print(f"  {key} = {value}")
