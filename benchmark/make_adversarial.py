"""生成对抗性 case —— 专测「看起来像问题、其实是正常的」。

真实场景里让人放弃工具的不是漏报，是天天报些没用的。这三个 case 都期望
「一条都不该报」或「只报该报的那一条」。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_csv(path: Path, rows: list[tuple[str, ...]], header: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow(row)


def write_case(slug: str, expected: dict, files: dict[str, str]) -> None:
    case_dir = ROOT / slug
    input_dir = case_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (input_dir / name).write_text(content, encoding="utf-8")
    (case_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{slug}: {len(files)} 个输入文件")


# ---------------------------------------------------------------- 1. 行序不同
shuffle_dir = ROOT / "adversarial-order"
(shuffle_dir / "input").mkdir(parents=True, exist_ok=True)
header = ["物料号", "名称", "单价"]
write_csv(shuffle_dir / "input" / "旧.csv", [
    ("M-1", "电源", "12000"), ("M-2", "导线", "500"), ("M-3", "磁芯", "850"),
], header)
write_csv(shuffle_dir / "input" / "新.csv", [
    ("M-3", "磁芯", "850"), ("M-1", "电源", "12000"), ("M-2", "导线", "500"),
], header)
(shuffle_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "对抗 · 行序打乱不算差异",
            "tool": "reconcile",
            "argv": ["run", "{input}/旧.csv", "{input}/新.csv", "--key", "物料号", "-o", "{out}"],
            "report": "{out}/旧_vs_新.json",
            "must_find": [],
            "must_not_report": [],
            "expect_empty": True,
            "notes": "三行数据完全相同，只是顺序不同；按主键匹配就不该报任何差异",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("adversarial-order: 2 个输入文件")


# ---------------------------------------------------------------- 2. 编号相近
code_dir = ROOT / "adversarial-code"
(code_dir / "input").mkdir(parents=True, exist_ok=True)
write_csv(code_dir / "input" / "A.csv", [("M-1004", "绝缘支架", "120")], header)
write_csv(code_dir / "input" / "B.csv", [("M-1005", "接线端子", "35")], header)
(code_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "对抗 · 编号相近不是同一个物料",
            "tool": "reconcile",
            "argv": ["run", "{input}/A.csv", "{input}/B.csv", "--key", "物料号", "-o", "{out}"],
            "report": "{out}/A_vs_B.json",
            "must_find": ["M-1004|仅左侧存在", "M-1005|仅右侧存在"],
            "must_not_report": ["M-1004|单价"],
            "notes": "M-1004 和 M-1005 是两个物料，不能被模糊匹配成「修改」",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("adversarial-code: 2 个输入文件")


# ---------------------------------------------------------------- 3. 单位等价
unit_dir = ROOT / "adversarial-unit"
(unit_dir / "input").mkdir(parents=True, exist_ok=True)
(unit_dir / "input" / "规格书.md").write_text(
    "| 参数 | 规格 |\n|---|---|\n| 整机重量 | 6.2 kg |\n| 电池容量 | 512 Wh |\n", encoding="utf-8"
)
(unit_dir / "input" / "汇报.md").write_text(
    "- 整机重量：6200 g\n- 电池容量：512 Wh\n", encoding="utf-8"
)
(unit_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "对抗 · 单位换算等价不算冲突",
            "tool": "spec",
            "argv": ["scan", "-d", "{input}", "-o", "{out}"],
            "report": "{out}/spec-consistency.json",
            "must_find": [],
            "must_not_report": ["整机重量", "电池容量"],
            "expect_empty": True,
            "notes": "6.2 kg 与 6200 g 换算后相等，不应报 high 级冲突",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("adversarial-unit: 2 个输入文件")
print("done ->", ROOT)
