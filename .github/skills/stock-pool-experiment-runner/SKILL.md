---
name: stock-pool-experiment-runner
description: Use when orchestrating a J-stock custom stock-pool experiment where a fixed entry condition is applied to a broad/full universe during a training window, good tickers are selected into one or more test universes, and those universes are evaluated out-of-sample against current and full-pool controls.
---

# Stock Pool Experiment Runner

Coordinate the stock-pool selection workflow without collapsing the train/test boundary.

## Atomic Tasks

Route work to these skills in order:

1. `stock-pool-split-planner`: define train windows, test windows, controls, pool sizes, and leakage rules.
2. `stock-pool-entry-signal-scan`: generate training-period `entry-signal-analysis` datasets from the broad/full universe.
3. `stock-pool-ticker-selector`: aggregate training signals by ticker and export selected universe JSON files.
4. `stock-pool-oos-evaluation-plan`: generate an approval-ready OOS evaluation manifest comparing selected, current, and full universes.
5. `evaluation-batch-executor`: execute only after the exact manifest is approved.
6. `stock-pool-oos-review`: summarize completed OOS results and leakage checks.

Use existing `evaluation-batch-runner` only when the user asks for a full batch workflow and a manifest approval boundary is needed.

## Hard Rules

- Treat ticker selection as model training. Never select tickers using dates that overlap the test window.
- Keep entry condition, ranking strategy, entry filters, sizing, capacity, and exit strategy fixed across universe controls unless the experiment explicitly varies one of them.
- Compare at least: current production pool, broad/full pool, and trained selected pool of the same target size as the current pool.
- Do not edit production config to run experiments. Pass universe files explicitly through CLI args or manifests.
- Use `G:/My Drive/AI-Stock-Sync/config.json` as production source of truth when resolving production defaults.
- Use absolute date ranges in plans and reports.

## Reporting

Before any long run, report:

- Train window and test window for each fold.
- Universe files for current, full, and selected pools.
- Pool sizes to export, usually including `140` plus sensitivity sizes such as `80` and `200`.
- The exact command or manifest that will run next.
- The approval state when execution would start.
