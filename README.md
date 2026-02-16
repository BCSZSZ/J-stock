# J-Stock-Analyzer

日本股票量化分析系统（基于 J-Quants API）：覆盖数据抓取、交易信号、单票/组合回测、宇宙选股与策略综合评价。

## ✨ 功能总览

### 1) 数据抓取与数据湖

- 从 J-Quants API 抓取并增量更新股票数据
- 自动维护 `features/raw_prices/raw_trades/raw_financials/metadata/benchmarks`
- 使用 Parquet 存储，便于回测与策略计算

### 2) 交易信号生成

- 支持按股票代码和日期生成信号
- 支持指定入场/出场策略
- 可直接用于日常监控与交易决策

### 交易执行规则（严格执行）

- 每个交易日收盘后生成信号（仅使用当日及以前数据）
- 买入/卖出统一在下一交易日开盘价执行
- 回测与组合回测均遵循上述规则，最后一个交易日生成的信号不会在样本内成交

### 3) 单股票回测

- 支持单策略或多策略组合回测
- 支持最近 N 年、起止日期、初始资金
- 输出收益率、回撤、夏普、交易统计等指标

### 4) 组合投资回测

- 支持监视列表全量或手动指定股票池
- 支持多策略组合回测
- 对比 TOPIX 与 Buy&Hold，输出组合层面业绩指标

### 5) 宇宙选股

- 从 CSV（默认 `data/jpx_final_list.csv`）进行评分筛选
- 支持 Top-N、断点续传、批处理、快速重评分（`--no-fetch`）
- 输出结果可用于更新监视列表

### 6) 策略综合评价

- 支持 `annual/quarterly/monthly/custom` 多时段评估
- 支持批量策略组合比较
- 输出 Markdown 报告 + CSV 原始结果 + 按市场环境聚合结果

### 7) 生产流程编排

- `production` 命令用于日常生产流程编排
- 支持 `--dry-run` 与 `--skip-fetch`

## 🚀 命令行大全

### A. 统一入口（推荐）：`main.py`

```bash
# 查看总帮助
python main.py --help

# 1) production
python main.py production
python main.py production --dry-run
python main.py production --skip-fetch

# 2) fetch
python main.py fetch --all
python main.py fetch --tickers 7974 8035 6501

# 3) signal
python main.py signal 7974
python main.py signal 7974 --date 2026-02-16
python main.py signal 7974 --entry EnhancedScorerStrategy --exit LayeredExitStrategy

# 4) backtest
python main.py backtest 7974
python main.py backtest 7974 --entry SimpleScorerStrategy EnhancedScorerStrategy --exit ATRExitStrategy LayeredExitStrategy
python main.py backtest 7974 --all-strategies
python main.py backtest 7974 --years 2 --capital 10000000

# 5) portfolio
python main.py portfolio --all
python main.py portfolio --tickers 7974 8035 6501
python main.py portfolio --all --entry SimpleScorerStrategy --exit LayeredExitStrategy
python main.py portfolio --all --all-strategies --years 2

# 6) universe
python main.py universe
python main.py universe --csv-file data/jpx_final_list.csv --top-n 50
python main.py universe --resume --checkpoint data/universe/checkpoint.json
python main.py universe --no-fetch

# 7) evaluate
python main.py evaluate --mode annual --years 2023 2024 2025
python main.py evaluate --mode quarterly --years 2024 2025
python main.py evaluate --mode monthly --years 2024 2025 --months 1 2 3
python main.py evaluate --mode custom --custom-periods '[["2024-Q1","2024-01-01","2024-03-31"]]'
python main.py evaluate --entry-strategies SimpleScorerStrategy --exit-strategies LayeredExitStrategy --verbose
```

#### `main.py` 子命令参数速查

- `production`: `--dry-run`, `--skip-fetch`
- `fetch`: `--all` 或 `--tickers ...`（二选一）
- `signal`: `ticker`, `--date`, `--entry`, `--exit`
- `backtest`: `ticker`, `--entry ...`, `--exit ...`, `--all-strategies`, `--years`, `--start`, `--end`, `--capital`
- `portfolio`: `--all` 或 `--tickers ...`（二选一）, `--entry ...`, `--exit ...`, `--all-strategies`, `--years`, `--start`, `--end`, `--capital`
- `universe`: `--csv-file`, `--top-n`, `--limit`, `--batch-size`, `--resume`, `--checkpoint`, `--no-fetch`
- `evaluate`: `--years ...`, `--mode`, `--months ...`, `--custom-periods`, `--entry-strategies ...`, `--exit-strategies ...`, `--output-dir`, `--verbose`

### B. 辅助命令脚本

