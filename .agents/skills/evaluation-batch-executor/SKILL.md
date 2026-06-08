---
name: evaluation-batch-executor
description: 'Use when: executing an already-approved worker-ready J-stock batch manifest. Launch one parent runner command from the current agent session, keep the manifest unchanged, and own bounded monitoring until completion or an explicit leave-running handoff.'
argument-hint: 'Provide the approved manifest path, expected output root, and whether you need launch-only or wait-for-completion behavior'
---

# Evaluation Batch Executor

## Purpose

Execute an already-approved worker-ready manifest only.

The workflow is always:

1. Confirm the exact manifest content was already approved.
2. Launch one parent runner command from the current agent session.
3. Record `parent_command -> terminal_id -> launch_time -> manifest_path -> local_run_dir` immediately.
4. Prefer passive waiting for the parent terminal to finish; only enter manual progress checks when the parent is still active and no terminal completion signal has arrived.
5. When manual checks are necessary, use bounded summary-first investigation from the same skill.
6. Report succeeded, failed, left-running, or abandoned status for the manifest as a whole, plus worker-level status from the runner summary.

## Hard Rules

- Do not generate or reinterpret worker planning here. Use `evaluation-batch-generator` first if the manifest does not already exist.
- Do not change the approved manifest contents.
- Do not add, remove, reorder, or silently rewrite manifest jobs after approval.
- Do not repartition `exit_strategies` or reinterpret `num_workers` here. Worker splitting belongs to generator.
- Do not use subagents by default. Use one current-session parent terminal per approved manifest.
- For multiple approved manifests, prefer `multi_tool_use.parallel` to launch concurrent parent runner commands.
- Prefer `mode=async` for long-running manifest execution. Use `mode=sync` with a generous timeout only when waiting is practical.
- Do not hand progress ownership off to `evaluation-progress-monitor` for new runs. Keep launch, bounded monitoring, and completion reporting inside this skill.
- Do not silently rerun failed commands. Report the failure and wait for user approval before retrying.
- Do not widen scope into result analysis here; execution status and output locations are the goal.
- Do not finish while required approved commands are still active unless the user explicitly asked to leave them running.
- Do not do manual progress reads before launch + 10 minutes unless the terminal tool itself reports completion, failure, or requests input sooner.
- Use the local runner `summary.json` as the primary progress source. Use terminal tail only for parent-runner errors or explicit prompts.
- Do not repeatedly poll `Get-CimInstance`, `tasklist`, `ps`, or similar process listings. If the runner summary already exposes worker telemetry, rely on it.
- If a process-level fallback is unavoidable for a legacy run, do at most one discovery pass and then wait on that fixed PID set. Do not rescan the process table.
- On each manual progress read, inspect only the newest `summary.json` and, if needed, one parent terminal tail or one newest worker-log tail.
- If there is no ETA or other reliable completion marker, keep a coarse 10-minute gap between manual checks.
- Do not use sleep commands or tight polling loops.

## Execution Contract

- Approved manifests should normally be executed from the J-stock repo root with a parent command such as `uv run python tools/evaluation_batch_runner.py --spec tmp/evaluationtmp.json`.
- Launch one parent runner from the J-stock repo root. The runner owns parallel worker subprocesses internally.
- Keep the approved manifest unchanged. Do not inject extra jobs, reorder jobs, or modify per-worker `exit_strategies` slices.
- Record the launch mapping in the main session immediately after the parent runner starts.
- Keep execution ownership in the current agent session so the parent terminal ID, completion notifications, and progress checks stay attributable.
- Control-plane artifacts are local under `tmp/parallel_eval/<timestamp>/`, while actual evaluation outputs still land under the configured output root such as `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.
- Prefer passive waiting first. If the parent command remains active after the initial launch window and there is no completion notification, defer the first manual check until launch + 10 minutes.
- For manual checks, inspect `summary.json` first. Use runner-emitted worker telemetry such as `status`, `worker_pid`, `last_output_at`, `output_line_count`, and incrementally discovered `output_dir` to judge whether the run is advancing.
- Only inspect a worker log tail when the summary alone is insufficient, such as a failed worker, a stale heartbeat, or missing output directories.
- If the current parent terminal transcript and the local runner summary disagree, prefer the local runner summary for worker status.
- If terminal output and on-disk artifacts disagree, prefer the local runner summary for worker status and the completed evaluation output directory on disk for final result files.

## Bounded Monitoring Policy

- First manual progress check: at or after launch + 10 minutes, unless the terminal already finished or asked for input sooner.
- Each manual progress check should usually use one tool batch only:
	- read the latest `summary.json`
	- optionally read one worker log tail or one parent terminal tail if the summary alone is ambiguous
- If the summary exposes a clear ETA, schedule the next manual check from that ETA:
	- ETA > 20 minutes: check again in 10 minutes
	- ETA between 6 and 20 minutes: check again at roughly ETA / 2
	- ETA <= 5 minutes: do not insert another midpoint check unless the terminal reports sooner
- If there is no ETA, use a fixed 10-minute cadence.
- If the summary shows output directories, completed workers, or recent `last_output_at` updates, treat that as positive progress and do not escalate to process inspection.
- Use process inspection only once for legacy runs that lack runner-emitted worker telemetry or when summary/log signals are absent and the parent terminal offers no decisive state.
- Once the parent terminal finishes, stop progress polling immediately and switch to final reporting.

## Reporting Format

When launch completes, report:

- Exact parent command.
- Terminal ID.
- Launch time.
- Manifest path.
- Expected local run directory or runs root if known.
- Initial output snapshot.

When a bounded progress update is necessary, report briefly:

- Summary status counts.
- Known output directories or the latest worker heartbeat.
- Any relevant parent-terminal or worker-log tail lines.
- Current interpretation.
- Next check timing and rationale.

When execution completes, report:

- Parent exit status.
- Local run directory.
- Summary JSON path.
- Worker log directory or representative log files.
- Discovered evaluation output directories.
- Important warning or error lines.
- Whether any worker remains active, failed, or needs explicit retry approval.