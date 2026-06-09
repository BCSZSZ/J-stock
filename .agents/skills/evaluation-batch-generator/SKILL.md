---
name: evaluation-batch-generator
description: 'Use when: generating worker-ready JSON manifests for J-stock evaluation, pos-evaluation, walk-forward-evaluate, or replay-evaluation batch execution. Resolve WebUI-equivalent defaults, split jobs by worker during generation, and stop before execution.'
argument-hint: 'Describe evaluation jobs, strategies, years, filters, sizing, desired worker parallelism, output root, and whether WebUI parity matters'
---

# Evaluation Batch Generator

## Purpose

Generate a worker-ready JSON manifest only. Do not execute it.

The workflow is always:

1. Extract requested parameters.
2. Resolve WebUI-equivalent defaults once.
3. Decide worker planning during generation, including how jobs are split across workers.
4. Build a strict runtime manifest at `tmp/evaluationtmp.json` and present its content for approval.
5. Stop and wait for explicit user approval.

After approval, hand execution to `evaluation-batch-executor`.

## Hard Rules

- Do not execute any evaluation/replay command.
- Do not modify source code, configs, or git state while using this skill unless the user separately asks for code changes.
- Generate a strict runtime JSON manifest at `tmp/evaluationtmp.json` and overwrite that file on each generation.
- Keep the checked-in human template at `.github/skills/evaluation-batch-generator/evaluation-batch-template.jsonc` and use it as the documented field/reference surface.
- The generator owns worker planning. Split jobs by worker here, not in the runner or executor.
- Emit worker-ready jobs. Each manifest `jobs[]` entry must already be one executable worker unit.
- Do not rely on executor or runner to reinterpret `num_workers`, repartition `exit_strategies`, or rebalance jobs.
- When presenting a manifest for approval, always report both worker-job counts and underlying evaluation-point counts. If one worker bundles multiple `exit_strategies`, state that explicitly instead of conflating job count with point count.
- Overlay defaults to OFF. Never add `--enable-overlay` unless the user explicitly asks for overlay. If the user wants overlay comparison, show both off/on commands and get approval.
- Keep manifests minimal but WebUI-equivalent: include required flags, user-requested overrides, and WebUI defaults that would change behavior if omitted. Omit a default only when the CLI/config would infer the same value, and mention important omitted defaults in the explanation.
- If command semantics are ambiguous, ask concise clarifying questions before building commands. Do not invent strategy names, report files, years, or output paths.
- When direct CLI fallback differs from WebUI behavior, prefer WebUI behavior and pin the relevant CLI flags explicitly instead of relying on parser/config fallback.

## Parameter Extraction

Extract these fields from the user's request when present:

- Command type: `evaluate`, `pos-evaluation`, `walk-forward-evaluate`, `replay-evaluation`.
- Worker planning: desired worker count, worker grouping intent, and how `exit_strategies` should be partitioned.
- Time scope: `--years`, `--months`, `--mode`, `--custom-periods`, `--launch-date`, `--launch-dates`.
- Strategies: `--entry-strategies`, `--exit-strategies`, `--ranking-strategies`, `--ranking-mode`.
- Replay inputs: `--report-file` or multiple report files.
- Position inputs: `--position-file`, `--profile-name` or profile names, position sizing mode.
- Entry filter: `--entry-filter-mode`, `--entry-filter-name`, `--atr-ratio-min`, `--atr-ratio-max`.
- Execution assumptions: `--buy-fill-mode`, `--entry-reference-mode`, fill buffer flags.
- Capacity and sizing: `--capacity-regime-mode`, `--position-sizing-mode`, `--risk-per-trade-pct`, `--atr-stop-multiple`.
- Universe/output: `--universe-file`, `--output-dir`, verbosity.
- Overlay: only when explicitly requested.

Normalize comma-separated or newline-separated user lists into CLI space-separated values because most strategy/year/report flags use argparse `nargs+`. Then convert that resolved parameter set into worker-ready manifest jobs.

## Default Resolution Pass

Resolve every parameter family once. Prefer WebUI behavior over raw CLI defaults.

Default source priority:

1. Explicit user request in the current message.
2. WebUI defaults from `/api/evaluation/options` in `web/api/routers/evaluation.py` and the frontend initialization in `web/frontend/src/pages/Evaluation.tsx`.
3. Project config values surfaced through the WebUI defaults, resolved from the runtime-selected config file path in `src/config/runtime.py`, with priority `JSA_CONFIG_FILE` > `G:/My Drive/AI-Stock-Sync/config.json` > `c:/code/J-stock/config.json`.
4. CLI parser defaults only when the WebUI/config default is unknown or intentionally omitted.

Runtime config note:

- In this workspace, if `G:/My Drive/AI-Stock-Sync/config.json` exists, treat it as the default source of truth for production-backed defaults unless the user explicitly points to another config or `JSA_CONFIG_FILE` is set.
- Production config source of truth is `G:/My Drive/AI-Stock-Sync/config.json`. Do not treat repo-local files such as `config.local.json`, `config.json.example`, or `c:/code/J-stock/config.json` as production config unless the user explicitly says they are testing a local fixture.
- Do not infer production defaults from `evaluation.default_entry_strategies` / `evaluation.default_exit_strategies` or from the repo-local `c:/code/J-stock/config.json` when the G-drive config is active.

WebUI vs direct CLI mismatch notes:

