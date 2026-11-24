---
name: compare-anything
description: One entry point for every kind of comparison — pick the right engine from the inputs and run it. Two files go to a document/table diff, two market commodities go to an equal-value exchange, a subject plus a rubric goes to a standards assessment. Use when the user says 对照 / 比较 / 核对 / 换多少 / 差在哪 without naming a tool, or when you are unsure which comparison engine fits. Enforces one contract across all three — every number traced to a source, every uncertain cell marked for human check, and no single-number answer where a range or a judgement queue belongs.
license: MIT
---

# Compare anything · 总入口

“对照万物”不是一个大程序，是**三种对照 + 一份共同的严谨性契约**。这个 skill 只做两件事：**选对引擎**，和**守住契约**。

## 路由表

| 你手上有什么 | 引擎 | 它回答 |
|---|---|---|
| 两个文件（xlsx / csv / docx / pptx / md / txt） | `reconcile` | 这两份哪里不一样 |
| 两个品种名（铜、铝、锌、铅、镍、螺纹钢、玉米、豆粕） | `exchange` | 一斤 A 换多少 B 才等值 |
| 一组指标 + 一个 `--rubric` | `assess` | 我对照标准差在哪、先补什么 |

```bash
python scripts/route.py which --left 合同A.docx --right 合同B.docx   # 只判断用哪个
python scripts/route.py run   --left 合同A.docx --right 合同B.docx
python scripts/route.py run   --left 铜 --right 铝 --quantity 1 --unit 斤
python scripts/route.py run   --rubric health-metabolic --kv "收缩压=142"
python scripts/route.py selftest
```

判断不出来时它会说“无法判断”，不会瞎猜。

## 严谨性契约（三个引擎都必须守）

| # | 契约 | reconcile 怎么落实 | exchange 怎么落实 | assess 怎么落实 |
|---|---|---|---|---|
| 1 | **结论可复算** | 打印对齐方式、主键列、模糊对数 | 打印公式和代入值 | 打印区间、目标、权重 |
| 2 | **数据有出处与时点** | 主键列、抽取段数、差异行位置 | 每行写来源 + 行情日期 | 每份 rubric 写来源 + 免责 |
| 3 | **不确定必须显式** | `⚠ 主键可能选错`、模糊匹配单列 | 逐行 `✅/⚠/❓` 核对状态 | `未提供` 项单列、`⚠ 仅分级不诊断` |
| 4 | **不给单一数字** | 差异清单而非“有错”结论 | 区间 + 敏感性 | 分级 + 优先级而非总分 |
| 5 | **不替代人** | 差异是待判断项 | 期货价≠成交价 | 不诊断、不开药 |

**任何一条做不到，就写“做不到”**，而不是含糊过去。

## 什么时候不该用它

- 图片、PDF、二进制 —— 先转格式
- 想让它**判定谁对谁错** —— 它只列差异和分级，判断权在人
- 政策 / 福利 / 法律条款 —— 地区与时效性太强，不该由工具下结论
- 没有基准的一次性闲聊 —— 没有参照系就没有对照

## 输出契约

不管走哪个引擎，回到用户面前时必须包含：

1. **结论一句话**（区间或分级，不是一个孤零零的数）
2. **依据**（公式 / 主键 / 区间 / 权重）
3. **不确定清单**（哪些必须人核对）
4. **来源与时间**
5. **建议的下一步**（去查什么、找谁确认）

## 三个引擎在哪

| 引擎 | 目录 | 能力 |
|---|---|---|
| `reconcile` | `../reconcile` | 文件对照：自动主键、模糊对齐、数字优先、Excel 差异清单 |
| `exchange` | `../exchange` | 物物换算：实时行情、区间、逐行核对表 |
| `assess` | `../assess` | 对象对标准：区间/目标/比例三种对照、照片转数值 |

## 错误注入验收

```bash
python scripts/acceptance.py --verbose
```

它不测「算得对不对」，测的是**数据有问题时工具有没有说**：空表、只有表头、文件不存在、品种不存在、单位不支持、指标全不匹配、坏数值、无法路由。一条不过就是真 bug。

建这套验收的当天就抓出三个：空表对照报「没有发现差异」（最危险的假阴性）、文件不存在抛 Python 堆栈、路由在文件缺失时仍然执行。

## 结论前必读：反模式清单

`references/anti-patterns.md` 列了八类「看起来对、其实错」的陷阱，全部来自 benchmark 里的真实缺陷：

| 陷阱 | 症状 |
|---|---|
| 负数被静默跳过 | 红字/冲销没计入，差异判成一致 |
| 边界值归错档 | TC 5.2 判成「合适」，而指南写 <5.2 |
| 空表/只有表头报「无差异」 | 什么都没比，却说没问题 |
| 二进制当文本读 | 乱码或崩溃 |
| 历史记录当现状 | 变更记录本身进了待更新清单 |
| 单位未归一化 | 12000 元 与 12 千元 被判成不同 |
| 改名报成删增 | 交付包对比以为丢了文件 |
| 跨期键漂移 | 持续问题判成「已解决+新增」 |

**给出「一致」「无差异」「已解决」之前，逐条自查。**

这八条里有七条是「一行代码」级别的错误（`<=` 写成 `==`、`>` 写成 `>=`、表头没识别、单位没换算、哈希没比、键没归一化），但每一条都会让用户拿到**相反**的结论。

先读这份清单，再看报告。

## 已知缺口（别假装没有）

- 价格只抓一个源，没有多源交叉验证
- 三个引擎的“核对状态”格式接近但未完全统一
- 没有跨期趋势（上月差异本月是否收敛）
- 报告没有版本号和输入指纹，事后复现要重跑
- 只支持元/吨品种；汇率、贵金属、能源未覆盖

这些写在这里，是为了让下一个改它的人知道该补哪里。
