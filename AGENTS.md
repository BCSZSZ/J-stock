# AGENTS.md

Durable guidance for Codex in this repository. Keep this file small and update it only for rules that should apply to every future task.

## Git Publishing

- When the user asks to upload, publish, or push code changes to GitHub, use the repository `main` branch by default.
- Do not create a `codex/...` branch, feature branch, draft PR, or PR workflow unless the user explicitly asks for one.
- If temporary branch work already exists, move the approved changes onto `main` before pushing when it is safe to do so.

## Production Configuration

- The production configuration source of truth is `G:\My Drive\AI-Stock-Sync\config.json`.
- Do not treat repo-local files such as `config.local.json`, `config.json.example`, or `C:\code\J-stock\config.json` as production config unless the user explicitly says they are testing a local fixture.
- Production state, signals, reports, universe files, and operational files live under `G:\My Drive\AI-Stock-Sync` by default.
- When resolving current production strategy defaults, read `production.strategy_groups` from `G:\My Drive\AI-Stock-Sync\config.json`. Do not infer production defaults from `evaluation.default_*` fields.
