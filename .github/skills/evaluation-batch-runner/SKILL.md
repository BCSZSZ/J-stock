---
name: evaluation-batch-runner
description: 'Use when: batch running J-stock evaluation, pos-evaluation, walk-forward-evaluate, or replay-evaluation backtests. Extract parameters from the user request, assemble minimal uv/python main.py commands, show commands for approval first, then run approved commands in parallel subagents and summarize backtest outputs.'
argument-hint: 'Describe evaluation/replay jobs, strategies, years, filters, sizing, output dir'
---

# Evaluation Batch Runner

## Purpose

Use this skill to help the user batch-run J-stock backtests and evaluation workflows from natural-language instructions.

The workflow is always:

1. Extract requested parameters.
2. Build the minimal executable command or command set.
3. Reply with the full command text and a short explanation.
4. Wait for explicit user approval before execution.
5. After approval, run multiple commands in parallel subagents when there is more than one command.
6. Wait for all runs to finish.
7. Analyze generated backtest outputs and summarize results.

## Hard Rules

- Do not execute any evaluation/replay command until the user explicitly approves the exact command text.
- Do not modify source code, configs, or git state while using this skill unless the user separately asks for code changes.
- Use `uv --directory "c:\code\J-stock" run python main.py ...` for commands unless the user explicitly requests another runner.
- Overlay defaults to OFF. Never add `--enable-overlay` unless the user explicitly asks for overlay. If the user wants overlay comparison, show both off/on commands and get approval.
- Keep commands minimal but WebUI-equivalent: include required flags, user-requested overrides, and WebUI defaults that would change behavior if omitted. Omit a default only when the CLI/config would infer the same value, and mention important omitted defaults in the explanation.
- If command semantics are ambiguous, ask concise clarifying questions before building commands. Do not invent strategy names, report files, years, or output paths.
- When direct CLI fallback differs from WebUI behavior, prefer WebUI behavior and pin the relevant CLI flags explicitly instead of relying on parser/config fallback.

## Parameter Extraction

Extract these fields from the user's request when present:

- Command type: `evaluate`, `pos-evaluation`, `walk-forward-evaluate`, `replay-evaluation`.
- Time scope: `--years`, `--months`, `--mode`, `--custom-periods`, `--launch-date`, `--launch-dates`.
- Strategies: `--entry-strategies`, `--exit-strategies`, `--ranking-strategies`, `--ranking-mode`.
- Replay inputs: `--report-file` or multiple report files.
- Position inputs: `--position-file`, `--profile-name` or profile names, position sizing mode.
- Entry filter: `--entry-filter-mode`, `--entry-filter-name`, `--atr-ratio-min`, `--atr-ratio-max`.
- Execution assumptions: `--buy-fill-mode`, `--entry-reference-mode`, fill buffer flags.
- Capacity and sizing: `--capacity-regime-mode`, `--position-sizing-mode`, `--risk-per-trade-pct`, `--atr-stop-multiple`.
- Universe/output: `--universe-file`, `--output-dir`, verbosity.
- Overlay: only when explicitly requested.

Normalize comma-separated or newline-separated user lists into CLI space-separated values because most strategy/year/report flags use argparse `nargs+`.

## Default Resolution Pass

Before building commands, resolve every parameter family once. Prefer WebUI behavior over raw CLI defaults.

Default source priority:

1. Explicit user request in the current message.
2. WebUI defaults from `/api/evaluation/options` in `web/api/routers/evaluation.py` and the frontend initialization in `web/frontend/src/pages/Evaluation.tsx`.
3. Project config values surfaced through the WebUI defaults, such as production strategy, ranking strategy, monitor list, position profiles, ATR runtime defaults, and evaluation output directory. Resolve these from the runtime-selected config file path in `src/config/runtime.py`, with priority `JSA_CONFIG_FILE` > `G:/My Drive/AI-Stock-Sync/config.json` > `c:/code/J-stock/config.json`.
4. CLI parser defaults only when the WebUI/config default is unknown or intentionally omitted.

Runtime config note:

- In this workspace, if `G:/My Drive/AI-Stock-Sync/config.json` exists, treat it as the default source of truth for production-backed defaults unless the user explicitly points to another config or `JSA_CONFIG_FILE` is set.
- Do not infer production defaults from `evaluation.default_entry_strategies` / `evaluation.default_exit_strategies` or from the repo-local `c:/code/J-stock/config.json` when the G-drive config is active.

WebUI vs direct CLI mismatch notes:

- Direct CLI `evaluate` resolves omitted `--entry-strategies` / `--exit-strategies` from `evaluation.default_entry_strategies` / `evaluation.default_exit_strategies`, not from `production.strategy_groups`. If you want WebUI/production parity, explicitly pin `--entry-strategies` and `--exit-strategies`.
- Direct CLI ranking mode falls back to `target20` when `--ranking-mode` is omitted. WebUI default is `prs_train`, so pin `--ranking-mode prs_train` unless the user requests otherwise.
- WebUI backend currently resolves production ranking strategy through `/api/evaluation/options`; when `production.signal_ranking_strategy` is absent, it currently falls back to `momentum`. Prefer actual WebUI behavior over raw config literal when generating WebUI-equivalent commands.

Current WebUI default rules to consider:

- Command type: default to `evaluate`.
- Time scope: default mode is `annual`; default years are the frontend rolling 5-year list from current year minus 4 through current year. Calculate this from the current session date, for example current year 2026 means `2022 2023 2024 2025 2026`. `months`, `custom-periods`, and launch dates are empty unless selected. `walk-forward-evaluate` defaults `--min-train-years 2` and only supports annual/quarterly mode. `replay-evaluation` has no year mode.
- Strategies: WebUI defaults `override_strategies=false`, so entry/exit strategies come from production defaults in `/api/evaluation/options`, which in turn should be read from the active runtime config file. Prefer `production.strategy_groups[id=group_main].entry_strategy` / `exit_strategy`, then the production default entry/exit fallbacks if present. If the user provides strategies, treat that as `override_strategies=true` and include `--entry-strategies` / `--exit-strategies`. Because direct CLI fallback differs here, keep these flags explicit whenever WebUI/production parity matters. WebUI ranking defaults to `--ranking-mode prs_train` and currently uses `momentum` as the effective default `--ranking-strategies` value when `production.signal_ranking_strategy` is absent, because the evaluation API falls back to `momentum`.
- Replay inputs: there is no default report file. For `replay-evaluation`, ask for one or more `--report-file` values if absent.
- Position inputs: for `pos-evaluation`, WebUI defaults to `evaluation.default_position_file` and `evaluation.default_profile_names`; profile sizing is used unless the user explicitly asks to override profile sizing. For non-pos evaluation commands, WebUI sends runtime position sizing defaults from portfolio config.
- Entry filter: WebUI default is `--entry-filter-mode atr`, not CLI `auto`. ATR bounds default to `evaluation.filters.default.atr_price_min/max` (`0.015` and `0.03` in the current config). Empty ATR bounds mean `none` and should be emitted as `--atr-ratio-min none` or `--atr-ratio-max none` when explicitly blank/unbounded.
- Execution assumptions: WebUI defaults to buy fill `next_open`, entry reference `raw_fill`, fill buffer disabled, and fill buffer pct `0.02`. `next_open` and `raw_fill` are also the CLI parser defaults in `main.py`, so omitting these flags preserves the same behavior unless the user explicitly overrides them. Multiple buy fill or entry reference modes expand to the Cartesian product of full runs.
- Capacity and sizing: WebUI default capacity regime comes from `evaluation.capacity_regime_mode` and is `off` in the current config. Position sizing comes from portfolio config (`atr` in the current config), with risk per trade `0.006` and ATR stop multiple `2.0`. If position sizing is `fixed`, do not include ATR sizing risk/stop flags.
- Universe/output: WebUI defaults to the production monitor list from the active runtime config as `--universe-file`, no universe pool IDs, configured evaluation output directory, and `verbose=false`. In the current G-drive config these resolve to `G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json` and `G:/My Drive/AI-Stock-Sync/strategy_evaluation`. Treat `--output-dir` as the output root only. For evaluation-family commands, the CLI automatically creates `YYYYMMDD/<run-slug>__HHMMSS/` under that root, for example `G:/My Drive/AI-Stock-Sync/strategy_evaluation/20260526/evaluate__annual__entry_MACDHist2BarAnySignMaxBiasPct10Entry__exit_4_MVXWL_N3_R0p54_T1p5_D10_B20p0_I1p5_plus3__fill_next_open__entryref_raw_fill__buffer_off__162138`. Do not manually append the dated/detail subdirectory in generated commands; the CLI builds it automatically. Output root can be omitted when using config default, but mention it in the explanation.
- Overlay: WebUI default is overlay off. For `evaluate`, `walk-forward-evaluate`, and `replay-evaluation`, omit `--enable-overlay`. For `pos-evaluation`, default overlay modes are `off`; include `--overlay-modes off` only when pinning WebUI parity is important.

Current workspace concrete defaults to remember:

