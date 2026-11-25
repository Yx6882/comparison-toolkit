---
name: assess
description: Compare one subject against a standard and produce a graded gap report — health markers against reference ranges (血脂/血糖/尿酸/血压), a person's skills against a job competency model (转行/晋升), or household spending against a 50/30/20 budget. Reads values typed in or extracted from a photo of a lab report, ranks what to fix first by gap × weight, and marks anything that warrants a doctor. Use when asked 体检报告怎么看 / 哪些指标要注意 / 我想转行做产品经理要补什么 / 我的开支结构健康吗 / 对照标准看看我差在哪. Ships editable JSON rubrics; the engine only does deterministic comparison, never diagnosis.
license: MIT
---

# Assess · 对象 vs 标准

## 开店测算（business.py）

```bash
python scripts/business.py payback -i 数据.json
python scripts/business.py demo
```

**全部是算术，数据由你填，工具不生成任何行业数据。**

### 四个能力

| 能力 | 算什么 |
|---|---|
| 回本周期 | 投资 ÷ 月净利 |
| 保本点 | 固定成本 ÷ (1 − 变动成本率) |
| 压力测试 | 收入 −10%/−20%/−30%、成本 +20%、两者叠加 |
| 城市系数 | 用城市收入相对全国的比值，估算租金/人力/客单价差异 |


### 另外五个子命令

| 命令 | 算什么 | 用途 |
|---|---|---|
| sens -i 数据.json | 敏感性排序 | 收入/变动成本/固定成本各 +10%，谁的净利影响最大 |
| seasonal -i 数据.json | 淡旺季全年现金流 | 12 个月系数，看谷底在哪、要备多少现金 |
| platform -i 数据.json | 平台抽成后的真实利润 | 含退货的推广费损失，很多人算错这一块 |
| labor -i 数据.json | 用工成本 | 工资 + 社保 + 公积金，实际比工资高 20%–35% |
| compare -i 数据.json | 多店对比 | 同一套指标横向比回本速度 |

**敏感性排序**能告诉你「先盯哪个」：

`
| 月收入     | +10% | +7,200 | +0.33 |
| 固定成本   | +10% | -5,000 | -0.23 |
| 变动成本率 | +10% | -4,800 | -0.22 |
→ 最敏感的是「月收入」
`

**平台抽成**最容易算错：退货订单的佣金一般能退，但**推广费不退**，物流还要付两趟。

`
未退货：售价 − 佣金 − 推广 − 成本 − 物流
退货：  −推广 − 物流×2
`

**用工成本**：5 人月薪 6000，实际成本 39,810（附加 32.7%）。费率各地差异大，必须用当地标准覆盖。

### 两个比回本周期更致命的判断

**1. 爬坡期现金流**

```
开业首月收入只有正常月份的四成，6 个月爬坡：

第 1 月  48,000  →  -21,200   累计 -21,200
第 2 月  62,400  →  -12,560   累计 -33,760
第 3 月  76,800  →   -3,920   累计 -37,680  ← 最低点
第 4 月  91,200  →   +4,720   累计 -32,960
...
需要额外准备 37,680 撑过最低点
```

**很多店不是不赚钱，是撑不到赚钱那天。** 回本周期算的是「多久拿回本金」，
爬坡期算的是「开业头几个月要垫多少」——后者才决定你能不能活到那一天。

**2. 租约够不够回本**

```
租约 18 个月，回本 22.7 个月 → 租约内回不了本，整个租期都在还本
租约 25 个月，回本 22.7 个月 → 只剩 2.3 个月赚钱，不够覆盖装修折旧
租约 60 个月，回本 22.7 个月 → 可盈利 37.3 个月
```

租约通常 3 年起，如果回本周期接近或超过租期，这个模型本身就不成立。

### 城市系数怎么用

```
输入：你所在城市的人均可支配收入（统计公报里能查到）
工具：按相对全国基准（39,218 元，2023 年）的比值，估算
      租金 ×比值^1.3 · 人力 ×比值^1.0 · 客单价 ×比值^0.8
```

**指数是经验假设，只用于「大致差多少」。** 真实租金请查当地商铺挂牌价，
人力请查当地社保基数和招聘薪资——这些是能查到的硬数据，别用估算值代替。

### 输入格式（JSON）

```json
{
  "investment": 500000,
  "monthly_revenue": 120000,
  "variable_cost_rate": 0.40,
  "monthly_fixed_cost": 50000,
  "ramp_months": 6,
  "ramp_start_ratio": 0.4,
  "lease_months": 36,
  "city_disposable_income": 60000
}
```

`ramp_months` / `lease_months` / `city_disposable_income` 是可选的——
不填就跳过对应分析，不会用默认值编造。

## A 股同行业真实数据

