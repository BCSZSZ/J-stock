# J-Stock-Analyzer CLI 命令配置完整分析

**生成日期**: 2026-01-22  
**版本**: v0.6.0 (Phase 5 进行中)

---

## 📋 配置文件位置

### 主配置文件

- **config.json** - 系统全局配置（必需）
- **production_state.json** - 生产环境状态文件（自动生成）
- **data/monitor_list.json** - 监视股票列表（推荐格式）
- **data/monitor_list.txt** - 监视股票列表（备用格式）
- **.env** - API密钥和环境变量

---

## 🎯 命令配置详解

### 1️⃣ 数据抓取命令 - `fetch`

```bash
python main.py fetch --all
python main.py fetch --tickers 7974 8035 6501
```

#### 配置参数来源

| 参数类型     | 配置源                                                            | 默认值/说明              |
| ------------ | ----------------------------------------------------------------- | ------------------------ |
| **API密钥**  | `.env`: JQUANTS_API_KEY                                           | **必需**，从J-Quants获取 |
| **监视列表** | `data/monitor_list.json` 或 `config.json: data.monitor_list_file` | 抓取对象股票列表         |
| **数据存储** | `config.json: data.data_dir`                                      | `data/`                  |

#### 输出文件

```
data/
├── features/              # 日线OHLCV + 14技术指标
│   └── {ticker}_features.parquet
├── raw_trades/            # 机构投资者周度流向
│   └── {ticker}_trades.parquet
├── raw_financials/        # 季度财务数据
│   └── {ticker}_financials.parquet
├── metadata/              # 公司信息和收益日历
│   └── {ticker}_metadata.json
└── benchmarks/            # TOPIX基准指数
    └── TOPIX_daily.parquet
```

#### 监视列表格式

**推荐格式（JSON）**:

```json
{
  "tickers": [
    { "code": "7974", "name": "任天堂" },
    { "code": "8035", "name": "东京电子" }
  ],
  "updated_at": "2026-01-22"
}
```

**备用格式（TXT）**:

```
7974
8035
# 注释行会被跳过
```

---

### 2️⃣ 生成交易信号命令 - `signal`

```bash
python main.py signal 7974
python main.py signal 7974 --date 2025-12-25 --entry EnhancedScorerStrategy --exit LayeredExitStrategy
```

#### 配置参数来源

| 参数      | 配置源         | 默认值                                  | 说明                   |
| --------- | -------------- | --------------------------------------- | ---------------------- |
| `ticker`  | **命令行必需** | -                                       | 股票代码               |
| `--date`  | 命令行可选     | 今天                                    | 信号日期（YYYY-MM-DD） |
| `--entry` | 命令行可选     | `config.json: default_strategies.entry` | `SimpleScorerStrategy` |
| `--exit`  | 命令行可选     | `config.json: default_strategies.exit`  | `ATRExitStrategy`      |

#### 可用策略列表

**入场策略（Entry Strategies）**:

- `SimpleScorerStrategy` ⭐ 推荐（生产环境）
- `EnhancedScorerStrategy`
- `MACDCrossoverStrategy`
- `BollingerSqueezeStrategy`
- `IchimokuStochStrategy`

**出场策略（Exit Strategies）**:

- `LayeredExitStrategy` ⭐ 推荐（2年147.83%回报）
- `ADXTrendExhaustionExit` ⭐ 备选（2年136.67%回报）
- `BollingerDynamicExit`
- `ATRExitStrategy`（基准）
- `ScoreBasedExitStrategy`

#### 输出示例

```
🎯 生成交易信号
   股票代码: 7974
   日期: 2026-01-22
   入场策略: SimpleScorerStrategy
   出场策略: LayeredExitStrategy
============================================================

✅ 信号生成成功
   动作: BUY
   置信度: 0.85
   原因: 技术指标强势（RSI=65，MACD上穿），机构流入+¥2.5B
```

---

### 3️⃣ 单股票回测命令 - `backtest`

```bash
# 默认配置
python main.py backtest 7974

# 指定策略
python main.py backtest 7974 --entry SimpleScorerStrategy --exit LayeredExitStrategy

# 多策略组合测试
python main.py backtest 7974 --entry SimpleScorerStrategy EnhancedScorerStrategy --exit LayeredExitStrategy ATRExitStrategy

# 全部策略组合（25种）
python main.py backtest 7974 --all-strategies

# 自定义时间和资金
python main.py backtest 7974 --start 2023-01-01 --end 2025-12-31 --capital 10000000

# 最近2年回测
python main.py backtest 7974 --years 2
```

