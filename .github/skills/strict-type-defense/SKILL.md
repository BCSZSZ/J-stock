# SKILL.md
name: strict-type-defense
description: Mandates strict Type Hinting and Interface Contracts to ensure code predictability and ease of automated refactoring.

## Core Directives
1. **Type First**: Always define structural types (`Protocol`, `TypedDict`, `Pydantic v2`) before implementing any execution logic.
2. **Zero 'Any' Tolerance**: Implicit or explicit `Any` is strictly forbidden. Use `TypeVar` or generic constraints for dynamic structures.
3. **Explicit Returns**: Every function and method MUST have a defined return type, including `-> None`.
4. **Contextual Error Handling**: Do not raise naked exceptions. Define custom domain exceptions and ensure they carry the current state payload (e.g., `raise InvalidStateError(state=current_state.model_dump())`) to provide exact Traceback context for future AI debugging.