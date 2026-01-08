# Stock Signal Scorer - Senior Trader Review

## Code Quality & Simplification Analysis

**Reviewer Perspective:** Senior Stock Trader + System Engineer  
**Review Date:** January 8, 2026  
**Objective:** Identify oversimplifications and missed opportunities

---

## EXECUTIVE SUMMARY

**Overall Assessment:** ⚠️ **FUNCTIONAL BUT SIMPLISTIC**

The scorer implements a solid conceptual framework (40% Technical, 30% Institutional, 20% Fundamental, 10% Volatility), but **significantly underutilizes available data** and employs **overly basic heuristics** in multiple areas.

**Critical Finding:** We have **107 fundamental columns, 39 investor flow columns, and 15 technical indicators** but only use a small fraction effectively.

---

## DETAILED FINDINGS

### 1. TECHNICAL SCORE (40% Weight) - Lines 88-115

**Status:** 🟡 **MODERATE SIMPLIFICATION**

#### What It Does:

- ✅ Perfect Order check (Price > EMA20 > EMA50 > EMA200)
- ✅ RSI overbought/oversold zones
- ⚠️ MACD histogram sign check only

#### Critical Simplifications:

**A. MACD Logic (Lines 110-115)**

```python
# Current Code:
if row['MACD_Hist'] > 0:
    score += 10
    if row['MACD'] > 0:
        score += 5
```

**Issues:**

- ❌ No crossover detection (MACD vs Signal line)
- ❌ No divergence analysis (price making new highs while MACD declining)
- ❌ Doesn't check if histogram is expanding or contracting
- 🔴 **Comment says "Histogram > 0 and expanding is bullish" but doesn't check expansion**

**Available But Unused:**

- We have `MACD`, `MACD_Signal`, `MACD_Hist` in data
- Could calculate: `recent_cross = (prev_MACD < prev_Signal) and (curr_MACD > curr_Signal)`
- Could check momentum: `histogram_expanding = curr_Hist > prev_Hist`

**Recommendation:** Need historical data (not just latest row) to implement properly

---

**B. RSI Logic (Lines 106-112)**

```python
if 40 <= rsi <= 65:
    score += 10  # Healthy trend
elif rsi > 75:
    score -= 10  # Overbought Risk
elif rsi < 30:
    score += 5   # Oversold bounce potential
```

**Issues:**

- ⚠️ Static thresholds (40/65/75/30) - not adaptive to volatility regimes
- ❌ No divergence check (RSI making lower lows while price making higher highs = bearish)
- ❌ Doesn't differentiate between trending vs ranging markets

**Missing Strategy:**

- In strong uptrends, RSI 60-80 can persist for weeks (not overbought)
- In downtrends, RSI 20-40 can persist (not oversold)
- Should check if RSI is above/below its own moving average

---

**C. Trend Alignment (Lines 92-99)**

```python
if row['Close'] > row['EMA_20'] > row['EMA_50'] > row['EMA_200']:
    score += 20
elif row['Close'] > row['EMA_200']:
    score += 10
elif row['Close'] < row['EMA_200']:
    score -= 20
```

**Issues:**

- ⚠️ No slope analysis (are EMAs rising or falling?)
- ❌ No distance check (Price 1% above EMA20 vs 20% above = different risk profiles)
- ❌ Gap between elif cases: What if `EMA_20 < Close < EMA_200`? Gets +10 regardless of intermediate EMAs

**Missing:**

- EMA slope: `(EMA_20_today - EMA_20_5days_ago) / EMA_20_5days_ago > 0`
- Cushion check: `(Close - EMA_20) / ATR` (how many ATRs away from support?)

---

### 2. INSTITUTIONAL SCORE (30% Weight) - Lines 117-149

**Status:** 🔴 **SEVERE SIMPLIFICATION**

#### What It Does:

- ✅ Tracks Foreign investor balance (FrgnBal)
- ✅ Checks if last week > average (acceleration)

#### Critical Simplifications:

**A. Single Investor Type (Lines 138-148)**

```python
net_foreign_flow = recent_trades['FrgnBal'].sum()

if net_foreign_flow > 0:
    score += 20
    if recent_trades.iloc[-1]['FrgnBal'] > recent_trades['FrgnBal'].mean():
        score += 10
else:
    score -= 20
```

**Issues:**