```bash
# 快速回测（不改配置文件）
python quick_backtest.py --list
python quick_backtest.py simple atr
python quick_backtest.py enhanced layered --ticker 6501 --start 2023-01-01 --end 2026-01-08 --capital 5000000

# 传统宇宙选股脚本
python run_universe_selector.py --help
python run_universe_selector.py --universe-file data/jpx_final_list.csv --top-n 50
python run_universe_selector.py --universe-file data/jpx_final_list.csv --top-n 30 --test

# 配置文件驱动回测入口
python start_backtest.py
python start_portfolio_backtest.py
```

更多细节见文档目录 [docs/README.md](docs/README.md)。

## 📁 项目架构（按当前源码）

```
j-stock-analyzer/
├── main.py                              # 统一CLI入口（7个子命令）
├── config.json                          # 系统配置（默认策略/回测区间/production配置）
├── src/
│   ├── cli/                             # production/fetch/signal/backtest/portfolio/universe/evaluate
│   ├── client/jquants_client.py         # J-Quants API 客户端
│   ├── data/                            # 数据抓取、特征计算、benchmark 管理
│   ├── analysis/strategies/             # Entry/Exit 策略实现
│   ├── backtest/                        # 单票与组合回测引擎
│   ├── evaluation/strategy_evaluator.py # 策略综合评价
│   ├── production/                      # 生产工作流（state/signal/report/trade）
│   ├── universe/                        # 宇宙选股逻辑
│   └── utils/strategy_loader.py         # 策略注册与组合生成
├── data/
│   ├── raw_prices/                      # 原始K线: {ticker}.parquet
│   ├── features/                        # 技术特征: {ticker}_features.parquet
│   ├── raw_trades/                      # 机构流向: {ticker}_trades.parquet
│   ├── raw_financials/                  # 财务数据: {ticker}_financials.parquet
│   ├── metadata/                        # 元数据: {ticker}_metadata.json
│   ├── benchmarks/                      # 基准数据: topix_daily.parquet
│   └── universe/                        # 宇宙选股中间结果与输出
├── output/
│   ├── signals/                         # production 信号输出
│   └── report/                          # production 报告输出
├── strategy_evaluation/                 # evaluate 命令输出
└── docs/
    ├── QUICKSTART.md
    ├── USAGE_GUIDE.md
    ├── STRATEGY_EVALUATION_GUIDE.md
    └── ...
```

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/yourusername/j-stock-analyzer.git
cd j-stock-analyzer
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API Key

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` and add your J-Quants API key:

```
JQUANTS_API_KEY=your_actual_api_key_here
```

**Get your API key**: Sign up at [JPX J-Quants](https://jpx-jquants.com/)

## Usage

### 基本使用（CLI）

```bash
python main.py --help
python main.py fetch --all
python main.py signal 7974
python main.py backtest 7974 --all-strategies
```

### 程序化读取数据（与当前源码一致）

```python
from src.data.stock_data_manager import StockDataManager

# 读取本地数据（无需API）
manager = StockDataManager()

features = manager.load_stock_features("7974")
metadata = manager.load_metadata("7974")

print(features.tail(1))
print(metadata)
```

## 当前实现（源码对齐）

### 数据抓取与更新

- 冷启动抓取最近约 5 年日线数据（`fetch_and_update_ohlc`）
- 增量模式按最后日期继续抓取并去重
- 请求限速与重试：1 秒节流、429 重试

### 策略与回测矩阵

- Entry 策略：`SimpleScorerStrategy` / `EnhancedScorerStrategy` / `MACDCrossoverStrategy` / `BollingerSqueezeStrategy` / `IchimokuStochStrategy`
- Exit 策略：`ATRExitStrategy` / `ScoreBasedExitStrategy` / `LayeredExitStrategy` / `BollingerDynamicExit` / `ADXTrendExhaustionExit`
- `--all-strategies` 为 5×5 共 25 组合（来自 `src/utils/strategy_loader.py`）

### 落盘文件（实际命名）

- `data/raw_prices/{ticker}.parquet`
- `data/features/{ticker}_features.parquet`
- `data/raw_trades/{ticker}_trades.parquet`
- `data/raw_financials/{ticker}_financials.parquet`
- `data/metadata/{ticker}_metadata.json`
- `data/benchmarks/topix_daily.parquet`

### evaluate 输出（实际命名）

- `{output_dir}/strategy_evaluation_raw_{timestamp}.csv`
- `{output_dir}/strategy_evaluation_by_regime_{timestamp}.csv`
- `{output_dir}/strategy_evaluation_report_{timestamp}.md`

## Development

### Running Tests

```bash
pytest tests/
```

### 文档入口

- 快速开始：`docs/QUICKSTART.md`
- 使用指南：`docs/USAGE_GUIDE.md`
- 回测配置：`docs/BACKTEST_CONFIG_GUIDE.md`
- 策略评估：`docs/STRATEGY_EVALUATION_GUIDE.md`

## License

MIT License

## Contributing

Pull requests welcome! Please ensure tests pass and follow PEP 8.

## Contact

For questions about J-Quants API: https://jpx-jquants.com/