#### 配置参数来源

| 参数               | 配置源                   | 默认值                                       | 说明                     |
| ------------------ | ------------------------ | -------------------------------------------- | ------------------------ |
| `ticker`           | **命令行必需**           | -                                            | 股票代码                 |
| `--entry`          | 命令行可选（支持多个）   | `config.json: default_strategies.entry`      | `SimpleScorerStrategy`   |
| `--exit`           | 命令行可选（支持多个）   | `config.json: default_strategies.exit`       | `ATRExitStrategy`        |
| `--all-strategies` | 命令行标志               | False                                        | 测试全部5×5=25种组合     |
| `--start`          | 命令行可选               | `config.json: backtest.start_date`           | `2021-01-01`             |
| `--end`            | 命令行可选               | `config.json: backtest.end_date`             | `2026-01-08`             |
| `--capital`        | 命令行可选               | `config.json: backtest.starting_capital_jpy` | ¥5,000,000               |
| `--years`          | 命令行可选               | -                                            | 覆盖--start，使用最近x年 |
| **Lot Size**       | `config.json: lot_sizes` | default=100                                  | 最小交易单位             |

#### Lot Size配置

```json
"lot_sizes": {
  "1321": 1,      // ETF类通常为1股单位
  "1343": 1,
  "default": 100  // 日本股票默认100股单位
}
```

#### 回测结果输出

```
📊 单股票回测
   股票代码: 7974
   时间范围: 2024-01-01 → 2026-01-08
   起始资金: ¥5,000,000
   入场策略: SimpleScorerStrategy
   出场策略: LayeredExitStrategy
============================================================

📈 回测结果
   最终资金: ¥12,391,500
   总收益率: 147.83%
   交易次数: 48
   胜率: 52.1%
   最大回撤: 18.32%
   夏普比率: 1.28

   买入持有收益: 65.23%
   择时Alpha: +82.60%
   TOPIX收益: 46.47%
   选股Alpha: +101.36%
```

#### 保存位置

- 控制台输出：实时显示
- 日志文件：`output/backtest_{ticker}_{timestamp}.txt`（如果启用output_logger）

---

### 4️⃣ 组合投资回测命令 - `portfolio`

```bash
# 监视列表全部股票
python main.py portfolio --all

# 指定股票组合
python main.py portfolio --tickers 7974 8035 6501 8306 4063

# 多策略测试
python main.py portfolio --all --entry SimpleScorerStrategy EnhancedScorerStrategy --exit LayeredExitStrategy ATRExitStrategy

# 全部策略组合
python main.py portfolio --all --all-strategies

# 最近2年回测
python main.py portfolio --all --years 2 --capital 10000000
```

#### 配置参数来源

| 参数                  | 配置源                                    | 默认值                                       | 说明                   |
| --------------------- | ----------------------------------------- | -------------------------------------------- | ---------------------- |
| `--all` / `--tickers` | **命令行必需（二选一）**                  | -                                            | 股票范围               |
| **监视列表**          | `data/monitor_list.json`                  | -                                            | --all时读取            |
| `--entry`             | 命令行可选（支持多个）                    | `config.json: default_strategies.entry`      | `SimpleScorerStrategy` |
| `--exit`              | 命令行可选（支持多个）                    | `config.json: default_strategies.exit`       | `ATRExitStrategy`      |
| `--all-strategies`    | 命令行标志                                | False                                        | 测试全部25种组合       |
| `--start` / `--end`   | 命令行可选                                | `config.json: backtest.*`                    | 时间范围               |
| `--capital`           | 命令行可选                                | `config.json: backtest.starting_capital_jpy` | ¥5,000,000             |
| `--years`             | 命令行可选                                | -                                            | 覆盖--start            |
| **最大持仓数**        | `config.json: portfolio.max_positions`    | 5                                            | 同时持有股票上限       |
| **仓位限制**          | `config.json: portfolio.max_position_pct` | 0.30 (30%)                                   | 单股最大仓位           |
| **最小仓位**          | `config.json: portfolio.min_position_pct` | 0.05 (5%)                                    | 单股最小仓位           |

#### 组合投资特殊机制

1. **信号竞争排序**: 当BUY信号 > 最大持仓数时，按评分排序选择
2. **资金分配**: 基于信号评分和风险参数动态分配
3. **Lot-based购买**: 遵循日本市场最小交易单位
4. **再平衡**: 无自动再平衡，完全基于Entry/Exit信号

