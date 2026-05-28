---
name: evaluation-batch-runner
description: 'Compatibility skill for end-to-end J-stock batch evaluation requests or when the user explicitly refers to evaluation-batch-runner. Route command generation to evaluation-batch-generator and approved execution plus bounded monitoring to evaluation-batch-executor.'
argument-hint: 'Describe whether you need command generation, approved execution, or monitoring for J-stock batch evaluations'
---

# Evaluation Batch Runner (Compatibility)

## Purpose

This is a compatibility entrypoint for older prompts that still refer to `evaluation-batch-runner`.

Prefer the split skills directly:

- `evaluation-batch-generator`: generate a worker-ready JSON manifest only and stop for approval.
- `evaluation-batch-executor`: execute an already-approved manifest and keep bounded monitoring plus completion reporting in the same skill.
- `evaluation-result-summary`: aggregate completed output directories into markdown comparison reports under `G:/My Drive/AI-Stock-Sync/summary`.

## Routing Contract

- If a worker-ready manifest does not yet exist, use `evaluation-batch-generator` and stop at approval.
- If a manifest was already approved, use `evaluation-batch-executor`.
- If an approved manifest is already running, continue with `evaluation-batch-executor` instead of splitting launch and monitoring across skills.
- If the user wants post-run aggregation or comparison of completed output directories, use `evaluation-result-summary`.
- Do not collapse generation, approval, execution, and monitoring into one phase unless the user explicitly asks for end-to-end handling and the approval boundary is still preserved.
- Do not execute evaluation/replay jobs before the user approves the exact manifest content.
- Do not use execution subagents by default for approved manifests.

## Notes

- `evaluation-progress-monitor` is legacy-only. New flows should keep bounded monitoring inside `evaluation-batch-executor`.
- Post-run markdown summaries belong in `evaluation-result-summary`, not in the executor.
- Prefer the split skills even when handling the whole task end to end.
