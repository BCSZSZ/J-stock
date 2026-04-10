# SKILL.md

name: modern-uv-workflow
description: TRIGGERS AUTOMATICALLY when writing standalone scripts, managing dependencies, or generating setup instructions. Forces the use of `uv`.

## Core Directives

1. **Exclusive Tooling**: NEVER use `pip`, `pip-tools`, or `poetry` directly. All package management MUST use `uv`.
2. **Project Management**: Use `uv add <pkg>` and `uv remove <pkg>`. Suggest `uv sync` to ensure reproducible environments.
3. **Standalone Scripts (PEP 723)**: When generating independent Python scripts, automatically inject `uv` inline-metadata at the top of the file.
   - _Format snippet:_
     ```python
     # /// script
     # requires-python = ">=3.12"
     # dependencies = [ "pydantic>=2.0", "httpx" ]
     # ///
     ```
4. **Execution**: Always suggest running scripts via `uv run script.py`.
