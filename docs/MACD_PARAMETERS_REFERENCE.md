# MACD Enhanced Parameters - Quick Reference Card

## Current Configuration (Baseline)
```python
MACDEnhancedFundamentalStrategy(
    # Confidence & Scoring
    base_confidence=0.55,              # MACD cross baseline [0.4-0.8]
    rs_weight=0.10,                    # RS contribution [0.0-0.4]
    bias_weight=0.35,                  # Bias contribution [0.2-0.6]
    
    # Entry Gates (BOTTLENECK)
    rs_threshold=0.30,                 # RS required to enter [0.0-1.0]
    bias_threshold=0.20,               # Bias required to enter [0.0-1.0]
    
    # RS Calculation
    rs_excess_threshold=0.20,          # ±20% outperformance scale [0.05-0.5]
    
    # Bias Recovery Window
    bias_lookback=10,                  # Days to check oversold [5-30]
    bias_oversold_threshold=-10.0,     # Oversold trigger [−20% to 0%]
    bias_recovery_threshold=-5.0,      # Recovery completion [−15% to 0%]
)
```

## Performance Baseline
```
Return:  25.131%
Alpha:   12.772%  ← 8.7% below MACDCrossover
Sharpe:  1.310
Trades:  ~25-35/year (vs 50-60 for MACDCrossover)
```

## Parameter Impact Matrix

### HIGH IMPACT (>3% alpha swing each)
```
┌─ rs_threshold [0.30]
│  └─ Current: Moderate-high bar (~6% excess return vs TOPIX)
│  └─ Test: 0.10, 0.15, 0.20, 0.25
│  └─ Effect: Lower = more entries = higher frequency
│  └─ Priority: PHASE 1 (Most critical)
│
└─ bias_threshold [0.20]
   └─ Current: Tight recovery requirement (10% recovered → score 0.2)
   └─ Test: 0.05, 0.10, 0.15
   └─ Effect: Lower = easier recovery detection = more entries
   └─ Priority: PHASE 1 (Most critical)
```

### MEDIUM IMPACT (1-3% alpha swing each)
```
┌─ bias_recovery_threshold [-5.0%]
│  └─ Current: Requires -10% → -5% (5 pp recovery range)
│  └─ Test: -8%, -3%, 0%
│  └─ Effect: Wider range = easier to achieve high bias score
│  └─ Priority: PHASE 2 (Secondary)
│
├─ bias_lookback [10 days]
│  └─ Current: 2-week window for oversold detection
│  └─ Test: 5, 15, 20
│  └─ Effect: Longer = captures slower recovery patterns
│  └─ Priority: PHASE 2 (Secondary)
│
├─ bias_weight [0.35]
│  └─ Current: 3.5× higher than RS (35% vs 10%)
│  └─ Test: 0.25, 0.30
│  └─ Effect: Lower = less emphasis on oversold recovery
│  └─ Priority: PHASE 3 (Optional)
│
└─ rs_weight [0.10]
   └─ Current: Small contribution
   └─ Test: 0.15, 0.20, 0.25
   └─ Effect: Higher = more reward for relative strength
   └─ Priority: PHASE 3 (Optional)
```

### LOW IMPACT (<1% alpha swing)
```
┌─ rs_excess_threshold [0.20]
│  └─ Current: ±20% outperformance = max score
│  └─ Priority: PHASE 3 (Optional)
│
├─ bias_oversold_threshold [-10.0%]
│  └─ Current: -10% deviation triggers oversold
│  └─ Priority: PHASE 2 (Secondary)
│
└─ base_confidence [0.55]
   └─ Current: MACD baseline (invariant baseline shift)
   └─ Priority: KEEP AS-IS (Minimal impact)
```

## Entry Gate Logic (The Bottleneck)

### Current Gate
```python
entry_gate = rs_score > rs_threshold OR bias_score > bias_threshold
# Both must fail for HOLD
```

### Filtering Effect
```
Scenario 1: Strong uptrend (RS=0.8, Bias=0.1)
  rs_score > 0.30? YES → PASS ✓ (BUY)

Scenario 2: Recovery trade (RS=0.2, Bias=0.6)
  rs_score > 0.30? NO
  bias_score > 0.20? YES → PASS ✓ (BUY)

Scenario 3: PROBLEM (Modest recovery)
  rs_score=0.25 > 0.30? NO
  bias_score=0.15 > 0.20? NO
  → FAIL ✗ (HOLD) ← FILTERED OUT!

Scenario 4: Higher momentum
  rs_score=0.5 > 0.30? YES → PASS ✓ (BUY)

Scenario 5: PROBLEM (Early bounce)
  rs_score=0.1 > 0.30? NO
  bias_score=0.1 > 0.20? NO
  → FAIL ✗ (HOLD) ← FILTERED OUT!
```

