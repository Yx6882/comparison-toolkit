# 对照万物 · Comparison Toolkit

[![tests](https://github.com/Yx6882/comparison-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/Yx6882/comparison-toolkit/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)


七个 skill + 一套验收工具，解决同一类问题：**给你两份东西，告诉你哪里不一样、先看哪个、怎么改、改完是否真的收敛了。**

## 怎么给 AI 用

**先说清楚**：这个仓库本身不等于「任何 AI 都能用」。取决于那个 AI 能不能执行命令、客户端支不支持 skills。

| 接入方式 | 前提 | 能做到什么 |
|---|---|---|
| **装进客户端的 skills 目录** | 客户端支持 Agent Skills（Claude Code / Cline / Cursor / DSH 等） | 完整：AI 自动发现并按需加载 |
| **让 AI 自己 clone 并跑脚本** | AI 有终端/代码执行能力 | 完整：`python scripts/xxx.py` 真跑 |
| **纯聊天窗口** | 只能读文档 | 只能「照着规则说」，跑不了脚本，做不了真对照 |

### 方式一：装进 skills 目录

```bash
python install.py                            # 自动检测常见客户端
python install.py --target ~/.claude/skills  # 或手动指定
python install.py --list                     # 先看会装什么
```

装完重启客户端，AI 就能在 skill 列表里看到它们。

### 方式二：让 AI 自己用

把仓库链接丢给能执行命令的 AI，一句话：

> clone 这个仓库，读 `compare-anything/SKILL.md`，然后按它的说明帮我对照 A 和 B。

AI 会自己 clone、读 SKILL、跑脚本。

### 方式三：纯聊天窗口

把具体某个 `SKILL.md` 的内容粘给它，它只能理解**规则**（比如「区间左闭右开」「负数必须计入合计」），但**跑不了代码**，做不了自动对照。适合问「这个方法该怎么用」，不适合干实际活。

## 手机上怎么用（豆包 / 千问 / DeepSeek 网页与 App）

手机端 AI 读不到 GitHub 的完整内容，也跑不了代码。但你可以用**纯文本版**：把它当对照顾问。

打开 [`compare-anything/references/anti-patterns.txt`](compare-anything/references/anti-patterns.txt)，里面第 4 节有一段**可直接复制的指令**，粘给 AI，再贴你的数据，它就会按九条清单帮你检查。

它做不到的：跑代码、读你手机里的大文件、精确比对几千行表格。
它做得到的：避免九条最常见的对照错误，帮你把问题问对。

| 环境 | 完整能力 | 顾问能力 |
|---|---|---|
| 手机 App / 网页聊天 | ❌ | ✅ 用纯文本版 |
| 电脑 + 能执行代码的 AI | ✅ `python install.py` | ✅ |

## 三种对照

| 你手上有什么 | 引擎 | 它回答 |
|---|---|---|
| 两个文件 / 两个目录 / 两张图 / 两段音频 | [`reconcile`](reconcile/) | 哪里不一样、谁先看、怎么改 |
| 一组指标 + 一份标准（rubric） | [`assess`](assess/) | **123 个行业**规则（91 个接了 A 股 5818 家真实财务数据）+ 开店测算 |
| 两个品种（铜、铝……） | [`exchange`](exchange/) | 一斤 A 换多少 B 才等值 |

再加四件配套的：

| Skill | 解决什么 |
|---|---|
| [`compare-anything`](compare-anything/) | 总入口：看输入选引擎；跨期趋势；**反模式清单** |
| [`spec-consistency`](spec-consistency/) | 多份文档里的参数是否一致；改了一个值谁还在用旧的 |
| [`ledger-match`](ledger-match/) | 金额组合对账；进项税勾稽（凭证 vs 发票） |
| [`ai-council`](ai-council/) | 多个模型/多个席位对同一问题独立回答再收敛 |
| [`accounting-checks`](accounting-checks/) | 十三个模块：报表勾稽/重算、凭证、余额表、流水、多期对比、现金流、比率、折旧、存货、约当产量、坏账、税额 |

## 快速开始

```bash
# 文件对照
python reconcile/scripts/reconcile.py run 旧版.docx 新版.docx

# 目录对照（含改名识别）
python reconcile/scripts/reconcile.py dir pkg_v1 pkg_v2

# 不确实该用哪个
python compare-anything/scripts/route.py run --left 铜 --right 铝

# 跑全部测试与验收
python benchmark/run.py
```

依赖：Python 3.10+。文件/表格对照需要 `openpyxl`、`python-docx`、`python-pptx`、`Pillow`；核心逻辑只用标准库。

## 安装与依赖

```bash
pip install -r requirements.txt
```

**但一个包都不装也能用。** 每个 skill 的第三方依赖都是可选的，缺了只影响对应格式，其余照常：

| Skill | 需要的包 | 缺了会怎样 |
|---|---|---|
| `ai-council` | 无 | 永远可用 |
| `exchange` | 无 | 永远可用（断网时读缓存行情） |
| `compare-anything` | 无 | 永远可用 |
| `ledger-match` | openpyxl | 只影响 Excel 读写；金额组合仍可用 |
| `assess` | openpyxl, Pillow | 影响 Excel 报告和演示图；分级逻辑仍可用 |
| `spec-consistency` | openpyxl, python-docx, python-pptx | 影响 xlsx/docx/pptx；`.md` 仍可读 |
| `reconcile` | openpyxl, python-docx, python-pptx, Pillow | 影响 xlsx/docx/pptx/图片；md/txt/csv/音频仍可用 |
| `benchmark` | openpyxl, python-docx | 部分 case（vat、合同）跑不起来 |

### 不装任何包的「最小可用集」

- 文本 / CSV / Markdown 对照
- 目录对照（含改名识别、内容哈希）
- 音频（WAV）对照
- 多方表决、跨期趋势、变更影响
- 物物等值换算
- 反模式清单

Python 3.10+。

## 这个仓库最值钱的东西

不是功能，是 **[反模式清单](compare-anything/references/anti-patterns.md)**。

它列了九类「看起来对、其实错」的陷阱——负数被跳过、边界值归错档、历史记录当现状、单位没归一化……全部来自 benchmark 抓到的真实缺陷。

**给出「一致」「无差异」「已解决」之前，先过一遍那九条。**

## 验收

```bash
python benchmark/run.py          # 21 个场景，带标准答案
python compare-anything/scripts/acceptance.py   # 11 条错误注入
```

单测合计 260+，分布在各个 skill 的 `tests/` 下。

## 边界

- 只报差异和分级，**不判断谁对**
- 健康类 rubric 只做数值分级，**不是诊断**
- 期货价 ≠ 成交价，物物换算不含加工费/运费
- 不替代会计师、医生、律师签署

MIT License。
