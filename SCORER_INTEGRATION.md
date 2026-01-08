# Stock Signal Scorer - Integration Summary

## Overview

The `scorer.py` module has been successfully integrated into the J-Stock-Analyzer environment with **minimal necessary changes** to preserve its original logic.

## Changes Made

### 1. Data Type Handling (CRITICAL FIX)

**File:** `src/analysis/scorer.py`  
**Function:** `_calc_fundamental_score()`

**Problem:** The J-Quants API returns financial data (`Sales`, `OP`) as strings, not numbers.

**Solution:** Added `pd.to_numeric()` conversion with null-safety checks:

```python
# Convert to numeric (columns are stored as strings)
latest_sales = pd.to_numeric(latest['Sales'], errors='coerce')
prev_sales = pd.to_numeric(prev['Sales'], errors='coerce')
latest_op = pd.to_numeric(latest['OP'], errors='coerce')
prev_op = pd.to_numeric(prev['OP'], errors='coerce')

# Revenue Growth Check with null safety
if pd.notna(latest_sales) and pd.notna(prev_sales) and latest_sales > prev_sales:
    score += 15
```

**Logic Preserved:** ✅ Original scoring algorithm unchanged, only data access layer modified.

---

## Verification Results

### Test Run (All 11 Tickers)

```
[OK] 8035:  68.0/100 - BUY
[OK] 8306:  65.0/100 - BUY
[OK] 7974:  48.0/100 - NEUTRAL
[OK] 7011:  58.0/100 - NEUTRAL
[OK] 6861:  48.0/100 - NEUTRAL
[OK] 8058:  65.0/100 - BUY
[OK] 6501:  71.0/100 - BUY         <-- TOP SCORE
[OK] 4063:  69.0/100 - BUY
[OK] 7203:  58.0/100 - NEUTRAL
[OK] 4568:  51.0/100 - NEUTRAL
[OK] 6098:  64.0/100 - NEUTRAL

Successfully tested 11/11 tickers ✅
```

### Top 3 Stocks (by Score)

1. **6501** (Hitachi): 71.0/100 - BUY
2. **4063** (Shin-Etsu Chemical): 69.0/100 - BUY
3. **8035** (Tokyo Electron): 68.0/100 - BUY

---

## Scorer Algorithm (Preserved)

### Composite Score Formula

```
Total Score = Technical (40%) + Institutional (30%) + Fundamental (20%) + Volatility (10%)
```

### Component Breakdown

#### 1. Technical Score (0-100)

- **Trend Alignment**: Perfect Order check (Price > EMA20 > EMA50 > EMA200)
- **RSI Logic**: Healthy trend (40-65), Overbought penalty (>75), Oversold potential (<30)
- **MACD Momentum**: Histogram and zero-line crossing analysis

#### 2. Institutional Score (0-100)

- **Focus**: Foreign investor flows (`FrgnBal` in `raw_trades`)
- **Timeframe**: Last 4 weeks
- **Logic**: Net buying = bullish, Accelerating buying = bonus, Selling = bearish penalty

#### 3. Fundamental Score (0-100)

- **Metrics**: Quarter-over-quarter Sales and Operating Profit growth
- **Margin Analysis**: Operating margin expansion bonus
- **Data Source**: `raw_financials` (quarterly reports)

#### 4. Volatility Score (0-100)

- **Volume Check**: Above 20-day SMA = high interest
- **Extension Penalty**: Price >5% above EMA20 = parabolic risk

#### 5. Risk Veto

- **Earnings Proximity**: If earnings date within 7 days → 50% penalty on technical score + "HOLD/WAIT" signal

---

## Signal Interpretation

| Score Range | Signal      | Meaning           |
| ----------- | ----------- | ----------------- |
| 80-100      | STRONG_BUY  | All systems green |
| 65-79       | BUY         | Favorable setup   |
| 46-64       | NEUTRAL     | Mixed signals     |
| 36-45       | SELL        | Weakening trend   |
| 0-35        | STRONG_SELL | Major red flags   |

**Special:** Any ticker with `EARNINGS_APPROACHING` flag → forced "HOLD/WAIT" regardless of score

---

## Usage Example

```python
from src.analysis.scorer import StockSignalScorer
import pandas as pd
import json

# Load data
df_features = pd.read_parquet('data/features/8035_features.parquet')
df_trades = pd.read_parquet('data/raw_trades/8035_trades.parquet')
df_financials = pd.read_parquet('data/raw_financials/8035_financials.parquet')

with open('data/metadata/8035_metadata.json', 'r') as f:
    metadata = json.load(f)

# Score the stock
scorer = StockSignalScorer()
result = scorer.evaluate("8035", df_features, df_trades, df_financials, metadata)

print(f"Score: {result.total_score}/100")
print(f"Signal: {result.signal_strength}")
print(f"Breakdown: {result.breakdown}")
print(f"Risk Flags: {result.risk_flags}")
```

---

## Data Compatibility

### Column Mappings (Verified)

| Scorer Variable      | J-Quants Column                              | Data Type       | Status                          |
| -------------------- | -------------------------------------------- | --------------- | ------------------------------- |
| `FrgnBal`            | `FrgnBal`                                    | float64         | ✅ Direct match                 |
| `Sales`              | `Sales`                                      | object (string) | ✅ Fixed with `pd.to_numeric()` |
| `OP`                 | `OP`                                         | object (string) | ✅ Fixed with `pd.to_numeric()` |
| Technical indicators | EMA_20/50/200, RSI, MACD, ATR, Volume_SMA_20 | float64         | ✅ Direct match                 |

---

## Test Files

1. **test_scorer.py** - Comprehensive test across all 11 tickers with ranking output
2. **examples.py** - Contains usage patterns for the scorer

Run tests:

```bash
python test_scorer.py
```

---

## Next Steps (User Decision)

1. ✅ **Scorer Integration** - COMPLETE
2. 🔲 **LLM Prompt Generation** - Use scorer results to create Gemini prompts
3. 🔲 **Batch Scoring Pipeline** - Automate daily scoring for all tickers
4. 🔲 **Alerting System** - Notify when scores cross thresholds
5. 🔲 **Backtesting** - Validate scoring accuracy against historical returns

---

## Important Notes

- **No Logic Changes**: The scoring algorithm remains exactly as designed
- **Only Modification**: Added type conversion for J-Quants string-type numeric columns
- **Fully Compatible**: Works with all 11 target tickers in the data lake
- **Production Ready**: Error handling and null-safety already built-in
