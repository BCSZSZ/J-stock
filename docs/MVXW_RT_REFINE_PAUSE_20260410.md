# MVXW RT Local Retune Pause Note (2026-04-10)

## Task Purpose

Objective: run a two-round local `R/T` retune around the current `MVXW` champion under the standard annual CLI workflow.

- Entry strategy fixed to `MACDPreCross2BarEntry`
- Exit family fixed to `MVXW_N5_*_D21_B20p0`
- Ranking rule fixed to `continuous_stability_rank` row 1 only
- No extra manual MDD gate

Current hall champion before this retune:

- `MVXW_N5_R3p35_T1p6_D21_B20p0`

## Completed

### 1. Local retune variants registered

The local `N=5 / D=21 / B=20.0` `R/T` neighborhood needed for coarse and fine retuning has been registered in code and covered by tests.

- Code support: `src/analysis/strategies/exit/multiview_grid_exit.py`
- Test coverage: `tests/test_mvxw_window_decay_exit.py`

### 2. Coarse 3x3 annual + continuous run completed

Coarse search range:

- `R = {3.25, 3.35, 3.45}`
- `T = {1.50, 1.60, 1.70}`

Output directory:

- `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvxw_rt_refine_20260410/coarse_grid`

Key result files:

- segmented raw: `strategy_evaluation_raw_20260410_172033.csv`
- continuous raw: `strategy_evaluation_continuous_raw_20260410_174911.csv`
- final rank: `strategy_evaluation_continuous_stability_rank_20260410_174924.csv`
- top10 summary: `strategy_evaluation_continuous_stability_top10_20260410_174924.md`

### 3. Coarse winner confirmed

Final coarse winner from `continuous_stability_rank` row 1:

- Entry: `MACDPreCross2BarEntry`
- Exit: `MVXW_N5_R3p25_T1p7_D21_B20p0`

Winner metrics:

| Metric | Coarse winner | Previous hall champion |
| --- | ---: | ---: |
| Continuous return % | `590.4923` | `519.9707` |
| Continuous alpha % | `507.7174` | `437.1959` |
| Continuous Sharpe | `1.9654` | `1.8646` |
| Continuous MDD % | `21.3003` | `22.8831` |
| Positive years | `5/5` | `5/5` |
| Positive alpha years | `5/5` | `4/5` |

This means the local coarse search already found a better center than the current hall reference.

## Fine-Grid Target Position

Fine-grid center is now fixed and does not need to be recomputed later:

- Center exit strategy: `MVXW_N5_R3p25_T1p7_D21_B20p0`

Planned fine 3x3 neighborhood:

- `R = {3.20, 3.25, 3.30}`
- `T = {1.65, 1.70, 1.75}`

Concrete fine candidates:

1. `MVXW_N5_R3p2_T1p65_D21_B20p0`
2. `MVXW_N5_R3p2_T1p7_D21_B20p0`
3. `MVXW_N5_R3p2_T1p75_D21_B20p0`
4. `MVXW_N5_R3p25_T1p65_D21_B20p0`
5. `MVXW_N5_R3p25_T1p7_D21_B20p0`
6. `MVXW_N5_R3p25_T1p75_D21_B20p0`
7. `MVXW_N5_R3p3_T1p65_D21_B20p0`
8. `MVXW_N5_R3p3_T1p7_D21_B20p0`
9. `MVXW_N5_R3p3_T1p75_D21_B20p0`

## Completion Status

Fine-grid execution completed on 2026-04-11.

- fine output directory: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvxw_rt_refine_20260410/fine_grid_r3p25_t1p7`
- output timestamp: `20260411_183639` (segmented), `20260411_185122` (continuous), `20260411_185128` (stability rank)
- all three output sets present: ✅ segmented, ✅ continuous companion, ✅ continuous_stability_rank

## Fine Grid Result

### Rank #1 (continuous_stability_rank)

`MVXW_N5_R3p2_T1p65_D21_B20p0`

| Metric | Value |
|---|---|
| continuous_return | 474.20% |
| continuous_alpha | 401.04% |
| continuous_sharpe | 1.862 |
| continuous_mdd | 23.03% |
| positive_years | 4/5 |
| avg_yearly_return | 43.67% |
| num_trades | 1291 |

### Comparison with current mvxw_champion

| Metric | Fine Grid #1 | Current Champion |
|---|---|---|
| exit_strategy | MVXW_N5_R3p2_T1p65_D21_B20p0 | MVXW_N5_R3p35_T1p6_D21_B20p0 |
| continuous_return | 474.20% | 519.97% |
| continuous_alpha | 401.04% | 437.20% |
| continuous_sharpe | 1.862 | 1.865 |
| continuous_mdd | 23.03% | 22.88% |
| positive_years | 4/5 | 5/5 |

### Decision

Fine grid winner does **not** beat the current hall champion on any key metric.
Hall of fame (`strategy_hall_of_fame.json`) was **not updated**.
Current mvxw_champion `MVXW_N5_R3p35_T1p6_D21_B20p0` remains.