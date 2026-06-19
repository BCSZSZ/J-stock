---
name: stock-pool-oos-evaluation-plan
description: Use when generating approval-ready J-stock out-of-sample evaluation commands or batch manifests that compare trained selected stock pools against current production and broad/full universe controls.
---

# Stock Pool OOS Evaluation Plan

Prepare OOS evaluation without executing it.

## Inputs

Require:

- Test range or OOS years for each fold.
- Selected-pool universe JSON files generated from training data only.
- Current production pool universe file.
- Broad/full universe file.
- Fixed entry strategy, exit strategy, ranking strategy, entry filter mode, sizing, and capacity assumptions.

Resolve production defaults from `G:/My Drive/AI-Stock-Sync/config.json` and `production.strategy_groups` when the user asks for production parity.

## Manifest Rules

Use `evaluation-batch-generator` when jobs are long, multi-fold, or need worker planning. Preserve its approval boundary:

- Generate or update `tmp/evaluationtmp.json`.
- Present the manifest content and exact universe controls.
- Stop before execution until the user approves the exact manifest.

For a small direct command plan, use `evaluate` with explicit universe files:

```powershell
uv run python main.py evaluate `
  --mode annual `
  --years <TEST_YEARS> `
  --entry-strategies <ENTRY_STRATEGY> `
  --exit-strategies <EXIT_STRATEGY> `
  --ranking-strategies <RANKING_STRATEGY> `
  --ranking-mode prs_train `
  --entry-filter-mode <ENTRY_FILTER_MODE> `
  --universe-file <CURRENT_POOL> <FULL_POOL> <SELECTED_POOL> `
  --output-dir "G:/My Drive/AI-Stock-Sync/strategy_evaluation"
```

Use explicit `--custom-periods` or start/end capable tooling if the OOS fold is a partial year and annual `--years` would include unwanted dates.

## Control Integrity

- Keep all non-universe parameters identical across controls.
- Pass current production pool explicitly instead of relying on config default.
- Name jobs and output labels with fold id and universe name.
- If selected pools have different sizes, run each size as a separate universe control and report sizes.
- Flag survivorship risk for full-universe controls based on current listing files.

## Output

Return:

- The proposed command or manifest JSON.
- Worker count and evaluation-point count when using a manifest.
- The universe files and expected ticker counts.
- Which defaults were pinned from production config.
- Which defaults were intentionally omitted because CLI/config behavior already matches.

Do not run the manifest or evaluation command in this skill.
