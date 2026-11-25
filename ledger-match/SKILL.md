---
name: ledger-match
description: Explain a summary ledger with a detail ledger — find which combination of detail lines adds up to each total (2000 = 4×500), report totals with no explanation, totals with several possible explanations, and detail lines that were never used. Use when two spreadsheets will not reconcile, when a total must be traced back to its source invoices or orders, when asked 对账 / 这笔钱从哪来 / 明细怎么凑成总额 / 两张表对不上 / 总价和分项对不平, or before closing a month. Reads xlsx and csv amounts; reports ambiguity instead of guessing.
license: MIT
---

# Ledger match


## 责任边界

只做金额组合搜索和税额分组比对，**不判断税务处理是否合规**。

勾稽结果不能直接用于纳税申报，需经税务师复核。纳税义务由纳税人承担（《税收征收管理法》）。


## The question it answers

One sheet says `2000`. Another sheet says `500, 500, 500, 500`. Are they the
same money — and if so, which lines are "the source"?

The honest answer is a **set of candidate combinations**, because `2000` can also
be `1200 + 800`, or `1000 + 500 + 500`. So the tool returns candidates, prefers
the explanation with the fewest lines, and labels the ones where the evidence is
ambiguous.

## Three outcomes, and all three matter

| Outcome | Meaning | What to do |
|---|---|---|
| **唯一** | exactly one combination explains the total | accept it, and check the invoice numbers |
| **多解** | several combinations fit | you cannot decide from amounts alone — add date, customer, doc number |
| **无解** | nothing in the detail adds up to the total | missing detail row, wrong period, or a different currency/tax basis |

An `unmatched` total is the most valuable finding in the report. It is either a
missing voucher or a figure that was typed into the summary and never supported.

## How the match works

1. read both sheets, parse amounts (accepts `2,000.00`, `¥2000`, `(500)` = -500)
2. sort totals largest-first
3. for each total, search the **still-unused** detail lines for combinations
   that sum to it within tolerance (`--tolerance`, default 0.01)
4. take the combination with the fewest lines; keep up to two alternatives
5. report leftovers

A detail line can only be spent once. That constraint is what makes the output
an explanation rather than a list of coincidences — and it is also why shared
allocation (one invoice split across two customers) is reported as `无解`.

## VAT reconciliation — 凭证 vs 勾选发票（进项税勾稽）

财务月末最常做的一次对账：会计凭证里的进项税额，和勾选抵扣的发票清单，对不对得上。

```bash
# 1) 出报告（md + json）
python scripts/vat_reconcile.py --voucher 凭证明细.xlsx --invoice 勾选发票.xlsx --out vat-run

# 2) 出核对表（xlsx，7 个 sheet）
python scripts/vat_export.py --voucher 凭证明细.xlsx --invoice 勾选发票.xlsx --out vat-run

# 3) 在原始表格的副本上标红，交给做账人
python scripts/vat_mark.py --voucher 凭证明细.xlsx --invoice 勾选发票.xlsx --out vat-run
```

`vat_mark.py` 只生成副本（`*_已标注.xlsx`），不改原文件。标色规则：

| 颜色 | 含义 | 触发条件 |
|---|---|---|
| **红** | 确定异常 | 发票税额÷金额不在标准税率 1/3/5/6/9/13 上（±0.15 个百分点）；或凭证某税率在发票里完全没有对应 |
| **黄** | 待核实 | 某个税率差异的「金额候选」——税额合计恰好等于差额，但凭证侧没有发票号，不能直接归因 |

每行最后一列写「勾稽标记」说明原因；另附一个「勾稽标记说明」sheet。

**口径假设（必须先确认）**：凭证的「借方金额」= 进项税额；发票税率由「票面税额 ÷ 金额」推断。验证方法——如果某个税率两边分毫不差（例如 1% 完全一致），说明口径成立。

三个脚本共用 15 个离线测试（	ests/test_vat.py），fixture 是手算可验证的一组小数据：凭证 297.14 / 发票 373.00 / 总差 -75.86。

**做不到的事**：凭证侧通常只有税率和金额，没有发票号，所以只能对到税率级；按票种算的铁路票、行程单、通行费属「计算抵扣」，其比例天然不是标准税率，要单独看；差额征税、农产品收购也会让比例偏离标准值。

## Run it

```bash
python scripts/ledger_match.py demo

python scripts/ledger_match.py match \
  --summary ./汇总表.xlsx  --summary-col 总价 --summary-label 客户 \
  --detail  ./明细表.xlsx  --detail-col 金额 --detail-label 单号 \
  --tolerance 0.01
```

Columns may be a header name, a letter (`C`), or a 1-based index. Sheets can be
named with `--summary-sheet` / `--detail-sheet`. Output goes to
`ledger-report/ledger-match.md` and `.json`.

`--fail-on-unmatched` makes it a CI/period-close gate: exit 1 if any total has
no explanation.

## Limits — say these out loud before trusting a run

- **only positive amounts are matched.** Refunds, red-letter entries and netting
  need a separate pass.
- **tax basis must match.** Mixing 含税 and 不含税 produces nonsense; convert
  first, then reconcile.
- **allocation is not supported.** If one order is split across two totals, each
  total will report `无解`. Use a split column, or reconcile in the other direction.
- **combinatorics grow.** With hundreds of detail lines and deep combinations,
  the search is pruned by `--max-items` (default 12). If you hit that ceiling, raise
  necessity: filter by month, customer or account before matching.
- **it never invents a line.** If it cannot explain a total, it says so.

## Output contract

| Item | Content |
|---|---|
| headline | totals, explained amount and percentage, unique / ambiguous / unmatched counts |
| matches | total → the detail lines used, with row references |
| alternatives | for ambiguous totals, the other plausible combinations |
| unused | detail lines that no total claimed, with the sum |
| basis | tolerance, max combination depth, any filter applied |

Report the `unmatched` and `多解` items to the user explicitly. Do not present a
"97% explained" figure without naming the 3% that is unexplained — that 3% is
usually the reason the books do not close.
