# Walk-Forward Tuning Log (2026-03-17)

## 1. Goal and Scope

This note records today's end-to-end walk-forward tuning work on the same 405-base evaluation result set (81 exit variants x 5 years), including:

- formula alignment decision
- lambda/w scanning process
- observed boundary behavior
- current recommended operating interpretation
- reproducible commands and output artifacts

Data baseline:

- Raw evaluation table: `strategy_evaluation/strategy_evaluation_raw_20260317_000413.csv`
- Sample years: 2021, 2022, 2023, 2024, 2025
- Walk-forward folds (min train years = 2): test years 2023, 2024, 2025

## 2. Formula Alignment Decision

### 2.1 Previous situation

There were two different 60/40 interpretations in use:

1) Existing strategy scoring standard (`risk60_profit40_v2`):

- risk 60% = mdd_inverse 35% + worst_year_return 25%
- profit 40% = avg_alpha 25% + positive_alpha_ratio 15%

2) Earlier walk-forward internal rank scoring:

- train/oos utility = 0.6 * return_rank + 0.4 * risk_rank
- risk_rank = 0.5 * sharpe_rank + 0.5 * mdd_quality_rank

### 2.2 Alignment done today

Walk-forward train selection and OOS utility were unified to `risk60_profit40_v2` model.

Code changes:

- Updated: `tools/walk_forward_stability.py`
  - Added `--selection-model` (default `risk60_profit40_v2`, optional `rank60_40`)
  - Train and OOS formula support aligned model
  - Report output includes `selection_model`

- Added: `tools/wf_fine_scan.py`
  - Fine-grained matrix scan over lambda/w around a center point
  - Automatically calls walk-forward script and aggregates top result by grid point

## 3. Stability Layer Definition

After formula alignment, outer stability remains:

`stability_score = 100 * ((1 - w) * (mean(oos_utility) - lambda * std(oos_utility)) + w * positive_alpha_rate)`

Interpretation:

- lambda controls fold-to-fold utility volatility penalty.
- w controls extra reward on positive-alpha consistency.
- If lambda = 0 and w = 0, score collapses to `100 * mean(oos_utility)`.

## 4. Scanning Process and Results

## 4.1 Round-1 fine scan around prior center

Command intent:

- center lambda=0.5, w=0.2
- lambda step 0.05, w step 0.02

Output:

- `strategy_evaluation/wf_fine_scan_20260317_002708.csv`
- `strategy_evaluation/wf_fine_scan_20260317_002708.md`

Observation:

- Best point moved to lower boundary of this grid (lambda=0.30, w=0.10), indicating more room toward smaller values.

## 4.2 Round-2 shifted lower scan

Command intent:

- center lambda=0.25, w=0.08
- lambda step 0.02, w step 0.01

Output:

- `strategy_evaluation/wf_fine_scan_20260317_002821.csv`
- `strategy_evaluation/wf_fine_scan_20260317_002821.md`

Observation:

- Best point again at lower boundary (lambda=0.15, w=0.02).

## 4.3 Round-3 near-zero scan

Command intent:

- center lambda=0.10, w=0.02
- lambda step 0.01, w step 0.005

Output:

- `strategy_evaluation/wf_fine_scan_20260317_002957.csv`
- `strategy_evaluation/wf_fine_scan_20260317_002957.md`

Observation:

- Best point reached global lower corner in tested domain: lambda=0.00, w=0.00.
- Top strategy at this point:
  - `entry_strategy=MACDCrossoverStrategy | exit_strategy=MVX_N8_R3p6_T1p5_D18_B19p5 | entry_filter=off`

## 4.4 Canonical report at current optimum point

Executed with aligned model and lambda=0, w=0.

Outputs:

- `strategy_evaluation/walk_forward_fold_winners_20260317_003156.csv`
- `strategy_evaluation/walk_forward_oos_panel_20260317_003156.csv`
- `strategy_evaluation/walk_forward_stability_20260317_003156.csv`
- `strategy_evaluation/walk_forward_report_20260317_003156.md`

Top row from stability table:

- strategy: `MACDCrossoverStrategy + MVX_N8_R3p6_T1p5_D18_B19p5`
- oos_utility_mean: 0.7640519251
- oos_utility_std: 0.1603147542
- oos_positive_alpha_rate: 0.6666666667
- stability_score: 76.4051925133

## 5. Business Interpretation of lambda=0, w=0

This does not mean "no risk control" in the overall scheme.

Reason:

- risk/return balancing is already embedded in `oos_utility` via `risk60_profit40_v2`.
- setting lambda=0, w=0 means no extra second-layer regularization on top of that base utility.

So the optimizer chooses:

- maximize average aligned utility
- no additional volatility penalty and no additional positive-alpha bonus

This is a valid mathematical optimum under current objective and constraints.

## 6. Practical Decision Note

Current finding suggests the objective is corner-seeking when lambda and w are unconstrained.

Two practical options:

1) Keep unconstrained optimum (lambda=0, w=0)
- pure performance under aligned base utility

2) Add business floor constraints (for robustness preference)
- e.g. lambda >= 0.10 to 0.20, w >= 0.02 to 0.10
- then pick local optimum inside constrained region

No final floor policy was locked today. This note only records empirical result and interpretation.

## 7. Key Commands Used Today

Baseline aligned walk-forward:

```powershell
e:/Code/AI-stock/J-stock/.venv/Scripts/python.exe tools/walk_forward_stability.py --raw-csv strategy_evaluation/strategy_evaluation_raw_20260317_000413.csv --group-cols entry_strategy exit_strategy entry_filter --min-train-years 2 --selection-model risk60_profit40_v2 --std-penalty 0 --oos-positive-weight 0 --output-dir strategy_evaluation
```

Fine scan round-1:

```powershell
e:/Code/AI-stock/J-stock/.venv/Scripts/python.exe tools/wf_fine_scan.py --raw-csv strategy_evaluation/strategy_evaluation_raw_20260317_000413.csv --group-cols entry_strategy exit_strategy entry_filter --min-train-years 2 --selection-model risk60_profit40_v2 --center-lambda 0.5 --center-w 0.2 --lambda-span 0.2 --w-span 0.1 --lambda-step 0.05 --w-step 0.02 --output-dir strategy_evaluation
```

Fine scan round-2:

```powershell
e:/Code/AI-stock/J-stock/.venv/Scripts/python.exe tools/wf_fine_scan.py --raw-csv strategy_evaluation/strategy_evaluation_raw_20260317_000413.csv --group-cols entry_strategy exit_strategy entry_filter --min-train-years 2 --selection-model risk60_profit40_v2 --center-lambda 0.25 --center-w 0.08 --lambda-span 0.1 --w-span 0.06 --lambda-step 0.02 --w-step 0.01 --output-dir strategy_evaluation
```

Fine scan round-3:

```powershell
e:/Code/AI-stock/J-stock/.venv/Scripts/python.exe tools/wf_fine_scan.py --raw-csv strategy_evaluation/strategy_evaluation_raw_20260317_000413.csv --group-cols entry_strategy exit_strategy entry_filter --min-train-years 2 --selection-model risk60_profit40_v2 --center-lambda 0.1 --center-w 0.02 --lambda-span 0.1 --w-span 0.02 --lambda-step 0.01 --w-step 0.005 --output-dir strategy_evaluation
```

## 8. Status at End of Day

- Formula alignment: completed
- Fine-grained lambda/w scan: completed (3 rounds)
- Current unconstrained optimum: lambda=0, w=0
- Reproducible artifacts saved under `strategy_evaluation/`
- This log saved for checkpoint and handoff