#### 组合回测结果输出

```
📊 组合投资回测 - 监视列表所有股票 (61只)
   策略组合数: 1
   入场策略: SimpleScorerStrategy
   出场策略: LayeredExitStrategy
   时间范围: 2024-01-01 → 2026-01-08
   股票代码: 7974, 8035, 6501, 8306, 4063...
   起始资金: ¥5,000,000
   最大持仓: 5只
============================================================

✅ 成功加载 61/61 只股票数据

📈 组合回测结果
   最终资金: ¥12,391,500
   总收益率: 147.83%
   交易次数: 964
   胜率: 48.4%
   最大回撤: 28.32%
   夏普比率: 1.28

   TOPIX收益: 46.47%
   超额收益: +101.36%
```

#### 保存位置

- 控制台输出：实时显示
- 日志文件：`output/portfolio_{timestamp}.txt`

---

### 5️⃣ 宇宙选股命令 - `universe`

```bash
# 默认配置（从1658只股票选Top 50）
python main.py universe

# 自定义Top N
python main.py universe --top-n 100

# 限制处理数量（调试用）
python main.py universe --limit 100

# 批量处理+断点续传
python main.py universe --batch-size 50 --resume

# 快速重新评分（不抓取数据）
python main.py universe --no-fetch
```

#### 配置参数来源

| 参数           | 配置源     | 默认值                    | 说明                |
| -------------- | ---------- | ------------------------- | ------------------- |
| `--csv-file`   | 命令行可选 | `data/jpx_final_list.csv` | JPX上市公司CSV      |
| `--top-n`      | 命令行可选 | 50                        | 选出Top N股票       |
| `--limit`      | 命令行可选 | -                         | 仅处理前N支（调试） |
| `--batch-size` | 命令行可选 | 100                       | 批次大小            |
| `--resume`     | 命令行标志 | False                     | 断点续传模式        |
| `--checkpoint` | 命令行可选 | 自动生成                  | checkpoint文件路径  |
| `--no-fetch`   | 命令行标志 | False                     | 跳过数据抓取        |

#### 5维度评分权重

```python
WEIGHT_VOL = 0.25        # 波动率（ATR/Price）
WEIGHT_LIQ = 0.25        # 流动性（Volume × Price）
WEIGHT_TREND = 0.20      # 趋势强度（EMA20 vs EMA200）
WEIGHT_MOMENTUM = 0.20   # 20日动量
WEIGHT_VOLSURGE = 0.10   # 成交量激增检测
```

#### 选股流程

```
1. 从CSV加载1658只JPX股票 → 2. 分批抓取数据（100只/批）
                            ↓
3. 计算5维度指标 → 4. 全局百分位排序 → 5. 加权评分
                                       ↓
6. 选出Top 50 → 7. 保存结果（JSON/CSV/TXT）
```

#### 输出文件

```
data/universe/
├── checkpoints/                           # 断点续传文件
│   └── universe_run_{timestamp}.json
├── scores_all_{timestamp}.parquet         # 全部股票评分
├── selection_{timestamp}.json             # Top N结果（JSON）
├── selection_{timestamp}.csv              # Top N结果（CSV）
└── scores_summary_{timestamp}.txt         # 评分摘要（可读）
```

#### 更新监视列表

选股完成后，可手动更新监视列表：

```bash
# 方式1：使用update_monitor_list.py脚本
python update_monitor_list.py --source data/universe/selection_latest.json

# 方式2：手动编辑data/monitor_list.json
```

---

### 6️⃣ 策略综合评价命令 - `evaluate`

```bash
# 年度评估
python main.py evaluate --mode annual --years 2023 2024 2025

# 季度评估
python main.py evaluate --mode quarterly --years 2024 2025

# 月度评估（指定月份）
python main.py evaluate --mode monthly --years 2024 2025 --months 1 2 3

# 自定义时间段
python main.py evaluate --mode custom --custom-periods '[["2024-Q1","2024-01-01","2024-03-31"],["2024-Q2","2024-04-01","2024-06-30"]]'

# 指定策略（避免测试全部25种）
python main.py evaluate --mode annual --years 2024 --entry-strategies SimpleScorerStrategy --exit-strategies LayeredExitStrategy ATRExitStrategy

# 详细输出模式
python main.py evaluate --mode annual --years 2024 --verbose
```

#### 配置参数来源