`rubrics/industry/` 里 **91 个行业**接了上市公司真实财务数据，
来源是东方财富公开接口（`RPT_LICO_FN_CPD`），**5818 家公司、2026 三季报**。

### 为什么用这个

原来的区间是经验值。接了真实数据后发现几处明显偏差：

| 行业 | 我们原来写的 | 上市公司真实中位数 |
|---|---|---|
| 软件开发 | 净利率 8%–18% | **−3.32%**（134 家） |
| IT服务 | 净利率 8%–18% | **−1.78%**（137 家） |
| 酒店餐饮 | 毛利率 55%–65% | **20.73%**（10 家） |
| 白酒 | — | 毛利率 **69.03%**（20 家） |

**软件行业整体是亏的。** 这跟我原来写的「8%–18% 正常」完全相反。

### 但两个数都留着

没有用真实数据替换经验区间，而是**并列显示**：

```
| 净利率 | -3 % | < 8 % | 偏低 |
...
## A 股同行业真实数据
来源：软件开发（2026 三季报，样本 134 家上市公司）
| 毛利率 | 44.24% | 26.72% – 62.91% |
| 净利率 | -3.32% | -28.87% – 4.06% |
```

因为**上市公司 ≠ 中小企业**：
- 上市公司规模大、规范、有融资渠道
- 一个 3 人的外包团队可能活得比上市公司滋润
- 餐饮、便利店、家政这类行业，上市公司样本又少又大

**看到两个数，自己判断**，比只给一个「标准答案」诚实。

### 怎么更新数据

```bash
python scripts/fetch_industry_data.py --write     # 重新抓（约 1 分钟）
python scripts/attach_market_data.py --write      # 重新接到规则上
```

爬虫带重试和节流。接口是东方财富的公开 JSON，不需要登录。

**注意**：`push2.eastmoney.com` 那个接口有反爬（连续请求会封），
所以用的是 `datacenter-web.eastmoney.com`，稳定得多。

## 行业规则库（123 个行业）

`rubrics/industry/` 下有 **123 个行业**的经营健康规则，覆盖 36 个分组：

| 分组 | 行业数 | 举例 |
|---|---|---|
| 餐饮 | 8 | 正餐、快餐、火锅、咖啡、茶饮、烘焙 |
| 零售 | 9 | 便利店、超市、服装、美妆、母婴、数码、药店 |
| 电商 | 4 | 平台店、独立站、直播带货、供货 |
| 教育 | 5 | 学科培训、兴趣班、成人培训、留学、在线 |
| 医疗 | 5 | 综合诊所、口腔、医美、康复、中医 |
| 美业 / 健身 | 8 | 美容、美发、美甲、皮肤管理、健身房、瑜伽 |
| 软件 / IT | 8 | SaaS、外包、小程序、游戏、运维、集成 |
| 制造 / 物流 / 贸易 | 14 | 机械、电子、服装、化工、快递、仓储、外贸 |
| 设计 / 咨询 / 广告 | 10 | 平面、室内、工业、UI、财税、法律、策划 |
| 其他 | 52 | 宠物、汽车、装修、旅游、酒店、中介、金融、养老… |

### 怎么用

```bash
python scripts/assess.py list                          # 看到全部
python scripts/assess.py run --rubric industry-cafe --kv "毛利率=65,净利率=10,租售比=18"
```

### 生成器

规则不是手写的 123 份，是**一张参数表生成的**：

```bash
python scripts/gen_industry_rubrics.py --list     # 看行业清单
python scripts/gen_industry_rubrics.py --write    # 重新生成全部
```

加一个行业 = 在 `INDUSTRIES` 里加一行：

```python
("my-industry", "我的行业", "分组", "footfall", (50, 65), (8, 15), "备注"),
```

四种指标组合（profile）按行业特性选：

| Profile | 指标 | 适合 |
|---|---|---|
| `footfall` | 毛利率、净利率、租售比、人力成本 | 吃客流的：餐饮、零售、美业、健身 |
| `knowledge` | 毛利率、净利率、人力成本、应收天数 | 卖知识的：软件、设计、咨询 |
| `flow` | 毛利率、净利率、库存天数、应收天数 | 走货的：制造、贸易、物流 |
| `deal` | 毛利率、净利率、人力成本、应收天数 | 靠成交的：中介、服务 |

### 指标方向（重要）

生成器按指标性质决定「哪个方向算问题」：

- **毛利率/净利率**：越高越好，偏低要关注
- **租金/人力占比**：成本项，**两端都可能有问题**（太低说明投入不足，太高挤压利润）
- **库存/应收天数**：时间项，越长越差

第一版把「人力成本 60%」判成了「较好」——那是把成本项当成了收益项。测试专门锁住了这个方向。

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
