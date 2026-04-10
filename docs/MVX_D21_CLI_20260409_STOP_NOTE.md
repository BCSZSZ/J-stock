# MVX D21 CLI Study Stop Note

Date: 2026-04-10

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

### 2bar Completed

- `twobar_round1_n`
- `twobar_round1_r`
- `twobar_round1_t`
- `twobar_grid1`
- `twobar_grid2`
- `twobar_grid3`

Final 2bar best result:

- Entry: `MACDPreCross2BarEntry`
- Exit: `MVX_N3_R3p35_T1p6_D21_B20p0`
- Sources:
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid3/strategy_evaluation_continuous_stability_rank_20260410_111409.csv`
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid3/strategy_evaluation_raw_20260410_105157.csv`
  - `G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid3/strategy_evaluation_continuous_raw_20260410_111401.csv`
- 5Y segmented returns: `-6.5389, 18.9122, 38.4349, 46.3693, 116.1021`
- 20% hit count: `3/5`
- Continuous return: `378.1765%`
- Continuous alpha: `295.4017%`
- Continuous Sharpe: `1.6158`
- Continuous MDD: `21.2450%`

Notable 2bar runner-up after `grid3`:

- Entry: `MACDPreCross2BarEntry`
- Exit: `MVX_N3_R3p25_T1p8_D21_B20p0`
- 5Y segmented returns: `0.5842, 10.4856, 33.5392, 33.6084, 106.3192`
- 20% hit count: `3/5`
- Positive years: `5/5`
- Continuous return: `364.8133%`
- Continuous MDD: `17.1780%`

Important 2bar follow-up observations from completed single-parameter rounds:

- `round1_r` top 2 `R`: `3.25`, `3.0`
- `round1_t` top 2 `T`: `1.6`, `2.0`
- `round1_n` top 2 `N`: `5`, `3`

These were used to construct `twobar_grid1`.

## Historical Stop Point

This file originally captured a 2026-04-09 pause at `twobar_grid1`, before the study was resumed.

- `twobar_grid1` later completed with full segmented + continuous + stability outputs.
- `twobar_grid2` later completed with full segmented + continuous + stability outputs.
- `twobar_grid3` later completed with full segmented + continuous + stability outputs.

The original interrupted state is no longer the active project state.

## Pending Work

Core CLI evaluation work for this MVX D21 study is now complete.

No mandatory backtest rounds remain.

Optional follow-up only:

- run one finalist robustness pass with `main.py pos-evaluation --mode annual` if position-profile validation is desired
- package the final three-way review into a report or commit message if needed

## Reference Commands

Final `twobar_grid3` command that completed the search:

```powershell
Push-Location "c:\Github\personal\stock-AI-python\j-stock-analyzer"
c:/Github/personal/stock-AI-python/j-stock-analyzer/.venv/Scripts/python.exe main.py evaluate --mode annual --years 2021 2022 2023 2024 2025 --entry-filter-mode off --entry-strategies MACDPreCross2BarEntry --exit-confirm-days 1 --exit-strategies MVX_N3_R3p15_T1p6_D21_B20p0 MVX_N3_R3p15_T1p7_D21_B20p0 MVX_N3_R3p15_T1p8_D21_B20p0 MVX_N3_R3p25_T1p6_D21_B20p0 MVX_N3_R3p25_T1p7_D21_B20p0 MVX_N3_R3p25_T1p8_D21_B20p0 MVX_N3_R3p35_T1p6_D21_B20p0 MVX_N3_R3p35_T1p7_D21_B20p0 MVX_N3_R3p35_T1p8_D21_B20p0 --output-dir "G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/twobar_grid3"
Pop-Location
```

Optional robustness-validation direction, still using CLI rather than custom scripts:

```powershell
Push-Location "c:\Github\personal\stock-AI-python\j-stock-analyzer"
c:/Github/personal/stock-AI-python/j-stock-analyzer/.venv/Scripts/python.exe main.py pos-evaluation --mode annual --years 2021 2022 2023 2024 2025 --entry-filter-mode off --exit-confirm-days 1 --entry-strategies MACDCrossoverStrategy MACDPreCross2BarEntry --exit-strategies MVX_N3_R3p85_T2p0_D21_B20p0 MVX_N3_R3p25_T1p6_D21_B20p0 MVX_N3_R3p35_T1p6_D21_B20p0 MVX_N3_R3p25_T1p8_D21_B20p0 --output-dir "G:/My Drive/AI-Stock-Sync/strategy_evaluation/mvx_d21_cli_20260409/finalists_pos_eval"
Pop-Location
```
