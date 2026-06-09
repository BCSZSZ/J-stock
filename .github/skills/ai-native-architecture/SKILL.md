---
name: ai-native-architecture
description: Use when designing or refactoring J-stock Python architecture, introducing new services/classes, separating business logic from I/O, or reviewing object-oriented code for hidden state and testability.
---

# AI-Native Architecture

Use this skill as an architectural bias, not a blanket prohibition. Prefer designs that make state explicit, calculations testable, and side effects easy to locate.

## Guidance

- Prefer pure functions or small services whose dependencies are injected explicitly.
- Keep mutable runtime state in explicit domain objects, request objects, or persistence layers instead of hidden instance attributes.
- Use `pydantic.BaseModel`, dataclasses, `TypedDict`, or existing project models when they improve clarity at module boundaries.
- Use RORO-style request/response objects for complex workflows, especially when a function has many related inputs or outputs.
- Keep file, network, subprocess, database, and clock access at workflow boundaries. Put deterministic calculations behind functions that can be tested without I/O.
- Preserve existing local patterns when they are clear and already tested. Do not refactor working code only to force a pattern.

## Review Checklist

- Can the core behavior be tested without touching the filesystem, network, or current time?
- Is the state needed by the calculation visible in the function signature or model?
- Are class attributes limited to stable dependencies, configuration, or caches with clear invalidation?
- Would a future agent understand how data flows through the module without reconstructing hidden mutations?

## Avoid

- Introducing broad architecture rewrites while making a narrow feature or bug fix.
- Adding Pydantic/dataclass wrappers for simple local values that are already obvious.
- Treating every class as invalid just because it owns state; prefer explicit, documented state when the domain requires it.