| 参数                 | 配置源                        | 默认值                 | 说明                            |
| -------------------- | ----------------------------- | ---------------------- | ------------------------------- |
| `--mode`             | **命令行必需**                | -                      | annual/quarterly/monthly/custom |
| `--years`            | 命令行必需（除custom）        | -                      | 年份列表                        |
| `--months`           | 命令行可选（monthly模式）     | 1-12                   | 月份列表                        |
| `--custom-periods`   | 命令行必需（custom模式）      | -                      | JSON格式时间段                  |
| `--entry-strategies` | 命令行可选                    | 全部5种                | 限制入场策略                    |
| `--exit-strategies`  | 命令行可选                    | 全部5种                | 限制出场策略                    |
| `--output-dir`       | 命令行可选                    | `strategy_evaluation/` | 输出目录                        |
| `--verbose`          | 命令行标志                    | False                  | 详细输出模式                    |
| **回测配置**         | 继承`config.json: backtest.*` | -                      | 初始资金、Lot Size等            |

#### 时间段格式

**annual模式**:

```python
[
  ["2024", "2024-01-01", "2024-12-31"],
  ["2025", "2025-01-01", "2025-12-31"]
]
```

**quarterly模式**:

```python
[
  ["2024-Q1", "2024-01-01", "2024-03-31"],
  ["2024-Q2", "2024-04-01", "2024-06-30"],
  ...
]
```

**monthly模式**:

```python
[
  ["2024-01", "2024-01-01", "2024-01-31"],
  ["2024-02", "2024-02-01", "2024-02-29"],
  ...
]
```

#### 市场环境分类

根据TOPIX收益率自动分类：

- **强势牛市**: TOPIX > +15%
- **温和牛市**: TOPIX +5% ~ +15%
- **横盘**: TOPIX -5% ~ +5%
- **熊市**: TOPIX < -5%

#### 输出文件

```
strategy_evaluation/
├── strategy_evaluation_report_{timestamp}.md    # Markdown综合报告
├── strategy_evaluation_raw_{timestamp}.csv      # 原始数据（所有策略×时段）
└── strategy_evaluation_by_regime_{timestamp}.csv # 按市场环境分组
```

#### 报告内容示例

```markdown
# 策略综合评价报告

## 评估概览

- 评估时段数: 24 (2024-2025月度)
- 策略组合数: 25 (5 Entry × 5 Exit)
- 总回测次数: 600

## Top 5 策略（按平均收益率）

| 排名 | 入场策略             | 出场策略               | 平均收益% | 夏普比率 | 胜率% |
| ---- | -------------------- | ---------------------- | --------- | -------- | ----- |
| 1    | SimpleScorerStrategy | LayeredExitStrategy    | 12.3      | 1.45     | 58.2  |
| 2    | SimpleScorerStrategy | ADXTrendExhaustionExit | 11.8      | 1.52     | 56.1  |

...

## 按市场环境分析

### 强势牛市（TOPIX > +15%）

- 最佳策略: SimpleScorerStrategy × LayeredExitStrategy (22.5%)
- 时段数: 6

### 熊市（TOPIX < -5%）

- 最佳策略: IchimokuStochStrategy × ATRExitStrategy (-3.2%)
- 时段数: 4
```

---

## 🔧 生产环境命令 - `production` (Phase 5)

```bash
# 完整工作流程（数据更新 + 信号生成 + 报告）
python main.py production

# 跳过数据抓取（使用现有数据）
python main.py production --skip-fetch

# 试运行模式（不保存状态）
python main.py production --dry-run
```

#### 配置参数来源

| 参数           | 配置源                                        | 默认值                       | 说明         |
| -------------- | --------------------------------------------- | ---------------------------- | ------------ |
| **策略组配置** | `config.json: production.strategy_groups`     | 见下表                       | 多策略组管理 |
| **状态文件**   | `config.json: production.state_file`          | `production_state.json`      | 持仓和历史   |
| **信号文件**   | `config.json: production.signal_file_pattern` | `output/signals/{date}.json` | 每日信号     |
| **报告文件**   | `config.json: production.report_file_pattern` | `output/report/{date}.md`    | 每日报告     |
| **历史记录**   | `config.json: production.history_file`        | `trade_history.json`         | 交易历史     |
| **买入阈值**   | `config.json: production.buy_threshold`       | 65                           | 入场评分门槛 |

#### 策略组配置示例

