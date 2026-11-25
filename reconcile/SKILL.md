---
name: reconcile
description: Compare any two files and report what differs — Excel/CSV tables by primary key, Word/PowerPoint/Markdown documents sentence by sentence, and mixed pairs by extracted key-value facts. Extracts a number or date change (120,000 → 135,000, 2026-12-31 → 2027-01-31, warranty 12 → 24 months), a renamed or reworded clause, a row that exists on only one side, and a price that moved in percentage points. Use when asked to 对照两个文件 / 找出两版差异 / 核对两张表 / 合同比对 / 文档对比 / 今日和昨日行情对比, when a revised document must be checked against the previous version, or when two exports of the same data should agree but might not. Works offline on xlsx, csv, docx, pptx, md and txt; produces a diffs spreadsheet plus a markdown report.
license: MIT
---

# Reconcile

## 会计场景

`references/accounting.md` 是给财务用的落地指南：三条硬规则（金额精确到分、日期精确到天、按影响金额排序）、能做什么、不能做什么、实操建议。

`examples/accounting/` 有两份可直接跑的示例表（应收明细 vs 客户对账单）。

**一句话边界**：能可靠地做「两张同结构明细表逐行比对」，不能做「银行流水自动勾对」（一对多匹配）。

## 改名 ≠ 删增

目录对照会按 **SHA-256** 把「仅在左侧」和「仅在右侧」的文件配对：

```
左：图A.png        右：图A_v2.png      → 内容一致，判定为「改名」
左：旧文件.txt     右：             → 真的删了
```

版本迭代加后缀（`_v2`、`_v3`）是常态，报成「删了一个、加了一个」会让人以为丢了文件。
一对改名在统计里按「1 对」算，不是 2 个变化。

## What it does

Two files in, a ranked difference list out. The engine is format-agnostic:

```
抽取 entities  →  对齐键（精确，再模糊）  →  比较属性（数字/日期优先，文本其次）  →  报告
```

- **tables** (`xlsx`, `csv`): rows become entities, the best primary-key column is
  picked automatically (`代码` / `物料号` / `编号` beat `名称`), every other column
  is compared cell by cell
- **documents** (`docx`, `pptx`, `md`, `txt`): paragraphs become entities, aligned
  by similarity (so a reworded clause still pairs up), then **numbers and dates
  are compared first** — that is where the real change usually is
- **mixed pairs**: a table against a document falls back on comparing strings and
  numbers extracted from both sides

## Why numbers come before wording

Two versions of a contract differ by one character and by 15,000 元. A pure text
diff buries the money in noise. So for documents the engine extracts every
number and date (`120,000`, `2026年12月31日`, `12 个月`) and reports those changes
as **high severity**, then reports reworded sentences separately as medium.

## Run it

```bash
python scripts/reconcile.py run 今日股价.xlsx 昨日股价.xlsx
python scripts/reconcile.py run 合同A.docx 合同B.docx -o out
python scripts/reconcile.py run 物料A.xlsx 物料B.xlsx --key 物料号 --fields 单价,数量

python scripts/reconcile.py demo      # builds three pairs (stocks, BOM, contracts) and runs them
```

Output: `reconcile-out/<left>_vs_<right>.md` and `reconcile-diff.xlsx` (a
filterable diff list plus a counts sheet).

Flags: `--key` override the auto-detected key column, `--fields` limit which
columns are compared, `--tolerance` relative numeric tolerance (default 1%).

## Comparison rules

| Situation | Behaviour |
|---|---|
| both sides numeric | compare in base units (`6.2kg` = `6200g`); relative delta |
| both sides percentages | compare in **percentage points** (`1.2%` vs `0.9%` → `-0.30pp`) |
| **version numbers** (`^2.0.0`, `6.13.0`) | compare as **text**, exactly — never as a percentage. `6.11.0` vs `6.13.0` is a release change, not a 0.3% drift |
| text vs text | similarity score; below 0.995 counts as a difference |
| document numbers/dates differ | high severity, regardless of wording similarity |
| key on one side only | `仅左侧` / `仅右侧`, with the row's other fields in the note |
| key reworded | fuzzy alignment at ≥82% similarity, listed separately so you can audit it |

## Output contract

