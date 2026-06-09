---
name: modern-uv-workflow
description: Use when adding or updating Python dependencies, writing standalone Python scripts, documenting local setup, or choosing Python execution commands in the J-stock repository where uv is the preferred workflow.
---

# Modern UV Workflow

Use `uv` as the default Python workflow for this repository while respecting existing project files and commands.

## Guidance

- Prefer existing repo commands first. If `pyproject.toml`, scripts, docs, or CI already define a command, follow that shape.
- Use `uv run ...` for local Python execution when no more specific project command exists.
- Use `uv sync` to recreate the project environment.
- Use `uv add <package>` and `uv remove <package>` for dependency changes when the user asks to change project dependencies.
- Ask or inspect first before changing dependency groups, optional extras, lockfiles, or Python version constraints.

## Standalone Scripts

- Add PEP 723 inline metadata only for independent scripts that are intended to run outside the project environment.
- Do not add inline metadata to normal repository modules, package files, test files, or scripts that already rely on the project environment.
- Include only the dependencies actually needed by the standalone script.

## Compatibility

- Do not rewrite documented `pip`, `python`, or CI commands unless the task is specifically to modernize setup.
- If a tool or upstream instruction requires `pip`, `python -m`, or another installer, explain the reason and keep the command scoped.
- Keep generated setup instructions reproducible and aligned with the repository's current tooling.
