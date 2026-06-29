from __future__ import annotations

from datetime import date
from typing import Any

from src.cli.evaluate import _resolve_entry_filter_variants
from src.config.runtime import get_config_file_path
from src.config.service import load_config as load_config_service
from src.entry_signal_analysis.models import (
    EntrySignalAnalysisRequest,
    EntrySignalEntryFilterMode,
)
from src.entry_signal_analysis.paths import default_output_dir
from src.production.config_manager import ConfigManager
from src.utils.atr_runtime_overrides import (
    _normalize_runtime_atr_bound,
    merge_entry_filter_variant_runtime_bounds,
)
from src.utils.momentum_exhaustion import (
    DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    MomentumExhaustionConfig,
    resolve_momentum_exhaustion_config,
)
from src.utils.industry_filter import (
    DEFAULT_INDUSTRY_FILTER_MODE,
    IndustryFilterConfig,
    resolve_industry_filter_config,
)
from src.utils.universe_loader import load_tickers_from_file


def load_runtime_config() -> dict[str, Any]:
    config_path = get_config_file_path()
    if not config_path.exists():
        return {}
    return load_config_service(str(config_path))


def load_config_manager() -> ConfigManager:
    return ConfigManager(str(get_config_file_path()))


def _coerce_date(value: str | None, fallback: date | None = None) -> date:
    if value:
        return date.fromisoformat(value)
    if fallback is not None:
        return fallback
    raise ValueError("date value is required")


def resolve_date_range(args: Any, config: dict[str, Any]) -> tuple[date, date]:
    if getattr(args, "years", None):
        years = sorted({int(year) for year in args.years})
        return date(years[0], 1, 1), date(years[-1], 12, 31)

    backtest_cfg = config.get("backtest", {}) if isinstance(config, dict) else {}
    start_fallback = (
        date.fromisoformat(str(backtest_cfg["start_date"]))
        if backtest_cfg.get("start_date")
        else None
    )
    end_fallback = (
        date.fromisoformat(str(backtest_cfg["end_date"]))
        if backtest_cfg.get("end_date")
        else None
    )
    return _coerce_date(getattr(args, "start", None), start_fallback), _coerce_date(
        getattr(args, "end", None),
        end_fallback,
    )


def resolve_production_ranking_strategy(raw_config: dict[str, Any]) -> str:
    production_cfg = raw_config.get("production", {}) if isinstance(raw_config, dict) else {}
    if "signal_ranking_strategy" not in production_cfg:
        return "momentum"
    configured_value = production_cfg.get("signal_ranking_strategy")
    if configured_value is None:
        return ""
    return str(configured_value).strip()


def resolve_entry_strategies(args: Any, config_mgr: ConfigManager) -> list[str]:
    if getattr(args, "entry_strategies", None):
        return [str(value) for value in args.entry_strategies]

    prod_cfg = config_mgr.get_production_config()
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    if strategy_groups:
        preferred = strategy_groups[0]
        if isinstance(preferred, dict) and preferred.get("entry_strategy"):
            return [str(preferred["entry_strategy"])]

    default_entry = getattr(prod_cfg, "default_entry_strategy", None)
    if default_entry:
        return [str(default_entry)]
    raise ValueError("entry-signal-analysis requires an entry strategy")


def resolve_universe_files(args: Any, config_mgr: ConfigManager) -> list[str]:
    if getattr(args, "universe_file", None):
        return [str(value) for value in args.universe_file]
    prod_cfg = config_mgr.get_production_config()
    monitor_file = getattr(prod_cfg, "monitor_list_file", None)
    if monitor_file:
        return [str(monitor_file)]
    raise ValueError("entry-signal-analysis requires a universe file")


def load_tickers(universe_files: list[str], limit: int | None = None) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for universe_file in universe_files:
        for ticker in load_tickers_from_file(universe_file):
            if ticker in seen:
                continue
            seen.add(ticker)
            tickers.append(ticker)
            if limit is not None and len(tickers) >= limit:
                return tickers
    return tickers


def resolve_output_dir(args: Any, config: dict[str, Any]) -> str:
    if getattr(args, "output_dir", None):
        return str(args.output_dir)
    entry_cfg = config.get("entry_signal_analysis", {}) if isinstance(config, dict) else {}
    configured = (
        str(entry_cfg["output_dir"])
        if isinstance(entry_cfg, dict) and entry_cfg.get("output_dir")
        else None
    )
    return default_output_dir(configured)


