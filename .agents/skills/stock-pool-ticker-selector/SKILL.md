---
name: stock-pool-ticker-selector
description: Use when aggregating J-stock training-period entry-signal-analysis or entry-exit-validation CSV artifacts by ticker, scoring ticker robustness, and exporting selected stock-pool universe JSON files for out-of-sample evaluation.
---

# Stock Pool Ticker Selector

Convert training-period signal results into fixed ticker universe files.

## Inputs

Use one of these training-only artifacts:

- Preferred entry-only input: `entry_signal_analysis_selected_*.csv`.
- Alternative entry-only diagnostic input: `entry_signal_analysis_candidates_*.csv`.
- Entry-plus-exit input: `combo_selected_trades.csv` from `entry-exit-validation`.

Require a known training cutoff. Reject or flag rows with `signal_date` or `entry_date` after the training end date.

## Ticker Metrics

Aggregate by normalized ticker code. Compute at least:

- `sample_count`
- `active_year_count`
- `win_rate`
- `avg_return`
- `median_return`
- `trimmed_mean_5pct`
- `p10_return`
- `p25_return`
- `top_5pct_contribution_ratio`
- `mean_without_top_5pct_return`

For `entry-signal-analysis`, use the planned primary return column such as `forward_return_3d_pct` or `forward_return_5d_pct`. For `entry-exit-validation`, use `return_pct`.

## Selection Rules

Default gates:

- Require `sample_count >= 20` for short training windows, or `>= 30` for multi-year training windows.
- Require signals in at least two distinct years when the training window spans at least two years.
- Rank by robust central performance and downside control, not raw average alone.
- Penalize high top-tail dependence, especially when `top_5pct_contribution_ratio > 0.5` or `mean_without_top_5pct_return` is negative.

Default score order:

1. Higher `trimmed_mean_5pct`.
2. Higher `median_return`.
3. Higher `p10_return`.
4. Higher `win_rate`.
5. Lower `top_5pct_contribution_ratio`.
6. Higher `sample_count`.

## Universe Output

Export JSON that `src.utils.universe_loader.load_tickers_from_file` can read:

```json
{
  "version": "1.0",
  "pool_id": "selected_top140_train_2022_2025",
  "created_at": "YYYY-MM-DDTHH:MM:SS",
  "selection_source": "<training CSV path>",
  "train_start": "YYYY-MM-DD",
  "train_end": "YYYY-MM-DD",
  "target_size": 140,
  "tickers": [
    {
      "code": "7203",
      "rank": 1,
      "score": 1.234,
      "sample_count": 42,
      "active_year_count": 3
    }
  ]
}
```

Write selected-pool artifacts under `G:/My Drive/AI-Stock-Sync/universe/` unless the user requests a repo-local fixture.

## Validation

- Reopen each generated JSON with `load_tickers_from_file`.
- Confirm unique ticker count equals the intended size, or explain why gates produced fewer names.
- Save the ticker score table next to the JSON when practical.
- Do not update production monitor lists or production config.