```json
"strategy_groups": [
  {
    "id": "group_a",
    "name": "积极进取组",
    "initial_capital": 2000000,
    "entry_strategy": "SimpleScorerStrategy",
    "exit_strategy": "LayeredExitStrategy"
  },
  {
    "id": "group_b",
    "name": "稳健防守组",
    "initial_capital": 2000000,
    "entry_strategy": "IchimokuStochStrategy",
    "exit_strategy": "ATRExitStrategy"
  }
]
```

#### Production工作流程

```
Step 1: 加载配置（config.json）
         ↓
Step 2: 加载/初始化状态（production_state.json）
         ↓
Step 3: [可选] 抓取最新数据（监视列表全部股票）
         ↓
Step 4: 综合评估所有股票（监视列表）
         ↓
Step 5: 生成交易信号
         ├─ Entry信号：非持仓股票 × 各组策略
         └─ Exit信号：当前持仓 × 各组策略
         ↓
Step 6: 保存信号文件（output/signals/{date}.json）
         ↓
Step 7: 生成每日报告（output/report/{date}.md）
         └─ 包含：市场概览、信号列表、持仓状态、综合评估表
```

#### 输出示例

**控制台**:

```
======================================================================
PRODUCTION WORKFLOW - Phase 5
======================================================================

[Phase 1] Loading configuration...
  State file: production_state.json
  Monitor list: data/production_monitor_list.json
  Buy threshold: 65

[Phase 2] Loading production state...
  Loaded 2 strategy group(s)
    积极进取组: ¥2,000,000 cash, 3 positions
    稳健防守组: ¥1,800,000 cash, 2 positions

[Data Update] Fetching latest market data...
  TOPIX updated: 1209 records
  Updated 61/61 stocks

[Phase 3] Generating trading signals...
  Strategies to evaluate: SimpleScorerStrategy, IchimokuStochStrategy
  Evaluating all 61 stocks...
  ✅ Evaluated 61 stocks

  Generating trading signals...
    Group: 积极进取组
      BUY: 5, SELL: 1
    Group: 稳健防守组
      BUY: 3, SELL: 0
    Total: 8 BUY, 1 SELL

  Signals saved to: output/signals/2026-01-22.json

[Phase 4] Generating daily report...
  Report saved to: output/report/2026-01-22.md

======================================================================
✅ PRODUCTION WORKFLOW COMPLETE
======================================================================
  Strategy Groups: 2
  Total Signals: 9
  Signal File: output/signals/2026-01-22.json
  Report File: output/report/2026-01-22.md
======================================================================
```

**信号文件（output/signals/2026-01-22.json）**:

```json
[
  {
    "group_id": "group_a",
    "ticker": "7974",
    "ticker_name": "任天堂",
    "signal_type": "BUY",
    "action": "BUY",
    "confidence": 0.85,
    "score": 78.5,
    "reason": "技术指标强势+机构流入",
    "current_price": 8450.0,
    "suggested_qty": 100,
    "required_capital": 845000.0,
    "strategy_name": "SimpleScorerStrategy",
    "timestamp": "2026-01-22T07:15:32"
  },
  {
    "group_id": "group_a",
    "ticker": "8035",
    "ticker_name": "东京电子",
    "signal_type": "SELL",
    "action": "SELL_50%",
    "confidence": 0.7,
    "score": 0,
    "reason": "Layer2触发：价格回撤6.2%从峰值",
    "current_price": 25300.0,
    "position_qty": 100,
    "entry_price": 23500.0,
    "entry_date": "2025-12-15",
    "holding_days": 38,
    "unrealized_pl_pct": 7.66,
    "strategy_name": "LayeredExitStrategy",
    "timestamp": "2026-01-22T07:15:45"
  }
]
```

---

## 📊 配置参数优先级规则

所有命令遵循统一的优先级规则：

```
命令行参数 > config.json配置 > 硬编码默认值
```

### 示例场景

**场景1**: 回测时间范围

```bash
# 优先级1: 命令行 --years（最高）
python main.py backtest 7974 --years 2

# 优先级2: 命令行 --start/--end
python main.py backtest 7974 --start 2024-01-01 --end 2025-12-31

# 优先级3: config.json: backtest.start_date / end_date
python main.py backtest 7974  # 使用config.json中的时间
```

**场景2**: 策略选择

```bash
# 优先级1: 命令行指定
python main.py backtest 7974 --entry EnhancedScorerStrategy

# 优先级2: config.json: default_strategies.entry
python main.py backtest 7974  # 使用SimpleScorerStrategy
```

---

## 🎯 常见配置场景

### 场景A: 每日自动化运行

**目标**: Windows计划任务每天7:00 AM执行