def resolve_entry_filter_variants(
    raw_config: dict[str, Any],
    mode: str,
    selected_names: list[str] | None,
) -> list[tuple[str, dict[str, Any]]]:
    production_cfg = raw_config.get("production", {}) if isinstance(raw_config, dict) else {}
    production_filter = production_cfg.get("entry_filter")

    if mode == "auto" and not selected_names and isinstance(production_filter, dict):
        return [("production", production_filter)]

    return _resolve_entry_filter_variants(raw_config, mode, selected_names)


def _is_pure_atr_filter_config(config: dict[str, Any] | None) -> bool:
    raw = config or {}
    if not bool(raw.get("enabled", False)):
        return False
    if raw.get("atr_price_min") is None and raw.get("atr_price_max") is None:
        return False
    return (
        not bool(raw.get("require_ema_bull_stack", False))
        and raw.get("rsi_min") is None
        and raw.get("rsi_max") is None
        and raw.get("min_price") is None
    )


def infer_entry_filter_mode_from_variants(
    variants: list[tuple[str, dict[str, Any]]],
) -> EntrySignalEntryFilterMode:
    if len(variants) > 1:
        return "grid"

    if not variants:
        return "off"

    name, config = variants[0]
    raw = config or {}
    if not bool(raw.get("enabled", False)):
        return "off"
    if str(name) == "atr" or _is_pure_atr_filter_config(raw):
        return "atr"
    return "single"


def resolve_tail_guard_config(
    raw_config: dict[str, Any],
    enabled_override: bool | None,
    max_rank_override: int | None,
    rank_limit_mode_override: str | None,
) -> dict[str, Any] | None:
    production_cfg = raw_config.get("production", {}) if isinstance(raw_config, dict) else {}
    base = production_cfg.get("tail_guard")
    config = dict(base) if isinstance(base, dict) else {}

    if enabled_override is not None:
        config["enabled"] = bool(enabled_override)
    elif "enabled" not in config:
        config["enabled"] = True

    if max_rank_override is not None:
        config["max_rank"] = int(max_rank_override)

    if "max_rank" not in config:
        config["max_rank"] = 12

    if rank_limit_mode_override is not None:
        config["rank_limit_mode"] = str(rank_limit_mode_override)

    return config


