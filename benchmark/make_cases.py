"""生成 benchmark 的对照集（输入文件 + 标准答案）。

跑一次即可，产物提交到 cases/ 下。每个 case 都是手算可验证的小数据。
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def write_case(slug: str, expected: dict, files: dict[str, str | bytes]) -> None:
    case_dir = ROOT / slug
    input_dir = case_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = input_dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    (case_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{slug}: {len(files)} 个输入文件")


# ---------------------------------------------------------------- case 1
write_case(
    "product-spec",
    {
        "name": "产品资料包 · 跨文档冲突",
        "tool": "spec",
        "argv": ["scan", "-d", "{input}", "-o", "{out}"],
        "report": "{out}/spec-consistency.json",
        "must_find": ["电池容量", "满载续航"],
        "must_not_report": ["充电时长"],
        "notes": "充电时长只在一份文档出现，是覆盖缺口不是冲突；重量用 kg/g 两种写法但换算等价",
    },
    {
        "规格书.md": """# 产品规格

| 参数 | 规格 |
|---|---|
| 电池容量 | 512 Wh |
| 满载续航 | 45 分钟 |
| 充电时长 | 3 小时 |
| 整机重量 | 6.2 kg |
""",
        "汇报.md": """# 卖点

- 电池容量：500 Wh
- 满载续航：50 分钟
- 整机重量：6200 g
""",
        "报价.md": """| 项目 | 取值 |
|---|---|
| 电池容量 | 512 Wh |
| 整机重量 | 6.2 kg |
""",
    },
)


# ---------------------------------------------------------------- case 2
def build_vat(input_dir: Path) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "凭证明细"
    ws.append(["单位", "凭证编号", "总摘要", "分录摘要", "科目编码", "科目名称", "管理对象", "主辅标志", "借方金额"])
    for index, (rate, amount) in enumerate([("13%税率", 130), ("9%税率", 95), ("6%税率", 60)], start=1):
        ws.append(["测试公司", f"记账凭证 {index}", "", "", "", "", rate, "主", amount])
    wb.save(input_dir / "凭证明细.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    ws.append([
        "序号", "是否勾选*", "数电发票号码", "发票代码", "发票号码", "开票日期*",
        "金额*", "票面税额*", "有效抵扣税额*", "购买方识别号*", "销售方纳税人名称",
    ])
    ws.append(["1", "是", "", "", "", "2026-11-01", 1000, 130, 130, "", "供应商A"])
    ws.append(["2", "是", "", "", "", "2026-11-02", 1000, 90, 90, "", "供应商B"])
    ws.append(["3", "是", "", "", "", "2026-11-03", 1000, 60, 60, "", "供应商C"])
    ws.append(["4", "是", "", "", "", "2026-11-04", 1000, 83, 83, "", "供应商D"])
    wb.save(input_dir / "发票.xlsx")


vat_dir = ROOT / "vat"
(vat_dir / "input").mkdir(parents=True, exist_ok=True)
build_vat(vat_dir / "input")
(vat_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "进项税勾稽 · 税率差异与异常票",
            "tool": "ledger",
            "argv": ["--voucher", "{input}/凭证明细.xlsx", "--invoice", "{input}/发票.xlsx", "--out", "{out}", "--json"],
            "report": "{out}/vat-reconcile.json",
            "must_find": ["9%", "异常"],
            "must_not_report": ["13%", "6%"],
            "notes": "9% 差 5 元（凭证 95 vs 发票 90）；那张 8.3% 的发票应归为异常税率；13% 和 6% 两边完全一致",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("vat: 2 个输入文件")


# ---------------------------------------------------------------- case 3
def build_contract(input_dir: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("第一条 甲方委托乙方完成设备安装调试工作。")
    doc.add_paragraph("第二条 合同总金额为人民币 120,000 元，含税。")
    doc.add_paragraph("第三条 乙方应于 2026 年 12 月 31 日前完成交付。")
    doc.add_paragraph("第四条 质保期为验收合格后 12 个月。")
    doc.save(input_dir / "合同A.docx")

    doc = Document()
    doc.add_paragraph("第一条 甲方委托乙方完成设备安装、调试及培训工作。")
    doc.add_paragraph("第二条 合同总金额为人民币 135,000 元，含税。")
    doc.add_paragraph("第三条 乙方应于 2027 年 1 月 31 日前完成交付。")
    doc.add_paragraph("第四条 质保期为验收合格后 24 个月。")
    doc.add_paragraph("第五条 乙方逾期交付的，每日按合同总额的 0.5% 支付违约金。")
    doc.save(input_dir / "合同B.docx")


contract_dir = ROOT / "contract"
(contract_dir / "input").mkdir(parents=True, exist_ok=True)
build_contract(contract_dir / "input")
(contract_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "合同改版 · 金额/日期/条款变化",
            "tool": "reconcile",
            "argv": ["run", "{input}/合同A.docx", "{input}/合同B.docx", "-o", "{out}"],
            "report": "{out}/合同A_vs_合同B.json",
            "must_find": ["120000", "2026年12月31日", "第五条"],
            "must_not_report": [],
            "notes": "金额 12 万→13.5 万、交付日期推后一个月、新增违约金条款；三条都必须被抓到",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("contract: 2 个输入文件")


# ---------------------------------------------------------------- case 4
def build_multi(input_dir: Path) -> None:
    rows = {
        "报价A.csv": [("M-1001", "12000", "2"), ("M-1002", "500", "4")],
        "报价B.csv": [("M-1001", "12000", "2"), ("M-1002", "600", "4")],
        "报价C.csv": [("M-1001", "13500", "2"), ("M-1002", "700", "4")],
    }
    for name, data in rows.items():
        with (input_dir / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["物料号", "单价", "数量"])
            for row in data:
                writer.writerow(row)


multi_dir = ROOT / "multi-vote"
(multi_dir / "input").mkdir(parents=True, exist_ok=True)
build_multi(multi_dir / "input")
(multi_dir / "expected.json").write_text(
    json.dumps(
        {
            "name": "三方报价 · 多数与无共识",
            "tool": "multi",
            "argv": ["multi", "{input}/报价A.csv", "{input}/报价B.csv", "{input}/报价C.csv", "--key", "物料号", "-o", "{out}"],
            "report": "{out}/reconcile-multi.xlsx",
            "must_find": ["M-1001|多数", "M-1002|无共识"],
            "must_not_report": ["数量|多数"],
            "notes": "M-1001 单价两票 12000、C 离群 13500；M-1002 单价 500/600/700 全不同",
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
print("multi-vote: 3 个输入文件")


# ---------------------------------------------------------------- case 5
write_case(
    "change-impact",
    {
        "name": "变更影响 · 谁还在用旧值",
        "tool": "impact",
        "argv": ["impact", "-d", "{input}", "--param", "内孔", "--old", "32", "--new", "36", "-o", "{out}"],
        "report": "{out}/change-impact.json",
        "must_find": ["汇报.md|stale"],
        "must_not_report": ["设计.md|stale"],
        "notes": "设计说明书写着新值 36，汇报备注还是旧值 32，供应商图纸是另一个型号 40（other）",
    },
    {
        "设计说明.md": "| 项目 | 取值 |\n|---|---|\n| 内孔 | Ø36 |\n| 环外径 | Ø112 |\n",
        "汇报备注.md": "- 内孔：Ø32（旧版数据，待更新）\n",
        "供应商图纸.md": "- 内孔 Ø40（客户定制版）\n",
    },
)
print("done ->", ROOT)
