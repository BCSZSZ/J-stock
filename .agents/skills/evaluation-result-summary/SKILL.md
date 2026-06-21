---
name: evaluation-result-summary
description: 'Use when: aggregating completed J-stock evaluation output directories into markdown summary reports under G:/My Drive/AI-Stock-Sync/summary without rerunning backtests, including global MDD-Win re-scoring via tools/score_evaluation_outputs.py when worker-local PRS is not comparable.'
argument-hint: 'Provide completed output directories, a runner summary.json path, or a run_dir, plus whether you want merge-surface or compare-jobs output'
---

# Evaluation Result Summary

## Purpose

Aggregate completed evaluation outputs into a markdown summary artifact only.

This skill is post-run analysis. It does not execute backtests, generate manifests, or modify source code.

The workflow is always:

1. Resolve the exact completed output directories to analyze.
2. Run the global scoring pass when the inputs are a batch/mesh/comparison with more than one completed output directory.
3. Decide the summary mode: `merge-surface`, `compare-jobs`, or `mesh-deep-dive`.
4. Read the completed result files needed for the requested summary.
5. Generate a markdown summary file under `G:/My Drive/AI-Stock-Sync/summary/<YYYY-MM-DD>/`.
6. Return the summary file path plus concise findings in chat.

## Hard Rules

- Do not execute `evaluate`, `pos-evaluation`, `walk-forward-evaluate`, or `replay-evaluation`.
- Do not generate or overwrite `tmp/evaluationtmp.json` here.
- Do not modify source code, configs, or git state while using this skill unless the user separately asks for code changes.
- Prefer explicit completed output directories, a local runner `summary.json`, or a local runner `run_dir` over broad filesystem discovery.
- If the current session already established the exact completed run, you may reuse that run's `summary.json` or output directories without re-discovering them.
- For batch/mesh/comparison summaries with multiple completed output directories, run `tools/score_evaluation_outputs.py` before drawing ranking conclusions.
- Do not use worker-local `prs_train_score` for cross-worker ranking when each worker/job has only one candidate, because local normalization collapses to neutral scores.
- Prefer explicit per-output parameter sidecars when present: `*_parameters_*.json` from `evaluate` and `evaluation_batch_job_*.json` from the batch runner.
- Read `*_raw_*.csv` and `*_prs_train_rank_*.csv` as the primary tabular sources.
- Read `*_exit_urgency_contribution_*.csv` only when the user asks for exit-mix diagnostics or when reporting the champion exit mix materially helps the conclusion.
- Treat this skill as read-mostly with one allowed artifact write: the generated markdown summary file under `G:/My Drive/AI-Stock-Sync/summary`.
- Do not silently merge unrelated runs. If the grouping axis is ambiguous, ask one concise clarifying question.
- Do not default to scanning all of `G:/My Drive/AI-Stock-Sync/strategy_evaluation` for the latest run when a narrower anchor already exists.

## Supported Modes

### `merge-surface`

Use when multiple output directories are worker slices of one logical parameter surface.

Typical examples:

- Multiple `R` slices for fixed `T` and `I`
- Multiple worker partitions of one exit grid
- Split output directories from one runner summary that should be merged into one logical table

Default report sections for `merge-surface`:

- Scope
- Executive Summary
- Primary merged table
- Top-N combinations by ranking metric
- Plateau table
- Band summary when the axis is ordinal or numeric
- Optional champion exit mix
- Provenance

### `compare-jobs`

Use when multiple completed output directories should be compared as peer jobs.

Typical examples:

- Comparing multiple entry pairs against the same top exits
- Comparing multiple approved manifests or worker jobs as parallel candidates
- Comparing different strategy bundles or parameter families side by side

Default report sections for `compare-jobs`:

- Scope
- Executive Summary
- Primary one-row-per-job comparison table
- Global top combinations across all jobs
- Per-job champions
- Optional champion exit mix
- Provenance

### `mesh-deep-dive`

Use when a completed parameter mesh needs a second-pass diagnostic report after an initial surface summary already exists.

Typical examples:

