# J-Stock-Analyzer - Complete Usage Guide

## System Components

The system is **modular** - each component can be tested and used independently.

---

## 🗂️ 1. DATA FETCHING (main.py)

**Purpose:** Fetch and update stock data from J-Quants API

**What it does:**
- ✅ Loads tickers from `monitor_list.json`
- ✅ Fetches **incremental** OHLCV data (only missing days)
- ✅ Computes technical indicators (EMA, RSI, MACD, ATR)
- ✅ Fetches financials, institutional flows, earnings calendar
- ❌ Does NOT run scoring, exit strategies, or backtesting

**Usage:**
```powershell
# Fetch/update data for all stocks in monitor list
python src/main.py
```

**Output:**
```
data/
├── features/          # {ticker}_features.parquet (OHLCV + indicators)
├── raw_prices/        # {ticker}.parquet (raw OHLCV)
├── raw_trades/        # {ticker}_trades.parquet (institutional flows)
├── raw_financials/    # {ticker}_financials.parquet (quarterly data)
└── metadata/          # {ticker}_metadata.json (earnings calendar)
```

**When to run:** 
- Daily (after market close ~7:00 AM JST)
- After adding new ticker to monitor_list.json
- Before running scorers/backtests

---

## 📊 2. SCORING STOCKS (test_scorer.py)

**Purpose:** Evaluate stocks using scoring strategies (SimpleScorer, EnhancedScorer)

**What it does:**
- ✅ Calculates 0-100 score for each stock
- ✅ Shows component breakdown (Technical, Institutional, Fundamental, Volatility)
- ✅ Identifies risk flags (earnings approaching, high volatility, etc.)
- ✅ Generates BUY/SELL signals based on score thresholds

**Usage:**

### Option 1: Test All Monitor List Stocks
```powershell
python test_scorer.py
# Press Enter to use default option 2
```

**Output:**
```
SUMMARY - All Stocks Ranked by Score
======================================================================
Ticker   Name                 Score    Signal           Risk Flags
----------------------------------------------------------------------
8035     Tokyo Electron        82.3    STRONG_BUY       -
6861     Keyence               78.1    BUY              -
7974     Nintendo              67.5    BUY              EARNINGS_APPROACHING
...
```

### Option 2: Test Single Ticker
```powershell
python test_scorer.py
# Enter 1
# Enter ticker: 8035
```

**Output:**
```
📊 Score Result:
  Ticker:         8035
  Total Score:    82.3/100
  Signal:         STRONG_BUY
  Strategy:       EnhancedScorer

🔍 Score Breakdown:
  Technical            85.2
  Institutional        78.5
  Fundamental          82.0
  Volatility           83.5

📈 Latest Data:
  Date:           2026-01-09
  Close:          ¥37,500
  RSI:            62.3
  MACD:           +125.50
```

### Option 3: Compare Scorers
```powershell
python test_scorer.py
# Enter 3
# Enter ticker: 8035
```

**When to use:**
- Daily - to identify new buy candidates
- Before entering a position
- To compare different scoring strategies

---

## 🚪 3. EXIT STRATEGY TESTING (test_exit.py)

**Purpose:** Test exit strategies on current or simulated positions

**What it does:**
- ✅ Evaluates whether to hold or sell a position
- ✅ Calculates profit/loss %
- ✅ Provides urgency level (LOW/MEDIUM/HIGH/EMERGENCY)
- ✅ Shows which rule triggered the exit (stop loss, profit target, score degradation, etc.)

**Usage:**

### Option 1: Test Sample Position
```powershell
python test_exit.py
# Press Enter for default
# Enter ticker: 8035
# Choose exiter: 3 (compare both)
```

**Output:**
```
📌 Sample Position Created (30 days ago):
  Entry Date:     2025-12-10
  Entry Price:    ¥31,861
  Entry Score:    75.0
  Quantity:       100 shares
  Peak Price:     ¥37,500

📊 Current Status:
  Current Date:   2026-01-09
  Current Price:  ¥37,200
  Current Score:  82.3/100
  P&L:            +16.75%
  Holding Days:   30

🚨 Exit Signal:
  Action:         SELL_50%
  Urgency:        MEDIUM
  Triggered By:   Layer3_Profit
  Reason:         +15% profit reached, lock in gains

💰 Financial Impact:
  P&L (¥):        ¥+533,900
  P&L (%):        +16.75%
```

### Option 2: Test Your Own Position
```powershell
python test_exit.py
# Enter 2
# Follow prompts to enter your position details
```

### Option 3: Compare ATR vs Layered
```powershell
python test_exit.py
# Enter 3
# Enter ticker
```

**When to use:**
- Daily - check if you should exit current holdings
- Before market open - plan your sells
- To compare exit strategies

---

## 📉 4. BACKTESTING (test_backtest.py)

**Purpose:** Test strategy performance on historical data (2021-2026)

**What it does:**
- ✅ Simulates buying/selling over 5 years
- ✅ Calculates total return %, Sharpe ratio, max drawdown
- ✅ Shows win rate, avg gain/loss per trade
- ✅ Compares multiple scorer+exiter combinations
- ✅ Generates detailed trade log

**Usage:**

### Method 1: Use Config File (Recommended)
```powershell
# Edit backtest_config.json to set:
# - Tickers to test
# - Date range
# - Strategy combinations
# - Starting capital

python test_backtest.py
```

**Config Example:**
```json
{
  "backtest_config": {
    "tickers": ["8035", "7974"],
    "start_date": "2021-01-01",
    "end_date": "2026-01-08",
    "starting_capital_jpy": 5000000
  },
  "strategies": [
    {"scorer": "SimpleScorer", "exiter": "LayeredExiter"},
    {"scorer": "EnhancedScorer", "exiter": "LayeredExiter"}
  ]
}
```

