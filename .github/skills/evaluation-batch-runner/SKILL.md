---
name: evaluation-batch-runner
description: 'Use when: orchestrating an end-to-end J-stock batch evaluation workflow, or when the user explicitly names evaluation-batch-runner. Schedule evaluation-batch-generator, evaluation-batch-executor, and evaluation-result-summary in order, preserving the manifest approval boundary and allowing subagent delegation only during approved execution.'
---

# Evaluation Batch Runner

## Purpose

Coordinate the three split J-stock evaluation skills as one higher-level workflow.

Use this skill as the scheduler, not as a replacement for the lower-level contracts:

1. `evaluation-batch-generator`: generate the worker-ready manifest and stop for approval.
2. `evaluation-batch-executor`: execute an already-approved manifest, monitor boundedly, and report completion.
3. `evaluation-result-summary`: aggregate completed output directories into markdown under `G:/My Drive/AI-Stock-Sync/summary`.

## Scheduling Flow

- Start from the earliest missing phase. If no worker-ready manifest exists or the requested parameters changed, enter Generation.
- If the exact manifest has not been approved, do not enter Execution.
- If an approved manifest is running or needs to be launched, enter Execution.
- If execution completed and the user asked for results, comparison, reporting, or end-to-end handling, enter Summary.
- If the user asks for only one phase, route directly to the relevant split skill while preserving the same invariants.

## Phase Contracts

### 1. Generation

- Use `evaluation-batch-generator`.
- Let the generator resolve defaults, worker partitioning, and strict `tmp/evaluationtmp.json` contents.
- Do not execute any evaluation, replay, or runner command during this phase.
- Present the manifest content and wait for explicit user approval before continuing.

### 2. Execution

- Use `evaluation-batch-executor`.
- Keep the approved manifest unchanged: no repartitioning, no reordering, no silently updated flags.
- Launch one parent runner per approved manifest and keep bounded monitoring until completion unless the user requests leave-running behavior.
- Execution-phase subagents are allowed only after manifest approval:
  - Use them for approved launch or monitoring when the run is long, multiple approved manifests need parallel ownership, or the user asks for subagents.
  - Delegate only to `evaluation-batch-executor`; pass the exact approved manifest path or content and the executor reporting contract.
  - Keep the main agent as scheduler of record; reconcile the subagent's `summary.json`, output directories, worker status, and warning/error report before final response.
  - Do not let a subagent regenerate, edit, reorder, or reinterpret the approved manifest.
  - If subagents are unavailable, continue in the current session with `evaluation-batch-executor`.

### 3. Summary

- Use `evaluation-result-summary` only after completed output directories or a runner `summary.json` exist.
- Prefer the executor's local `summary.json` or exact completed output directories as the source of truth.
- Generate the markdown summary artifact under `G:/My Drive/AI-Stock-Sync/summary`.
- Do not rerun evaluations, generate manifests, or change source code during this phase.

## Approval Boundary

- Preserve the approval boundary even for "end-to-end" requests.
- Stop after Generation unless the user has already approved the exact manifest content to execute.
- Treat approval of a high-level plan as insufficient for execution; execution requires approval of the concrete manifest.
- If the user approves an existing manifest by path, verify that the path and content are the intended approved artifact before Execution.

## Subagent Prompt Shape

When delegating approved execution, keep the prompt narrow:

```text
Use evaluation-batch-executor for this approved J-stock manifest.

Manifest path: <path>
Approval evidence: <short reference>
Required behavior: launch, monitor, and report completion for this manifest only. Keep the manifest unchanged. Return parent command, terminal id, local run dir, summary.json path, output dirs, worker status, and warnings/errors.
```

Do not include generator instructions, summary instructions, or expected performance conclusions in the execution subagent prompt.

## Reporting Discipline

- State the active phase and why it is active.
- After Generation, return the manifest approval request from `evaluation-batch-generator`.
- After Execution, return the executor's run status and output locations.
- After Summary, return the markdown summary path plus concise findings.
- `evaluation-progress-monitor` is legacy-only. New flows keep monitoring inside `evaluation-batch-executor`.
