# compare-anything · 对照万物总入口

三种对照，一份契约：

| 输入 | 引擎 | 回答 |
|---|---|---|
| 两个文件 | reconcile | 哪里不一样 |
| 两个品种 | exchange | 一斤 A 换多少 B |
| 指标 + rubric | assess | 对照标准差在哪 |

    python scripts/route.py which --left 合同A.docx --right 合同B.docx
    python scripts/route.py run   --left 铜 --right 铝 --quantity 1 --unit 斤
    python scripts/route.py run   --rubric health-metabolic --kv "收缩压=142"

## 严谨性契约（五条）

1. 结论可复算：公式、主键、对齐方式都打印
2. 数据有出处与时点
3. 不确定必须显式标（✅/⚠/❓）
4. 不给单一数字，给区间/分级/清单
5. 不替代人

实现程度见 SKILL.md 的对照表——三个引擎各有强弱，没有一个是满分。

## 错误注入验收

    python scripts/acceptance.py --verbose

专喂坏数据（空表、缺文件、错品种、错单位、坏数值），检查工具会不会「假装没事」。
当天就抓出 3 个真 bug，其中一个最危险：空表对照输出「没有发现差异」。

## 已知缺口

多源交叉验证、跨期趋势、报告指纹、汇率与贵金属覆盖——都还没做。

MIT。