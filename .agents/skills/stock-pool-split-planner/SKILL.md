---
name: stock-pool-split-planner
description: Use when designing leakage-safe train/test windows, universe controls, and pool-size variants for J-stock experiments that select tickers from historical entry-signal performance before out-of-sample evaluation.
---

# Stock Pool Split Planner

Create the experiment contract before generating data or running backtests.

## Inputs

Resolve or ask for:

- Fixed entry strategy and whether production ranking/filter defaults should be pinned.
- Broad/full universe file to scan during training.
- Current production pool file from `G:/My Drive/AI-Stock-Sync/config.json`.
- Target pool sizes, with `140` as the primary size when matching the current pool.
- Train/test folds, using only dates before each test fold to select tickers.
- Whether the selection is entry-only or entry-plus-exit. For the user's current workflow, default to entry-only.

## Default Split Shape

Prefer anchored walk-forward style when the user has no stronger preference:

- Train `2022-01-01` through `2024-12-31`, test `2025-01-01` through `2025-12-31`.
- Train `2022-01-01` through `2025-12-31`, test from `2026-01-01` through the latest available date.

If data availability differs, adjust with explicit absolute dates and state the reason.

## Controls

Plan these universe controls for each OOS fold:

- `current140`: production/current 140-stock pool, passed as an explicit universe file.
- `full`: broad/full universe, with survivorship-bias caveats if it is based on a current listing file.
- `selected_top140`: tickers selected from the training window only.
- Optional sensitivity pools: `selected_top80`, `selected_top200`.

## Output

Return a compact plan table with:

- Fold id.
- Training range.
- Test range.
- Scan universe.
- Output selected-pool files to be generated.
- OOS universe controls.
- Any unresolved inputs.

Do not run `entry-signal-analysis`, write universe files, or generate evaluation manifests in this skill.
