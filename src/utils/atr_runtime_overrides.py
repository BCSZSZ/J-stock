from __future__ import annotations

from typing import Any

from src.utils.atr_position_sizing import normalize_position_sizing_mode


def has_portfolio_runtime_overrides(args: object) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in ("position_sizing_mode", "risk_per_trade_pct", "atr_stop_multiple")
    )


def has_entry_filter_runtime_bounds(args: object) -> bool:
    return any(
        getattr(args, name, None) is not None
        for name in ("atr_ratio_min", "atr_ratio_max")
    )


def merge_portfolio_runtime_overrides(
    args: object,
    base_overrides: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    overrides = dict(base_overrides or {})
    changed = False

    position_sizing_mode = getattr(args, "position_sizing_mode", None)
    if position_sizing_mode is not None:
        overrides["position_sizing_mode"] = normalize_position_sizing_mode(
            position_sizing_mode
        )
        changed = True

    atr_updates: dict[str, Any] = {}
    existing_atr = overrides.get("atr_position_sizing")
    if isinstance(existing_atr, dict):
        atr_updates.update(existing_atr)

    risk_per_trade_pct = getattr(args, "risk_per_trade_pct", None)
    if risk_per_trade_pct is not None:
        atr_updates["risk_per_trade_pct"] = float(risk_per_trade_pct)
        changed = True

    atr_stop_multiple = getattr(args, "atr_stop_multiple", None)
    if atr_stop_multiple is not None:
        atr_updates["atr_stop_multiple"] = float(atr_stop_multiple)
        changed = True

    if atr_updates:
        overrides["atr_position_sizing"] = atr_updates

    if changed or base_overrides is not None:
        return overrides
    return None


def merge_entry_filter_runtime_bounds(
    filter_config: dict[str, Any] | None,
    args: object,
) -> dict[str, Any]:
    config = dict(filter_config or {})

    atr_ratio_min = getattr(args, "atr_ratio_min", None)
    if atr_ratio_min is not None:
        config["atr_price_min"] = float(atr_ratio_min)

    atr_ratio_max = getattr(args, "atr_ratio_max", None)
    if atr_ratio_max is not None:
        config["atr_price_max"] = float(atr_ratio_max)

    return config


def merge_entry_filter_variant_runtime_bounds(
    variants: list[tuple[str, dict[str, Any]]],
    args: object,
) -> list[tuple[str, dict[str, Any]]]:
    if not has_entry_filter_runtime_bounds(args):
        return variants
    return [
        (name, merge_entry_filter_runtime_bounds(config, args))
        for name, config in variants
    ]