def build_request_from_args(args: Any) -> EntrySignalAnalysisRequest:
    config_mgr = load_config_manager()
    raw_config = config_mgr.raw_config
    prod_cfg = config_mgr.get_production_config()
    start_date, end_date = resolve_date_range(args, raw_config)
    entry_strategies = resolve_entry_strategies(args, config_mgr)
    universe_files = resolve_universe_files(args, config_mgr)
    tickers = load_tickers(universe_files, limit=getattr(args, "limit", None))
    if not tickers:
        raise ValueError("entry-signal-analysis resolved an empty ticker universe")

    ranking_strategy = str(
        getattr(args, "ranking_strategy", None)
        or resolve_production_ranking_strategy(raw_config)
        or "momentum"
    )
    position_sizing_mode = str(
        getattr(args, "position_sizing_mode", None)
        or getattr(prod_cfg, "position_sizing_mode", "atr")
        or "atr"
    )
    default_horizons = [1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 80]
    horizons = [int(value) for value in (getattr(args, "horizons", None) or default_horizons)]
    parsed_primary_horizons = [
        int(value) for value in (getattr(args, "primary_horizons", None) or [])
    ]
    fallback_primary_horizon = int(
        getattr(args, "primary_horizon", None) or (5 if 5 in horizons else horizons[0])
    )
    risk_per_trade_pct = getattr(args, "risk_per_trade_pct", None)
    if risk_per_trade_pct is None:
        risk_per_trade_pct = getattr(prod_cfg.atr_position_sizing, "risk_per_trade_pct", None)
    atr_stop_multiple = getattr(args, "atr_stop_multiple", None)
    if atr_stop_multiple is None:
        atr_stop_multiple = getattr(prod_cfg.atr_position_sizing, "atr_stop_multiple", None)
    atr_ratio_min = getattr(args, "atr_ratio_min", None)
    if atr_ratio_min is not None:
        atr_ratio_min = _normalize_runtime_atr_bound(atr_ratio_min)
    atr_ratio_max = getattr(args, "atr_ratio_max", None)
    if atr_ratio_max is not None:
        atr_ratio_max = _normalize_runtime_atr_bound(atr_ratio_max)

    return EntrySignalAnalysisRequest(
        entry_strategies=entry_strategies,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        analysis_profile=str(getattr(args, "analysis_profile", None) or "priority15"),
        large_artifact_format=str(
            getattr(args, "large_artifact_format", None) or "parquet"
        ),
        horizons=horizons,
        primary_horizon=fallback_primary_horizon,
        primary_horizons=parsed_primary_horizons,
        label_mode=str(getattr(args, "label_mode", None) or "next_open"),
        ranking_strategy=ranking_strategy,
        entry_filter_mode=str(getattr(args, "entry_filter_mode", None) or "auto"),
        entry_filter_names=list(getattr(args, "entry_filter_name", None) or []),
        position_sizing_mode=position_sizing_mode,
        risk_per_trade_pct=(float(risk_per_trade_pct) if risk_per_trade_pct is not None else None),
        atr_stop_multiple=(float(atr_stop_multiple) if atr_stop_multiple is not None else None),
        atr_ratio_min=atr_ratio_min,
        atr_ratio_max=atr_ratio_max,
        tail_guard_enabled=getattr(args, "tail_guard_enabled", None),
        tail_guard_max_rank=getattr(args, "tail_guard_max_rank", None),
        tail_guard_rank_limit_mode=getattr(args, "tail_guard_rank_limit_mode", None),
        momentum_exhaustion_mode=getattr(args, "momentum_exhaustion_mode", None),
        momentum_exhaustion_max_score=getattr(args, "momentum_exhaustion_max_score", None),
        momentum_exhaustion_threshold_method=(
            getattr(args, "momentum_exhaustion_threshold_method", None) or "absolute"
        ),
        industry_filter_mode=getattr(args, "industry_filter_mode", None),
        max_buy_per_industry_per_day=getattr(args, "max_buy_per_industry_per_day", None),
        max_total_positions_per_industry=getattr(
            args,
            "max_total_positions_per_industry",
            None,
        ),
        industry_reference_file=getattr(args, "industry_reference_file", None),
        target_pcts=[float(value) for value in (getattr(args, "target_pcts", None) or [5, 8, 10, 15, 20])],
        stop_pcts=[float(value) for value in (getattr(args, "stop_pcts", None) or [3, 5, 8, 10, 12])],
        target_stop_horizons=[
            int(value)
            for value in (getattr(args, "target_stop_horizons", None) or [10, 20, 40, 60, 80])
        ],
        checkpoint_days=[int(value) for value in (getattr(args, "checkpoint_days", None) or [10, 20, 40])],
        cooldown_days=[int(value) for value in (getattr(args, "cooldown_days", None) or [5, 10, 20, 40])],
        late_entry_days=[int(value) for value in (getattr(args, "late_entry_days", None) or [1, 2, 3, 5])],
        cost_bps=[float(value) for value in (getattr(args, "cost_bps", None) or [10, 20, 50, 100])],
        data_root=str(getattr(args, "data_root", None) or "data"),
        output_dir=resolve_output_dir(args, raw_config),
    )


def resolve_filter_variants_for_request(
    request: EntrySignalAnalysisRequest,
) -> list[tuple[str, dict[str, Any]]]:
    raw_config = load_runtime_config()
    variants = resolve_entry_filter_variants(
        raw_config,
        request.entry_filter_mode,
        request.entry_filter_names,
    )

    override_args = type(
        "EntrySignalRuntimeOverrides",
        (),
        {
            "atr_ratio_min": request.atr_ratio_min,
            "atr_ratio_max": request.atr_ratio_max,
        },
    )()
    return merge_entry_filter_variant_runtime_bounds(variants, override_args)


def resolve_effective_entry_filter_for_request(
    request: EntrySignalAnalysisRequest,
) -> tuple[EntrySignalEntryFilterMode, list[str]]:
    variants = resolve_filter_variants_for_request(request)
    return infer_entry_filter_mode_from_variants(variants), [str(name) for name, _ in variants]


def resolve_tail_guard_for_request(
    request: EntrySignalAnalysisRequest,
) -> dict[str, Any] | None:
    raw_config = load_runtime_config()
    return resolve_tail_guard_config(
        raw_config,
        enabled_override=request.tail_guard_enabled,
        max_rank_override=request.tail_guard_max_rank,
        rank_limit_mode_override=request.tail_guard_rank_limit_mode,
    )


def resolve_momentum_exhaustion_for_request(
    request: EntrySignalAnalysisRequest,
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


def resolve_industry_filter_for_request(
    request: EntrySignalAnalysisRequest,
) -> IndustryFilterConfig:
    raw_config = load_runtime_config()
    return resolve_industry_filter_config(
        raw_config,
        default_mode=DEFAULT_INDUSTRY_FILTER_MODE,
        mode_override=request.industry_filter_mode,
        max_buy_per_industry_per_day_override=request.max_buy_per_industry_per_day,
        max_total_positions_per_industry_override=request.max_total_positions_per_industry,
        reference_file_override=request.industry_reference_file,
    )