**Output:**
```
======================================================================
Backtest: 8035 (Tokyo Electron)
Strategy: SimpleScorer + LayeredExiter
Period: 2021-01-01 to 2026-01-08
======================================================================

💰 Capital:
  Starting: ¥5,000,000
  Ending:   ¥6,399,500
  Profit:   ¥1,399,500

📊 Returns:
  Total Return:      +27.99%
  Annualized:        +5.05%
  Sharpe Ratio:      1.61
  Max Drawdown:      -15.30%

📈 Trading:
  Trades:            149
  Win Rate:          53.0%
  Avg Gain:          +5.20%
  Avg Loss:          -3.10%
  Avg Hold:          1.4 days
  Profit Factor:     1.85
```

### Method 2: Custom Backtest Script
```python
from src.backtest.engine import BacktestEngine
from src.analysis.scorers import EnhancedScorer
from src.analysis.exiters import LayeredExiter

engine = BacktestEngine(starting_capital_jpy=5_000_000)

result = engine.run(
    ticker="8035",
    scorer=EnhancedScorer(),
    exiter=LayeredExiter(),
    start_date="2021-01-01",
    end_date="2026-01-08"
)

print(result.to_summary_string())
```

**When to use:**
- Before deploying a new strategy
- To compare different scorer/exiter combinations
- To validate system changes
- To analyze historical performance

---

## 📚 5. LEARNING EXAMPLES (examples.py)

**Purpose:** Interactive examples of data layer operations

**What it includes:**
- Example 1: Single stock ETL
- Example 2: Batch processing
- Example 3: Read data lake layers
- Example 4: Incremental update demo
- Example 5: Custom feature engineering
- Example 6: Daily update workflow
- Example 7: Stock screening

**Usage:**
```powershell
# Edit examples.py to uncomment the example you want
python examples.py
```

**When to use:**
- Learning how the system works
- Understanding data structures
- Building custom features

---

## 🔄 Typical Workflows

### Daily Trading Workflow

```powershell
# 1. Update data (morning after market data available)
python src/main.py

# 2. Score all stocks (find new opportunities)
python test_scorer.py
# -> Identify stocks with score >= 65 for potential buy

# 3. Check exit signals (manage current positions)
python test_exit.py
# -> Enter 2 (test your positions)
# -> Check each holding

# 4. Execute trades manually (or via broker API in future)
```

### Weekly Research Workflow

```powershell
# 1. Update data
python src/main.py

# 2. Run backtest on new strategy ideas
# Edit backtest_config.json with new combinations
python test_backtest.py

# 3. Compare results and choose best strategy

# 4. Update production strategy if improvement found
```

### Adding New Stock Workflow

```powershell
# 1. Add to monitor_list.json
# Edit data/monitor_list.json, add:
# {"code": "XXXX", "name": "Company", "sector": "...", ...}

# 2. Fetch data (will do full 5-year fetch for new stock)
python src/main.py

# 3. Score it
python test_scorer.py
# Enter 1, then ticker XXXX

# 4. Backtest it (optional)
# Edit backtest_config.json to include XXXX
python test_backtest.py
```

---

## 📋 File Reference

| File | Purpose | When to Run |
|------|---------|-------------|
| `src/main.py` | Fetch/update data | Daily/Weekly |
| `test_scorer.py` | Score stocks, find opportunities | Daily |
| `test_exit.py` | Check exit signals for holdings | Daily |
| `test_backtest.py` | Historical performance testing | As needed |
| `examples.py` | Learning/experimentation | As needed |

---

## 🎯 Quick Reference

### I want to...

**...get latest data for all stocks**
```powershell
python src/main.py
```

**...find buy opportunities**
```powershell
python test_scorer.py
# Press Enter (tests all stocks)
```

**...check if I should sell**
```powershell
python test_exit.py
# Enter 2 (test your position)
```

**...test a new strategy**
```powershell
# Edit backtest_config.json
python test_backtest.py
```

**...add a new stock**
```powershell
# 1. Edit data/monitor_list.json
# 2. python src/main.py
# 3. python test_scorer.py (score it)
```

---

## ⚠️ Important Notes

1. **Always fetch data first:** Run `python src/main.py` before scoring/testing
2. **Data is incremental:** Main.py only fetches missing days (fast)
3. **New stocks fetch 5 years:** First fetch for new ticker takes longer
4. **Scorers need data:** All strategies require features, trades, financials
5. **Backtests are slow:** Testing 5 years takes 1-2 minutes per ticker

---

## 🔧 Troubleshooting

**Error: "Features not found for {ticker}"**
- Solution: Run `python src/main.py` first to fetch data

**Error: "JQUANTS_API_KEY not found"**
- Solution: Create `.env` file with `JQUANTS_API_KEY=your_key_here`

**Backtest shows -99% return**
- This is ATRExiter with 100% position sizing (design issue, not bug)
- Use LayeredExiter instead or reduce position size

**Scorer returns 0.0 score**
- Check if data files exist in `data/` folders
- Verify ticker code is correct (4 digits, no prefix)

---

## 📞 Need Help?

Check the detailed documentation:
- [README.md](README.md) - Project overview
- [QUICKSTART.md](QUICKSTART.md) - Getting started
- [EXIT_STRATEGY_RESEARCH.md](EXIT_STRATEGY_RESEARCH.md) - Exit strategy details
- [DATA_LAKE_GUIDE.md](DATA_LAKE_GUIDE.md) - Data architecture
