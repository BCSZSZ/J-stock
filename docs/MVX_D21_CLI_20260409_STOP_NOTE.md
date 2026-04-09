# MVX D21 CLI Study Stop Note

Date: 2026-04-09

## Scope

This note records the current stop point for the annual CLI study covering:

- Baseline entry: `MACDCrossoverStrategy`
- 2bar entry: `MACDPreCross2BarEntry`
- Exit family: MVX with fixed `D=21`, `B=20.0`
- Evaluation basis: annual 2021-2025, `entry-filter-mode off`, `exit-confirm-days 1`

## Code And Config Work Already Done

- Added annual companion continuous output to `evaluate` and `pos-evaluation` in [src/cli/evaluate.py](../src/cli/evaluate.py).
- Added annual `continuous + stability` ranking output in [src/cli/evaluate.py](../src/cli/evaluate.py).
- Changed repo-side evaluation default confirm days to `1` in:
  - [config.local.json](../config.local.json)
  - [config.aws.json](../config.aws.json)
  - [config.aws-sim.json](../config.aws-sim.json)
  - [config.json.example](../config.json.example)
  - [docs/features/EVALUATION_EXIT_CONFIRMATION_SYNC.md](features/EVALUATION_EXIT_CONFIRMATION_SYNC.md)
- Extended the D21/B20 MVX registry in [src/analysis/strategies/exit/multiview_grid_exit.py](../src/analysis/strategies/exit/multiview_grid_exit.py).
- Optimized 2bar evaluation runtime in:
  - [src/evaluation/strategy_evaluator.py](../src/evaluation/strategy_evaluator.py)
  - [src/analysis/strategies/entry/macd_precross_momentum_entry.py](../src/analysis/strategies/entry/macd_precross_momentum_entry.py)
- Added regression coverage in:
  - [tests/test_cli_evaluate_annual_outputs.py](../tests/test_cli_evaluate_annual_outputs.py)
  - [tests/test_macd_precross_momentum_entry.py](../tests/test_macd_precross_momentum_entry.py)
  - [tests/test_multiview_unified_tp_exit.py](../tests/test_multiview_unified_tp_exit.py)

Active local runtime config updates were also applied outside this repo in `G:/My Drive/AI-Stock-Sync/config.json`, but that file is not tracked by this git repository.

## Completed CLI Runs

All completed outputs were written under:

`G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409`

### Baseline Completed

- `baseline_round1_n`
- `baseline_round1_r`
- `baseline_round1_t`
- `baseline_grid1`
- `baseline_grid2`
- `baseline_grid3`

Best completed baseline result:

- Entry: `MACDCrossoverStrategy`
- Exit: `MVX_N3_R3p85_T2p0_D21_B20p0`
- Source: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/baseline_grid3/strategy_evaluation_continuous_stability_rank_20260409_133712.csv`
- 5Y segmented returns: `21.8681, 37.1937, 26.6823, 6.3911, 111.8074`
- 20% hit count: `4/5`
- Continuous return: `349.9233%`
- Continuous alpha: `267.1485%`
- Continuous Sharpe: `1.6768`
- Continuous MDD: `24.7030%`

### Production Reference Completed

- `production_reference`

Current production reference result:

- Entry: `MACDCrossoverStrategy`
- Exit: `MVX_N3_R3p25_T1p6_D21_B20p0`
- Source: `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/production_reference/strategy_evaluation_continuous_stability_rank_20260409_135229.csv`
- 5Y segmented returns: `21.1985, 32.4263, 20.7685, 1.1396, 74.5346`
- 20% hit count: `4/5`
- Continuous return: `275.0268%`
- Continuous alpha: `192.2519%`
- Continuous Sharpe: `1.5077`
- Continuous MDD: `23.1513%`

### 2bar Completed Before Stop

- `twobar_round1_n`
- `twobar_round1_r`
- `twobar_round1_t`

Current best completed 2bar result remains:

- Entry: `MACDPreCross2BarEntry`
- Exit: `MVX_N5_R3p25_T1p6_D21_B20p0`
- Sources:
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_round1_n/strategy_evaluation_continuous_stability_rank_20260409_133115.csv`
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_round1_r/strategy_evaluation_continuous_stability_rank_20260409_171101.csv`
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_round1_t/strategy_evaluation_continuous_stability_rank_20260409_173311.csv`
- 5Y segmented returns: `0.9980, 17.3800, 33.5731, 7.7416, 120.8672`
- 20% hit count: `2/5`
- Continuous return: `329.5931%`
- Continuous alpha: `246.8182%`
- Continuous Sharpe: `1.4661`
- Continuous MDD: `24.9684%`

