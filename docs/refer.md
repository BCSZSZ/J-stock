# J-Stock-Analyzer 参考文档（源码对齐版）

> 说明：本文档是**参考说明**，不是 Copilot 指令文件。
>
> 真实行为以 `main.py`、`src/cli/*`、`config.json`、`src/utils/strategy_loader.py` 为准。

## 1. 项目定位（当前代码）

J-Stock-Analyzer 目前提供：

- 生产流程编排（`production`）
- 数据抓取（`fetch`）
- 交易信号（`signal`）
- 单股票回测（`backtest`）
- 组合回测（`portfolio`）
- 宇宙选股（`universe`）
- 策略综合评价（`evaluate`）

统一入口：`main.py`

---

## 2. CLI 命令（与 `main.py --help` 对齐）

### 2.1 顶层命令

```bash
python main.py --help
```

子命令：

- `production`
- `fetch`
- `signal`
- `backtest`
- `portfolio`
- `universe`
- `evaluate`

### 2.2 production

```bash
python main.py production [--dry-run] [--skip-fetch]
```

参数：

- `--dry-run`：试运行模式（不执行交易）
- `--skip-fetch`：跳过数据抓取步骤

### 2.3 fetch

```bash
python main.py fetch (--all | --tickers T1 T2 ...)
```

参数：

- `--all`：抓取监视列表中的所有股票
- `--tickers`：指定股票代码列表

### 2.4 signal

```bash
python main.py signal TICKER [--date YYYY-MM-DD] [--entry ENTRY] [--exit EXIT]
```

默认值来源（代码行为）：

- `--entry` 默认来自 `config.json -> default_strategies.entry`
- `--exit` 默认来自 `config.json -> default_strategies.exit`

### 2.5 backtest

```bash
python main.py backtest TICKER \
  [--entry E1 E2 ...] [--exit X1 X2 ...] [--all-strategies] \
  [--years N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--capital AMOUNT]
```

说明：

- `--all-strategies` 按 `strategy_loader` 动态计算策略组合数。
- 当前注册策略为 5 个 entry × 5 个 exit，共 **25** 组合。

默认值来源（代码行为）：

- `--entry/--exit` 默认来自 `config.json -> default_strategies`
- `--start/--end/--capital` 默认来自 `config.json -> backtest`

### 2.6 portfolio

```bash
python main.py portfolio (--all | --tickers T1 T2 ...) \
  [--entry E1 E2 ...] [--exit X1 X2 ...] [--all-strategies] \
  [--years N] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--capital AMOUNT]
```

说明与默认值来源与 `backtest` 同逻辑。

### 2.7 universe

```bash
python main.py universe \
  [--csv-file PATH] [--top-n N] [--limit N] [--batch-size N] \
  [--resume] [--checkpoint PATH] [--no-fetch]
```

### 2.8 evaluate

```bash
python main.py evaluate \
  [--years Y1 Y2 ...] [--mode {annual,quarterly,monthly,custom}] \
  [--months M1 M2 ...] [--custom-periods JSON] \
  [--entry-strategies E1 E2 ...] [--exit-strategies X1 X2 ...] \
  [--output-dir DIR] [--verbose]
```

---

## 3. 策略注册（源码真实值）

来源：`src/utils/strategy_loader.py`

### Entry Strategies（5）

- `SimpleScorerStrategy`
- `EnhancedScorerStrategy`
- `MACDCrossoverStrategy`
- `BollingerSqueezeStrategy`
- `IchimokuStochStrategy`

### Exit Strategies（5）

- `ATRExitStrategy`
- `ScoreBasedExitStrategy`
- `LayeredExitStrategy`
- `BollingerDynamicExit`
- `ADXTrendExhaustionExit`

组合数：`5 × 5 = 25`

---

## 4. 配置与默认值

主配置文件：`config.json`

关键默认值：

- `default_strategies.entry`
- `default_strategies.exit`
- `backtest.start_date`
- `backtest.end_date`
- `backtest.starting_capital_jpy`

production 相关：

- `production.monitor_list_file`
- `production.state_file`
- `production.signal_file_pattern`
- `production.report_file_pattern`
- `production.history_file`

---

## 5. 数据目录与输出命名（当前实现）

### 数据目录

- `data/raw_prices/{ticker}.parquet`
- `data/features/{ticker}_features.parquet`
- `data/raw_trades/{ticker}_trades.parquet`
- `data/raw_financials/{ticker}_financials.parquet`
- `data/metadata/{ticker}_metadata.json`
- `data/benchmarks/topix_daily.parquet`

### evaluate 输出

由 `StrategyEvaluator.save_results(prefix="strategy_evaluation")` 生成：

- `strategy_evaluation_raw_{timestamp}.csv`
- `strategy_evaluation_by_regime_{timestamp}.csv`
- `strategy_evaluation_report_{timestamp}.md`

### production 输出

由 `config.json` pattern 控制，默认：

- `output/signals/{date}.json`
- `output/report/{date}.md`

---

## 6. 代码结构（简化视图）

```text
main.py
src/
  cli/
  client/
  data/
  analysis/strategies/
  backtest/
  evaluation/
  production/
  universe/
  utils/
```

---

## 7. 文档边界说明

本文件仅做“源码现状参考”，不承诺：

- 历史版本性能结论
- 未来路线图
- 与当前代码无关的操作规范

如遇冲突，优先级：

1. 可执行代码（`main.py`、`src/cli/*`）
2. 配置文件（`config.json`）
3. 本参考文档

---

## 8. 维护建议

每次改动 CLI 或策略注册后，至少执行：

```bash
python main.py --help
python main.py backtest --help
python main.py portfolio --help
python main.py evaluate --help
```

并同步更新本文档第 2、3 节。