| Item | Content |
|---|---|
| headline | mode (record/text), aligned pairs, fuzzy count, diff counts |
| value diffs | key, field, left, right, delta |
| text diffs | key, both texts, similarity |
| only-left / only-right | the entity and its attributes |
| key column chosen | named explicitly, so a wrong choice is visible |
| xlsx | same items, one row each, filterable, with severity |

Never claim "identical" without stating the key column used and how many pairs
were fuzzy-aligned — a 4/4 fuzzy match means every sentence was rewritten.


## 修复建议（patch / apply）—— 从「发现问题」到「给出改法」

```bash
python scripts/reconcile.py patch --diff step1/A_vs_B.json -o patches
python scripts/reconcile.py apply --patch patches/fix-patch.csv --target B.csv --key 物料号 -o fixed
```

patch 从差异 JSON 生成修复清单，按风险分三级：

| 风险 | 类型 | 处理方式 |
|---|---|---|
| 低 | 数值差异 | 可精确替换；pply 会校验原值 |
| 中 | 文本差异 | 只建议人工改；自动替换可能命中别处 |
| 高 | 新增/缺失项 | 补还是删要业务判断，不自动改 |

pply 的三道保险：

1. **只生成副本**（B.fixed.csv），原文件永远不动
2. **校验原值**：当前值 ≠ 补丁里的原值就跳过，防止改错行
3. **只接受 CSV**：xlsx/docx/pptx 直接拒绝——自动改格式文件容易破坏合并单元格和样式

修完再跑一次 
un，差异应当归零；不归零说明补丁方向反了（基准选错了）。

## 影响排序 —— 先看哪个


差异清单默认按类型分组，但人打开报告第一眼需要的不是「有 40 条」，而是「先看哪 3 条」。

有金额字段（金额/单价/总价/费用/成本/amount/price）时，报告会多一段**优先看这些**，按「差值 × 数量」降序。数量列缺失时按 1 计。

> 这只是**排序依据**，不是实际损失。单价和金额同时变化时，两者会各算一次（数据本身就冗余）。

## 多方对照（共识表决）—— 三份以上，找出谁不一样


```bash
python scripts/reconcile.py multi 报价A.csv 报价B.csv 报价C.csv --key 物料号
```

三份以上同一份数据放在一起，逐字段表决：

| 判定 | 含义 | 该做什么 |
|---|---|---|
| 完全一致 | 所有来源相同 | 可以放心 |
| 多数一致 | 两票对一票 | **先看离群的那个**——它可能是唯一对的 |
| 无共识 | 各说各话 | 最危险：说明这个参数的口径本身没统一，不是谁抄错 |
| 缺失 | 某个来源没这项 | 补数据，不要当成一致 |

单位、千分位、大小写会先归一化再表决（`6.2kg` = `6200 g`，`1,200` = `1200`）。

**多数不等于正确。** 两个来源一致可能是一起错；表决只告诉你「谁不一样」，不告诉你「谁对」。

## 媒体对照（图像 / 音频）—— 只比文件，不判身份


```bash
python scripts/reconcile.py run 截图_改前.png 截图_改后.png
python scripts/reconcile.py run 录音A.wav 录音B.wav
```

图像：格式、尺寸、色彩模式、感知哈希距离（0–64）、差异像素比例、差异区域 bbox。
音频：采样率、声道、位深、时长、RMS、峰值、静音比例，以及时长差和响度差。

**这不是身份识别。** 不做声纹比对、不做指纹特征点匹配、不做活体检测。
这些需要专门的模型和大规模标注数据，没有它们谈错误率就是编数字。
本工具能说的是「这两个文件像不像」，不能说的是「是不是同一个人」。

## Honest limits

- **images, PDF, binary**: not supported — convert to docx/xlsx/txt first
- **semantic equivalence**: `营收` vs `营业收入` are different keys unless you add a
  synonym or pre-normalise; the engine matches spelling, not meaning
- **free prose with no structure**: every sentence becomes a diff; that is
  correct but not useful — feed it structured sections
- **key choice matters most**: if the auto-picked key is wrong, pass `--key`
- **order**: rows are matched by key, so a re-sorted file is not a difference
  (that is the point)

## Files

| Need | File |
|---|---|
| The engine | `scripts/reconcile.py` |
| Tests (three demo pairs end-to-end) | `tests/test_reconcile.py` |
| Chinese overview | `README.zh-CN.md` |