- Confirming whether each mesh axis has a stable single-factor tendency.
- Comparing full-period results against 2025/2026 or 2026-only conclusions.
- Finding whether the current best region is a plateau, an edge, or an unresolved boundary.
- Producing concrete next-mesh recommendations from completed annual evaluation outputs.

Reference implementation:

- `references/mesh_deep_dive_report.py`

Default report sections for `mesh-deep-dive`:

- Scope
- Parameter grid check
- Executive summary
- Top overall combinations
- Top 2026 combinations
- Single-axis marginal tables with paired deltas
- 2026 and 2025/2026 confirmation
- Risk x ATR surface
- Daily x total cap surface
- Plateau / high-table analysis
- Next mesh recommendation
- Provenance

Required metrics for `mesh-deep-dive`:

- full-period mean return
- 2026 return
- 2025/2026 mean return
- average max drawdown and worst-year max drawdown
- average Sharpe
- average win rate from `win_rate_pct`
- 2026 win rate from `win_rate_pct`
- trade count when it materially affects interpretation

## Input Resolution

Accept one of these inputs, in descending priority:

1. Explicit completed output directories.
2. An explicit local runner `summary.json` path.
3. An explicit local runner `run_dir`.
4. A current-session completed run that already established the exact output directories.

If a runner `summary.json` is provided, prefer it as the source of truth for completed worker output directories.

## Global Scoring Pass

Run this pass for any completed batch with multiple output directories, especially one-worker-per-cell meshes. It is read-only with respect to evaluation outputs and writes only score artifacts under `tmp/evaluation_global_scores` unless the user specifies another output directory.

Preferred command when a runner summary exists:

```powershell
uv run python tools/score_evaluation_outputs.py `
  --summary-json <local-run-dir>/summary.json `
  --out-dir tmp/evaluation_global_scores `
  --output-prefix <short-run-slug> `
  --top-n 20
```

When only explicit output directories are available, pass each one:

```powershell
uv run python tools/score_evaluation_outputs.py `
  --output-dir "<completed-output-dir-1>" `
  --output-dir "<completed-output-dir-2>" `
  --out-dir tmp/evaluation_global_scores `
  --output-prefix <short-run-slug> `
  --top-n 20
```

Use `--recent-period <period>` only when the user explicitly wants a fixed recent period; otherwise let the tool use each candidate's latest period.

Global scoring formula:

- `mdd_win_score = 0.25*mean_return + 0.15*recent_return + 0.25*avg_mdd_inverse + 0.10*worst_mdd_inverse + 0.20*mean_win_rate + 0.05*mean_sharpe`
- Normalization is robust 10%-90% winsorized normalization across the merged candidate pool.

Use the generated CSV/Markdown from `tools/score_evaluation_outputs.py` as the default ranking source for cross-output conclusions. Include both paths in the final markdown Provenance section when available.

## Summary Artifact Rules

Default summary root:

- `G:/My Drive/AI-Stock-Sync/summary`

Default directory layout:

- `G:/My Drive/AI-Stock-Sync/summary/<YYYY-MM-DD>/`

Default file naming rule:

- `<timestamp>__<mode>__<slug>.md`

Examples:

- `20260528_173140__compare-jobs__entry-top4.md`
- `20260528_160823__merge-surface__i1p2-t1p0-r.md`

Reuse/update policy:

- Default behavior is to create a new markdown summary file.
- Only update an existing summary file when the user explicitly provides that summary file path or clearly asks to continue enriching the same markdown artifact.
- Do not silently overwrite a prior summary just because the date or topic looks similar.

Required frontmatter fields:

```yaml
---
summary_version: 1
generated_at: 2026-05-28T17:40:00
mode: compare-jobs
source_run_dir: C:/code/J-stock/tmp/parallel_eval/20260528_173140
source_summary_json: C:/code/J-stock/tmp/parallel_eval/20260528_173140/summary.json
source_output_dirs:
  - G:/My Drive/AI-Stock-Sync/strategy_evaluation/20260528/...
  - G:/My Drive/AI-Stock-Sync/strategy_evaluation/20260528/...
