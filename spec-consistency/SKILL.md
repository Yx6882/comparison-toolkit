---
name: spec-consistency
description: Audit whether a set of product documents agree with each other — spec sheet, deck, quote, manual, README — and report every number that differs (512 Wh vs 500 Wh), every unit that drifts (6.0 kg vs 6000 g), every parameter that appears in one document and vanishes in another; also diff two revisions of the same spec (V1 vs V2) to show what actually changed and which changes the change log never recorded. Use when preparing a product launch, a bid or tender package, a customer-facing pack, a datasheet, or any release where the same specification is repeated across Word, PowerPoint, Excel and Markdown; also use when a sales deck and a spec sheet may disagree, when reviewing a CR/V revision, or when asked to 核对资料包 / 检查参数一致性 / 统一规格说法 / 校对报价单与规格书 / 对比两版改了什么 / 变更单有没有漏. Produces a severity-ranked report with the source sentence for every finding.
license: MIT
---

# Spec consistency

## 两类内容不算规格

| 情况 | 处理 | 为什么 |
|---|---|---|
| 变更记录表（表头含「原值/旧值/变更前」） | 整表跳过 | 记录的是历史，不是当前规格；当成规格会让变更影响把说明本身报成待整改项 |
| 近似写法（「内孔约 Ø32」「大约 32」） | 剥掉「约/大约/近」再取参数名 | 参数仍是「内孔」，修饰词不该进键 |

``内孔 Ø32±0.05`` 这种带公差的写法会正常解析成 内孔=32（公差忽略）。

## The problem this solves

Every document in a product pack can be individually correct while the *set* is
wrong. The spec sheet says 512 Wh, the deck says 500 Wh, the quote inherits the
old number, the website copies the deck. Nobody re-reads all five before launch,
and the customer notices first.

This skill audits the **set**, not the document. It extracts every
`parameter: value unit` pair, lines them up across files and formats, and reports
where they contradict each other.

## When to use it

- a product launch or a customer-facing pack (spec + deck + quote + manual)
- a bid / tender package, where a wrong number is disqualifying
- after a spec change, to find every copy that has not caught up
- a recurring CI gate on the docs folder
- before sending anything to a customer, distributor or reviewer

Do **not** use it for: one document, prose quality, or design review. For a
single document there is nothing to cross-check.

## Workflow

1. **Collect** — put the pack in one folder. Supported: `.docx`, `.pptx`,
   `.xlsx`, `.md`, `.txt`, `.csv`. Subfolders are scanned; `.git`,
   `node_modules`, `reports` are skipped.
2. **Extract** — the script pulls `参数：值 单位` pairs from paragraphs, slides,
   speaker notes, tables and spreadsheets. Two table layouts are understood:
   key-value (`参数 | 规格`) and wide (`型号 | 电池容量 | 单价`).
3. **Compare** — three checks, in this order:
   - **cross-document**: the same parameter has different values in different files
   - **internal**: the same parameter has different values *within* one file
   - **coverage**: a parameter appears in only one file, so it cannot be cross-checked
4. **Rank** — `high` = values genuinely differ; `medium` = axes do not match or a
   single file contradicts itself; `low` = unit style drift or coverage gap.
5. **Judge** — every finding carries the source sentence. Check the context
   before declaring a real contradiction: a quote with two SKUs legitimately
   holds two capacities.
6. **Report** — `spec-consistency.md` for humans, `.json` for CI. Exit code 1
   with `--fail-on high`.

```bash
python scripts/spec_audit.py demo                      # build a contradictory pack, audit it
python scripts/spec_audit.py scan ./product-material -o reports
python scripts/spec_audit.py scan ./material --fail-on high   # CI gate
```

## Version comparison — "what changed between V1 and V2?"

Two input shapes, same command:

```bash
# two revisions living in two folders (the usual real-project shape)
python scripts/spec_audit.py versions \
  --from-dir ./pkg_v1 --to-dir ./pkg_v2 \
  --changelog ./pkg_v2/11_变更单_v1到v2.md -o reports

# one table with version columns: | 项目 | V1 | V2 |
python scripts/spec_audit.py versions -d ./docs --from V1 --to V2
```

It answers three questions, in this order of importance:

1. **which parameters changed** — with old value, new value and the delta
2. **which changes the change log never mentions** — the gap that ships as a surprise
3. which parameters appeared or vanished (hidden by default, `--show-added`)

Rules that keep it honest: table values beat prose values (a spec table is
normative, a paragraph is discussion); a unit difference that converts (`6200 g`
vs `6.2 kg`) is not a change; and the comparison never invents a parameter that
appears in neither revision.

What it still cannot do: read an arrow written in prose (`内孔 Ø32→Ø36`). If the
revision is only described in sentences, add a small comparison table to the doc
first — that is also the table a reviewer wants anyway.

## What "consistent" means here

A value is consistent when it converts to the same base unit within tolerance
(default 0.5%). `6.2 kg` and `6200 g` agree. `6.0 kg` and `6.2 kg` do not.
`45 分钟` and `45 min` agree and are reported only as a unit-style note.

A value is **not** comparable when the dimensions differ — `%` against `元`,
`W` against `Wh`. That is a `medium` finding: the parameter name is doing double
duty and will confuse readers, not just this script.

## The human part (do not skip it)

The extractor is heuristic. It will produce:

- **false positives** when one file legitimately holds several SKUs — detect by
  "same document, several values", and fix by putting the model name in the
  parameter (`PX-200 电池容量`) or in the table header
- **false negatives** when the value lives in a chart, an image, a rendered PDF,
  or prose without a unit
- **synonym misses** when two teams call the same thing differently — extend
  `SYNONYMS` in the script, and treat an unexpectedly `low` finding as a naming
  problem, not a data problem

Your job as the agent: read the context column, decide which value is the truth,
and propose the edit list. Do not silently pick the majority value — the spec
sheet is usually authoritative even when the deck is more numerous.

## Output contract

Always deliver:

| Item | Content |
|---|---|
| headline | how many documents, how many parameters, how many conflicts |
| conflicts | parameter, each value with its document, severity |
| truth source | which document should win for each conflict, and why |
| edit list | file → old string → new string, ready to apply |
| unverifiable | parameters seen in only one document, plus anything the extractor could not read |
| caveats | findings that are probably legitimate (multi-SKU), stated as such |

Never report a conflict without the source sentence. Never say "the documents
are inconsistent" without naming which value wins.

## Files

| Need | File |
|---|---|
| What counts as inconsistent, dimension by dimension | `references/consistency-rules.md` |
| How to run an audit, fix findings, and keep it fixed | `references/workflow.md` |
| The extractor | `scripts/spec_audit.py` |
| Chinese overview and demo output | `README.zh-CN.md` |