**Result:** ~30-50% of MACD crosses filtered out
**Cost:** -8.7% alpha from reduced opportunity set

## Optimization Phases

### PHASE 1: Gate Relaxation
```
Test Grid:
  rs_threshold ∈ {0.10, 0.15, 0.20, 0.25, 0.30}
  bias_threshold ∈ {0.05, 0.10, 0.15, 0.20}

Combinations: 5 × 4 = 20
Backtests: 20 × 5 years = 100 total

Expected Winner: rs_threshold=0.20, bias_threshold=0.10
Expected Alpha Range: 18-22%
Target: Close gap from -8.7% → <5%

Timeline: ~2-4 hours (parallel possible)
```

### PHASE 2: Recovery Window Tuning
```
Test Grid (if Phase 1 succeeds):
  bias_lookback ∈ {5, 10, 15, 20}
  bias_recovery_threshold ∈ {-8%, -3%, 0%}
  
Combinations: ~12
Expected Gain: +1-2% alpha
Trigger: Run only if Phase 1 ≥18% alpha
```

### PHASE 3: Weight Optimization
```
Test Grid (if Phase 1+2 leave gap >3%):
  rs_weight ∈ {0.05, 0.10, 0.15, 0.20, 0.25}
  bias_weight ∈ {0.25, 0.30, 0.35, 0.40}

Combinations: ~20
Expected Gain: +0.3-1.0% alpha
Trigger: Only if needed after Phase 1+2
```

## Scoring Formulas

### Relative Strength (RS) Score
```
1. Calculate excess return: excess = stock_20d_return - topix_20d_return
2. Normalize using threshold (±20%):
   if excess ≤ -20%:     rs_score = 0.0
   if -20% < excess < 0: rs_score = 0.5 × (excess + 20%) / 20%
   if 0 ≤ excess < 20%:  rs_score = 0.5 + 0.5 × (excess / 20%)
   if excess ≥ 20%:      rs_score = 1.0

3. Examples:
   excess = -20% → rs_score = 0.0
   excess = -10% → rs_score = 0.25
   excess = 0%   → rs_score = 0.5
   excess = +10% → rs_score = 0.75
   excess = +20% → rs_score = 1.0
```

### Bias (乖離率) Score
```
1. Check if oversold in lookback window:
   recent_bias = [Bias_i for i in last 10 days]
   touched_oversold = any(recent_bias < -10%) ?
   
   if NOT touched_oversold: bias_score = 0.0

2. If oversold detected, score recovery:
   current_bias = (Close - SMA25) / SMA25 × 100
   progress = (current_bias - oversold_threshold) / (recovery_threshold - oversold_threshold)
   bias_score = clamp(progress, 0.0, 1.0)
   
   Range: -10% → -5% = [0, 1]
   Examples (assuming -10% oversold → -5% recovery target):
   current_bias = -10% → progress = 0.0 → bias_score = 0.0
   current_bias = -8%  → progress = 0.4 → bias_score = 0.4
   current_bias = -5%  → progress = 1.0 → bias_score = 1.0
   current_bias = 0%   → progress = 1.0 → bias_score = 1.0 (clamped)
```

### Final Confidence
```
confidence = base_confidence + rs_score × rs_weight + bias_score × bias_weight
           = 0.55 + rs_score × 0.10 + bias_score × 0.35

Range: [0.55, 1.0]
Examples:
  Perfect signal (RS=1.0, Bias=1.0): 0.55 + 0.10 + 0.35 = 1.00
  RS-driven (RS=0.8, Bias=0): 0.55 + 0.08 + 0.00 = 0.63
  Bias-driven (RS=0, Bias=0.6): 0.55 + 0.00 + 0.21 = 0.76
```

## Decision Tree (Current)

```
MACD Golden Cross Detected?
├─ NO → HOLD (confidence=0.0)
└─ YES → Calculate RS & Bias scores
   ├─ RS_score > 0.30 or Bias_score > 0.20?
   │  ├─ YES (Entry gate PASSES)
   │  │  └─ BUY (confidence = 0.55 + weights)
   │  └─ NO (Entry gate FAILS)
   │     └─ HOLD (confidence = 0.55 + weights, but not executed)
```

## Recommendation for Testing

### Start With
1. **rs_threshold = 0.20** (from 0.30) → Admit modest outperformance
2. **bias_threshold = 0.10** (from 0.20) → Easier recovery detection
3. **All else unchanged** (other 7 params at current)

### Expected Outcome
- Trades/year: ~35-45 (up from 25-35)
- Alpha: ~18-20% (up from 12.8%, gap from -8.7% to -1.5%)
- Sharpe: ~1.45-1.55 (up from 1.31)

### If Successful
- Proceed to Phase 2 (recovery window tuning)
- Target final alpha: 20-22% (gap: -0.5% to -1.5%)

### If Unsuccessful
- Keep MACDCrossover as production default
- Document findings for future reference
