---
name: stock-pool-entry-signal-scan
description: Use when generating training-window entry-signal-analysis datasets for a J-stock stock-pool experiment, especially scanning a broad/full universe with a fixed entry strategy before ticker-level pool selection.
---

# Stock Pool Entry Signal Scan

Generate training data for ticker selection. This skill does not select tickers and does not run portfolio evaluation.

## Command Shape

Use `entry-signal-analysis` for production-style entry signal quality:

```powershell
uv run python main.py entry-signal-analysis `
  --entry-strategies <ENTRY_STRATEGY> `
  --universe-file <FULL_UNIVERSE_FILE> `
  --start <TRAIN_START> `
  --end <TRAIN_END> `
  --horizons 1 3 5 `
  --primary-horizons 3 5 `
  --primary-horizon 3 `
  --label-mode next_open `
  --ranking-strategy <RANKING_STRATEGY> `
  --entry-filter-mode <ENTRY_FILTER_MODE> `
  --output-dir "G:/My Drive/AI-Stock-Sync/entry_signal_analysis"
```

Prefer explicit `--start` and `--end` for fold-specific training windows. Use `--years` only when full calendar years are intended.

## Parameter Rules

- Resolve production defaults from `G:/My Drive/AI-Stock-Sync/config.json`, especially `production.strategy_groups` and `production.signal_ranking_strategy`.
- Use the same ranking strategy and entry filter mode later used in OOS evaluation unless the experiment intentionally varies them.
- Do not include OOS/test dates in the scan.
- Keep the broad/full universe fixed for training scans across folds unless the experiment explicitly studies full-universe definitions.
- Use `entry-exit-validation` instead only when the user asks to select tickers by entry-plus-exit behavior.

## Required Artifacts

After a run, locate and report:

- `entry_signal_analysis_manifest.json`
- `entry_signal_analysis_candidates_*.csv`
- `entry_signal_analysis_selected_*.csv`
- `entry_signal_analysis_summary_*.json`
- `entry_signal_analysis_report_*.md`

Use `selected` rows for pool selection unless the user asks to score all BUY candidates.

## Validation

Check the manifest before handing off to ticker selection:

- `start_date` and `end_date` match the training fold.
- `universe_size` matches the expected broad/full universe.
- `entry_strategies`, `ranking_strategy`, `entry_filter_mode`, and horizons match the plan.
- Candidate and selected counts are nonzero, or the empty result is explicitly reported.
