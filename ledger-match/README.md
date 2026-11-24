# ledger-match · 对账与进项税勾稽

两个东西：

1. **金额组合**：给定一批金额和一笔目标，找出哪些金额加起来等于目标（子集和）。
2. **进项税勾稽**：把凭证里的进项税额和发票的税额按税率分组比对，找出差异、异常税率、可疑组合。

```bash
python scripts/ledger_match.py --target 2000 --items 500,500,500,500
python scripts/vat_reconcile.py --voucher 凭证明细.xlsx --invoice 发票.xlsx
python scripts/vat_export.py  --voucher 凭证明细.xlsx --invoice 发票.xlsx
python scripts/vat_mark.py    --voucher 凭证明细.xlsx --invoice 发票.xlsx
```

## 进项税三件套的分工

| 脚本 | 产出 | 用途 |
|---|---|---|
| `vat_reconcile` | 控制台报告 + JSON | 看差异 |
| `vat_export` | Excel 核对表（7 张工作表） | 给财务复核 |
| `vat_mark` | 在原表上标红黄 | 定位到具体行 |

`vat_mark` 会生成副本，**不动原文件**。

## 已知边界

- 只比对税额，不判断业务实质
- 红字发票按负值计入合计
- 税率用「税额 ÷ 金额绝对值」推断，非标准税率归为「异常」待人工判断
- 不替代会计师签署

MIT。
