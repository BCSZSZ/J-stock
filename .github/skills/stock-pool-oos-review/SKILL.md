---
name: stock-pool-oos-review
description: Use when reviewing completed J-stock custom stock-pool out-of-sample evaluations, comparing selected pools with current and full-pool controls, and auditing leakage or survivorship-bias risks.
---

# Stock Pool OOS Review

Summarize completed OOS stock-pool experiments from machine-readable artifacts.

## Sources

Prefer:

- Runner `summary.json` under `tmp/parallel_eval/<run>/...`.
- Raw evaluation CSVs under `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- Generated universe JSON metadata and ticker score CSVs.

Do not rely on terminal-rendered markdown for numeric comparisons when encoding is unreliable.

## Metrics

Compare each universe control on:

- Annual or period `return_pct`.
- `topix_return_pct` and `alpha`.
- `sharpe_ratio`.
- `max_drawdown_pct`.
- `num_trades`.
- `win_rate_pct`.
- Trade concentration if raw trade files are available.
- Pool size and effective ticker count.

Report both fold-level results and pooled OOS averages. Keep training metrics separate from OOS metrics.

## Leakage Audit

Check and state:

- Selected-pool `train_end` is strictly before OOS `test_start`.
- Selection source CSV contains no rows after `train_end`.
- Selected universe file was passed explicitly to OOS evaluation.
- Current, full, and selected controls share the same entry/exit/ranking/filter/sizing settings.
- Pool sizes are equal where the claim depends on a size-matched comparison.
- Full-universe control may contain survivorship bias if sourced from a current listing file.

## Decision Framing

Treat a selected pool as promising only if:

- It beats current and full controls out-of-sample on return or alpha.
- It does not materially worsen drawdown or Sharpe.
- Improvement is not explained by a few trades or one market regime.
- The same selection logic works across more than one OOS fold.

## Output

Produce a concise markdown report, preferably under `G:/My Drive/AI-Stock-Sync/summary`, with:

- Experiment scope and absolute dates.
- Universe/control table.
- OOS result table.
- Leakage audit checklist.
- Findings and next recommended experiment.