- 🔴 **ONLY uses FrgnBal** - ignores 12 other investor categories!
- ❌ No divergence analysis (foreigners buying while individuals selling = strong signal)
- ❌ No trend strength (gradual accumulation vs sudden spike)
- ❌ Binary logic (>0 = good, <0 = bad) - no nuance for magnitude

**Available But COMPLETELY IGNORED:**

```
PropBal     - Proprietary traders (banks/securities, fast money)
IndBal      - Individual retail (contrarian indicator)
BrkBal      - Brokers
SecCoBal    - Securities companies
InvTrBal    - Investment trusts (smart money)
BusCoBal    - Business corporations (buybacks)
InsСoBal    - Insurance companies (long-term institutional)
BankBal     - Banks
TrstBnkBal  - Trust banks (pension funds)
OthFinBal   - Other financial institutions
```

**What Senior Traders Actually Do:**

- **Divergence Plays:** If Foreign + TrustBank buying but Prop selling → strong conviction
- **Retail Fade:** Individual investors are historically wrong at extremes
- **Smart Money Consensus:** InvTr + Foreign + TrustBank all positive = institutional accumulation
- **Velocity Matters:** 4-week cumulative sum doesn't show if buying is accelerating or decelerating

**Recommendation:**

```python
# Example sophisticated approach:
smart_money = FrgnBal + InvTrBal + TrstBnkBal + InsСoBal
dumb_money = IndBal + PropBal
consensus_score = (smart_money / abs(smart_money + dumb_money)) * 100

# Check for trend
weeks = 4
recent_avg = smart_money[-2:].mean()
older_avg = smart_money[-weeks:-2].mean()
is_accelerating = recent_avg > older_avg
```

---

**B. Fixed 4-Week Lookback (Line 131)**

```python
mask = (df_trades['EnDate'] <= current_date) & (df_trades['EnDate'] >= current_date - timedelta(days=35))
```

**Issues:**

- ⚠️ Arbitrary 4-week window (why not 8 or 12?)
- ❌ No adaptive window based on volatility
- ❌ Doesn't compare to longer-term baseline (is this 4-week buying unusual?)

**Better Approach:**

- Compare 4-week flow to 26-week average
- Flag if current flow is > 2 standard deviations from mean

---

### 3. FUNDAMENTAL SCORE (20% Weight) - Lines 151-188

**Status:** 🔴 **SEVERE UNDERUTILIZATION**

#### What It Does:

- ✅ Sales growth (QoQ)
- ✅ Operating Profit growth (QoQ)
- ✅ Operating margin expansion

#### Critical Simplifications:

**A. Only Uses 3 of 107 Columns (Lines 168-186)**

```python
latest_sales = pd.to_numeric(latest['Sales'], errors='coerce')
prev_sales = pd.to_numeric(prev['Sales'], errors='coerce')
latest_op = pd.to_numeric(latest['OP'], errors='coerce')
prev_op = pd.to_numeric(prev['OP'], errors='coerce')

# Revenue Growth Check
if pd.notna(latest_sales) and pd.notna(prev_sales) and latest_sales > prev_sales:
    score += 15

# Operating Profit Growth Check
if pd.notna(latest_op) and pd.notna(prev_op) and latest_op > prev_op:
    score += 15

# Profit Margin Expansion
latest_margin = latest_op / latest_sales
prev_margin = prev_op / prev_sales
if latest_margin > prev_margin:
    score += 10
```

**Issues:**

