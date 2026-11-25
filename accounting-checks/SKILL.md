---
name: accounting-checks
description: Check whether a set of books actually balances — the three financial statements tie out (assets = liabilities + equity, retained earnings roll-forward, cash on the cash-flow statement vs cash on the balance sheet), the chart of accounts rolls forward (opening + debit − credit = closing), vouchers are internally consistent (debit-credit balance, period cutoff, numbering gaps, empty summaries), bank transactions match book records one-to-many, and financial ratios compute. Use when given balance sheet / income statement / trial balance / voucher / bank statement data and asked 平不平 / 勾稽 / 对不对得上 / 报表核对 / 查账 / 勾银行流水 / 财务比率 before filing, audit, or month-end close. Pure arithmetic and rule checks only; it reports discrepancies and never advises on tax treatment or business judgement.
license: MIT
---

# 会计勾稽检查

**只回答一个问题：这套账，平不平？**

五个模块，全是会计恒等式、规则和算法。它不判断业务实质，不评估税务处理，不给筹划建议。

| 模块 | 回答什么 | 命令 |
|---|---|---|
| 报表勾稽 | 三张表对得上吗 | `statements.py check -i 报表.json` |
| 报表重算 | 报表是不是由科目余额算出来的 | `recalc.py check -i 报表.json` |
| 凭证合规 | 凭证本身有没有毛病 | `vouchers.py check -i 凭证.json` |
| 科目余额表 | 期初+借−贷=期末吗 | `ledger.py check -i 余额表.json` |
| 银行流水 | 一笔账对应哪几笔流水 | `bank.py match -i 流水.json` |
| 财务比率 | 各项比率是多少 | `ratios.py calc -i 报表.json` |
| 折旧 | 四种方法下每期提多少 | `depreciation.py calc -i 资产.json` |
| 存货计价 | 三种方法下成本差多少 | `inventory.py calc -i 收发存.json` |
| 约当产量 | 完工和在产各摊多少成本 | `equivalent_units.py calc -i 成本.json` |
| 坏账准备 | 按账龄该提多少 | `bad_debt.py calc -i 应收.json` |

每个都有 `demo` 子命令，不用准备数据就能跑（共十个模块）。

```bash
python scripts/statements.py demo
python scripts/vouchers.py demo
python scripts/ledger.py demo
python scripts/bank.py demo
python scripts/ratios.py demo
```

## 为什么值得做

手工核这几样，最容易漏的是：

- 资产 = 负债 + 所有者权益，差了 1 分钱也要翻半天
- 未分配利润：期初 + 净利润 − 分红 ± 调整，链条断在哪一步
- 科目余额表：某个科目的期末对不对，靠手算容易错
- 银行流水：一笔 10,000 的应收，可能是 3,000 + 2,000 + 5,000 三笔凑的
- 凭证：借贷不平、跨期、跳号，翻几百张找不出来

这些都是**确定的算术**，机器算比人快，而且不会累。


## 科目余额表勾稽

```bash
python scripts/ledger.py check -i 科目余额表.json
```

| 检查 | 关系式 |
|---|---|
| 单科目滚算 | 借方科目：期初 + 借 − 贷 = 期末；贷方科目镜像 |
| 期初余额合计 | 借方余额合计 = 贷方余额合计 |
| 本期发生额 | 借方合计 = 贷方合计 |
| 期末余额合计 | 借方余额合计 = 贷方余额合计 |

单科目只检查滚算关系；「发生额平衡」是**全表恒等式**，必须用完整的科目集才成立。

## 银行流水一对多匹配

```bash
python scripts/bank.py match -i 流水.json
```

一笔账面应收 10,000，银行流水是三笔 3,000 + 2,000 + 5,000。工具做子集和搜索。

**两轮匹配**（重要）：

1. **先做一对一**：单笔金额能对上的，先配掉
2. **再做组合**：剩下的记录才做组合搜索

为什么分两轮：如果直接组合搜索，一笔 6,800 的单笔流水可能被别的目标的组合抢走，导致真正对应它的记录反而配不上。

容差用于覆盖手续费、利息差额，默认 0（精确匹配）。

## 财务比率

```bash
python scripts/ratios.py calc -i 报表.json
```