- Direct CLI `evaluate` resolves omitted `--entry-strategies` / `--exit-strategies` from `evaluation.default_entry_strategies` / `evaluation.default_exit_strategies`, not from `production.strategy_groups`. If you want WebUI/production parity, explicitly pin `--entry-strategies` and `--exit-strategies`.
- Direct CLI ranking mode falls back to `target20` when `--ranking-mode` is omitted. WebUI default is `prs_train`, so pin `--ranking-mode prs_train` unless the user requests otherwise.
- WebUI backend currently resolves production ranking strategy through `/api/evaluation/options`; when `production.signal_ranking_strategy` is absent, it currently falls back to `momentum`. Prefer actual WebUI behavior over raw config literal when generating WebUI-equivalent commands.

Current workspace concrete defaults to remember:

- Production entry default: `MACDHist2BarAnySignMaxBiasPct10Entry` from `G:/My Drive/AI-Stock-Sync/config.json` `production.strategy_groups[id=group_main].entry_strategy`.
- Production exit default: `MVXWL_N3_R0p75_T1p0_D10_B20p0_I1p2` from `G:/My Drive/AI-Stock-Sync/config.json` `production.strategy_groups[id=group_main].exit_strategy`.
- Evaluation fallback entry default in the same file is different: `evaluation.default_entry_strategies = MACDPreCross3BarEntry`. Do not silently substitute this when the task clearly intends production/WebUI defaults.
- Effective WebUI ranking strategy default is currently `momentum`.
- Output root default is `G:/My Drive/AI-Stock-Sync/strategy_evaluation` and the CLI auto-creates the dated detailed run directory beneath it.

Minimal manifest rule after defaults are resolved:

- Include a default flag when omitting it would change behavior compared with WebUI, such as `--entry-filter-mode atr`, rolling default `--years`, production default strategies, ranking strategy, or default universe file.
- Omit a default flag when the CLI/config will reliably produce the same behavior, such as overlay off, fill buffer disabled, output dir from config, or default buy fill/reference modes.
- If a required value has no WebUI default, ask before producing commands.
- In the approval explanation, state which WebUI defaults were assumed, which defaults were omitted because they match CLI/config behavior, and how worker jobs were partitioned.

## Manifest Construction

Runtime manifest form:

```json
{
	"schema_version": 1,
	"jobs": [
		{
			"worker_id": "groupA_w01",
			"job_name": "groupA_worker01",
			"command": "evaluate",
			"base_args": ["--mode", "annual", "--years", "2026"],
			"exit_strategies": ["MVXWL_...", "MVXWL_..."],
			"expected_output_root": "G:/My Drive/AI-Stock-Sync/strategy_evaluation"
		}
	]
}
```

Rules:

- The generated runtime manifest must be strict JSON with no comments. Put comments only in the checked-in `.jsonc` template.
- The generated runtime manifest path is always `tmp/evaluationtmp.json` relative to the J-stock repo root.
- Assume the runner will be launched with the current working directory at the J-stock repo root. Do not hardcode a checkout path such as `c:\code\J-stock` into manifest jobs.
- Each `jobs[]` entry must already be the final worker slice. The runner will execute jobs exactly as provided.
- The runtime job shape should include at least `worker_id`, `job_name`, `command`, `base_args`, and `exit_strategies`.
- `base_args` must contain only `main.py <command>` arguments. Do not include wrapper tokens such as `uv`, `run`, `python`, `main.py`, or `--exit-strategies` there.
- For `walk-forward-evaluate`, include `--years` if the user provided years; ask if missing and needed.
- For `replay-evaluation`, include `--report-file` because it is required.
- For ATR-only entry filtering, use `--entry-filter-mode atr`.
- Blank ATR% bounds mean unbounded. If the user explicitly says ATR min/max is blank or unlimited, use `--atr-ratio-min none` or `--atr-ratio-max none`.
- If `--position-sizing-mode fixed`, do not include `--risk-per-trade-pct` or `--atr-stop-multiple`; they are sizing parameters and are ignored in fixed mode.
- ATR% entry filter bounds are independent from ATR position sizing. They can still be included when sizing is fixed if the user wants ATR filtering.
- If the user asks for a synchronized MVXWL sweep where `T`, `I`, and ATR stop multiple move together, split worker jobs after that synchronization is resolved. Keep the exit strategy name and `--atr-stop-multiple` numerically aligned, for example `T1p8_I1p8` with `--atr-stop-multiple 1.8`.
- Use quoted paths for paths with spaces, especially under `G:\My Drive\AI-Stock-Sync`.
- Do not pre-compose dated run directories for `--output-dir`. Pass only the desired root; `src/cli/evaluate.py` will create the dated run folder automatically.
- Prefer local control-plane artifacts. The generated manifest is local under `tmp/`, while actual evaluation results still land under the configured output root such as `G:/My Drive/AI-Stock-Sync/strategy_evaluation`.

## Reference Files

- Human template: `.github/skills/evaluation-batch-generator/evaluation-batch-template.jsonc`
- Runtime manifest: `tmp/evaluationtmp.json`

Keep the human template commented and complete. Keep the runtime manifest strict and executable.

## Approval Response Format

Before running, respond with:

````markdown
**Manifest**
```json
<worker-ready manifest>
```

**Explanation**
- <why these jobs were split this way>
- <worker-job counts and evaluation-point counts by relevant grid/job_group; if workers bundle multiple exit_strategies, say so explicitly>
- <which WebUI defaults were pinned>
- <which defaults were intentionally omitted>
- <generated file: tmp/evaluationtmp.json>

Please approve before I run this manifest.
````

Do not call terminal tools for the backtest commands until the user approves.

Generating or overwriting `tmp/evaluationtmp.json` is allowed during this skill. Executing that manifest is not.
