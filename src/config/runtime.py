import json
import os
from pathlib import Path
from typing import Any, Dict


DEFAULT_CONFIG_FILE = "config.json"
CONFIG_ENV_VAR = "JSA_CONFIG_FILE"


def get_config_file_path() -> Path:
    """Return config path from env override or default file name."""
    return Path(os.getenv(CONFIG_ENV_VAR, DEFAULT_CONFIG_FILE))


def load_runtime_config() -> Dict[str, Any]:
    """Load JSON config using runtime-selected config file path."""
    config_path = get_config_file_path()
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_s3_path(path_value: str) -> bool:
    return str(path_value).strip().lower().startswith("s3://")


def is_local_path(path_value: str) -> bool:
    return not is_s3_path(path_value)


def sample_path_from_pattern(path_pattern: str) -> str:
    """Replace known placeholders with a sample value for parent-dir checks."""
    return path_pattern.replace("{date}", "1970-01-01")