算九个比率：流动、速动、资产负债率、毛利率、净利率、ROE、ROA、应收周转率、存货周转率。

**「通用参考」不是行业标准。** 零售业流动比率 1.0 可能正常，重资产制造业要 2.0 以上。输出只标「偏离」，不下结论。缺数据会显示 `—`，不会当成通过。

## 五个模块共同的边界

- 只做算术和规则，不判断业务
- 缺数据标「数据不足」，不当成通过
- 容差默认 0.01 元（会计到分）
- 红字、负数、负权益都是合法数据，不会被误伤


## 固定资产折旧

```bash
python scripts/depreciation.py calc -i 资产.json
python scripts/depreciation.py demo
```

四种方法：年限平均、工作量、双倍余额递减、年数总和。

**计提规则**（《企业会计准则第 4 号》惯例）：
- 当月增加的固定资产，当月不提，**下月起计提**
- 当月减少的，**当月照提**，下月起停提

中途处置时，处置当月仍计提，之后停止。

## 存货计价

```bash
python scripts/inventory.py calc -i 收发存.json
python scripts/inventory.py demo
```

三种方法：先进先出、月末一次加权平均、移动加权平均。

同样一批收发，三种方法会给出三个不同的发出成本——这是正常的，
选哪种取决于企业会计政策，工具只负责算。

## 约当产量成本核算

```bash
python scripts/equivalent_units.py calc -i 成本.json
python scripts/equivalent_units.py demo
```

加权平均法（含期初）：

```
材料约当产量 = 完工 + 期末在产品 × 材料完工程度
加工约当产量 = 完工 + 期末在产品 × 加工完工程度
单位成本     = (期初成本 + 本期投入) ÷ 约当产量
```

材料一次投入时完工程度填 1.0。工具会校验「完工成本 + 在产品成本 = 总成本」。

## 坏账准备

```bash
python scripts/bad_debt.py calc -i 应收.json
python scripts/bad_debt.py demo
```

按账龄分组、乘计提比例、和账上已有准备对比，算出补提或冲回金额，并给出分录。

账龄标签是**左开右闭**：`91–180 天` 表示 91 到 180（含），避免「90–180」这种不知道 90 算哪档的写法。

## 报表独立重算

```bash
python scripts/recalc.py check -i 报表.json
python scripts/recalc.py demo
```

从科目余额表按标准公式**重新算一遍三大表**，和系统导出的报表对比。

用途：系统（用友/金蝶/任何 ERP）导出的报表，是不是真的由科目余额算出来的？
如果公式被改过、或者报表被手工调过，重算结果就对不上。

内置的是《企业会计准则》通用科目编码映射（1001/1122/2202…）。
企业用自定义编码时，用 `mapping` 字段覆盖，否则重算没意义。

## 责任边界（必读）

## 责任边界（必读）

这个工具**只做运算和核对**，不提供专业意见。

**它做的：**

- 加减乘除、恒等式校验
- 规则匹配（借贷平衡、要素完整、税率对应）
- 差异定位（哪张表、哪一栏、差多少）

**它不做的：**

- 会计判断——这笔业务该不该这么记
- 税务判断——这个处理合不合规
- 审计意见——报表是否公允
- 法律结论——合同是否有效

**后果承担：**

- 会计责任由单位负责人承担（《会计法》第四条：单位负责人对本单位的会计工作和会计资料的真实性、完整性负责）
- 纳税义务由纳税人承担（《税收征收管理法》）
- 审计意见只能由注册会计师出具（《注册会计师法》）

**工具的输出是「数据层面的核对结果」，不是专业意见。** 正式对外出具报告、申报纳税、接受审计前，必须由具备资质的注册会计师、税务师复核。

## 技术边界

- **只做恒等式校验**。它不知道你的业务，不知道这个数该不该这么记。
- **容差默认 0.01 元**。会计要精确到分，不用百分比。
- **缺项跳过，但会说明跳过了什么**。不会把"没数据"当成"通过"。
- **不判断对错，只判断平不平**。一套账完全平衡，也可能每一笔都是错的。
- 不做税务处理判断、不做筹划建议、不替代审计。

MIT。
