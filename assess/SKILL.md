---
name: assess
description: Compare one subject against a standard and produce a graded gap report — health markers against reference ranges (血脂/血糖/尿酸/血压), a person's skills against a job competency model (转行/晋升), or household spending against a 50/30/20 budget. Reads values typed in or extracted from a photo of a lab report, ranks what to fix first by gap × weight, and marks anything that warrants a doctor. Use when asked 体检报告怎么看 / 哪些指标要注意 / 我想转行做产品经理要补什么 / 我的开支结构健康吗 / 对照标准看看我差在哪. Ships editable JSON rubrics; the engine only does deterministic comparison, never diagnosis.
license: MIT
---

# Assess · 对象 vs 标准

## 内置规则库（按行业）

| Rubric | 行业 | 检查什么 |
|---|---|---|
| `health-metabolic` | 健康 | 血脂/血糖/尿酸/血压分级 |
| `career-pm` | 职场 | 产品经理能力对照 |
| `budget-50-30-20` | 个人财务 | 收入分配比例 |
| `shop-operating` | **开店** | 毛利率、租售比、库存周转、人力成本 |
| `invest-portfolio` | **投资** | 权益占比、集中度、现金垫、最大回撤 |
| `code-quality` | **编程** | 覆盖率、圈复杂度、重复率、文件规模 |
| `hiring-match` | **招聘** | 要求覆盖、必备技能、经验差距、技能重叠 |

加规则的代价是**一个 JSON 文件**，不用改代码：

```bash
python scripts/assess.py run --rubric shop-operating --kv "毛利率=28,租售比=18"
python scripts/assess.py run --rubric code-quality --kv "测试覆盖率=35,代码重复率=12"
```

每个 rubric 都写清了：
- 数据来源和适用范围
- 免责声明（不构成专业意见）
- 每档的具体建议

## 怎么加一个新行业

照着 `rubrics/shop-operating.json` 的结构写一份，放进 `rubrics/` 就能用。

三种对照类型：
- `range`：数值落在哪个区间（毛利率 28% → 一般）
- `target`：离目标差多少（覆盖率目标 80%）
- `ratio`：算个比率再对照

## 区间语义：左闭右开

`max` 是这一级的**上界**，落在界值上归**下一级**：

| 数值 | 分级 | 为什么 |
|---|---|---|
| TC 5.19 | 合适 | < 5.2 |
| TC 5.2 | **边缘升高** | 指南写的是「<5.2 合适」，5.2 已进入下一档 |
| TC 6.2 | 升高 | 已到「升高」的下界 |

这与临床指南的写法一致（"TC <5.2 mmol/L 为合适水平，5.2–6.2 为边缘升高"）。参考栏显示 `< 5.2` 而不是 `≤ 5.2`。

边界值是这个工具最容易被信任错的地方——**差 0.01 就换一个分级**，所以用 `>=` 而不是 `>`。

## The other half of reconciliation

`reconcile` compares two observations. This one compares **one subject against a
reference system** — a lab range, a competency model, a budget ratio. Same
skeleton, different question:

```
读取对象（数值 / 自评分 / 金额）
   → 找到对应基准（区间 / 目标 / 比例）
      → 分级 + 差距 + 权重
         → 排序：先补什么
```

## Three layers (and why)

| Layer | Where | Why it lives there |
|---|---|---|
| **数据层** | `rubrics/*.json` | reference ranges, targets, weights, source, advice text — editable without touching code |
| **逻辑层** | `scripts/assess.py` | classification, gap, priority; deterministic and testable |
| **交互层** | the agent | natural language in, photo reading, report explanation |

Because the rubric is data, a new scenario is **a JSON file, not a program**.

## Run it

```bash
python scripts/assess.py list
python scripts/assess.py run --rubric health-metabolic --kv "总胆固醇=6.42,甘油三酯=2.85,收缩压=142"
python scripts/assess.py run --rubric career-pm --input self.json
python scripts/assess.py run --rubric budget-50-30-20 --kv "必要支出=8200,生活享受=4300,储蓄投资=2500,收入=15000"
python scripts/assess.py demo
```

Output: a markdown verdict + table, and `assess-<id>.xlsx` with colour-coded rows
(green normal / yellow watch / orange concern / red see-a-doctor).

## Reading a photo

No OCR dependency is needed: **hand the image to the multimodal model**, have it
transcribe the rows, then run the engine on the transcribed numbers.

```
1. user sends 化验单.jpg
2. you read: 项目 / 结果 / 单位 / 参考范围
3. write {"总胆固醇": 6.42, "甘油三酯": 2.85, "收缩压": 142}
4. python scripts/assess.py run --rubric health-metabolic --input values.json
5. report the verdict, then hand the image + report to a doctor
```

Always show the transcribed numbers back to the user **before** interpreting —
a misread digit is the main failure mode of this path.

## Adding a scenario

Create `rubrics/<id>.json`:

```jsonc
{
  "id": "career-pm", "title": "...", "kind": "career",
  "source": "...", "disclaimer": "...",
  "items": [
    {"key": "需求分析", "name": "需求分析与优先级", "kind": "target",
     "target": 4, "direction": "higher_better", "weight": 0.22,
     "advice": {"短板": "...", "明显不足": "...", "略低": "...", "达标": "..."}}
  ]
}
```

Three `kind`s exist:

| kind | compares | used by |
|---|---|---|
| `range` | value against ascending `max` steps | lab markers, thresholds |
| `target` | value or score against a goal | skills, capability self-assessment |
| `ratio` | value ÷ `denominator` against a percentage goal | budget structure, allocation |

## Safety boundary — read this before shipping any rubric

- **health**: the rubric only grades against published cut-offs and says when to
  see a doctor. It never diagnoses, never names a drug, never says "you have X".
  Every health report ships with the disclaimer and the rubric's source.
- **policy / benefits (社保、个税、补贴)**: do **not** encode. Regional, time-sensitive,
  and a wrong answer costs the user money. Give a "go verify here" checklist instead.
- **money**: a ratio is a starting point, not a standard. High-rent cities
  legitimately exceed 50% necessities — the rubric says so in its own disclaimer.
- **career**: scores are self-reported. Say so, and ask for evidence (a portfolio
  piece) before treating a score as fact.

## Output contract

| Item | Content |
|---|---|
| verdict | one line: within range / needs attention / see a doctor |
| table | indicator, value, reference, level, advice |
| missing | indicators not provided, so the reader knows the gap |
| priority | for non-health rubrics: ranked by gap × weight |
| source + disclaimer | always, never omitted |

Never output a health verdict without the disclaimer and the source line.
