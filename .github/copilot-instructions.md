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

---

## **CRITICAL: Interface Contracts & Data Structures**

> **WHY THIS SECTION EXISTS:**  
> We encountered multiple type mismatch bugs during backtest implementation because components expected different data formats. This section documents ALL interfaces to prevent future mismatches.

### 1. **Data Source Interfaces (StockDataManager)**

#### Raw Data Files (Parquet)

**features/{ticker}_features.parquet**
```python
# Columns (from compute_features):
Date: datetime64[ns]          # Trading date (INDEX after engine loads it)
Open: float64                 # Opening price
High: float64                 # Daily high
Low: float64                  # Daily low
Close: float64                # Closing price
Volume: int64                 # Trading volume
EMA_20: float64              # 20-day EMA
EMA_50: float64              # 50-day EMA
EMA_200: float64             # 200-day EMA
RSI: float64                 # 14-day RSI (0-100)
MACD: float64                # MACD line
MACD_Signal: float64         # Signal line
MACD_Hist: float64           # Histogram
ATR: float64                 # 14-day ATR
Volume_SMA_20: float64       # 20-day volume average

# Typical size: ~1,222 rows (5 years daily data)
# Usage: Set Date as index in backtest engine
```

**raw_trades/{ticker}_trades.parquet**
```python
# Columns (from API, filtered to TSEPrime):
EnDate: datetime64[ns]       # Week ending date (COLUMN, not index)
Section: str                 # Market section (filter to "TSEPrime")
InvestorCode: str           # Investor type code
PurchaseValue: int64        # Buy volume (¥)
SalesValue: int64           # Sell volume (¥)
BalanceValue: int64         # Net flow (¥)

# Typical size: ~48 rows (weekly data, ~6 investor types × 52 weeks ÷ 6)
# Usage: Scorers filter by current_date, keep EnDate as column
```

**raw_financials/{ticker}_financials.parquet**
```python
# Columns (from API):
DiscDate: datetime64[ns]     # Disclosure date (COLUMN, not index)
Quarter: str                 # FY quarter (e.g., "Q2")
TotalAssets: float64        # Total assets (¥ millions)
Equity: float64             # Shareholders equity
Revenue: float64            # Quarterly revenue
OperatingProfit: float64    # Operating profit
NetIncome: float64          # Net income
EPS: float64                # Earnings per share
ROE: float64                # Return on equity (%)
ROA: float64                # Return on assets (%)
DebtRatio: float64          # Debt/Equity ratio

# Typical size: ~20 rows (quarterly data, 5 years)
# Usage: Scorers filter by DiscDate <= current_date
```

**metadata/{ticker}_metadata.json**
```python
{
  "earnings_calendar": [
    {
      "Date": "2026-02-15",      # ISO format string
      "EventType": "Quarterly",
      "FiscalQuarter": "Q3"
    }
  ]
}
# Usage: Check earnings proximity for risk flags
```

#### DataFrame Contracts for Scorers/Exiters

**When BacktestEngine calls scorer.evaluate():**
```python
df_features: pd.DataFrame
    - Date is INDEX (pd.DatetimeIndex)
    - All technical columns present
    - Forward-filled (no gaps)

df_trades: pd.DataFrame
    - EnDate is COLUMN (not index)
    - Filtered to TSEPrime section
    - May be empty

df_financials: pd.DataFrame
    - DiscDate is COLUMN (not index)
    - May be empty

metadata: dict
    - Parsed JSON
    - May have empty earnings_calendar list
```

---

### 2. **Scorer Interface (BaseScorer)**

#### Input Contract

```python
class BaseScorer(ABC):
    def evaluate(
        self,
        ticker: str,
        df_features: pd.DataFrame,     # Date as INDEX
        df_trades: pd.DataFrame,       # EnDate as COLUMN
        df_financials: pd.DataFrame,   # DiscDate as COLUMN
        metadata: dict
    ) -> ScoreResult:
```

#### Output Contract

```python
@dataclass
class ScoreResult:
    ticker: str                    # Stock code
    total_score: float            # 0-100 (THIS IS THE NUMERIC VALUE)
    signal_strength: str          # "STRONG_BUY", "BUY", "NEUTRAL", "SELL", "STRONG_SELL"
    breakdown: Dict[str, float]   # Component scores (Technical: 75.2, etc.)
    risk_flags: List[str]         # ["EARNINGS_APPROACHING", "HIGH_VOLATILITY"]
    strategy_name: str            # "SimpleScorer", "EnhancedScorer"
```

**⚠️ CRITICAL TYPE HANDLING:**
```python
# WRONG (causes comparison errors):
if current_score > 70:  # current_score is ScoreResult object!

# CORRECT (extract numeric value):
if isinstance(current_score, ScoreResult):
    score_value = current_score.total_score
else:
    score_value = current_score

if score_value > 70:  # Now it's a float
```

#### Abstract Methods to Implement

```python
@abstractmethod
def _get_weights(self) -> Dict[str, float]:
    """Return {"technical": 0.4, "institutional": 0.2, "fundamental": 0.2, "volatility": 0.2}"""

@abstractmethod
def _calc_technical_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
    """Return 0-100 based on EMA crossovers, RSI, MACD"""

@abstractmethod
def _calc_institutional_score(self, df_trades: pd.DataFrame, current_date: pd.Timestamp) -> float:
    """Return 0-100 based on investor flows in last 4 weeks"""

@abstractmethod
def _calc_fundamental_score(self, df_fins: pd.DataFrame) -> float:
    """Return 0-100 based on ROE, growth, debt ratio"""

@abstractmethod
def _calc_volatility_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
    """Return 0-100 based on ATR, volatility patterns"""
```

---

