"""编一个贴近真实复杂度的进项税场景：多税率 + 红字冲销 + 混合票种。

真实业务里红字发票（负数）很常见，工具如果直接跳过，合计就会错。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "cases" / "vat-red"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
(ROOT / "input").mkdir(parents=True, exist_ok=True)


def build() -> None:
    from openpyxl import Workbook

    # 凭证：按税率分组的进项税额
    wb = Workbook()
    ws = wb.active
    ws.title = "凭证明细"
    ws.append(["单位", "凭证编号", "总摘要", "分录摘要", "科目编码", "科目名称", "管理对象", "主辅标志", "借方金额"])
    for index, (rate, amount) in enumerate(
        [("13%税率", 1300), ("9%税率", 900), ("6%税率", 600), ("1%税率", 100)], start=1
    ):
        ws.append(["测试公司", f"记账凭证 {index}", "", "", "", "", rate, "主", amount])
    wb.save(ROOT / "input" / "凭证明细.xlsx")

    # 发票：含一张 13% 的红字发票（负数）
    wb = Workbook()
    ws = wb.active
    ws.title = "sheet1"
    ws.append([
        "序号", "是否勾选*", "数电发票号码", "发票代码", "发票号码", "开票日期*",
        "金额*", "票面税额*", "有效抵扣税额*", "购买方识别号*", "销售方纳税人名称", "票种*",
    ])
    rows = [
        ("1", "是", "2026-11-01", 10000, 1300, 1300, "供应商A", "数电发票（增值税专用发票）"),
        ("2", "是", "2026-11-02", 10000, 900, 900, "铁路", "数电发票（铁路电子客票）"),
        ("3", "是", "2026-11-03", 10000, 600, 600, "供应商C", "数电发票（增值税专用发票）"),
        ("4", "是", "2026-11-04", 10000, 100, 100, "供应商D", "数电发票（增值税专用发票）"),
        # 红字冲销：金额与税额都是负数
        ("5", "是", "2026-11-05", -384.62, -50, -50, "供应商A", "数电发票（增值税专用发票）"),
    ]
    for seq, selected, date, amount, tax, valid, seller, kind in rows:
        ws.append([seq, selected, "", "", "", date, amount, tax, valid, "", seller, kind])
    wb.save(ROOT / "input" / "发票.xlsx")

    (ROOT / "expected.json").write_text(
        json.dumps(
            {
                "name": "进项税 · 红字冲销（编造但贴近真实）",
                "tool": "ledger",
                "argv": ["--voucher", "{input}/凭证明细.xlsx", "--invoice", "{input}/发票.xlsx", "--out", "{out}", "--json"],
                "report": "{out}/vat-reconcile.json",
                "must_find": ["13%"],
                "must_not_report": ["9%", "6%", "1%"],
                "notes": (
                    "凭证 13% 是 1300，发票 13% 是 1300 + (-50 红字) = 1250，应报差 50。"
                    "如果工具跳过负数发票，13% 就会被判成一致——那是漏报。"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("vat-red case built")


build()
print("预期：13% 差额 +50.00（凭证 1300 vs 发票 1250），其余税率一致")
