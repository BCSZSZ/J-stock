---
name: evaluation-progress-monitor
description: 'Legacy-only monitoring skill. New J-stock batch runs should keep bounded monitoring inside evaluation-batch-executor.'
argument-hint: 'Use only for legacy prompts that explicitly require this skill; otherwise route monitoring back to evaluation-batch-executor'
---

# Evaluation Progress Monitor

## Purpose

This skill is deprecated for new workflows.

Use `evaluation-batch-executor` instead so launch, bounded monitoring, and final reporting stay in one lifecycle.

Keep this skill only for legacy prompts that explicitly ask for it or for older conversations that already established it as the active monitoring surface.

This skill does not generate commands and should not be the default entrypoint for newly launched manifests.

The workflow is:

1. Confirm the command has already been launched.
2. Identify the local runner summary/log directory when one exists.
3. Avoid early manual progress reads.
4. Read local summary/log state first, then only the terminal tail when needed.
5. Use ETA or clear progress markers to schedule the next check.
6. Stop monitoring once the run finishes or requests input.
7. Report final status, local run directory, output directory, and the most relevant result files.

## Hard Rules

- Do not launch a new backtest/evaluation command unless the user separately asked for execution.
- Monitor known parent terminals or explicitly provided local run directories from the current agent session; do not hand execution or progress tracking off to subagents by default.
- Do not discover or infer unknown workers from process lists; monitor only known terminal IDs, known local run directories, or an explicitly inherited running parent terminal.
- Do not manually check progress before 10 minutes have elapsed from launch, unless the terminal tool already reports completion or requests input sooner.
- Use the local runner summary as the primary worker-progress source when it exists. Use terminal output mainly to understand parent-runner state or failures.
- Do not repeatedly poll `Get-CimInstance`, `tasklist`, `ps`, or similar process-list commands when summary/log artifacts or terminal output are available.
- On each manual progress read, use only the latest summary snapshot and, if needed, the latest terminal tail or the newest worker log tail.
- Do not read full scrollback unless the latest tail is insufficient to understand a failure.
- If ETA is available, dynamically adjust the next check time from that ETA.
- If ETA is not available, keep a coarse 10-minute cadence between checks.
- Do not use sleep commands or tight polling loops.

## Monitoring Policy

- If you inherit an already-running terminal, or if execution was previously launched by the current agent session, the first manual progress check must be at or after launch + 10 minutes unless the terminal already reported completion or requested input sooner.
- On each progress check, inspect the newest `summary.json` first when available. Report worker counts by status and only open a worker log when the summary alone is insufficient.
- If you need terminal context, inspect only the newest parent terminal snapshot and focus on the last 5 meaningful lines.
- Recognize progress cues such as worker status counts, `x/y`, annual task counters, continuous task counters, percent complete, remaining symbols, or explicit ETA.
- If explicit ETA is present, set the next manual check delay dynamically:
  - If ETA is greater than 20 minutes, check again in 10 minutes.
  - If ETA is between 6 and 20 minutes, check again at roughly ETA / 2.
  - If ETA is 5 minutes or less, do not add extra midpoint polling; wait for the expected completion window unless the terminal reports sooner.
- If there is no ETA, keep a fixed 10-minute gap between manual checks.
- If the command finishes, errors, or requests input, stop monitoring immediately and switch to result/failure reporting.

## Reporting Format

When reporting a progress update, keep it brief:

```markdown
**Progress**
- Summary status:
  - <running/completed/failed worker counts>
  - <known output directories or latest completed worker>
- Terminal or worker-log tail (last 5 meaningful lines when needed):
  - <line 1>
  - <line 2>
  - <line 3>
  - <line 4>
  - <line 5>
- Current interpretation: <what stage the run is in>
- Next check plan: <time or ETA-based rationale>
```

When the run finishes, report:

- Parent exit status.
- Local run directory.
- Summary JSON path.
- Representative worker logs when relevant.
- Output directory.
- Most relevant result files.
- Any warning/error lines that matter.
- A one-paragraph status summary.
- If the parent terminal transcript and local summary disagree, state the conflict explicitly and prefer the local summary for worker status.
- If local summary and evaluation outputs disagree, state the conflict explicitly and prefer the completed evaluation run directory on disk for final result file references.

## J-stock Notes

- Evaluation outputs usually land under the configured output root and then auto-expand into `YYYYMMDD/<run-slug>__HHMMSS/`.
- For this workspace, the output root usually resolves to `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- Batch-runner control-plane artifacts are local and should usually live under `tmp/parallel_eval/<timestamp>/`.
- Use the completed run directory contents, not the parent date directory, when identifying result files for analysis.