---
name: evaluation-result-summary
description: 'Use when: aggregating completed J-stock evaluation output directories into markdown summary reports under G:/My Drive/AI-Stock-Sync/summary without rerunning backtests.'
argument-hint: 'Provide completed output directories, a runner summary.json path, or a run_dir, plus whether you want merge-surface or compare-jobs output'
---

# Evaluation Result Summary

## Purpose

Aggregate completed evaluation outputs into a markdown summary artifact only.

This skill is post-run analysis. It does not execute backtests, generate manifests, or modify source code.

The workflow is always:

1. Resolve the exact completed output directories to analyze.
2. Decide the summary mode: `merge-surface` or `compare-jobs`.
3. Read the completed result files needed for the requested summary.
4. Generate a markdown summary file under `G:/My Drive/AI-Stock-Sync/summary/<YYYY-MM-DD>/`.
5. Return the summary file path plus concise findings in chat.

## Hard Rules

- Do not execute `evaluate`, `pos-evaluation`, `walk-forward-evaluate`, or `replay-evaluation`.
- Do not generate or overwrite `tmp/evaluationtmp.json` here.
- Do not modify source code, configs, or git state while using this skill unless the user separately asks for code changes.
- Prefer explicit completed output directories, a local runner `summary.json`, or a local runner `run_dir` over broad filesystem discovery.
- If the current session already established the exact completed run, you may reuse that run's `summary.json` or output directories without re-discovering them.
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

## Input Resolution

Accept one of these inputs, in descending priority:

1. Explicit completed output directories.
2. An explicit local runner `summary.json` path.
3. An explicit local runner `run_dir`.
4. A current-session completed run that already established the exact output directories.

If a runner `summary.json` is provided, prefer it as the source of truth for completed worker output directories.

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

- required: `*_raw_*.csv`
- required: `*_prs_train_rank_*.csv`
- optional: `*_exit_urgency_contribution_*.csv`
- optional: `*_annual_final_review_*.md`

Primary join rule:

- Prefer `entry_strategy + exit_strategy` when both are present in the extracted tables.
- If that pair is not explicitly available, use the finest stable key available and state the fallback in the Notes or Provenance section.

Default ranking rule:

1. `prs_train_score` descending
2. `return_pct` descending
3. `max_drawdown_pct` ascending

## Default Report Shapes

For `merge-surface`, the primary markdown table should usually be the full merged surface.

Recommended columns:

- parameter axis or axes
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

## J-stock Notes

- Default output root for evaluation results is usually `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- When a local runner `summary.json` exists, use it to identify the exact completed output directories rather than inferring them from timestamps alone.
- Keep the markdown summary artifact separate from the human-authored daily notes under `G:/My Drive/AI-Stock-Sync/reports`.
- Prefer a new summary markdown per analysis pass unless the user explicitly asks to enrich an existing summary file.