**config.json配置**:

```json
{
  "production": {
    "monitor_list_file": "data/production_monitor_list.json",
    "buy_threshold": 65,
    "strategy_groups": [
      {
        "id": "main",
        "name": "主策略",
        "initial_capital": 5000000,
        "entry_strategy": "SimpleScorerStrategy",
        "exit_strategy": "LayeredExitStrategy"
      }
    ]
  }
}
```

**Windows任务计划命令**:

```powershell
cd C:\path\to\j-stock-analyzer
.\venv\Scripts\python.exe main.py production
```

---

### 场景B: 策略研究与优化

**目标**: 测试多种策略组合找最优解

**步骤1**: 单股票快速验证

```bash
python main.py backtest 7974 --all-strategies --years 2
```

**步骤2**: 组合投资验证

```bash
python main.py portfolio --all --entry SimpleScorerStrategy --exit LayeredExitStrategy ADXTrendExhaustionExit --years 2
```

**步骤3**: 跨时段综合评价

```bash
python main.py evaluate --mode monthly --years 2024 2025 --entry-strategies SimpleScorerStrategy --exit-strategies LayeredExitStrategy ADXTrendExhaustionExit
```

---

### 场景C: 选股与更新流程

**目标**: 每月更新监视列表

**步骤1**: 宇宙选股（每月1日）

```bash
python main.py universe --top-n 50 --batch-size 100
```

**步骤2**: 人工审核结果

```bash
# 查看 data/universe/selection_latest.json
# 结合基本面分析剔除不符合的股票
```

**步骤3**: 更新监视列表

```bash
python update_monitor_list.py --source data/universe/selection_latest.json
```

**步骤4**: 抓取新增股票数据

```bash
python main.py fetch --all
```

---

## 🔍 配置文件完整模板

### config.json完整示例

```json
{
  "data": {
    "monitor_list_file": "data/monitor_list.txt",
    "data_dir": "data"
  },

  "backtest": {
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000,
    "output_dir": "backtest_results"
  },

  "portfolio": {
    "max_positions": 5,
    "max_position_pct": 0.3,
    "min_position_pct": 0.05,
    "output_dir": "portfolio_backtest_results"
  },

  "lot_sizes": {
    "1321": 1,
    "1343": 1,
    "default": 100
  },

  "default_strategies": {
    "entry": "SimpleScorerStrategy",
    "exit": "ATRExitStrategy"
  },

  "production": {
    "monitor_list_file": "data/production_monitor_list.json",
    "state_file": "production_state.json",
    "signal_file_pattern": "output/signals/{date}.json",
    "report_file_pattern": "output/report/{date}.md",
    "history_file": "trade_history.json",
    "max_positions_per_group": 5,
    "max_position_pct": 0.3,
    "buy_threshold": 65,
    "strategy_groups": [
      {
        "id": "group_a",
        "name": "积极进取组",
        "initial_capital": 2000000,
        "entry_strategy": "SimpleScorerStrategy",
        "exit_strategy": "LayeredExitStrategy"
      },
      {
        "id": "group_b",
        "name": "稳健防守组",
        "initial_capital": 2000000,
        "entry_strategy": "IchimokuStochStrategy",
        "exit_strategy": "ATRExitStrategy"
      }
    ]
  }
}
```

### .env环境变量

```bash
# J-Quants API密钥（必需）
JQUANTS_API_KEY=your_api_key_here

# Python编码（Windows）
PYTHONIOENCODING=utf-8
```

---

## 📚 相关文档

- **快速开始**: [README.md](README.md)
- **策略评价指南**: 见`docs/STRATEGY_EVALUATION_QUICK_START.md`
- **生产部署总结**: 见`docs/DEPLOYMENT_SUMMARY_JAN16.md`
- **Phase 1-4文档**: 见`docs/PHASE*_*.md`

---

## ⚠️ 重要注意事项

1. **API配额**: J-Quants免费版有API调用限制，避免频繁全量抓取
2. **数据一致性**: 回测前确保数据完整（运行`python verify_data.py`）
3. **时间对齐**: 回测时间范围必须在数据范围内
4. **策略匹配**: Entry和Exit策略必须使用正确的类名（区分大小写）
5. **Lot Size**: 交易股票前确认lot_sizes配置正确
6. **状态管理**: production模式会持久化状态到production_state.json，不要手动修改

---

**生成工具**: GitHub Copilot  
**版本**: 1.0  
**最后更新**: 2026-01-22
