# J-Stock-Analyzer

日本股票量化分析系统 - 基于 J-Quants API 的数据抓取、策略回测与信号生成平台

## ✨ 核心功能

### 1. 📥 数据抓取

- 从 J-Quants API 自动获取日本股票数据
- 支持增量更新，减少 API 调用
- Parquet 格式存储，高效读写

### 2. 🎯 策略信号生成

- 基于技术指标和综合评分的入场判断
- 支持多种出场策略（ATR/分数衰减/分层控制/Bollinger动态/ADX趋势穷尽）
- 实时生成交易信号

### 3. 📊 回测分析

- **单股票回测** - 全仓交易模拟
- **组合投资回测** - 多股票分散投资（最多 5 只同时持仓）
- 双基准对比：Buy&Hold vs TOPIX
- 完整性能指标：夏普比率、最大回撤、择时 Alpha、选股 Alpha

### 4. 🔬 策略综合评价 (新增)

- **多时段评估**：支持月度、季度、整年、自定义时间段
- **Period标签**：所有报表中清晰区分不同时段的相同策略表现
- **市场环境分类**：按 TOPIX 收益率自动分类（熊市/温和牛市/强势牛市等）
- **完整报告**：Markdown 报告 + 原始数据 CSV + 按市场环境分组的 CSV
- **跨期分析**：对比同一策略在不同市场环境下的表现

### 5. 🌐 宇宙选股

- 从 1,658 只 JPX 上市公司中评分筛选
- 基于 5 维度百分位排序（波动率、流动性、趋势、动量、成交量）
- 输出监视列表供实时信号生成使用

## 🚀 快速开始

### 统一 CLI 命令

```bash
# 查看所有可用命令
python main.py --help

# 1. 数据抓取
python main.py fetch --all                    # 抓取监视列表所有股票
python main.py fetch --tickers 7974 8035      # 抓取指定股票

# 2. 生成交易信号（新功能）
python main.py signal 7974                    # 生成今日信号
python main.py signal 7974 --date 2026-01-08  # 指定日期

# 3. 单股票回测
python main.py backtest 7974                  # 使用默认策略
python main.py backtest 7974 \
  --entry EnhancedScorerStrategy \
  --exit LayeredExitStrategy

# 4. 组合投资回测
python main.py portfolio --all                # 回测监视列表所有股票
python main.py portfolio --tickers 7974 8035 6501

# 5. 宇宙选股 (Universe Selection)
python main.py universe                       # 从1658只JPX股票中评分和筛选

# 6. 策略综合评价 (Strategy Evaluation) ⭐ 新功能
# 月度回测多个时段的多种策略组合（新的period标签增强）
python main.py evaluate --mode monthly \
  --years 2024 2025 \
  --months 1 2 3                              # 2024-01, 2024-02, ... 2025-03

# 年度评估
python main.py evaluate --mode annual \
  --years 2023 2024 2025

# 季度评估
python main.py evaluate --mode quarterly \
  --years 2024 2025

# 自定义时间段评估
python main.py evaluate --mode custom \
  --custom-periods '[["2024-Q1","2024-01-01","2024-03-31"],["2024-Q2","2024-04-01","2024-06-30"]]'
```

详细使用方法请参阅 [QUICKSTART.md](QUICKSTART.md) 和 [STRATEGY_EVALUATION_QUICK_START.md](STRATEGY_EVALUATION_QUICK_START.md)

## 📁 项目架构（全新）

```
j-stock-analyzer/
├── src/
│   ├── client/
│   │   ├── __init__.py
│   │   └── jquants_client.py           # J-Quants API V2 wrapper
│   ├── data/
│   │   ├── __init__.py
│   │   ├── stock_data_manager.py       # Core business logic
│   │   ├── benchmark_manager.py        # TOPIX benchmark管理
│   │   ├── universe_selector.py        # 宇宙选股
│   │   └── pipeline.py                 # 数据抓取管道
│   ├── analysis/
│   │   ├── scorers/                    # 入场策略 (SimpleScorerStrategy, EnhancedScorerStrategy等)
│   │   ├── exiters/                    # 出场策略 (ATRExitStrategy, LayeredExitStrategy等)
│   │   ├── base_scorer.py              # 基础评分接口
│   │   ├── base_exiter.py              # 基础出场接口
│   │   └── technical_indicators.py     # 技术指标计算
│   ├── backtest/
│   │   ├── single_engine.py            # 单股票回测引擎
│   │   └── portfolio_engine.py         # 组合投资回测引擎
│   ├── evaluation/
│   │   └── strategy_evaluator.py       # 策略综合评价系统 (支持period标签)
│   ├── utils/
│   │   ├── __init__.py
│   │   └── helpers.py
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   └── main.py                         # Entry point with 6 CLI commands
├── data/
│   ├── features/                       # Daily OHLCV + 14 technical indicators
│   ├── raw_trades/                     # Weekly institutional flows
│   ├── raw_financials/                 # Quarterly fundamentals
│   ├── benchmarks/                     # TOPIX daily data
│   ├── metadata/                       # Earnings calendar & company info
│   ├── universe/                       # Universe selection results
│   └── monitor_list.json               # 61-stock tracking list
├── strategy_evaluation/                # Strategy evaluation outputs (ignored by git)
│   ├── strategy_evaluation_report_*.md  # Markdown reports with period labels
│   ├── strategy_evaluation_raw_*.csv    # Raw strategy metrics
│   └── strategy_evaluation_by_regime_*.csv  # Results grouped by market environment
├── tests/
├── .env.example
├── requirements.txt
├── setup.py
├── main.py                             # Unified CLI entry point
├── QUICKSTART.md                       # Quick start guide
├── STRATEGY_EVALUATION_QUICK_START.md  # Strategy evaluation guide
└── README.md
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

### Basic Example

```bash
python src/main.py
```

This will:

1. Fetch/update data for Sony (6758) and Toyota (7203)
2. Calculate technical indicators
3. Generate structured analysis prompts

### Programmatic Usage

```python
from src.data.stock_data_manager import StockDataManager
import os