- Production entry default: `MACDHist2BarAnySignMaxBiasPct10Entry` from `G:/My Drive/AI-Stock-Sync/config.json` `production.strategy_groups[id=group_main].entry_strategy`.
- Production exit default: `MVXW_N3_R0p54_T1p3_D10_B20p0` from `G:/My Drive/AI-Stock-Sync/config.json` `production.strategy_groups[id=group_main].exit_strategy`.
- Evaluation fallback entry default in the same file is different: `evaluation.default_entry_strategies = MACDPreCross3BarEntry`. Do not silently substitute this when the task clearly intends production/WebUI defaults.
- Effective WebUI ranking strategy default is currently `momentum`.
- Output root default is `G:/My Drive/AI-Stock-Sync/strategy_evaluation` and the CLI auto-creates the dated detailed run directory beneath it.

Minimal command rule after defaults are resolved:

- Include a default flag when omitting it would change behavior compared with WebUI, such as `--entry-filter-mode atr`, rolling default `--years`, production default strategies, ranking strategy, or default universe file.
- Omit a default flag when the CLI/config will reliably produce the same behavior, such as overlay off, fill buffer disabled, output dir from config, or default buy fill/reference modes.
- If a required value has no WebUI default, ask before producing commands.
- In the approval explanation, state which WebUI defaults were assumed and which defaults were omitted because they match CLI/config behavior.

## Command Construction

Base form:

```powershell
uv --directory "c:\code\J-stock" run python main.py <command> <minimal-flags>
```

Rules:

- For `walk-forward-evaluate`, include `--years` if the user provided years; ask if missing and needed.
- For `replay-evaluation`, include `--report-file` because it is required.
- For ATR-only entry filtering, use `--entry-filter-mode atr`.
- Blank ATR% bounds mean unbounded. If the user explicitly says ATR min/max is blank or unlimited, use `--atr-ratio-min none` or `--atr-ratio-max none`.
- If `--position-sizing-mode fixed`, do not include `--risk-per-trade-pct` or `--atr-stop-multiple`; they are sizing parameters and are ignored in fixed mode.
- ATR% entry filter bounds are independent from ATR position sizing. They can still be included when sizing is fixed if the user wants ATR filtering.
- If the user asks for production-like ranking, use the configured/default ranking strategy only when known; otherwise ask or omit ranking overrides.
- Use quoted paths for paths with spaces, especially under `G:\My Drive\AI-Stock-Sync`.
- Do not pre-compose dated run directories for `--output-dir`. Pass only the desired root; `src/cli/evaluate.py` will create the dated run folder automatically.
- If the user asks for a synchronized MVXWL sweep where `T`, `I`, and ATR stop multiple move together, generate one command per value. Keep the exit strategy name and `--atr-stop-multiple` numerically aligned, for example `T1p8_I1p8` with `--atr-stop-multiple 1.8`.

## Reference Patterns

Use these as precision anchors when future requests match the same intent.

### Synced MVXWL Sweep Reference

Intent:

- Command type: `evaluate`
- Years: rolling WebUI default for 2026 -> `2022 2023 2024 2025 2026`
- Production/WebUI entry default pinned explicitly: `MACDHist2BarAnySignMaxBiasPct10Entry`
- Exit family: `MVXWL_N3_R0p54_*_D10_B20p0_*`
- Sweep values: `1.3 1.5 1.8 2.1 2.3`
- Synchronize `T`, `I`, and `--atr-stop-multiple` to the same numeric value in each run
- Preserve WebUI defaults: `--entry-filter-mode atr`, `--atr-ratio-min 0.015`, `--atr-ratio-max 0.03`, `--ranking-mode prs_train`, `--ranking-strategies momentum`, production monitor list, overlay off, fill buffer off, `next_open`, `raw_fill`

Reference commands:

```powershell
uv --directory "c:\code\J-stock" run python main.py evaluate --mode annual --years 2022 2023 2024 2025 2026 --entry-strategies MACDHist2BarAnySignMaxBiasPct10Entry --exit-strategies MVXWL_N3_R0p54_T1p3_D10_B20p0_I1p3 --entry-filter-mode atr --atr-ratio-min 0.015 --atr-ratio-max 0.03 --ranking-mode prs_train --ranking-strategies momentum --universe-file "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" --position-sizing-mode atr --risk-per-trade-pct 0.006 --atr-stop-multiple 1.3
uv --directory "c:\code\J-stock" run python main.py evaluate --mode annual --years 2022 2023 2024 2025 2026 --entry-strategies MACDHist2BarAnySignMaxBiasPct10Entry --exit-strategies MVXWL_N3_R0p54_T1p5_D10_B20p0_I1p5 --entry-filter-mode atr --atr-ratio-min 0.015 --atr-ratio-max 0.03 --ranking-mode prs_train --ranking-strategies momentum --universe-file "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" --position-sizing-mode atr --risk-per-trade-pct 0.006 --atr-stop-multiple 1.5
uv --directory "c:\code\J-stock" run python main.py evaluate --mode annual --years 2022 2023 2024 2025 2026 --entry-strategies MACDHist2BarAnySignMaxBiasPct10Entry --exit-strategies MVXWL_N3_R0p54_T1p8_D10_B20p0_I1p8 --entry-filter-mode atr --atr-ratio-min 0.015 --atr-ratio-max 0.03 --ranking-mode prs_train --ranking-strategies momentum --universe-file "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" --position-sizing-mode atr --risk-per-trade-pct 0.006 --atr-stop-multiple 1.8
uv --directory "c:\code\J-stock" run python main.py evaluate --mode annual --years 2022 2023 2024 2025 2026 --entry-strategies MACDHist2BarAnySignMaxBiasPct10Entry --exit-strategies MVXWL_N3_R0p54_T2p1_D10_B20p0_I2p1 --entry-filter-mode atr --atr-ratio-min 0.015 --atr-ratio-max 0.03 --ranking-mode prs_train --ranking-strategies momentum --universe-file "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" --position-sizing-mode atr --risk-per-trade-pct 0.006 --atr-stop-multiple 2.1
uv --directory "c:\code\J-stock" run python main.py evaluate --mode annual --years 2022 2023 2024 2025 2026 --entry-strategies MACDHist2BarAnySignMaxBiasPct10Entry --exit-strategies MVXWL_N3_R0p54_T2p3_D10_B20p0_I2p3 --entry-filter-mode atr --atr-ratio-min 0.015 --atr-ratio-max 0.03 --ranking-mode prs_train --ranking-strategies momentum --universe-file "G:/My Drive/AI-Stock-Sync/state/production_monitor_list.json" --position-sizing-mode atr --risk-per-trade-pct 0.006 --atr-stop-multiple 2.3
```

Why this reference matters:

- The entry strategy is pinned to production/WebUI default because direct CLI fallback would otherwise use `evaluation.default_entry_strategies` and drift to `MACDPreCross3BarEntry`.
- `--ranking-mode prs_train` is pinned because direct CLI fallback is `target20`.
- `--ranking-strategies momentum` is pinned because current WebUI behavior resolves to `momentum` through the evaluation API.
- `--output-dir` is intentionally omitted because the configured output root is already correct and the CLI auto-builds the dated run directory.

## Approval Response Format

Before running, respond with:

````markdown
**Commands**
```powershell
<command 1>
<command 2>
```

**Explanation**
- <why these flags are included>
- <what defaults are intentionally omitted>
- <where outputs are expected>

Please approve before I run these.
````

Do not call terminal tools or subagents for the backtest commands until the user approves.

## Execution After Approval

If there is one command:

- Run it directly with `run_in_terminal` in sync mode and a generous timeout.
- If the command later needs manual progress monitoring, apply the separate `evaluation-progress-monitor` skill.
- Do not leave required evaluation commands running when finishing the turn.

If there are multiple commands:

- Start one subagent per command using `runSubagent`.
- Prefer `multi_tool_use.parallel` to launch subagents concurrently.
- Do not use the `Explore` read-only subagent for command execution.
- Give each subagent exactly one approved command and this instruction: run only that command, do not edit files, capture exit code, key stdout/stderr, generated output paths, and final status.
- If a launched command needs manual progress monitoring, apply the separate `evaluation-progress-monitor` skill instead of embedding ad hoc polling rules here.

Subagent prompt template:

```text
You are executing one approved J-stock backtest command.
Repository: c:\code\J-stock
Hard rules: do not edit files, do not change configs, do not commit, do not add overlay flags, run exactly the approved command below.
If manual progress monitoring is needed after launch, apply the separate `evaluation-progress-monitor` skill.
Command:
<approved command>
After it finishes, report: exit code, generated output paths, important warnings/errors, and the most relevant result files for analysis.
```

Wait until all subagents return before analyzing results.

## Result Analysis

After all commands finish:

1. Report each command's status: succeeded, failed, or incomplete.
2. Locate output files from stdout or the configured output directory.
3. Prefer structured outputs over text scraping: CSV/JSON with pandas or standard parsers, markdown report only when structured files are unavailable.
4. Summarize the most important metrics available, such as total return, annual/period return, max drawdown, trade count, win rate, final equity, ranking position, and notable warnings.
5. For multi-command runs, compare results side by side and call out the best/worst tradeoffs.
6. For replay runs, include generated replay sidecars/reports, last-day production-style output, pending signals, positions, and any mismatch or warning lines.
7. If a command failed, include the failure reason and the smallest next step to fix it.

Final summary should include:

- Commands run.
- Output locations.
- Key metrics and ranking conclusions.
- Failures or caveats.
- Recommended next run, only when it follows naturally from the result.