---
```

Section update markers:

- When generating or updating markdown, wrap replaceable sections with explicit markers so future runs can update a single section without rewriting the whole file.
- Use markers such as:

```md
<!-- section:primary-table:start -->
...table content...
<!-- section:primary-table:end -->
```

## Data Extraction Rules

From each completed output directory:

- preferred: `*_parameters_*.json`
- optional: `evaluation_batch_job_*.json`
- required: `*_raw_*.csv`
- required: `*_prs_train_rank_*.csv`
- optional: `*_exit_urgency_contribution_*.csv`
- optional: `*_annual_final_review_*.md`

For `mesh-deep-dive`, run the reference script instead of recreating ad hoc analysis code:

```powershell
uv run python .agents/skills/evaluation-result-summary/references/mesh_deep_dive_report.py `
  --output-root "G:/My Drive/AI-Stock-Sync/strategy_evaluation/<YYYYMMDD>" `
  --source-summary "G:/My Drive/AI-Stock-Sync/summary/<YYYY-MM-DD>/<existing-summary>.md" `
  --output "G:/My Drive/AI-Stock-Sync/summary/<YYYY-MM-DD>/<timestamp>__mesh-deep-dive__<slug>.md" `
  --title "<report title>"
```

`mesh-deep-dive` must treat raw CSV `win_rate_pct` as a first-class metric. Include both full-period `avg_win` and `win_2026` in top tables, single-axis marginal tables, risk/ATR surfaces, cap surfaces, and plateau tables.

Parameter-source priority:

1. explicit run parameter sidecar `*_parameters_*.json`
2. batch-runner job sidecar `evaluation_batch_job_*.json`
3. runner `summary.json` / worker `full_command`
4. explicit columns in `*_raw_*.csv` / `*_prs_train_rank_*.csv`
5. output directory slug decoding
6. `*_trades_*.csv` embedded JSON only as a last-resort fallback

Primary join rule:

- Prefer `entry_strategy + exit_strategy` when both are present in the extracted tables.
- If that pair is not explicitly available, use the finest stable key available and state the fallback in the Notes or Provenance section.

Default ranking rule:

1. Cross-output global `mdd_win_score` descending when a batch has multiple completed output directories.
2. Worker-local `prs_train_score` descending only when the score was computed over multiple candidates in the same output.
3. `return_pct` descending.
4. `max_drawdown_pct` ascending.

## Default Report Shapes

For `merge-surface`, the primary markdown table should usually be the full merged surface.

Recommended columns:

- parameter axis or axes
- high-value run parameters when they materially affect interpretation: universe, fill mode, entry reference mode, buffer setting, position sizing mode, ATR risk per trade, ATR stop multiple
- ranking score
- return
- max drawdown
- win rate
- num trades
- sharpe
- optional local slice rank if it helps provenance

For `compare-jobs`, the primary markdown table should usually be one row per job.

Recommended columns:

- job label
- inferred or declared strategy bundle
- key resolved run parameters from sidecars when present
- best combination
- best ranking score
- best return
- best max drawdown
- average ranking score
- average return
- average max drawdown
- average sharpe
- trades range or representative trade count

## Reporting Format

In chat, respond with:

- the generated markdown summary file path
- 3 to 5 concise findings
- any ambiguity or assumption that materially affected grouping

The markdown file itself should contain the full tables and supporting detail.

When parameter sidecars exist, include a dedicated parameter section in the markdown body before the main performance tables. That section should prefer explicit sidecar values over values reverse-engineered from trade rows or strategy-name tokens.

## J-stock Notes

- Default output root for evaluation results is usually `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- When a local runner `summary.json` exists, use it to identify the exact completed output directories rather than inferring them from timestamps alone.
- Newer runs may contain `*_parameters_*.json` and `evaluation_batch_job_*.json`; treat them as the canonical source for authored and resolved parameter context.
- Keep the markdown summary artifact separate from the human-authored daily notes under `G:/My Drive/AI-Stock-Sync/reports`.
- Prefer a new summary markdown per analysis pass unless the user explicitly asks to enrich an existing summary file.