### 3. **Exiter Interface (BaseExiter)**

#### Input Contract

```python
@dataclass
class Position:
    ticker: str
    entry_price: float
    entry_date: pd.Timestamp              # ⚠️ MUST be Timestamp, not string!
    entry_score: float
    quantity: int
    peak_price_since_entry: Optional[float] = None  # Track for trailing stops
```

**⚠️ CRITICAL: Entry Date Type**
```python
# WRONG (causes date arithmetic errors):
position = Position(
    entry_date="2025-01-15",  # String!
)

# CORRECT:
position = Position(
    entry_date=pd.Timestamp("2025-01-15"),  # Timestamp object
)
```

#### Evaluation Method

```python
class BaseExiter(ABC):
    @abstractmethod
    def evaluate_exit(
        self,
        position: Position,
        df_features: pd.DataFrame,      # Date as INDEX
        df_trades: pd.DataFrame,        # EnDate as COLUMN
        df_financials: pd.DataFrame,    # DiscDate as COLUMN
        metadata: dict,
        current_score: ScoreResult      # ⚠️ This is ScoreResult object, not float!
    ) -> ExitSignal:
```

**⚠️ CRITICAL: ScoreResult Handling in Exiters**
```python
def evaluate_exit(self, position, df_features, df_trades, df_financials, metadata, current_score):
    # MUST extract numeric value at start!
    from ..scorers.base_scorer import ScoreResult
    
    if isinstance(current_score, ScoreResult):
        score_value = current_score.total_score
        score_breakdown = current_score.breakdown
    else:
        score_value = current_score
    
    # Now use score_value for all comparisons
    if score_value < 40:  # ✅ Correct
        return self._create_signal(...)
```

#### Output Contract

```python
@dataclass
class ExitSignal:
    ticker: str
    action: str              # "HOLD", "SELL_25%", "SELL_50%", "SELL_75%", "SELL_100%"
    urgency: str            # "LOW", "MEDIUM", "HIGH", "EMERGENCY"
    reason: str             # Human-readable explanation
    triggered_by: str       # "P0_StopLoss", "Layer3_Profit", etc.
    current_price: float
    current_score: float    # ⚠️ Store the NUMERIC value here (not ScoreResult)
    entry_price: float
    entry_score: float
    profit_loss_pct: float  # Calculated: ((current - entry) / entry) * 100
    holding_days: int       # Calculated: (current_date - entry_date).days
```

---

### 4. **Backtest Engine Interface**

#### Trade Record

```python
@dataclass
class Trade:
    entry_date: str          # ISO format "YYYY-MM-DD"
    entry_price: float
    entry_score: float       # Numeric score at entry (not ScoreResult)
    exit_date: str          # ISO format "YYYY-MM-DD"
    exit_price: float
    exit_reason: str        # From ExitSignal.reason
    exit_urgency: str       # From ExitSignal.urgency
    holding_days: int
    shares: int
    return_pct: float       # Percentage return
    return_jpy: float       # Yen return
    peak_price: float       # Highest price during hold
```

#### Backtest Result

```python
@dataclass
class BacktestResult:
    ticker: str
    ticker_name: str
    scorer_name: str
    exiter_name: str
    start_date: str
    end_date: str
    starting_capital_jpy: float
    
    # Performance Metrics
    final_capital_jpy: float
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    
    # Trade Statistics
    num_trades: int
    win_rate_pct: float
    avg_gain_pct: float
    avg_loss_pct: float
    avg_holding_days: float
    profit_factor: float
    
    # Benchmark (optional)
    benchmark_return_pct: Optional[float] = None
    alpha: Optional[float] = None
    beat_benchmark: Optional[bool] = None
    
    # Trade Details
    trades: List[Trade] = field(default_factory=list)
```

#### Engine Entry Point

```python
class BacktestEngine:
    def run(
        self,
        ticker: str,
        scorer: BaseScorer,      # Instance, not class
        exiter: BaseExiter,      # Instance, not class
        start_date: str,         # "YYYY-MM-DD"
        end_date: str           # "YYYY-MM-DD"
    ) -> BacktestResult:
```

---

### 5. **Common Type Pitfalls & Solutions**

#### Problem 1: ScoreResult vs float

**Symptom:** `'<' not supported between instances of 'ScoreResult' and 'int'`

**Root Cause:** Exiter receives ScoreResult object but treats it as float

**Solution:**
```python
# At start of evaluate_exit():
from ..scorers.base_scorer import ScoreResult

if isinstance(current_score, ScoreResult):
    score_value = current_score.total_score  # Extract float
else:
    score_value = current_score

# Use score_value for all numeric operations
```

#### Problem 2: String vs Timestamp for dates

**Symptom:** `unsupported operand type(s) for -: 'Timestamp' and 'str'`

**Root Cause:** Position.entry_date is string but code does date arithmetic

**Solution:**
```python
# When creating Position in backtest engine:
position = Position(
    ticker=ticker,
    entry_price=entry_price,
    entry_date=pd.Timestamp(entry_date),  # ✅ Convert to Timestamp
    entry_score=entry_score,
    quantity=shares
)
```

#### Problem 3: DataFrame index assumptions

**Symptom:** KeyError or unexpected filtering behavior

**Root Cause:** Code assumes Date is index but it's a column (or vice versa)

**Solution:**
```python
# Backtest engine MUST set Date as index for features:
df_features = pd.read_parquet(path)
if 'Date' in df_features.columns:
    df_features['Date'] = pd.to_datetime(df_features['Date'])
    df_features = df_features.set_index('Date')

# Scorers/Exiters MUST keep EnDate/DiscDate as columns:
# (Do NOT set as index - filtering logic expects columns)
```

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