Important 2bar follow-up observations from completed single-parameter rounds:

- `round1_r` top 2 `R`: `3.25`, `3.0`
- `round1_t` top 2 `T`: `1.6`, `2.0`
- `round1_n` top 2 `N`: `5`, `3`

These were used to construct `twobar_grid1`.

## Stop Point

`twobar_grid1` was started with these 8 combinations:

- `MVX_N3_R3p0_T1p6_D21_B20p0`
- `MVX_N3_R3p0_T2p0_D21_B20p0`
- `MVX_N3_R3p25_T1p6_D21_B20p0`
- `MVX_N3_R3p25_T2p0_D21_B20p0`
- `MVX_N5_R3p0_T1p6_D21_B20p0`
- `MVX_N5_R3p0_T2p0_D21_B20p0`
- `MVX_N5_R3p25_T1p6_D21_B20p0`
- `MVX_N5_R3p25_T2p0_D21_B20p0`

Segmented annual phase completed and saved these outputs:

- `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid1/strategy_evaluation_raw_20260409_175503.csv`
- `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid1/strategy_evaluation_report_20260409_175503.md`

The continuous companion phase was still running when work was stopped.

Exact stop status:

- `twobar_grid1` continuous run had reached `6/8` tasks complete.
- The background terminal was then explicitly killed.
- No final `twobar_grid1` continuous raw file or `continuous_stability_rank` file should be assumed complete.

## Pending Work

Still not completed:

- rerun `twobar_grid1` to completion
- derive `twobar_grid2` around the winning `R/T` center from `grid1`
- derive `twobar_grid3` around the winning `R/T` center from `grid2`
- produce the final three-way review: baseline best vs production vs final 2bar best

## Resume Instructions

Recommended resume approach:

1. Rerun `twobar_grid1` from scratch using the same command.
2. Read the resulting `continuous_stability_rank` winner.
3. Build `twobar_grid2` as a `3 x 3` refinement around the winning `R/T` center, keeping `N={5,3}` if both remain competitive.
4. Build `twobar_grid3` as the second `3 x 3` refinement around the new winning center.
5. Redo the final three-way report using:
   - baseline best from `baseline_grid3`
   - production reference
   - final 2bar best from `grid3`

Command to resume `twobar_grid1`:

```powershell
Push-Location "c:\Github\personal\stock-AI-python\j-stock-analyzer"
c:/Github/personal/stock-AI-python/j-stock-analyzer/.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-filter-mode off --entry-strategies MACDPreCross2BarEntry --exit-confirm-days 1 --exit-strategies MVX_N3_R3p0_T1p6_D21_B20p0 MVX_N3_R3p0_T2p0_D21_B20p0 MVX_N3_R3p25_T1p6_D21_B20p0 MVX_N3_R3p25_T2p0_D21_B20p0 MVX_N5_R3p0_T1p6_D21_B20p0 MVX_N5_R3p0_T2p0_D21_B20p0 MVX_N5_R3p25_T1p6_D21_B20p0 MVX_N5_R3p25_T2p0_D21_B20p0 --output-dir "G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid1"
Pop-Location
```