# Initialize
manager = StockDataManager(api_key=os.getenv('JQUANTS_API_KEY'))

# Generate analysis prompt
prompt = manager.generate_llm_prompt('6758')  # Sony
print(prompt)
```

### Sample Output

```
# Input Data
- **Ticker:** 6758
- **Price:** ¥12,450.00
- **Trend:** Above EMA200 (Price: 12450.00, EMA200: 11800.00)

## 1. Market Context (The Dice)
- **Foreign Investors (Weekly):** ¥1,234,567,890 (Buying)
- **TOPIX Correlation:** Strong (0.78)
- **Next Earnings Date:** 2026-02-10 (WARNING: 33 days left)

## 2. Technicals
- **RSI:** 62.34
- **MACD:** 0.0123

## 3. Fundamentals
- **Op. Profit:** ¥890,000M
```

## Key Features

### 1. Incremental Updates

- **Cold Start**: Fetches 2 years of historical data
- **Incremental**: Only fetches new data since last update
- **Deduplication**: Automatic handling of overlapping data

### 2. Five Critical Datasets

| Dataset           | Endpoint                         | Purpose              |
| ----------------- | -------------------------------- | -------------------- |
| Daily Bars        | `/v2/equities/bars/daily`        | OHLC price data      |
| Investor Types    | `/v2/equities/investor-types`    | Foreign/Retail flows |
| Earnings Calendar | `/v2/equities/earnings-calendar` | Risk event dates     |
| TOPIX Index       | `/v2/indices/bars/daily/topix`   | Market correlation   |
| Financial Summary | `/v2/fins/summary`               | Fundamentals check   |

### 3. Technical Indicators

- **EMA**: 20, 50, 200-period
- **RSI**: 14-period
- **MACD**: 12/26/9 configuration
- **ATR**: 14-period volatility
- **Bollinger Bands**, **Ichimoku**, **Stochastic** (in strategy variants)

### 4. Entry Strategies (Scorers)

- **SimpleScorerStrategy**: Basic 4-factor scoring (Technical/Institutional/Fundamental/Volatility)
- **EnhancedScorerStrategy**: Improved weighting and edge detection
- **MACDCrossoverStrategy**: MACD-based entry signals
- **BollingerSqueezeStrategy**: Bollinger Band squeeze detection
- **IchimokuStochStrategy**: Ichimoku cloud + Stochastic hybrid

### 5. Exit Strategies (Exiters)

- **ATRExitStrategy**: ATR-based trailing stops
- **LayeredExitStrategy**: Multi-layer profit-taking (P1 25%, P2 50%, P3 100%)
- **BollingerDynamicExit**: Dynamic exits based on Bollinger Band width
- **ADXTrendExhaustionExit**: ADX trend strength exhaustion detection
- **ScoreBasedExitStrategy**: Exits when score drops below threshold

### 6. Rate Limiting

- Automatic 1-second delays between requests
- Retry logic for 429 (Too Many Requests) errors
- Graceful degradation on missing data

## Data Storage

### Parquet Files

Data is stored in `./data/` with naming convention:

- OHLC: `{code}_ohlc.parquet`
- Columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`

### Why Parquet?

- **Fast**: Columnar format optimized for analytics
- **Compact**: 10x smaller than CSV
- **S3-Ready**: Can easily migrate to cloud storage

## Development

### Running Tests

```bash
pytest tests/
```

### Code Standards

- ✅ Type hints on all methods
- ✅ Docstrings explaining logic
- ✅ Error handling with logging
- ✅ PEP 8 compliant

### Extending the System

To add new indicators:

```python
# In stock_data_manager.py -> add_indicators()
df['YOUR_INDICATOR'] = ta.your_function(df['Close'])
```

To add new data sources:

```python
# In jquants_client.py
def get_new_endpoint(self, params):
    return self._make_request('/v2/new/endpoint', params)
```

## Troubleshooting

### "No data returned for {code}"

- Check if stock code is correct (e.g., '6758' not 'SONY')
- Verify API key is valid
- Check if market is open (data lags by 1 day)

### "Rate limit hit (429)"

- System will auto-retry after 5 seconds
- Consider reducing number of concurrent tickers

### "Investor data not available"

- This is normal - data is weekly and may lag
- System handles gracefully with "N/A" fallback

## Roadmap

- [x] Multi-strategy backtest framework (5 scorers × 5 exiters = 25 combinations)
- [x] Strategy comprehensive evaluation system with period labels
- [x] Universe selection from 1,658 JPX stocks
- [x] Portfolio-level backtesting with TOPIX benchmark
- [ ] Add more advanced indicators (CCI, Stochastic RSI)
- [ ] Implement screener for multi-stock filtering
- [ ] Add S3 storage backend for cloud deployment
- [ ] Create Streamlit dashboard for real-time monitoring
- [ ] Integrate ML-based scoring (LSTM/Transformer)
- [ ] AWS Lambda deployment (Phase 5 - Production pipeline)

## License

MIT License

## Contributing

Pull requests welcome! Please ensure tests pass and follow PEP 8.

## Contact

For questions about J-Quants API: https://jpx-jquants.com/

```
python src/main.py
```

This will initialize the `StockDataManager`, fetch data for the specified tickers, add technical indicators, and print the formatted prompts.

## Contributing

Contributions are welcome! Please submit a pull request or open an issue for any enhancements or bug fixes.

## License

This project is licensed under the MIT License. See the LICENSE file for details.
