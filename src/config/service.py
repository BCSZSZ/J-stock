import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

from .runtime import get_config_file_path

def _ensure_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    section = cfg.get(name)
    if isinstance(section, dict):
        return section
    cfg[name] = {}
    return cfg[name]


def _normalize_evaluation(eval_cfg: Dict[str, Any]) -> None:
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


def _normalize_overlays(overlays_cfg: Dict[str, Any]) -> None:
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


def normalize_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
    cfg = deepcopy(raw_config if isinstance(raw_config, dict) else {})

    eval_cfg = _ensure_section(cfg, "evaluation")
    overlays_cfg = _ensure_section(cfg, "overlays")
    _ensure_section(cfg, "production")

    _normalize_evaluation(eval_cfg)
    _normalize_overlays(overlays_cfg)

    return cfg


def load_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else get_config_file_path()
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return normalize_config(raw)
