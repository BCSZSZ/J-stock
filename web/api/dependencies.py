"""Shared dependencies for API routers."""

from functools import lru_cache
from pathlib import Path

from src.production.config_manager import ConfigManager, ProductionConfig
from src.config.runtime import get_config_file_path


@lru_cache(maxsize=1)
def get_config_manager() -> ConfigManager:
    config_path = str(get_config_file_path())
    return ConfigManager(config_path)


def get_production_config() -> ProductionConfig:
    return get_config_manager().get_production_config()


def get_project_root() -> Path:
    return Path(__file__).resolve().parents[2]
