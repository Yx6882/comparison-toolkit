# assess · 对象 vs 标准

对账的另一半。econcile 比的是「两份观测」；这里比的是「**一个对象 vs 一套基准**」。

    python scripts/assess.py list
    python scripts/assess.py run --rubric health-metabolic --kv "总胆固醇=6.42,收缩压=142"
    python scripts/assess.py run --rubric career-pm --input self.json
    python scripts/assess.py run --rubric budget-50-30-20 --kv "必要支出=8200,收入=15000"
    python scripts/assess.py demo

## 三层结构

| 层 | 在哪 | 为什么 |
|---|---|---|
| 数据层 | `rubrics/*.json` | 区间、目标、权重、来源、建议文案——改 JSON 就能换场景，不用改代码 |
| 逻辑层 | `scripts/assess.py` | 分级、算差距、排优先级，确定性、可测试 |
| 交互层 | Agent | 自然语言进、读照片、解释报告 |

**加一个场景 = 加一个 JSON 文件。**

## 三种对照类型

| kind | 比什么 | 用在哪 |
|---|---|---|
| `range` | 值 vs 递增的 `max` 档位 | 体检指标、阈值 |
| `target` | 值/评分 vs 目标 | 能力自评 |
| `ratio` | 值 ÷ `denominator` vs 百分比目标 | 开支结构 |

## 照片怎么处理

不用装 OCR：**把图片交给多模态模型读**，读成数值再喂引擎。

    1. 用户发来化验单照片
    2. Agent 读出 项目/结果/单位/参考范围
    3. 写成 {"总胆固醇": 6.42, "收缩压": 142}
    4. python scripts/assess.py run --rubric health-metabolic --input values.json
    5. 先把读到的数字回显给用户确认，再解释结论

**数字回显这一步不能省**——读错一位数是这条链路最大的失败点。

## 安全边界

- **健康**：只按公开切点分级、只提示就医，**不诊断、不推荐药物**；每份报告都带来源和免责声明
- **政策福利（社保/个税/补贴）**：不做。地区差异大、时效性强，答错会让人吃亏——只给「去哪儿核实」的清单
- **钱**：比例是起点不是标准，一线城市必要支出超 50% 很正常（rubric 里写了）
- **职场**：自评分，不是结论；建议用作品证据校准

## 文件

    SKILL.md                  # Agent 入口
    scripts/assess.py         # 引擎
    rubrics/*.json            # 健康 / 职场 / 预算
    tests/test_assess.py      # 15 个离线测试

MIT。