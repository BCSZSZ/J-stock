---
name: evaluation-progress-monitor
description: 'Use when: monitoring long-running J-stock evaluate, pos-evaluation, walk-forward-evaluate, or replay-evaluation commands after launch. Handles low-frequency terminal progress checks, terminal-tail reading, ETA-based next-check timing, and avoiding over-polling.'
argument-hint: 'Describe the running evaluation command, terminal state, launch time, and what progress summary you need'
---

# Evaluation Progress Monitor

## Purpose

Use this skill to monitor already-started J-stock backtest and evaluation commands without excessive polling.

The workflow is:

1. Confirm the command has already been launched.
2. Avoid early manual progress reads.
3. Read only the terminal tail, not full output or repeated process lists.
4. Use ETA or clear progress markers to schedule the next check.
5. Stop monitoring once the run finishes or requests input.
6. Report final status, output directory, and the most relevant result files.

## Hard Rules

- Do not launch a new backtest/evaluation command unless the user separately asked for execution.
- Do not manually check progress before 10 minutes have elapsed from launch, unless the terminal tool already reports completion or requests input sooner.
- Use terminal output as the primary progress source. Do not repeatedly poll `Get-CimInstance`, `tasklist`, `ps`, or similar process-list commands when terminal output is available.
- On each manual progress read, use only the latest terminal tail and summarize only the last 5 meaningful lines.
- Do not read full scrollback unless the latest tail is insufficient to understand a failure.
- If ETA is available, dynamically adjust the next check time from that ETA.
- If ETA is not available, keep a coarse 10-minute cadence between checks.
- Do not use sleep commands or tight polling loops.

## Monitoring Policy

- Prefer an initial `run_in_terminal` sync execution with a timeout of at least 600000 ms for long-running evaluation-family commands.
- If the command is still running after that timeout, or if you inherit an already-running terminal, the first manual progress check must be at or after launch + 10 minutes.
- On each progress check, inspect only the newest terminal snapshot and focus on the last 5 meaningful lines.
- Recognize progress cues such as `x/y`, annual task counters, continuous task counters, percent complete, remaining symbols, or explicit ETA.
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
- Terminal tail (last 5 meaningful lines):
  - <line 1>
  - <line 2>
  - <line 3>
  - <line 4>
  - <line 5>
- Current interpretation: <what stage the run is in>
- Next check plan: <time or ETA-based rationale>
```

When the run finishes, report:

- Exit status.
- Output directory.
- Most relevant result files.
- Any warning/error lines that matter.
- A one-paragraph status summary.

## J-stock Notes

- Evaluation outputs usually land under the configured output root and then auto-expand into `YYYYMMDD/<run-slug>__HHMMSS/`.
- For this workspace, the output root usually resolves to `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- Use the completed run directory contents, not the parent date directory, when identifying result files for analysis.