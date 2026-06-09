---
name: strict-type-defense
description: Use when editing or reviewing J-stock Python code where type clarity, boundary validation, error context, or reduction of unsafe dynamic values materially affects correctness or maintainability.
---

# Strict Type Defense

Use this skill as a type-safety checklist. Improve type clarity where it reduces risk, but keep changes proportional to the task and consistent with the surrounding code.

## Guidance

- Add return annotations for new or modified functions when practical, including `-> None`.
- Prefer precise types for public APIs, persistence boundaries, config parsing, strategy results, and tabular row objects.
- Use existing project models first. Introduce `Protocol`, `TypedDict`, dataclasses, or Pydantic models only when they clarify a real boundary or repeated structure.
- Avoid new `Any` in user-facing or shared code. If dynamic data is unavoidable, narrow it promptly with validation, parsing, or local casts.
- Preserve existing `Any` or loose types when tightening them would expand the scope beyond the requested change.
- Include contextual error messages for domain failures. Add custom exceptions only when the codebase already has a matching pattern or the failure is reused across call sites.

## Review Checklist

- Are new function signatures understandable without reading the whole implementation?
- Are external inputs parsed or validated before business logic uses them?
- Are optional values, empty collections, and missing fields handled explicitly?
- Would stricter typing catch a realistic bug in this change?
- Are casts, ignores, and dynamic access kept local and explained when non-obvious?

## Avoid

- Requiring Pydantic for every structure.
- Reordering implementation only to declare all types first.
- Turning a narrow fix into a broad typing migration.
- Replacing flexible strategy/plugin interfaces with rigid types before their shape is stable.
