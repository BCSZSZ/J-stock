# GitHub Copilot Instructions - J-Stock-Analyzer

## Project Overview

**J-Stock-Analyzer** is a production-grade Japanese stock trading system with:

- **Entry Logic:** Scoring strategies (SimpleScorer, EnhancedScorer)
- **Exit Logic:** Exit strategies (ATRExiter, LayeredExiter)
- **Backtesting:** Strategy performance evaluation framework
- **ML Pipeline:** Deep learning for strategy optimization (future)
- **Automation:** Daily cron job (local → AWS migration planned)

---

## System Architecture

### Current Structure

```
j-stock-analyzer/
├── src/
│   ├── client/          # J-Quants API V2 wrapper
│   ├── data/            # Data pipeline (incremental updates)
│   ├── analysis/
│   │   ├── scorers/     # Entry strategies (BaseScorer, SimpleScorer, EnhancedScorer)
│   │   ├── exiters/     # Exit strategies (BaseExiter, ATRExiter, LayeredExiter)
│   │   └── technical_indicators.py
│   ├── config/
│   └── utils/
├── data/                # Parquet data lake (features, trades, financials, metadata)
├── tests/
└── [test scripts]       # test_scorer.py, test_exit.py
```

### Data Lake (Parquet Files)

- **features/** - Daily OHLCV + technical indicators (~1,222 rows/stock)
- **raw_trades/** - Weekly institutional flows (~48 rows/stock)
- **raw_financials/** - Quarterly fundamentals (~20 rows/stock)
- **metadata/** - Earnings calendar, company info (JSON)

---

## Daily Workflow (Cron Job Target)

**Execution:** Daily 7:00 AM JST (after market data available)

### Step 1: Add New Stock to Monitor

- **Logic:** TBD (user will define criteria)
- **Action:** Add ticker to monitor list
- **Data:** Fetch 5-year historical data for newcomer

### Step 2: Data Update

- **Newcomers:** Full 5-year historical fetch
- **Existing:** Incremental update
- **Endpoints:**
  - Daily bars (OHLCV)
  - Investor types (institutional flows)
  - Financials (quarterly reports)
  - Earnings calendar (risk events)

### Step 3: Run Scorer (Entry Evaluation)

- **Strategy:** TBD by user at runtime
- **Input:** Latest data for all monitored stocks
- **Output:** Score (0-100), signal (BUY/NEUTRAL/SELL), breakdown

### Step 4: Run Exiter (Position Management)

- **Strategy:** TBD by user at runtime
- **Input:** Current holdings (user-provided position list)
- **Output:** ExitSignal (HOLD/SELL_X%, urgency, reason)

### Step 5: Generate Daily Report

- **Format:** Markdown or HTML email
- **Contents:**
  - Market summary (TOPIX, sector rotation)
  - New BUY signals (sorted by score)
  - Exit recommendations for current holdings
  - Risk alerts (earnings approaching, institutional exodus)

---

## Backtest Framework (Utility Function)

**Purpose:** Evaluate strategy performance over historical data

### Interface

```python
def backtest_strategy(
    ticker: str,
    scorer_class: Type[BaseScorer],
    exiter_class: Type[BaseExiter],
    start_date: str,
    end_date: str,
    initial_capital: float
) -> BacktestResult:
    """
    Backtest a scorer+exiter combination on historical data.

    Returns:
        BacktestResult with metrics:
        - Total return %
        - Sharpe ratio
        - Max drawdown
        - Win rate
        - Avg gain/loss per trade
        - Number of trades
    """
```

### Workflow

1. Load historical data (features, trades, financials)
2. Iterate day-by-day:
   - If no position: Run scorer, enter if score ≥65
   - If in position: Run exiter, exit if signal != HOLD
3. Track: Entry/exit prices, holding periods, P&L
4. Calculate: Sharpe, drawdown, win rate, etc.

---

## Deep Learning Pipeline (Future)

**Goal:** Train neural networks to improve scoring/exit strategies

### Phase 1: Feature Engineering

- Input features: Technical (EMA, RSI, MACD), Fundamental (EPS, Sales), Institutional (flows)
- Output target: Future return (1-week, 1-month, 3-month)

### Phase 2: Model Training

- Architecture: LSTM or Transformer for time series
- Loss: Directional accuracy + Sharpe optimization
- Validation: Walk-forward (train 2021-2023, test 2024-2025)

### Phase 3: Strategy Integration

- Create MLScorer (inherits BaseScorer)
- Create MLExiter (inherits BaseExiter)
- Compare to rule-based strategies in backtest

---

## Coding Standards

### Architecture Patterns

- **Strategy Pattern:** All scorers inherit `BaseScorer`, all exiters inherit `BaseExiter`
- **Abstract Base Classes:** Use `ABC` and `@abstractmethod` for interfaces
- **Dataclasses:** Use `@dataclass` for data transfer objects (`ScoreResult`, `ExitSignal`, `Position`)

### File Organization

- **One class per file:** `simple_scorer.py` contains only `SimpleScorer`
- **Folders for categories:** `scorers/`, `exiters/`, `backtesting/` (future)
- **Package exports:** `__init__.py` exports all public classes

### Import Style

```python
# Recommended (modular)
from src.analysis.scorers import SimpleScorer, EnhancedScorer
from src.analysis.exiters import ATRExiter, LayeredExiter

# Backward compatible (deprecated)
from src.analysis.scorer import SimpleScorer  # Still works via redirect
```

### Naming Conventions

- **Classes:** PascalCase (`SimpleScorer`, `ATRExiter`)
- **Methods:** snake_case (`evaluate_exit`, `_check_emergency`)
- **Private methods:** Leading underscore (`_calc_technical_score`)
- **Constants:** UPPER_SNAKE (`EMERGENCY_EXIT_TRIGGERS`)

### Type Hints

- **Always use type hints:** Function signatures must have types
- **Return types required:** Especially for public methods

```python
def evaluate_exit(self, position: Position, ...) -> ExitSignal:
    ...
```

### Documentation

- **Docstrings:** All public classes/methods must have docstrings
- **Inline comments:** Explain WHY not WHAT (code explains what)
- **Japanese market context:** Note cultural/regulatory specifics

```python
# Japanese companies are conservative with guidance → beats are strong signals
if beat_ratio > 1.02:  # Beat by 2%+
    score += 15
```

---

## Japanese Stock Market Specifics

### Cultural Context

- **Conservative guidance:** Companies under-promise, over-deliver
- **Earnings gaps:** Avg 8-12% (vs 4-6% US) - don't hold overnight
- **Retail = contrarian indicator:** Retail buying at tops = warning sign

### Data Characteristics

- **Foreign investors:** 30% of volume, trend leaders
- **Trust banks (TrstBnkBal):** Pension funds, long-term smart money
- **Retail (IndBal):** Contrarian, fade at extremes
- **Proprietary traders (PropBal):** Fast money, short-term

### Technical Differences

- **Lower volatility:** Avg daily move ~1.2% (vs 1.8% US)
- **ATR usage critical:** Fixed % stops don't work (vary by sector)
- **EMA200 significance:** Strong support/resistance level

---

## Position Management

### Position Tracking

User will provide current holdings via:

- Manual list (CSV, JSON)
- OR database table (future)
- OR portfolio tracker integration (future)

**Required fields:**

```python
Position(
    ticker="8035",
    entry_price=31861,
    entry_date="2025-12-09",
    entry_score=75.0,
    quantity=100,
    peak_price_since_entry=37373  # Track for trailing stops
)
```

### Exit Execution

- System generates `ExitSignal`
- User executes manually (current)
- Auto-execution via broker API (future)

---

## AWS Migration Plan (Future)

### Current: Local Cron

```bash
# crontab -e
0 7 * * * /path/to/venv/bin/python /path/to/daily_pipeline.py
```

### Future: AWS Architecture

- **Lambda:** Daily trigger (CloudWatch Events)
- **S3:** Data lake storage (replace local Parquet)
- **DynamoDB:** Position tracking, monitor list
- **SES:** Email reports
- **SageMaker:** ML model training/inference

---

## Critical Rules for Copilot

### ❌ NEVER DO (Unless Explicitly Asked)

1. **Do NOT create markdown files** - Code and docstrings only
2. **Do NOT modify scorer/exiter base classes** - Extend, don't change
3. **Do NOT use fixed % for stops** - Always use ATR multipliers
4. **Do NOT ignore earnings dates** - Japanese gaps are brutal
5. **Do NOT remove backward compatibility** - Keep old import paths working

### ✅ ALWAYS DO

1. **Use type hints** - Every function signature
2. **Add docstrings** - Explain purpose and Japanese market context
3. **Test before commit** - Run test_scorer.py, test_exit.py
4. **Update **init**.py** - When adding new strategies
5. **Consider ATR** - Price-based decisions must account for volatility
6. **Track peak price** - Required for trailing stops

### 🎯 When Implementing New Strategies

```python
# Scorer example
class MomentumScorer(BaseScorer):
    """Focus on price momentum and volume."""

    def __init__(self):
        super().__init__(strategy_name="Momentum_v1")

    def _get_weights(self) -> Dict[str, float]:
        return {"technical": 0.6, "institutional": 0.2, "fundamental": 0.1, "volatility": 0.1}

    # Implement all @abstractmethod from BaseScorer
    def _calc_technical_score(self, row, df_features) -> float: ...
    def _calc_institutional_score(self, df_trades, current_date) -> float: ...
    def _calc_fundamental_score(self, df_fins) -> float: ...
    def _calc_volatility_score(self, row, df_features) -> float: ...

# Then add to scorers/__init__.py
from .momentum_scorer import MomentumScorer
__all__ = [..., 'MomentumScorer']
```

### 🔍 When Debugging

1. Check test scripts first (test_scorer.py, test_exit.py)
2. Verify data files exist (data/features/, data/raw_trades/, etc.)
3. Check for encoding issues (use `encoding='utf-8'` for JSON)
4. Print score breakdown to diagnose which component is failing

### 📊 When Adding Metrics

- Sharpe ratio = (Return - RiskFreeRate) / StdDev
- Max drawdown = Peak-to-trough decline
- Win rate = Winning trades / Total trades
- Expectancy = (AvgWin × WinRate) - (AvgLoss × LossRate)

---

## Quick Reference

### Run Tests

```bash
# Activate venv
.\venv\Scripts\Activate.ps1  # Windows
source venv/bin/activate      # Linux/Mac

# Test scorers
python test_scorer.py

# Test exiters
python test_exit.py
```

### Add New Stock Data

```python
from src.data.stock_data_manager import StockDataManager

manager = StockDataManager(api_key="your_key")
manager.update_stock("8035")  # Full 2-year fetch if new
```

### Check Current Scores

```python
from src.analysis.scorers import EnhancedScorer
scorer = EnhancedScorer()
result = scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
print(result.total_score, result.signal_strength)
```

### Evaluate Exit

```python
from src.analysis.exiters import ATRExiter, Position
exiter = ATRExiter()
signal = exiter.evaluate_exit(position, df_features, df_trades, df_financials, metadata, current_score)
print(signal.action, signal.reason)
```

---

## Version History

- **v0.1.0** - Initial scorer integration
- **v0.2.0** - Modular scorer refactor (BaseScorer + strategies)
- **v0.3.0** - Exit strategy framework (BaseExiter + ATR/Layered)
- **v0.4.0** - Daily pipeline (planned)
- **v0.5.0** - Backtest framework (planned)
- **v1.0.0** - ML pipeline (planned)

---

## Context for LLM

**When user says "add to monitor list":**

- Means: Add ticker to tracking system
- Action: Fetch historical data + add to daily evaluation

**When user says "run the pipeline":**

- Means: Steps 1-5 of daily workflow
- Action: Update data → Score all → Check exits → Generate report

**When user says "backtest this":**

- Means: Historical performance evaluation
- Action: Run scorer+exiter combo over past 5 years, return metrics

**When user mentions AWS:**

- Means: Future deployment target
- Don't implement AWS yet, but keep architecture cloud-ready (stateless, config-driven)

---

## Remember

This is a **real trading system** for Japanese equities. Code quality matters:

- ❌ No untested strategies
- ❌ No magic numbers (use constants with explanations)
- ❌ No "TODO" without GitHub issue
- ✅ Test on real data (we have 11 tickers: 8035, 8306, 7974, 7011, 6861, 8058, 6501, 4063, 7203, 4568, 6098)
- ✅ Consider earnings calendar (Japanese gaps are 2-3x US)
- ✅ Respect institutional flows (they lead the market)

**Final Rule:** When in doubt, ask user. Don't guess about strategy logic or risk parameters.
