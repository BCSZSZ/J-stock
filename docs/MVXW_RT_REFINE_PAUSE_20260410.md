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

## Pause Status

Fine-grid execution was started once, then intentionally stopped to pause the workflow.

- fine output directory: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvxw_rt_refine_20260410/fine_grid_r3p25_t1p7`
- status at pause time: no output files present

The workflow is paused cleanly at the point where the fine-grid center and exact candidate set are already locked.

## Remaining Work

### 1. Run the fine 3x3 annual CLI

Use the same workflow pattern as coarse:

```powershell
c:/Github/personal/stock-AI-python/j-stock-analyzer/.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-filter-mode off --entry-strategies MACDPreCross2BarEntry --exit-confirm-days 1 --exit-strategies MVXW_N5_R3p2_T1p65_D21_B20p0 MVXW_N5_R3p2_T1p7_D21_B20p0 MVXW_N5_R3p2_T1p75_D21_B20p0 MVXW_N5_R3p25_T1p65_D21_B20p0 MVXW_N5_R3p25_T1p7_D21_B20p0 MVXW_N5_R3p25_T1p75_D21_B20p0 MVXW_N5_R3p3_T1p65_D21_B20p0 MVXW_N5_R3p3_T1p7_D21_B20p0 MVXW_N5_R3p3_T1p75_D21_B20p0 --output-dir "G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvxw_rt_refine_20260410/fine_grid_r3p25_t1p7"
```

### 2. Wait for the full annual workflow to finish

Do not stop at segmented `45/45`.

Completion means all three are present:

1. segmented outputs
2. continuous companion outputs
3. `strategy_evaluation_continuous_stability_rank_*.csv`

### 3. Select the final retune winner

Rule:

- read `continuous_stability_rank` row 1 only

### 4. Post-fine follow-up

If the fine winner still beats the current hall entry, then update the hall/benchmark JSON references accordingly.