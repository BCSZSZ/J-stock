# copilot.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Project-level Hard Rule: Overlay Default OFF

**All evaluations and production runs in this repo default to `overlay=OFF`. Never silently enable overlay.**

- Do **not** add `--enable-overlay` to `evaluate` / `pos-evaluation` commands unless the user explicitly asks for an overlay comparison.
- When proposing or running benchmarks, assume overlay=OFF. The 4-year continuous-return baseline of ~1949% on `MVXW_N5_R3p35_T1p45_D10_B20p0` is established with overlay OFF; turning overlay ON collapses trade count by ~99% in 2022–2024 and is **not** the production target.
- Configs (`config.json`, `config.local.json`, `config.aws.json`, `config.aws-sim.json`, `G:\My Drive\AI-Stock-Sync\config.json`) MUST keep `overlays.enabled = false` (boolean). Do not change this without explicit user approval.
- For overlay studies, use `--overlay-modes off on` (pos-evaluation) or run two separate `evaluate` runs (without and with `--enable-overlay`) and report both.
- See `instruction.md` "全局策略：Overlay 默认 OFF" for the full rationale and code paths.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

## 5. Technology-Specific Routing (Python Context)

**Silently load context based on the current stack. Do not narrate skill loading.**

When working in this repository (especially Python code), evaluate the user's intent and implicitly apply the following technical constraints by loading the respective rules from `.github/skills/`:

- **For Complex Logic & State Machines:** Apply `ai-native-architecture`. Use pure functions, stateless classes, and the Receive an Object, Return an Object (RORO) pattern. Never mutate state internally.
- **For Data Structures & Interfaces:** Apply `strict-type-defense`. Zero `Any` tolerance. Enforce Pydantic v2 models and complete type hints before writing execution logic.
- **For Dependencies & Scripts:** Apply `modern-uv-workflow`. Exclusively use `uv` for package management and PEP 723 inline-metadata for standalone scripts.

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---
