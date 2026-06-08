from __future__ import annotations

from typing import TypeAlias

from src.entry_exit_validation.models import (
    EntryExitEntryFilterMode,
    EntryExitValidationRequest,
)
from src.entry_exit_validation.paths import default_output_dir
from src.entry_signal_analysis.runtime import (
    infer_entry_filter_mode_from_variants,
    load_config_manager,
    load_runtime_config,
    load_tickers,
    resolve_date_range,
    resolve_entry_filter_variants,
    resolve_production_ranking_strategy,
    resolve_tail_guard_config,
    resolve_universe_files,
)
from src.utils.atr_runtime_overrides import (
    _normalize_runtime_atr_bound,
    merge_entry_filter_variant_runtime_bounds,
)
from src.utils.momentum_exhaustion import (
    DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    MomentumExhaustionConfig,
    resolve_momentum_exhaustion_config,
)


FilterVariant: TypeAlias = tuple[str, dict[str, object]]


def resolve_entry_strategies(args: object) -> list[str]:
    values = getattr(args, "entry_strategies", None)
    if values:
        return [str(value) for value in values]

    config_mgr = load_config_manager()
    prod_cfg = config_mgr.get_production_config()
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    entries: list[str] = []
    for group in strategy_groups:
        if isinstance(group, dict) and group.get("entry_strategy"):
            value = str(group["entry_strategy"])
            if value not in entries:
                entries.append(value)
    if entries:
        return entries

    default_entry = getattr(prod_cfg, "default_entry_strategy", None)
    if default_entry:
        return [str(default_entry)]
    raise ValueError("entry-exit-validation requires at least one entry strategy")


def resolve_exit_strategies(args: object) -> list[str]:
    values = getattr(args, "exit_strategies", None)
    if values:
        return [str(value) for value in values]

    config_mgr = load_config_manager()
    prod_cfg = config_mgr.get_production_config()
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    exits: list[str] = []
    for group in strategy_groups:
        if isinstance(group, dict) and group.get("exit_strategy"):
            value = str(group["exit_strategy"])
            if value not in exits:
                exits.append(value)
    if exits:
        return exits

    default_exit = getattr(prod_cfg, "default_exit_strategy", None)
    if default_exit:
        return [str(default_exit)]
    raise ValueError("entry-exit-validation requires at least one exit strategy")


def resolve_output_dir(args: object, config: dict[str, object]) -> str:
    if getattr(args, "output_dir", None):
        return str(getattr(args, "output_dir"))
    entry_exit_cfg = config.get("entry_exit_validation", {})
    configured = (
        str(entry_exit_cfg["output_dir"])
        if isinstance(entry_exit_cfg, dict) and entry_exit_cfg.get("output_dir")
        else None
    )
    return default_output_dir(configured)


def _normalize_optional_atr(value: object) -> float | None:
    if value is None:
        return None
    normalized = _normalize_runtime_atr_bound(value)
    return float(normalized) if normalized is not None else None


def build_request_from_args(args: object) -> EntryExitValidationRequest:
    config_mgr = load_config_manager()
    raw_config = config_mgr.raw_config
    start_date, end_date = resolve_date_range(args, raw_config)
    universe_files = resolve_universe_files(args, config_mgr)
    tickers = load_tickers(universe_files, limit=getattr(args, "limit", None))
    if not tickers:
        raise ValueError("entry-exit-validation resolved an empty ticker universe")

    ranking_strategy = str(
        getattr(args, "ranking_strategy", None)
        or resolve_production_ranking_strategy(raw_config)
        or "momentum"
    )

    return EntryExitValidationRequest(
        entry_strategies=resolve_entry_strategies(args),
        exit_strategies=resolve_exit_strategies(args),
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        horizons=[int(value) for value in (getattr(args, "horizons", None) or [3, 5, 7, 9, 11])],
        primary_horizon=int(getattr(args, "primary_horizon", None) or 5),
        execution_mode=str(getattr(args, "execution_mode", None) or "next_open"),
        signal_scope=str(getattr(args, "signal_scope", None) or "all"),
        ranking_strategy=ranking_strategy,
        entry_filter_mode=str(getattr(args, "entry_filter_mode", None) or "auto"),
        entry_filter_names=list(getattr(args, "entry_filter_name", None) or []),
        atr_ratio_min=_normalize_optional_atr(getattr(args, "atr_ratio_min", None)),
        atr_ratio_max=_normalize_optional_atr(getattr(args, "atr_ratio_max", None)),
        tail_guard_enabled=getattr(args, "tail_guard_enabled", None),
        tail_guard_max_rank=getattr(args, "tail_guard_max_rank", None),
        tail_guard_rank_limit_mode=getattr(args, "tail_guard_rank_limit_mode", None),
        momentum_exhaustion_mode=getattr(args, "momentum_exhaustion_mode", None),
        momentum_exhaustion_max_score=getattr(args, "momentum_exhaustion_max_score", None),
        momentum_exhaustion_threshold_method=(
            getattr(args, "momentum_exhaustion_threshold_method", None) or "absolute"
        ),
        max_holding_trading_days=int(getattr(args, "max_holding_trading_days", None) or 60),
        partial_exit_policy=str(getattr(args, "partial_exit_policy", None) or "first_sell_full_exit"),
        min_samples=int(getattr(args, "min_samples", None) or 30),
        data_root=str(getattr(args, "data_root", None) or "data"),
        output_dir=resolve_output_dir(args, raw_config),
    )


def resolve_filter_variants_for_request(
    request: EntryExitValidationRequest,
) -> list[FilterVariant]:
    raw_config = load_runtime_config()
    variants = resolve_entry_filter_variants(
        raw_config,
        request.entry_filter_mode,
        request.entry_filter_names,
    )
    override_args = type(
        "EntryExitRuntimeOverrides",
        (),
        {
            "atr_ratio_min": request.atr_ratio_min,
            "atr_ratio_max": request.atr_ratio_max,
        },
    )()
    merged = merge_entry_filter_variant_runtime_bounds(variants, override_args)
    return [(str(name), dict(config)) for name, config in merged]


def resolve_effective_entry_filter_for_request(
    request: EntryExitValidationRequest,
) -> tuple[EntryExitEntryFilterMode, list[str]]:
    variants = resolve_filter_variants_for_request(request)
    mode = infer_entry_filter_mode_from_variants(variants)
    return mode, [str(name) for name, _ in variants]


def resolve_tail_guard_for_request(
    request: EntryExitValidationRequest,
) -> dict[str, object] | None:
    raw_config = load_runtime_config()
    return resolve_tail_guard_config(
        raw_config,
        enabled_override=request.tail_guard_enabled,
        max_rank_override=request.tail_guard_max_rank,
        rank_limit_mode_override=request.tail_guard_rank_limit_mode,
    )


def resolve_momentum_exhaustion_for_request(
    request: EntryExitValidationRequest,
) -> MomentumExhaustionConfig:
    raw_config = load_runtime_config()
    return resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
        mode_override=request.momentum_exhaustion_mode,
        max_score_override=request.momentum_exhaustion_max_score,
        threshold_method_override=request.momentum_exhaustion_threshold_method,
        use_configured_mode=False,
    )
