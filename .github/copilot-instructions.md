# copilot.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

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

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

---

## 5. Project Scope (endfield-draw-calculator)

- Primary files today:
  - `myturnDRAW6up.py` (character draw logic)
  - `weapon_draw.py` (weapon draw logic)
  - `streamlit_all_app.py` (combined Streamlit app)
- Current stack: Python + Streamlit (+ numpy/pandas/plotly if already used).
- Default expectation: preserve current calculation behavior unless explicitly asked to change rules or probabilities.

## 6. Calculation Changes

- For probability/DP updates, state the model assumption before coding.
- Keep numeric invariants explicit where applicable (e.g., probability bounds, monotonic trends).
- Prefer small pure helper functions for transition/math logic.
- If formulas change, include a short note in code or README describing impact.

## 7. Streamlit Changes

- Keep UI edits incremental and task-driven; do not redesign unrelated sections.
- Reuse existing interaction patterns (inputs → compute → chart/table/text result).
- Prefer lightweight rerun-friendly logic; avoid hidden global mutable state.

## 8. Extensibility Without Over-Engineering

- New features should be added as small, isolated modules/functions with clear boundaries.
- Keep app entry points stable; integrate new calculators/components via composition, not large rewrites.
- Avoid speculative plugin systems/config frameworks unless explicitly requested.
- When adding a new feature type, document where it plugs in and how to run it.

## 9. Validation and Run Commands

- Minimum validation after edits:
  - Run relevant script(s): `python myturnDRAW6up.py` / `python weapon_draw.py`
  - Run app if UI touched: `streamlit run streamlit_all_app.py`
  - Check for import/runtime errors introduced by the change.

## 10. Change Discipline for This Repo

- Keep diffs small and directly traceable to the request.
- Do not rename files/public interfaces unless requested.
- Do not add new dependencies unless necessary; justify in one sentence when added.
- Update README only when usage/setup/output expectations actually change.