- 🔴 **Uses 3 columns, ignores 104 others**
- ❌ No EPS check (we have `EPS` column #17)
- ❌ No forward guidance analysis (we have `NxFNCSales`, `NxFNCOP`, `NxFNCEPS`)
- ❌ No quality metrics (we have `TA` = Total Assets, `Eq` = Equity, `EqAR` = Equity Ratio)
- ❌ No cash flow analysis (we have `CFO`, `CFI`, `CFF`)
- ❌ No valuation context (EPS growing but already expensive?)
- ❌ Only compares latest vs previous quarter (not YoY or vs industry)

**Available But IGNORED:**

```
CRITICAL METRICS:
  EPS      - Earnings per share (profitability per shareholder)
  BPS      - Book value per share (safety margin)
  CFO      - Operating cash flow (quality of earnings)
  EqAR     - Equity ratio (financial health)

FORWARD GUIDANCE:
  NxFNCSales   - Next fiscal year sales forecast
  NxFNCOP      - Next fiscal year operating profit forecast
  NxFNCEPS     - Next fiscal year EPS forecast
  FNCEPS       - Current fiscal year EPS forecast

QUALITY CHECKS:
  CFO vs NP    - Cash earnings vs accounting earnings
  Eq / TA      - Leverage ratio
  PayoutRatioAnn - Dividend sustainability
```

**What Real Fundamental Analysis Includes:**

1. **Earnings Quality:** CFO > Net Profit (real cash generation)
2. **Growth Sustainability:** Compare actual vs forecast (beat/miss)
3. **Margin Trends:** 3-quarter moving average vs single QoQ
4. **Balance Sheet Health:** Equity Ratio > 40% (low leverage)
5. **Shareholder Returns:** EPS growth + dividend growth
6. **Guidance:** Is management raising or lowering forecasts?

**Example Better Implementation:**

```python
# 1. EPS Growth (more important than revenue)
eps_growth = (latest_EPS - prev_EPS) / abs(prev_EPS)
if eps_growth > 0.10:  # 10% QoQ growth
    score += 20
elif eps_growth > 0.05:
    score += 10

# 2. Forecast Beat
actual_sales = latest['Sales']
forecast_sales = latest['FSales']  # Forecast from previous quarter
if actual_sales > forecast_sales * 1.02:  # Beat by 2%
    score += 15

# 3. Cash Flow Quality
cfo = pd.to_numeric(latest['CFO'], errors='coerce')
net_profit = pd.to_numeric(latest['NP'], errors='coerce')
if cfo > net_profit:  # Real cash backing earnings
    score += 10

# 4. Forward Guidance Improvement
if latest['NxFNCOP'] > prev['NxFNCOP']:  # Raising guidance
    score += 15
```

---

### 4. VOLATILITY SCORE (10% Weight) - Lines 190-210

**Status:** 🔴 **EXPLICITLY MARKED AS SIMPLIFIED**

#### What It Does:

- ✅ Volume above average check
- ⚠️ Price extension check (not ATR)

#### Critical Simplifications:

**Code:**

```python
def _calc_volatility_score(self, row: pd.Series) -> float:
    score = 50.0

    # Volume Liquidity Check
    if row['Volume'] > row['Volume_SMA_20']:
        score += 10

    # ATR Check (Simplified)
    # Ideally, we compare ATR % to historical average, but here we keep it simple
    # If price is far above EMA20 (extended), penalize
    deviation = (row['Close'] - row['EMA_20']) / row['EMA_20']
    if deviation > 0.05:  # Price is 5% above EMA20 (Parabolic)
        score -= 10

    return np.clip(score, 0, 100)
```

**Issues:**

- 🔴 **COMMENT ADMITS IT'S SIMPLIFIED** (Line 201-203)
- 🔴 **Doesn't actually use ATR** despite function name and comment
- ❌ No historical ATR comparison
- ❌ No Sharpe ratio (risk-adjusted returns)
- ❌ No max drawdown analysis
- ❌ No beta/correlation to market
- ⚠️ Volume check is binary (>SMA = good) - no magnitude scaling
- ⚠️ 5% threshold is arbitrary and not adaptive

**What It SHOULD Do (Per Comment):**

```python
# "Ideally, we compare ATR % to historical average"
atr_percent = (row['ATR'] / row['Close']) * 100
historical_atr_avg = df['ATR'].tail(50).mean() / df['Close'].tail(50).mean() * 100

if atr_percent < historical_atr_avg * 0.8:  # Low volatility regime
    score += 15  # Safer entry
elif atr_percent > historical_atr_avg * 1.5:  # High volatility
    score -= 15  # Risky environment
```

**Additional Missing Risk Metrics:**

- **Drawdown:** How far from 52-week high?
- **Volume Velocity:** Is volume accelerating or decelerating?
- **Relative Volatility:** Stock ATR vs market ATR (TOPIX)
- **Liquidity Depth:** Average daily volume vs position size

---

### 5. EARNINGS RISK VETO (Lines 56-62, 212-226)

**Status:** 🟡 **MODERATE - FUNCTIONAL BUT BASIC**

#### What It Does:

- ✅ Checks if earnings within 7 days
- ✅ Applies 50% penalty to technical score

#### Issues:

**Code:**

```python
if self._is_near_earnings(metadata, current_date):
    risk_flags.append("EARNINGS_APPROACHING")
    tech_score *= 0.5  # Only penalizes technical!
```

**Problems:**

- ⚠️ Only penalizes `tech_score`, not total score
- ⚠️ 50% penalty is arbitrary
- ❌ Doesn't consider historical earnings volatility (some stocks gap 10%, others 1%)
- ❌ Doesn't differentiate between pre-earnings and post-earnings
- ❌ 7-day window may be too wide (earnings after-hours today vs 7 days out = different risk)

**Better Approach:**

```python
# Check earnings volatility history
avg_earnings_gap = calculate_avg_earnings_day_gap(ticker)  # From historical metadata

if days_to_earnings <= 1:
    total_score *= 0.3  # Imminent risk
elif days_to_earnings <= 3:
    total_score *= 0.6
elif days_to_earnings <= 7:
    total_score *= 0.8

if avg_earnings_gap > 0.05:  # Stock typically gaps >5%
    risk_flags.append("HIGH_EARNINGS_VOLATILITY")
```

---

### 6. SCORE INTERPRETATION (Lines 228-239)

**Status:** 🔴 **ARBITRARY THRESHOLDS**

#### Code:

```python
if score >= 80:
    return "STRONG_BUY"
elif score >= 65:
    return "BUY"
elif score <= 35:
    return "STRONG_SELL"
elif score <= 45:
    return "SELL"
else:
    return "NEUTRAL"
```

**Issues:**

- 🔴 **Thresholds (80, 65, 45, 35) are completely arbitrary**
- ❌ No backtesting to validate these levels
- ❌ No confidence intervals (score=79.9 vs 80.1 shouldn't be different signals)
- ❌ No consideration of historical win rate at each threshold
- ⚠️ Gap: score=36-44 returns "NEUTRAL" not "SELL"

**What's Missing:**

- **Historical Performance:** "BUY signals with score >65 have 58% win rate over 30 days"
- **Confidence Bands:** score=65±5 should all be "BUY (Medium Confidence)"
- **Adaptive Thresholds:** In bull markets, maybe 70 is the new "BUY" threshold

---

## MISSING COMPONENTS (Not in Code at All)

### 1. **Price Action Quality**

- No support/resistance levels
- No candlestick patterns
- No gap analysis
- No volatility contraction/expansion patterns

### 2. **Sector/Market Context**

- No relative strength vs TOPIX (we fetch TOPIX data!)
- No sector rotation analysis
- No correlation to market regime

### 3. **Risk Management**

- No position sizing guidance
- No stop-loss calculation
- No profit target
- No Kelly Criterion application

### 4. **Time-Series Analysis**

- Only uses latest row, not historical patterns
- No trend strength/duration
- No cycle analysis
- No seasonality

### 5. **Multi-Timeframe Analysis**

- Only daily data, no weekly/monthly confluence
- No higher timeframe trend filter

---

## SCORING MATRIX: HOW MUCH DATA IS ACTUALLY USED?

| Component         | Available Columns      | Used Columns                          | Utilization % |
| ----------------- | ---------------------- | ------------------------------------- | ------------- |
| **Technical**     | 15                     | 9 (Close, EMA×3, RSI, MACD×3, Volume) | 60%           |
| **Institutional** | 39 investor types      | 1 (FrgnBal only)                      | **2.6%** 🔴   |
| **Fundamental**   | 107 metrics            | 3 (Sales, OP, margin calc)            | **2.8%** 🔴   |
| **Volatility**    | 15 (same as technical) | 4 (Close, EMA_20, Volume, Volume_SMA) | 27%           |
| **Risk**          | earnings_calendar      | Basic 7-day check                     | 🟡 Functional |

**OVERALL DATA UTILIZATION: ~15%** 🔴

We are ignoring **85% of available data**.

---

## WEIGHT ALLOCATION REVIEW

```python
self.weights = {
    "technical": 0.4,      # 40%
    "institutional": 0.3,  # 30%
    "fundamental": 0.2,    # 20%
    "volatility": 0.1      # 10%
}
```

**Analysis:**

- ✅ Technical 40% makes sense (price is truth)
- ⚠️ Institutional 30% too high given only 1 investor type used
- 🟡 Fundamental 20% reasonable but underutilized
- ⚠️ Volatility 10% too low (risk is everything in trading)

**Trader Perspective:**

- For **swing trading (5-30 days):** Current weights OK
- For **long-term investing (6+ months):** Fundamental should be 40%, Technical 30%
- For **day trading:** Technical 60%, Institutional 20%, Volatility 20%

**Recommendation:** Make weights configurable per strategy

---

## RECOMMENDATIONS BY PRIORITY

### 🔴 CRITICAL (Fix Immediately)

1. **Institutional Score:**

   - Add at least 3 more investor types (Proprietary, Individual, Investment Trust)
   - Implement divergence analysis (smart money vs dumb money)

2. **Fundamental Score:**

   - Add EPS growth check (most important metric)
   - Add forward guidance comparison (beat/miss)
   - Add cash flow quality check (CFO vs Net Profit)

3. **Volatility Score:**
   - Actually use ATR as the comment says
   - Compare current ATR% to 50-day average ATR%

### 🟡 IMPORTANT (Enhance Effectiveness)

4. **Technical Score:**

   - Add MACD crossover detection (need historical data)
   - Add EMA slope analysis
   - Make RSI thresholds adaptive to volatility

5. **Score Thresholds:**

   - Backtest to find optimal cutoffs
   - Add confidence bands

6. **Earnings Risk:**
   - Penalize total score, not just technical
   - Add volatility-weighted penalty

### 🟢 NICE TO HAVE (Future Enhancement)

7. **Multi-Timeframe Confluence**
8. **Relative Strength vs Market**
9. **Position Sizing Output**
10. **Seasonal/Cyclical Analysis**

---

## CODE MODIFICATION DIFFICULTY ASSESSMENT

| Fix                                      | Impact | Complexity | Data Required     | Estimate |
| ---------------------------------------- | ------ | ---------- | ----------------- | -------- |
| Institutional: Add 3 more investor types | High   | Low        | Already have      | 1 hour   |
| Fundamental: Add EPS growth              | High   | Low        | Already have      | 30 min   |
| Fundamental: Add forecast beat/miss      | High   | Medium     | Already have      | 1 hour   |
| Volatility: ATR historical comparison    | Medium | Medium     | Need historical   | 2 hours  |
| Technical: MACD crossover                | Medium | Medium     | Need historical   | 2 hours  |
| Technical: EMA slope                     | Medium | Low        | Need historical   | 1 hour   |
| Earnings: Penalty refinement             | Medium | Low        | Current data      | 30 min   |
| Score thresholds: Backtest               | High   | High       | Need returns data | 8+ hours |

**Total for Critical Fixes:** ~3 hours of development
**Total for Critical + Important:** ~10 hours
**Total for All:** ~20+ hours (includes backtesting infrastructure)

---

## FINAL VERDICT

**Current State:** 🟡 **PRODUCTION-READY FOR MVP, NOT FOR SERIOUS MONEY**

**Strengths:**

- ✅ Solid conceptual framework
- ✅ Clean code structure
- ✅ Proper null handling
- ✅ Good documentation

**Weaknesses:**

- 🔴 Underutilizes 85% of available data
- 🔴 Oversimplified institutional analysis (only 1 of 13 investor types)
- 🔴 Oversimplified fundamental analysis (3 of 107 metrics)
- 🔴 Volatility score doesn't actually use ATR properly
- 🔴 Arbitrary thresholds with no backtesting

**Risk Assessment:**

- ✅ Safe for paper trading / learning
- ⚠️ Use with caution for real money (max 5% of portfolio per trade)
- 🔴 NOT ready for automated trading without human oversight
- 🔴 NOT ready for institutional use

**Recommendation:**
Implement **Critical Fixes** (3 hours) before using for any real capital allocation. The current system is a good V1 prototype but leaves significant alpha on the table.

---

## NEXT STEPS

1. **Immediate:** Fix institutional score to use 4 investor types (smart money composite)
2. **Short-term:** Add EPS growth and forecast guidance to fundamental score
3. **Medium-term:** Implement proper ATR volatility analysis
4. **Long-term:** Build backtesting framework to validate all thresholds

**Bottom Line:** The scorer is simplified where the comment says it is, AND in many places where it doesn't admit it. It's functional, but a senior trader would want 3-4x more sophistication before risking real capital.
