# SKILL.md
name: agent-tdd-reflection
description: Forces the AI to use Test-Driven Development (TDD) and a deliberate Chain-of-Thought reflection process before modifying code.

## Workflow Directives
When asked to implement a feature or fix a bug, you MUST follow these sequential steps:
1. **Generate Tests First**: Before writing implementation code, write diverse `pytest` unit tests (including edge cases and property-based tests via `hypothesis` if applicable) based on the function signature and docstring.
2. **Execution & Analysis**: Analyze the test results or any traceback provided by the user.
3. **Mandatory Reflection**: If tests fail or a bug is reported, you MUST output a brief text reflection explaining exactly *why* the failure occurred and *how* you intend to fix it, BEFORE generating any code.
   * *Example*: "The logic fails because the strategy object mutates the input directly instead of returning a new state copy. I will update the method to use `.model_copy(update=...)`."
4. **Implementation**: Output the corrected code only after the reflection.