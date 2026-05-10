import json
from copy import deepcopy
from pathlib import Path
from typing import Optional, cast

from .capacity import (
    ConfigValidationError,
    parse_capacity_regime,
    parse_evaluation_capacity_mode,
    parse_production_capacity_mode,
)
from .runtime import get_config_file_path


FORBIDDEN_TOP_LEVEL_KEYS = (
    "entry_eval_exit_strategies",
    "alternative_strategies_note",
)
FORBIDDEN_SECTION_KEYS = {
    "evaluation": ("entry_filters",),
    "portfolio": ("min_position_pct",),
}


def _ensure_section(cfg: dict[str, object], name: str) -> dict[str, object]:
    section = cfg.get(name)
    if isinstance(section, dict):
        return cast(dict[str, object], section)
    cfg[name] = {}
    return cast(dict[str, object], cfg[name])


def _normalize_evaluation(eval_cfg: dict[str, object]) -> None:
    filters_cfg = eval_cfg.get("filters")
    if not isinstance(filters_cfg, dict):
        filters_cfg = {}

    mode = str(filters_cfg.get("mode", "single")).lower()
    if mode not in {"auto", "off", "single", "grid"}:
        mode = "single"

    default_filter = filters_cfg.get("default")
    if not isinstance(default_filter, dict):
        default_filter = {"enabled": False}

    variants = filters_cfg.get("variants")
    if not isinstance(variants, dict):
        variants = {}

    eval_cfg["filters"] = {
        "mode": mode,
        "default": default_filter,
        "variants": variants,
    }


def _normalize_overlays(overlays_cfg: dict[str, object]) -> None:
    enabled_raw = overlays_cfg.get("enabled")
    active_raw = overlays_cfg.get("active")

    global_enabled = bool(enabled_raw) if isinstance(enabled_raw, bool) else False
    active = (
        [str(x) for x in active_raw]
        if isinstance(active_raw, list)
        else ["SectorBreadthOverlay"]
    )

    overlays_cfg["enabled"] = global_enabled
    overlays_cfg["active"] = active


def _reject_legacy_keys(cfg: dict[str, object]) -> None:
    for key in FORBIDDEN_TOP_LEVEL_KEYS:
        if key in cfg:
            raise ConfigValidationError(
                f"Legacy config key is not supported anymore: {key}",
                {"path": key, "value": cfg.get(key)},
            )

    for section_name, keys in FORBIDDEN_SECTION_KEYS.items():
        section = _ensure_section(cfg, section_name)
        for key in keys:
            if key in section:
                raise ConfigValidationError(
                    f"Legacy config key is not supported anymore: {section_name}.{key}",
                    {"path": f"{section_name}.{key}", "value": section.get(key)},
                )


def normalize_config(raw_config: dict[str, object]) -> dict[str, object]:
    cfg = deepcopy(raw_config if isinstance(raw_config, dict) else {})
    if not isinstance(cfg, dict):
        raise ConfigValidationError(
            "Top-level config must be a JSON object",
            {"value_type": type(raw_config).__name__},
        )

    cfg = cast(dict[str, object], cfg)

    _reject_legacy_keys(cfg)

    eval_cfg = _ensure_section(cfg, "evaluation")
    overlays_cfg = _ensure_section(cfg, "overlays")
    production_cfg = _ensure_section(cfg, "production")

    _normalize_evaluation(eval_cfg)
    _normalize_overlays(overlays_cfg)

    cfg["capacity_regime"] = parse_capacity_regime(cfg.get("capacity_regime")).to_dict()
    eval_cfg["capacity_regime_mode"] = parse_evaluation_capacity_mode(
        eval_cfg.get("capacity_regime_mode")
    )
    production_cfg["capacity_regime_mode"] = parse_production_capacity_mode(
        production_cfg.get("capacity_regime_mode")
    )

    return cfg


def load_config(config_path: Optional[str] = None) -> dict[str, object]:
    path = Path(config_path) if config_path else get_config_file_path()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_config(raw)
