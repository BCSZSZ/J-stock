# SKILL.md
name: modern-uv-workflow
description: Enforces the exclusive use of `uv` for all dependency management, virtual environments, and script execution.

## Core Directives
1. **Exclusive Tooling**: NEVER use `pip`, `pip-tools`, or `poetry` directly. All package management MUST use `uv`.
2. **Project Management**: Use `uv add <pkg>` and `uv remove <pkg>`. Suggest `uv sync` to ensure reproducible environments.
3. **Standalone Scripts (PEP 723)**: When generating independent Python scripts, automatically inject `uv` inline-metadata at the top of the file.
   * *Format snippet:*
     ```python
     # /// script
     # requires-python = ">=3.12"
     # dependencies = [ "pydantic>=2.0", "httpx" ]
     # ///
     ```
4. **Execution**: Always suggest running scripts via `uv run script.py`.