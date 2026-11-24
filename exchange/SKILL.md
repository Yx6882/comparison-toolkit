---
name: exchange
description: Convert one physical quantity into another at equal market value — how many jin of aluminium equal one jin of copper, how much rebar one ton of copper buys — using live Shanghai futures quotes, and reporting a range rather than a single number. Every row carries source, quote time and a checklist that flags what a human must verify: futures price vs actual spot, premium/discount, processing and freight cost, purity, tax. Use when asked 一斤铜换多少铝 / 值不值 / 等值换算 / 以物易物 / 这个价换那个划算吗, or any "A 换 B 多少才不亏" question. Offline tests, one live data source, no estimation without a source.
license: MIT
---

# Exchange · 物物等值换算

## The question it answers

“一斤铜换多少斤铝才不亏？” 本质是一道等值换算：

```
数量(B) = 数量(A) × 单价(A) ÷ 单价(B)
```

但**单价是活的**，所以一个确定的数字就是错的。本工具的输出是三样东西：

1. **一个中值**（当前行情下的等值点）
2. **一个区间**（按当日最高/最低组合出的最不利与最有利）
3. **一张逐行核对表**（哪些数据可信、哪些必须人工确认）

## 严谨性约定

| 约定 | 做法 |
|---|---|
| 不存单点 | 每个品种都存 `last / low / high`，结论给区间 |
| 数据有出处 | 每行写来源（新浪财经期货实时行情）和行情日期 |
| 数据有寿命 | 超过 12 小时标 `⚠ 请先 fetch 更新` |
| 价格性质要分清 | 期货价 ≠ 现货价 ≠ 实物成交价，报告里明写 |
| 交易成本单独列 | 加工费、运费、成色折价、批量折扣、税费，全部标 `⚠ 未计入` |
| 计算过程可复核 | 打印公式和代入数值，允许手算核对 |
| **双源交叉验证** | 同一品种抓新浪 + 东方财富，偏差 ≤0.5% 标 ✅，0.5–2% 标口径差异，>2% 标疑似数据错位 |
| 不确定就说不确定 | 标的、成色、地区不同时写 `❓ 请人工确认` |

**任何一行只要没把握，就不给 ✅。** 这是本工具和“随口算个数”的唯一区别。

## Run it

```bash
python scripts/exchange.py fetch                                  # 抓最新行情（8 个品种）
python scripts/exchange.py list                                   # 看已抓品种和时效
python scripts/exchange.py convert --from 铜 --to 铝 --quantity 1 --unit 斤
python scripts/exchange.py convert --from 铜 --to 螺纹钢 --quantity 1 --unit 吨
```

支持单位：`吨 / 公斤 / 斤 / 克`。品种：铜、铝、锌、铅、镍、螺纹钢、玉米、豆粕（元/吨的连续合约）。

## Output

```
## 结论：约 4.21 斤
按当日行情区间，结果在 4.14 – 4.37 斤 之间。
> 等值换算，不是成交价。请以当日实际报价人工核对。

| 项目 | 数值 | 当日区间 | 来源 | 数据时间 | 核对状态 |
| 铜（沪铜连续） | 88,810 元/吨 | 88,700 – 91,810 | 新浪财经 | 2026-11-25 | ✅ 交易所行情 |
| 铝（沪铝连续） | 21,070 元/吨 | 21,000 – 21,445 | 新浪财经 | 2026-11-25 | ✅ 交易所行情 |
| 换算 | 44.41 ÷ 10.54 = 4.21 斤 | 4.14 – 4.37 斤 | 计算 | — | ⚠ 未计交易成本 |
```

## Adding a material

在 `scripts/exchange.py` 的 `SYMBOLS` 里加一行（新浪期货连续合约代码 → 品种名），前提是该品种报价是 **元/吨**。其他单位（黄金 元/克、原油 元/桶）需要另建换算基表，不要硬塞进来。

## Honest limits

- **期货 ≠ 现货**：期货价 + 升贴水才是提货价，升贴水因地区、品牌、时间而异
- **成色差异巨大**：铜 99.95% 与废铜、铝锭与铝型材，价差可达 10–30%
- **不含交易成本**：加工费、运费、过磅误差、税费都没算，实际换货一定不等于这个数
- **只覆盖元/吨的品种**：贵金属、能源、汇率不在其中
- **不构成交易建议**：这是算术，不是投资判断

## Files

| Need | File |
|---|---|
| 引擎（抓取 + 换算 + 核对表） | `scripts/exchange.py` |
| 行情缓存（抓取后生成） | `data/prices.json` |
| 测试 | `tests/test_exchange.py` |
