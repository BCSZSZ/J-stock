from __future__ import annotations

from pathlib import Path


GDRIVE_ENTRY_EXIT_VALIDATION_DIR = Path(
    r"G:\My Drive\AI-Stock-Sync\entry_exit_validation"
)


def default_output_dir(configured_output_dir: str | None = None) -> str:
    if GDRIVE_ENTRY_EXIT_VALIDATION_DIR.parent.exists():
        return str(GDRIVE_ENTRY_EXIT_VALIDATION_DIR)
    if configured_output_dir:
        return configured_output_dir
    return "entry_exit_validation"
