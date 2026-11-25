# 从这里开始

**你不需要会编程。** 每件事都是「复制一条命令 → 粘贴 → 回车 → 看结果」。

---

## 这是什么

一套帮你**对照两份东西、找出不一样**的工具。

不是软件，没有安装包，没有界面。几个脚本，跑一下出结果。

| 你手上有什么 | 它能给你什么 |
|---|---|
| 两份合同 / 两个文件夹 / 两张图 | 哪几个字、哪个文件、哪个像素不一样 |
| 一套会计账 | 勾稽平不平、凭证有没有毛病、银行流水对不对上 |
| 开店的数（投资、房租、客流） | 多久回本、要垫多少钱、收入跌 20% 还撑不撑得住 |

**它不做的事**：不记账、不报税、不替你做决定、不给你法律或投资建议。

---

## 三步开始（5 分钟）

### 第 1 步：装 Python

打开 https://www.python.org/downloads/ ，下载安装。

**安装时一定要勾选 `Add Python to PATH`**（第一个界面最下面）。

装完验证：按 `Win + R` → 输入 `cmd` → 回车 → 打：

```
python --version
```

看到 `Python 3.10` 或更高就行。

### 第 2 步：下载

打开 https://github.com/Yx6882/comparison-toolkit/releases/latest

下载最下面的 `comparison-toolkit-vX.X.X.zip`，解压到你想放的地方（比如 `D:\tools\`）。

### 第 3 步：跑第一个命令

在解压出来的文件夹里，`Shift` + 右键 → **在此处打开命令窗口**。

然后打：

```
python benchmark/run.py
```

等 1–2 分钟，最后一行显示：

```
汇总：22 个场景 · 命中 50 · 漏报 0 · 误报 0 · P=1.00 R=1.00 F1=1.00
```

**装好了。**

---

## 三个最常见的任务

### 任务一：对比两个文件夹

**场景**：客户给了新版图纸，我要知道改了哪几个字、哪个尺寸。

```
python reconcile/scripts/reconcile.py dir 旧版文件夹 新版文件夹 -o 报告
```

（把「旧版文件夹」「新版文件夹」换成你的实际路径，比如 `D:\项目\v1`）

**得到**：`报告\` 文件夹里两个文件——`.md` 直接看，`.xlsx` 发给别人。

报告会说：哪些文件新增、哪些删除、哪些内容改了（精确到哪个参数、旧值、新值）。

**对比两份具体文件**（表格、清单）：

```
python reconcile/scripts/reconcile.py run 旧版.xlsx 新版.xlsx -o 报告
```

---

### 任务二：核对会计账

**场景**：月末结账前，确认资产负债表平不平。

**新建一个 `报表.json`**（用记事本，注意存成 UTF-8）：

```json
{
  "balance_sheet": {
    "total_assets": 5000000,
    "total_liabilities": 2000000,
    "total_equity": 3000000
  }
}
```

然后：

```
python accounting-checks/scripts/statements.py check -i 报表.json
```

**得到**（直接显示在屏幕上）：

```
✓ 资产负债平衡   5,000,000.00 = 2,000,000.00 + 3,000,000.00
– 未分配利润滚动  缺少 期初未分配 / 期末未分配 / 净利润 之一
```

`✓` 是通过，`✗` 是不符，`–` 是数据不够（**不会当成通过**）。

**数据给得越全，检查项越多**。完整的结构：

```json
{
  "balance_sheet": {
    "total_assets": 5000000,
    "total_liabilities": 2000000,
    "total_equity": 3000000
  },
  "income_statement": {"net_profit": 500000},
  "equity_change": {
    "opening_retained": 2000000,
    "closing_retained": 2450000,
    "dividends": 0
  },
  "cash_flow": {"ending_cash": 800000},
  "balance_sheet_cash": 800000
}
```

其他会计检查的命令：

```
python accounting-checks/scripts/vouchers.py check -i 凭证.json
python accounting-checks/scripts/ledger.py check -i 余额表.json
python accounting-checks/scripts/bank.py match -i 流水.json
python accounting-checks/scripts/recalc.py check -i 报表.json
```

**每个都有 `demo`，不知道怎么填就先跑一遍看示例**：

```
python accounting-checks/scripts/statements.py demo
```

---

### 任务三：算开店回本

**场景**：投资 50 万，算多久回本、要垫多少钱。

**新建 `我的店.json`**：

```json
{
  "investment": 500000,
  "monthly_revenue": 120000,
  "variable_cost_rate": 0.40,
  "monthly_fixed_cost": 50000,
  "ramp_months": 6,
  "ramp_start_ratio": 0.4,
  "lease_months": 36
}
```

含义：投资 50 万、月营业 12 万、变动成本占 40%、固定成本（房租工资）5 万、
开业后 6 个月恢复到正常水平、首月只有四成、租约 36 个月。

```
python assess/scripts/business.py payback -i 我的店.json
```

**得到**：

- 回本周期（22.7 个月）
- 保本月收入（83,333）
- **爬坡期要垫多少钱**（37,680）—— 大部分店死在这一步
- 收入跌 20%、成本涨 20% 还撑不撑得住
- 租约 36 个月够不够回本

---

## 你的行业在哪

想知道「我这行毛利率多少算正常」：

```
python assess/scripts/assess.py list
```

列出 123 个行业。找到你的，比如咖啡店是 `industry-cafe`：

```
python assess/scripts/assess.py run --rubric industry-cafe --kv "毛利率=65,净利率=10,租售比=18"
```

报告会显示两栏：**经验区间** 和 **A 股同行业真实数据**（5818 家上市公司里同行的情况）。

**两个数不一样是正常的**——上市公司和你这种规模的小店，本来就不该用同一把尺子。

---

## 如果你用 AI 助手

用 Claude Code、Cursor、Cline 这类能执行命令的 AI，可以直接让它装：

```
git clone https://github.com/Yx6882/comparison-toolkit.git
cd comparison-toolkit
python install.py
```

装完直接说「帮我对比这两个文件夹」，AI 会自己调用，不用记命令。

**手机上用不了**——手机上的豆包、千问读不到 GitHub，也跑不了代码。

---

## 卡住了

**打 `python` 说「不是内部或外部命令」**
→ 没装好，或没勾 `Add Python to PATH`。重装，记得勾。

**下载不了 GitHub**
→ 国内网络经常连不上。多试几次，或换手机热点。

**报告看不懂**
→ 开头都有「结论」一行，先看那个。细节表格是核对时用的。

**不知道数据怎么填**
→ 每个脚本都有 `demo`：
```
python assess/scripts/business.py demo
```

---

## 一句话

```
第一步：python benchmark/run.py 确认能用
第二步：找到最像你需求的那个任务，照抄命令
第三步：卡住了看「卡住了」，或者截图问人
```

**别从头读文档。** 388 个文件里，你只需要上面这几条命令。
