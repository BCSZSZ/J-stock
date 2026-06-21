import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.backtest.entry_reference import normalize_entry_reference_mode
from src.backtest.fill_buffer import normalize_fill_buffer_pct
from src.evaluation import (
    MarketRegime,
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods,
)
from src.evaluation.report_context import resolve_report_strategy_context
from src.evaluation.replay_seed import (
    ReplaySeed,
    extract_report_date,
    load_replay_seed,
    resolve_latest_available_end_date,
)
from src.evaluation.strategy_evaluator import select_rank_df_for_mode
from src.evaluation.scoring import candidate_key_columns, rank_final_prs, summarize_prs_train_metrics
from src.evaluation.trade_indicator_enrichment import write_enriched_trades_sidecar
from src.config.runtime import get_config_file_path, is_local_path
from src.production.config_manager import ConfigManager
from src.utils.atr_runtime_overrides import (
    merge_entry_filter_variant_runtime_bounds,
    merge_portfolio_runtime_overrides,
)
from src.utils.atr_position_sizing import normalize_position_sizing_mode
from src.utils.momentum_exhaustion import (
    DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    resolve_momentum_exhaustion_config,
)
from src.utils.industry_filter import (
    DEFAULT_INDUSTRY_FILTER_MODE,
    resolve_industry_filter_config,
)
from src.utils.strategy_loader import get_strategy_complexity_penalty

from .common import load_config


DEFAULT_EVALUATION_OUTPUT_DIR = Path("strategy_evaluation")


@dataclass
class EvaluationRunContext:
    """Single evaluation run context (profile/overlay/universe combination)."""

    name: str
    prefix: str
    monitor_list_file: Optional[str] = None
    portfolio_overrides: Optional[Dict[str, Any]] = None
    enable_overlay: Optional[bool] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationOutputBundle:
    """Segmented and optional continuous outputs for one run context."""

    segmented: Dict[str, str]
    continuous: Optional[Dict[str, str]] = None
    annual_companion: Optional[Dict[str, str]] = None
    final_report: Optional[str] = None


def _log_step(message: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def _dedupe_preserve_order(values):
    """Remove duplicates while preserving order."""
    if not values:
        return []
    seen = set()
    deduped = []
    for item in values:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _dedupe_filter_variants(variants):
    """Deduplicate filter variants by (name, normalized config json)."""
    if not variants:
        return []
    seen = set()
    deduped = []
    for name, cfg in variants:
        cfg = cfg or {}
        key = (str(name), json.dumps(cfg, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, cfg))
    return deduped


def _resolve_output_root(user_output_dir):
    if user_output_dir:
        root = str(user_output_dir)
    else:
        cfg = load_config()
        configured = cfg.get("evaluation", {}).get("output_dir")
        root = str(configured) if configured else str(DEFAULT_EVALUATION_OUTPUT_DIR)

    if is_local_path(root):
        Path(root).mkdir(parents=True, exist_ok=True)
    return root


def _summarize_selection_for_dir(label: str, values) -> str:
    normalized = _dedupe_preserve_order(values or [])
    if not normalized:
        return f"{label}_all"

    if len(normalized) == 1:
        return f"{label}_{_sanitize_name(str(normalized[0]))[:72]}"

    first = _sanitize_name(str(normalized[0]))[:36]
    return f"{label}_{len(normalized)}_{first}_plus{len(normalized) - 1}"


def _format_dir_scalar(value) -> str:
    if value is None or str(value).strip() == "":
        return "cfg"
    try:
        text = f"{float(value):g}"
    except (TypeError, ValueError):
        text = str(value).strip()
    return _sanitize_name(text.replace("-", "m").replace(".", "p")) or "cfg"


def _short_mode_slug(value, mapping: Dict[str, str]) -> str:
    mode = str(value or "cfg").strip().lower()
    return mapping.get(mode, _sanitize_name(mode) or "cfg")


def _build_momentum_output_slug(args) -> str:
    mode_slug = _short_mode_slug(
        getattr(args, "momentum_exhaustion_mode", None),
        {"off": "off", "shadow": "shd", "enforce": "enf"},
    )
    if mode_slug in {"off", "cfg"}:
        return f"mom_{mode_slug}"
    max_score = _format_dir_scalar(
        getattr(args, "momentum_exhaustion_max_score", None)
    )
    return f"mom_{mode_slug}_s{max_score}"


def _build_industry_output_slug(args) -> str:
    mode_slug = _short_mode_slug(
        getattr(args, "industry_filter_mode", None),
        {"off": "off", "shadow": "shd", "enforce": "enf"},
    )
    if mode_slug in {"off", "cfg"}:
        return f"ind_{mode_slug}"
    daily_cap = _format_dir_scalar(
        getattr(args, "max_buy_per_industry_per_day", None)
    )
    total_cap = _format_dir_scalar(
        getattr(args, "max_total_positions_per_industry", None)
    )
    return f"ind_{mode_slug}_d{daily_cap}_t{total_cap}"


_OUTPUT_SIGNATURE_FIELDS = (
    "mode",
    "years",
    "months",
    "custom_periods",
    "launch_date",
    "entry_filter_mode",
    "entry_filter_name",
    "atr_ratio_min",
    "atr_ratio_max",
    "ranking_mode",
    "ranking_strategies",
    "buy_fill_mode",
    "entry_reference_mode",
    "fill_buffer_enabled",
    "fill_buffer_pct",
    "capacity_regime_mode",
    "position_sizing_mode",
    "risk_per_trade_pct",
    "atr_stop_multiple",
    "enable_overlay",
    "momentum_exhaustion_mode",
    "momentum_exhaustion_max_score",
    "momentum_exhaustion_threshold_method",
    "industry_filter_mode",
    "max_buy_per_industry_per_day",
    "max_total_positions_per_industry",
    "industry_reference_file",
    "allow_held_position_buys",
    "universe_file",
)


def _build_output_signature_slug(
    run_kind: str,
    args,
    entry_strategies,
    exit_strategies,
) -> str:
    payload = {
        "run_kind": run_kind,
        "entry_strategies": _json_safe_value(entry_strategies),
        "exit_strategies": _json_safe_value(exit_strategies),
    }
    for field_name in _OUTPUT_SIGNATURE_FIELDS:
        payload[field_name] = _json_safe_value(getattr(args, field_name, None))
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(serialized.encode("utf-8")).hexdigest()[:8]
    return f"sig_{digest}"


def _reserve_identity_suffix(base_slug: str, identity_parts: List[str]) -> str:
    identity_suffix = "__".join(part for part in identity_parts if part)
    if not identity_suffix:
        return base_slug[:180].rstrip("_")

    max_len = 180
    separator = "__"
    max_base_len = max_len - len(separator) - len(identity_suffix)
    if max_base_len <= 0:
        return identity_suffix[:max_len].rstrip("_")

    truncated_base = base_slug[:max_base_len].rstrip("_")
    return f"{truncated_base}{separator}{identity_suffix}".rstrip("_")


def _build_output_run_slug(run_kind: str, args, eval_cfg) -> str:
    entry_strategies, exit_strategies = _resolve_entry_exit_strategies(
        args, eval_cfg, announce=False
    )
    parts = [_sanitize_name(run_kind.replace("-", "_"))]

    mode = getattr(args, "mode", None)
    if mode:
        parts.append(_sanitize_name(str(mode)))

    parts.append(_summarize_selection_for_dir("entry", entry_strategies))
    parts.append(_summarize_selection_for_dir("exit", exit_strategies))
    parts.append(_sanitize_name(f"fill_{getattr(args, 'buy_fill_mode', 'next_open') or 'next_open'}"))
    parts.append(
        _sanitize_name(
            f"entryref_{normalize_entry_reference_mode(getattr(args, 'entry_reference_mode', 'raw_fill'))}"
        )
    )
    fill_buffer_enabled = bool(getattr(args, "fill_buffer_enabled", False))
    fill_buffer_pct = normalize_fill_buffer_pct(getattr(args, "fill_buffer_pct", 0.02))
    if fill_buffer_enabled:
        parts.append(
            _sanitize_name(
                f"buffer_on_{fill_buffer_pct:.4f}".replace(".", "p")
            )
        )
    else:
        parts.append("buffer_off")

    if run_kind == "pos-evaluation":
        profile_names = _dedupe_preserve_order(
            getattr(args, "profile_name", None)
            or eval_cfg.get("default_profile_names", [])
        )
        parts.append(_summarize_selection_for_dir("profile", profile_names))

    slug = "__".join(part for part in parts if part)
    identity_parts = [
        _build_momentum_output_slug(args),
        _build_industry_output_slug(args),
        _build_output_signature_slug(
            run_kind,
            args,
            entry_strategies,
            exit_strategies,
        ),
    ]
    return _reserve_identity_suffix(slug, identity_parts)


def _create_unique_output_run_dir(date_dir: Path, run_slug: str, now: datetime) -> Path:
    timestamp = now.strftime("%H%M%S_%f")
    base_name = f"{run_slug}__{timestamp}"
    for index in range(1000):
        suffix = "" if index == 0 else f"_{index:02d}"
        candidate = date_dir / f"{base_name}{suffix}"
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not create unique evaluation output dir: {base_name}")


def _resolve_output_dir(run_kind: str, args, user_output_dir, eval_cfg):
    output_root = _resolve_output_root(user_output_dir)

    if not is_local_path(output_root):
        print(f"📁 输出目录: {output_root}")
        return output_root

    now = datetime.now()
    date_dir = Path(output_root) / now.strftime("%Y%m%d")
    run_slug = _build_output_run_slug(run_kind, args, eval_cfg)
    run_dir = _create_unique_output_run_dir(date_dir, run_slug, now)

    print(f"📁 输出根目录: {output_root}")
    print(f"📁 本次输出目录: {run_dir}")
    return str(run_dir)


def _json_safe_value(value: Any):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]
    return str(value)


def _build_run_metadata(
    *,
    run_kind: str,
    args,
    periods,
    prefix: str,
    output_dir: str,
    monitor_list_file: Optional[str],
    portfolio_overrides: Optional[Dict[str, Any]],
    enable_overlay: bool,
    ranking_mode: str,
    entry_filter_variants,
    entry_strategies,
    exit_strategies,
    context_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context_metadata = context_metadata or {}
    years = getattr(args, "years", None) or []
    period_rows = [
        {
            "period": str(period_label),
            "start_date": str(start_date),
            "end_date": str(end_date),
        }
        for period_label, start_date, end_date in periods
    ]
    filter_rows = [
        {"name": str(name), "config": _json_safe_value(cfg or {})}
        for name, cfg in (entry_filter_variants or [])
    ]

    return {
        "schema_version": 1,
        "run_kind": run_kind,
        "mode": getattr(args, "mode", None),
        "years": [int(year) if str(year).isdigit() else str(year) for year in years],
        "periods": period_rows,
        "prefix": prefix,
        "output_dir": output_dir,
        "entry_strategies": [str(item) for item in (entry_strategies or [])],
        "exit_strategies": [str(item) for item in (exit_strategies or [])],
        "entry_filter_mode": getattr(args, "entry_filter_mode", None),
        "entry_filter_variants": filter_rows,
        "ranking_mode": ranking_mode,
        "ranking_strategies": [
            str(item) for item in (getattr(args, "ranking_strategies", None) or [])
        ],
        "buy_fill_mode": getattr(args, "buy_fill_mode", "next_open"),
        "entry_reference_mode": normalize_entry_reference_mode(
            getattr(args, "entry_reference_mode", "raw_fill")
        ),
        "fill_buffer_enabled": bool(getattr(args, "fill_buffer_enabled", False)),
        "fill_buffer_pct": normalize_fill_buffer_pct(
            getattr(args, "fill_buffer_pct", 0.02)
        ),
        "overlay_enabled": bool(enable_overlay),
        "capacity_regime_mode_override": getattr(args, "capacity_regime_mode", None),
        "momentum_exhaustion_mode": getattr(args, "momentum_exhaustion_mode", None),
        "momentum_exhaustion_max_score": getattr(args, "momentum_exhaustion_max_score", None),
        "momentum_exhaustion_threshold_method": getattr(
            args,
            "momentum_exhaustion_threshold_method",
            None,
        ),
        "industry_filter_mode": getattr(args, "industry_filter_mode", None),
        "max_buy_per_industry_per_day": getattr(
            args,
            "max_buy_per_industry_per_day",
            None,
        ),
        "max_total_positions_per_industry": getattr(
            args,
            "max_total_positions_per_industry",
            None,
        ),
        "industry_reference_file": getattr(args, "industry_reference_file", None),
        "allow_held_position_buys": bool(
            getattr(args, "allow_held_position_buys", False)
        ),
        "universe_name": str(context_metadata.get("universe_name") or ""),
        "universe_file": str(
            context_metadata.get("universe_file") or monitor_list_file or ""
        ),
        "monitor_list_file": str(monitor_list_file or ""),
        "portfolio_overrides": _json_safe_value(portfolio_overrides or {}),
        "context_metadata": _json_safe_value(context_metadata),
    }


def _load_entry_filter_variants(cfg):
    eval_cfg = cfg.get("evaluation", {})
    variants_cfg = eval_cfg.get("filters", {}).get("variants", {})
    if isinstance(variants_cfg, dict) and variants_cfg:
        variants = []
        for name, filter_cfg in variants_cfg.items():
            if isinstance(filter_cfg, dict):
                variants.append((str(name), filter_cfg))
        if variants:
            return variants

    return []


def _resolve_entry_filter_variants(cfg, mode, selected_names):
    eval_cfg = cfg.get("evaluation", {})
    default_filter_cfg = eval_cfg.get("filters", {}).get("default", {})
    named_variants = _load_entry_filter_variants(cfg)
    named_map = {name: variant_cfg for name, variant_cfg in named_variants}

    if mode == "off":
        return [("off", {"enabled": False})]

    if mode == "atr":
        if selected_names:
            raise ValueError("atr模式不支持 --entry-filter-name；它只启用ATR%过滤")
        return [
            (
                "atr",
                {
                    "enabled": True,
                    "require_ema_bull_stack": False,
                    "rsi_min": None,
                    "rsi_max": None,
                    "atr_price_min": default_filter_cfg.get("atr_price_min"),
                    "atr_price_max": default_filter_cfg.get("atr_price_max", 0.04),
                    "min_price": None,
                },
            )
        ]

    if mode == "single":
        if selected_names:
            if len(selected_names) != 1:
                raise ValueError("single模式下 --entry-filter-name 只能指定1个")
            name = selected_names[0]
            if name not in named_map:
                raise ValueError(f"未找到entry filter: {name}")
            return [(name, named_map[name])]
        return [("default", default_filter_cfg)]

    if mode == "grid":
        if not named_variants:
            raise ValueError(
                "grid模式需要在config.evaluation.filters.variants中定义至少1个过滤器"
            )
        if not selected_names:
            return named_variants
        missing = [name for name in selected_names if name not in named_map]
        if missing:
            raise ValueError(f"未找到entry filter: {', '.join(missing)}")
        return [(name, named_map[name]) for name in selected_names]

    if selected_names:
        if not named_variants:
            raise ValueError("当前配置未定义filters.variants，无法按名称选择")
        missing = [name for name in selected_names if name not in named_map]
        if missing:
            raise ValueError(f"未找到entry filter: {', '.join(missing)}")
        return [(name, named_map[name]) for name in selected_names]
    if named_variants:
        return named_variants
    return [("default", default_filter_cfg)]


def _print_available_entry_filters(cfg):
    eval_cfg = cfg.get("evaluation", {})
    default_filter_cfg = eval_cfg.get("filters", {}).get("default", {})
    named_variants = _load_entry_filter_variants(cfg)

    print("\n🧪 可用 Entry Filter:")
    print(
        f"   - default (fallback): enabled={default_filter_cfg.get('enabled', False)}"
    )
    if named_variants:
        for name, variant_cfg in named_variants:
            print(f"   - {name}: enabled={variant_cfg.get('enabled', False)}")
    else:
        print("   - (未定义 evaluation.filters.variants)")


def _build_periods(args):
    periods = []

    if args.mode == "annual":
        if not args.years:
            raise ValueError("annual模式需要指定--years参数")
        periods = create_annual_periods(args.years)
        print("📅 评估模式: 整年")
        print(f"   年份: {', '.join(map(str, args.years))}")

    elif args.mode == "quarterly":
        if not args.years:
            raise ValueError("quarterly模式需要指定--years参数")
        periods = create_quarterly_periods(args.years)
        print("📅 评估模式: 季度")
        print(f"   年份: {', '.join(map(str, args.years))}")

    elif args.mode == "monthly":
        if not args.years:
            raise ValueError("monthly模式需要指定--years参数")

        months = args.months if args.months else list(range(1, 13))
        for year in args.years:
            periods.extend(create_monthly_periods(year, months))

        print("📅 评估模式: 月度")
        print(f"   年份: {', '.join(map(str, args.years))}")
        print(f"   月份: {', '.join(map(str, months))}")

    elif args.mode == "custom":
        if not args.custom_periods:
            raise ValueError("custom模式需要指定--custom-periods参数")

        try:
            periods = json.loads(args.custom_periods)
            print("📅 评估模式: 自定义")
            print(f"   时间段数: {len(periods)}")
        except json.JSONDecodeError as e:
            raise ValueError(f"custom_periods JSON解析失败: {e}")

    if not periods:
        raise ValueError("没有有效的时间段")

    periods = _apply_launch_date_clip(periods, getattr(args, "launch_date", None))

    print("\n📊 时间段列表:")
    for label, start, end in periods[:5]:
        print(f"   {label}: {start} ~ {end}")
    if len(periods) > 5:
        print(f"   ... 共 {len(periods)} 个时间段")

    return periods


def _apply_launch_date_clip(
    periods: List[Tuple[str, str, str]],
    launch_date: str | List[str] | None,
) -> List[Tuple[str, str, str]]:
    launch_dates = _parse_launch_dates(launch_date)
    if not launch_dates:
        return periods

    clipped: List[Tuple[str, str, str]] = []
    adjusted = 0
    skipped = 0
    multi_launch_mode = len(launch_dates) > 1

    for selected_launch_date, launch_dt in launch_dates:
        for label, start, end in periods:
            start_dt = datetime.strptime(start, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end, "%Y-%m-%d").date()
            if multi_launch_mode and launch_dt < start_dt:
                skipped += 1
                continue
            if launch_dt > end_dt:
                skipped += 1
                continue

            clipped_start_dt = max(start_dt, launch_dt)
            clipped_start = clipped_start_dt.isoformat()
            clipped_label = label
            if multi_launch_mode:
                clipped_label = f"{label}_launch_{selected_launch_date}"
                if clipped_start != start:
                    adjusted += 1
                    clipped_label = f"{clipped_label}_from_{clipped_start}"
            elif clipped_start != start:
                adjusted += 1
                clipped_label = f"{label}_from_{clipped_start}"
            clipped.append((clipped_label, clipped_start, end))

    if not clipped:
        raise ValueError("launch_date 晚于所有评估时间段的结束日期，没有可运行区间")

    print("\n🚀 启动日裁剪:")
    print(f"   launch_dates: {', '.join(raw for raw, _ in launch_dates)}")
    if multi_launch_mode:
        print(f"   启动日个数: {len(launch_dates)}")
    print(f"   调整区间数: {adjusted}")
    if skipped:
        print(f"   跳过区间数: {skipped}")

    return clipped


def _parse_launch_dates(
    launch_date: str | List[str] | None,
) -> List[Tuple[str, date]]:
    if not launch_date:
        return []

    raw_values = [launch_date] if isinstance(launch_date, str) else list(launch_date)
    parsed_dates: List[Tuple[str, date]] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("--launch-date 必须是 YYYY-MM-DD 格式") from exc
        parsed_dates.append((value, parsed))
        seen.add(value)

    return parsed_dates


def _build_segmented_continuous_periods(args, periods: List[Tuple[str, str, str]]):
    """Build one full-span continuous companion for annual/quarterly segmented runs."""
    if getattr(args, "mode", None) not in {"annual", "quarterly"} or len(periods) < 2:
        return []

    start_date = min(start for _, start, _ in periods)
    end_date = max(end for _, _, end in periods)
    years = [int(year) for year in (getattr(args, "years", []) or [])]
    if years:
        if min(years) == max(years):
            label = f"{min(years)}_continuous"
        else:
            label = f"{min(years)}-{max(years)}_continuous"
    else:
        label = f"{start_date}_to_{end_date}_continuous"

    return [(label, start_date, end_date)]


def _resolve_include_continuous(args, eval_cfg: Dict[str, Any]) -> bool:
    cli_value = getattr(args, "include_continuous", None)
    if cli_value is not None:
        return bool(cli_value)
    return bool(eval_cfg.get("include_continuous", False))


def _sanitize_name(name: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in ["-", "_"]) else "_" for ch in name)


def _resolve_universe_variants(universe_files):
    if not universe_files:
        return [("default", None)]

    variants = []
    for item in universe_files:
        p = Path(item)
        if not p.exists():
            raise ValueError(f"股票池文件不存在: {p}")
        variants.append((p.stem, str(p)))
    return variants


def _resolve_effective_overlay_enabled(config, args, override: bool = None) -> bool:
    """Resolve final overlay switch from CLI/config/override in one place.

    PROJECT POLICY: overlay defaults to OFF for both evaluate and pos-evaluation.
    Resolution order:
      1. explicit ``override`` (callable-level) if not None
      2. CLI flag ``--enable-overlay`` (args.enable_overlay) if it set True
      3. ``config.overlays.enabled`` boolean (after normalize_config)
      4. Fallback: False (OFF)
    See instruction.md "全局策略：Overlay 默认 OFF" for rationale.
    """
    if override is not None:
        return bool(override)

    arg_overlay = getattr(args, "enable_overlay", None)
    if arg_overlay is None:
        return bool(config.get("overlays", {}).get("enabled", False))
    return bool(arg_overlay)


def _resolve_ranking_mode(config, args) -> str:
    """Resolve ranking mode from CLI first, then config, then default."""
    arg_mode = getattr(args, "ranking_mode", None)
    if arg_mode in {"legacy", "target20", "risk60_profit40", "prs_train"}:
        return arg_mode

    cfg_mode = config.get("evaluation", {}).get("ranking", {}).get("mode")
    if cfg_mode == "risk60_profit40_v2":
        return "risk60_profit40"
    if cfg_mode in {"legacy", "target20", "risk60_profit40", "prs_train"}:
        return cfg_mode

    return "target20"


def _prepare_common_evaluation_inputs(args, config):
    """Resolve entry filters, periods and universe variants shared by both commands."""
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return None

    entry_filter_variants = _resolve_entry_filter_variants(
        config,
        mode=args.entry_filter_mode,
        selected_names=selected_filter_names,
    )
    entry_filter_variants = merge_entry_filter_variant_runtime_bounds(
        entry_filter_variants,
        args,
    )
    periods = _build_periods(args)
    universe_variants = _resolve_universe_variants(args.universe_file)

    return entry_filter_variants, periods, universe_variants


def _prepare_walk_forward_inputs(args, config):
    """Resolve entry filters, base periods and universe variants for walk-forward."""
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return None

    entry_filter_variants = _resolve_entry_filter_variants(
        config,
        mode=args.entry_filter_mode,
        selected_names=selected_filter_names,
    )
    entry_filter_variants = merge_entry_filter_variant_runtime_bounds(
        entry_filter_variants,
        args,
    )

    years = sorted({int(year) for year in (args.years or [])})
    if not years:
        raise ValueError("walk-forward模式需要指定--years参数")

    walk_forward_mode = _resolve_walk_forward_mode(args)
    min_train_years = max(1, int(args.min_train_years))
    if len(years) < min_train_years + 1:
        raise ValueError(
            f"至少需要 {min_train_years + 1} 个年份，当前仅提供 {len(years)} 个"
        )

    base_periods = _build_walk_forward_base_periods(walk_forward_mode, years)
    min_train_periods = _resolve_walk_forward_min_train_periods(
        walk_forward_mode,
        min_train_years,
    )
    if len(base_periods) < min_train_periods + 1:
        raise ValueError(
            f"walk-forward {walk_forward_mode} 模式至少需要 {min_train_years + 1} 个年份才能形成测试窗口"
        )

    universe_variants = _resolve_universe_variants(args.universe_file)

    print("📅 Anchored Walk-Forward 模式")
    print(f"   粒度: {walk_forward_mode}")
    print(f"   年份: {', '.join(map(str, years))}")
    print(f"   最小训练年份数: {min_train_years}")
    print(f"   基础时间窗数: {len(base_periods)}")
    print(f"   测试窗口数: {len(base_periods) - min_train_periods}")

    return entry_filter_variants, years, base_periods, universe_variants


def _prepare_replay_inputs(args, config):
    """Resolve entry filters and universe variants for replay evaluation."""
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return None

    entry_filter_variants = _resolve_entry_filter_variants(
        config,
        mode=args.entry_filter_mode,
        selected_names=selected_filter_names,
    )
    entry_filter_variants = merge_entry_filter_variant_runtime_bounds(
        entry_filter_variants,
        args,
    )
    universe_variants = _resolve_universe_variants(args.universe_file)
    return entry_filter_variants, universe_variants


def _resolve_replay_report_files(args) -> List[Path]:
    raw_values = getattr(args, "report_file", None) or []
    if isinstance(raw_values, (str, Path)):
        raw_values = [raw_values]

    report_files: List[Path] = []
    seen: set[str] = set()
    for value in raw_values:
        normalized = str(value).strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        report_files.append(Path(normalized))
    return report_files


def _build_replay_report_run_args(args, report_file: Path):
    run_args = SimpleNamespace(**vars(args))
    run_args.report_file = str(report_file)

    strategy_context: Dict[str, str] = {}
    if not getattr(args, "entry_strategies", None) or not getattr(args, "exit_strategies", None):
        try:
            strategy_context = resolve_report_strategy_context(report_file)
        except Exception:
            strategy_context = {}

    if not getattr(args, "entry_strategies", None) and strategy_context.get("entry_strategy"):
        run_args.entry_strategies = [strategy_context["entry_strategy"]]
    if not getattr(args, "exit_strategies", None) and strategy_context.get("exit_strategy"):
        run_args.exit_strategies = [strategy_context["exit_strategy"]]

    return run_args, strategy_context


def _resolve_exit_confirm_days(args, eval_cfg) -> int:
    """Resolve exit confirmation days with CLI override precedence."""
    exit_confirm_days = getattr(args, "exit_confirm_days", None)
    if exit_confirm_days is None:
        exit_confirm_days = int(eval_cfg.get("exit_confirmation_days", 1))
    return max(1, int(exit_confirm_days))


def _resolve_entry_exit_strategies(args, eval_cfg, announce: bool = True):
    """Resolve entry and exit strategy lists from CLI/config with de-duplication."""
    entry_strategies = args.entry_strategies
    if not entry_strategies:
        entry_strategies = eval_cfg.get("default_entry_strategies")
        if announce and entry_strategies:
            print("\n🧭 使用 evaluation.default_entry_strategies")
            print(f"   入场策略: {', '.join(entry_strategies)}")

    original_entry_count = len(entry_strategies) if entry_strategies else 0
    entry_strategies = _dedupe_preserve_order(entry_strategies)
    if entry_strategies and len(entry_strategies) != original_entry_count:
        print(f"⚠️ 入场策略去重: {original_entry_count} -> {len(entry_strategies)}")

    exit_strategies = args.exit_strategies
    if not exit_strategies:
        exit_strategies = eval_cfg.get("default_exit_strategies")
        if announce and exit_strategies:
            print("\n🧭 使用 evaluation.default_exit_strategies")
            print(f"   出场策略: {', '.join(exit_strategies)}")

    if announce and not exit_strategies:
        print("\n⚠️ 警告: 未定义 evaluation.default_exit_strategies，将使用所有可用策略")

    original_exit_count = len(exit_strategies) if exit_strategies else 0
    exit_strategies = _dedupe_preserve_order(exit_strategies)
    if exit_strategies and len(exit_strategies) != original_exit_count:
        print(f"⚠️ 出场策略去重: {original_exit_count} -> {len(exit_strategies)}")
    if exit_strategies:
        from src.utils.strategy_loader import ensure_exit_strategy_registered

        for exit_strategy in exit_strategies:
            ensure_exit_strategy_registered(exit_strategy)

    return entry_strategies, exit_strategies


def _resolve_overlay_config(config, args, enable_overlay_override: bool = None):
    use_overlay = _resolve_effective_overlay_enabled(
        config=config,
        args=args,
        override=enable_overlay_override,
    )
    if use_overlay:
        overlay_config = dict(config)
        overlays_cfg = dict(config.get("overlays", {}))
        overlays_cfg["enabled"] = True
        overlay_config["overlays"] = overlays_cfg
    else:
        overlay_config = {}
    return use_overlay, overlay_config


def _build_evaluator(
    args,
    config,
    output_dir,
    monitor_list_file,
    portfolio_overrides,
    enable_overlay,
    exit_confirm_days,
    entry_filter_variants,
    replay_seed: Optional[ReplaySeed] = None,
    run_metadata: Optional[Dict[str, Any]] = None,
):
    """Create a StrategyEvaluator with the shared runtime settings."""
    _, overlay_config = _resolve_overlay_config(
        config=config,
        args=args,
        enable_overlay_override=enable_overlay,
    )

    ranking_strategies = getattr(args, "ranking_strategies", None)
    momentum_exhaustion_config = resolve_momentum_exhaustion_config(
        config,
        default_mode=DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
        mode_override=getattr(args, "momentum_exhaustion_mode", None),
        max_score_override=getattr(args, "momentum_exhaustion_max_score", None),
        threshold_method_override=getattr(
            args,
            "momentum_exhaustion_threshold_method",
            None,
        ),
        use_configured_mode=False,
    )
    industry_filter_config = resolve_industry_filter_config(
        config,
        default_mode=DEFAULT_INDUSTRY_FILTER_MODE,
        mode_override=getattr(args, "industry_filter_mode", None),
        max_buy_per_industry_per_day_override=getattr(
            args,
            "max_buy_per_industry_per_day",
            None,
        ),
        max_total_positions_per_industry_override=getattr(
            args,
            "max_total_positions_per_industry",
            None,
        ),
        reference_file_override=getattr(args, "industry_reference_file", None),
    )
    effective_run_metadata = dict(run_metadata or {})
    effective_run_metadata.update(
        {
            "momentum_exhaustion_mode": momentum_exhaustion_config.mode,
            "momentum_exhaustion_max_score": momentum_exhaustion_config.max_score,
            "momentum_exhaustion_threshold_method": (
                momentum_exhaustion_config.threshold_method
            ),
            "industry_filter_mode": industry_filter_config.mode,
            "max_buy_per_industry_per_day": (
                industry_filter_config.max_buy_per_industry_per_day
            ),
            "max_total_positions_per_industry": (
                industry_filter_config.max_total_positions_per_industry
            ),
            "industry_reference_file": industry_filter_config.reference_file,
            "allow_held_position_buys": bool(
                getattr(args, "allow_held_position_buys", False)
            ),
        }
    )

    return StrategyEvaluator(
        data_root="data",
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        replay_seed=replay_seed,
        verbose=args.verbose,
        exit_confirmation_days=exit_confirm_days,
        buy_fill_mode=getattr(args, "buy_fill_mode", "next_open"),
        entry_reference_mode=getattr(args, "entry_reference_mode", "raw_fill"),
        fill_buffer_enabled=getattr(args, "fill_buffer_enabled", False),
        fill_buffer_pct=getattr(args, "fill_buffer_pct", 0.02),
        capacity_regime_mode_override=getattr(args, "capacity_regime_mode", None),
        overlay_config=overlay_config,
        entry_filter_config=config.get("evaluation", {}).get("filters", {}).get(
            "default", {}
        ),
        entry_filter_variants=entry_filter_variants,
        portfolio_overrides=portfolio_overrides,
        ranking_strategies=ranking_strategies,
        momentum_exhaustion_config=momentum_exhaustion_config,
        industry_filter_config=industry_filter_config,
        allow_held_position_buys=bool(
            getattr(args, "allow_held_position_buys", False)
        ),
        run_metadata=effective_run_metadata,
    )


def _print_saved_files(files: Dict[str, str], indent: str = "  ") -> None:
    print(f"{indent}📄 原始结果: {files['raw']}")
    print(f"{indent}📊 市场环境分析: {files['regime']}")
    if files.get("parameters"):
        print(f"{indent}🧭 参数快照: {files['parameters']}")
    if files.get("trades"):
        print(f"{indent}🧾 原始交易明细: {files['trades']}")
    if files.get("trades_indicators"):
        print(f"{indent}🧪 交易指标快照: {files['trades_indicators']}")
    if files.get("exit_trigger_summary"):
        print(f"{indent}🚪 第一层退出原因明细: {files['exit_trigger_summary']}")
    if files.get("exit_urgency_summary"):
        print(f"{indent}📚 第二层退出类型汇总: {files['exit_urgency_summary']}")
    if files.get("exit_urgency_contribution"):
        print(f"{indent}📈 第三层退出贡献汇总: {files['exit_urgency_contribution']}")
    if files.get("exit_summary_report"):
        print(f"{indent}🧠 退出结果总结报告: {files['exit_summary_report']}")
    if files.get("legacy_rank"):
        print(f"{indent}🏁 Legacy排名: {files['legacy_rank']}")
    if files.get("target20_rank"):
        print(f"{indent}🎯 Target20排名: {files['target20_rank']}")
    if files.get("risk60_profit40_rank"):
        print(f"{indent}⚖️ Risk60/Profit40排名: {files['risk60_profit40_rank']}")
    if files.get("prs_train_rank"):
        print(f"{indent}🛡️ PRS-Train排名: {files['prs_train_rank']}")
    print(f"{indent}📝 综合报告: {files['report']}")


def _print_companion_files(files: Optional[Dict[str, str]], indent: str = "  ") -> None:
    if not files:
        return

    if files.get("continuous_stability_rank"):
        print(
            f"{indent}🏆 Continuous+Stability排名: {files['continuous_stability_rank']}"
        )


def _markdown_table(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _annual_rank_group_columns(segmented_df: pd.DataFrame, continuous_df: pd.DataFrame) -> List[str]:
    candidate_columns = [
        "entry_strategy",
        "exit_strategy",
        "entry_filter",
        "exit_confirmation_days",
        "buy_fill_mode",
        "entry_reference_mode",
        "fill_buffer_enabled",
        "fill_buffer_pct",
        "position_profile",
        "overlay_mode",
        "universe_name",
        "universe_file",
        "max_positions",
        "max_position_pct",
        "starting_capital_jpy",
    ]
    return [
        column
        for column in candidate_columns
        if column in segmented_df.columns or column in continuous_df.columns
    ]


def _annual_std(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if len(numeric) <= 1:
        return 0.0
    return float(numeric.std(ddof=0))


def _build_annual_continuous_stability_rank_df(
    segmented_df: pd.DataFrame,
    continuous_df: pd.DataFrame,
) -> pd.DataFrame:
    group_columns = _annual_rank_group_columns(segmented_df, continuous_df)
    if not {"entry_strategy", "exit_strategy", "entry_filter"}.issubset(group_columns):
        raise ValueError("annual stability ranking 缺少必要策略列")

    annual_stats = (
        segmented_df.groupby(group_columns, as_index=False)
        .agg(
            avg_yearly_return_pct=("return_pct", "mean"),
            avg_yearly_alpha_pct=("alpha", "mean"),
            avg_yearly_sharpe_ratio=("sharpe_ratio", "mean"),
            avg_yearly_mdd_pct=("max_drawdown_pct", "mean"),
            total_yearly_trades=("num_trades", "sum"),
            positive_years=(
                "return_pct",
                lambda series: int((pd.to_numeric(series, errors="coerce") > 0).sum()),
            ),
            positive_alpha_years=(
                "alpha",
                lambda series: int((pd.to_numeric(series, errors="coerce") > 0).sum()),
            ),
            worst_year_return_pct=("return_pct", "min"),
            annual_return_std_pct=("return_pct", _annual_std),
        )
    )

    yearly_return_pivot = (
        segmented_df.pivot_table(
            index=group_columns,
            columns="period",
            values="return_pct",
            aggfunc="first",
        )
        .reset_index()
    )
    yearly_return_pivot.columns = [
        column if column in group_columns else f"year_return_{column}"
        for column in yearly_return_pivot.columns
    ]

    continuous_stats = (
        continuous_df.groupby(group_columns, as_index=False)
        .agg(
            continuous_period=("period", "first"),
            continuous_start_date=("start_date", "first"),
            continuous_end_date=("end_date", "first"),
            continuous_return_pct=("return_pct", "mean"),
            continuous_topix_return_pct=("topix_return_pct", "mean"),
            continuous_alpha_pct=("alpha", "mean"),
            continuous_sharpe_ratio=("sharpe_ratio", "mean"),
            continuous_mdd_pct=("max_drawdown_pct", "mean"),
            continuous_num_trades=("num_trades", "sum"),
            continuous_win_rate_pct=("win_rate_pct", "mean"),
        )
    )

    rank_df = annual_stats.merge(yearly_return_pivot, on=group_columns, how="left")
    rank_df = rank_df.merge(continuous_stats, on=group_columns, how="left")
    rank_df = rank_df.sort_values(
        [
            "continuous_return_pct",
            "continuous_alpha_pct",
            "positive_years",
            "positive_alpha_years",
            "avg_yearly_alpha_pct",
            "annual_return_std_pct",
            "worst_year_return_pct",
            "avg_yearly_mdd_pct",
            "continuous_mdd_pct",
            "continuous_sharpe_ratio",
        ],
        ascending=[False, False, False, False, False, True, False, True, True, False],
        kind="mergesort",
    ).reset_index(drop=True)
    rank_df.insert(0, "continuous_stability_rank", range(1, len(rank_df) + 1))
    return rank_df


def _write_annual_continuous_stability_rank(
    output_dir: str,
    prefix: str,
    segmented_raw_path: Optional[str],
    continuous_raw_path: Optional[str],
) -> Optional[Dict[str, str]]:
    if not segmented_raw_path or not continuous_raw_path:
        return None

    try:
        segmented_df = pd.read_csv(segmented_raw_path)
        continuous_df = pd.read_csv(continuous_raw_path)
        rank_df = _build_annual_continuous_stability_rank_df(
            segmented_df=segmented_df,
            continuous_df=continuous_df,
        )
    except Exception as e:
        print(f"⚠️ Continuous+Stability排名生成失败 ({prefix}): {e}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(output_dir)
    rank_path = output_root / f"{prefix}_continuous_stability_rank_{timestamp}.csv"
    rank_df.to_csv(rank_path, index=False, encoding="utf-8-sig")
    print(f"✅ Continuous+Stability排名已保存: {rank_path}")

    top_columns = [
        column
        for column in [
            "continuous_stability_rank",
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "position_profile",
            "overlay_mode",
            "universe_name",
            "continuous_return_pct",
            "continuous_alpha_pct",
            "positive_years",
            "positive_alpha_years",
            "avg_yearly_alpha_pct",
            "annual_return_std_pct",
            "worst_year_return_pct",
            "avg_yearly_mdd_pct",
            "continuous_mdd_pct",
        ]
        if column in rank_df.columns
    ]
    report_path = output_root / f"{prefix}_continuous_stability_top10_{timestamp}.md"
    report_lines = [
        "# Annual Continuous + Stability Top 10",
        "",
        f"- segmented raw: {segmented_raw_path}",
        f"- continuous raw: {continuous_raw_path}",
        "",
        _markdown_table(rank_df[top_columns].head(10).round(4)),
        "",
    ]
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    print(f"✅ Continuous+Stability Top10已保存: {report_path}")

    return {
        "continuous_stability_rank": str(rank_path),
        "continuous_stability_report": str(report_path),
    }


def _segmented_mode_label(mode: str) -> str:
    if mode == "annual":
        return "年度"
    if mode == "quarterly":
        return "季度"
    return "周期"


def _normalize_result_ticker(value: object) -> str:
    if value is None or pd.isna(value):
        return ""

    text = str(value).strip()
    if text.endswith(".T"):
        text = text[:-2]
    if text.endswith(".0"):
        text = text[:-2]

    digits = "".join(ch for ch in text if ch.isdigit())
    return digits.zfill(4) if digits else text


def _normalize_sector_name(value: object) -> str:
    sector = str(value or "").strip()
    if not sector or sector == "-":
        return "未分类"
    return sector


def _load_sector_by_ticker() -> Dict[str, str]:
    jpx_master_path = Path(__file__).resolve().parents[2] / "data" / "jpx_final_list.csv"
    if not jpx_master_path.exists():
        return {}

    try:
        df = pd.read_csv(jpx_master_path, dtype=str, encoding="utf-8-sig")
    except Exception:
        try:
            df = pd.read_csv(jpx_master_path, dtype=str)
        except Exception:
            return {}

    sector_col = next(
        (column for column in df.columns if "33" in str(column) and "業種" in str(column)),
        None,
    )
    if sector_col is None or "Code" not in df.columns:
        return {}

    sector_by_ticker: Dict[str, str] = {}
    for _, row in df.iterrows():
        code = _normalize_result_ticker(row.get("Code"))
        if not code:
            continue
        sector_by_ticker[code] = _normalize_sector_name(row.get(sector_col))
    return sector_by_ticker


def _coerce_float(value: object) -> Optional[float]:
    try:
        numeric = pd.to_numeric(value, errors="coerce")
    except Exception:
        return None
    if pd.isna(numeric):
        return None
    return float(numeric)


def _format_count(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "-"
    return f"{int(round(numeric)):,}"


def _format_jpy(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:,.0f}"


def _format_pct(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:.2f}%"


def _format_ratio(value: object) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "-"
    return f"{numeric * 100:.1f}%"


def _format_number(value: object, digits: int = 2) -> str:
    numeric = _coerce_float(value)
    if numeric is None:
        return "-"
    return f"{numeric:.{digits}f}"


def _markdown_table_from_rows(
    rows: List[Dict[str, str]],
    columns: List[str],
    empty_text: str = "无数据。",
) -> str:
    if not rows:
        return empty_text
    return _markdown_table(pd.DataFrame(rows, columns=columns))


def _prepare_review_frames(
    raw_path: Optional[str],
    trades_path: Optional[str],
    sector_by_ticker: Dict[str, str],
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    raw_df = pd.read_csv(raw_path) if raw_path else pd.DataFrame()
    trades_df = pd.read_csv(trades_path) if trades_path else pd.DataFrame()

    if not raw_df.empty:
        if "entry_filter" in raw_df.columns:
            raw_df["entry_filter"] = raw_df["entry_filter"].fillna("off")
        if "buy_fill_mode" in raw_df.columns:
            raw_df["buy_fill_mode"] = raw_df["buy_fill_mode"].fillna("next_open")
        else:
            raw_df["buy_fill_mode"] = "next_open"
        if "entry_reference_mode" in raw_df.columns:
            raw_df["entry_reference_mode"] = raw_df["entry_reference_mode"].fillna("raw_fill")
        else:
            raw_df["entry_reference_mode"] = "raw_fill"
        if "fill_buffer_enabled" in raw_df.columns:
            raw_df["fill_buffer_enabled"] = raw_df["fill_buffer_enabled"].fillna(False).astype(bool)
        else:
            raw_df["fill_buffer_enabled"] = False
        if "fill_buffer_pct" in raw_df.columns:
            raw_df["fill_buffer_pct"] = pd.to_numeric(
                raw_df["fill_buffer_pct"], errors="coerce"
            ).fillna(0.0)
        else:
            raw_df["fill_buffer_pct"] = 0.0
        if "exit_confirmation_days" in raw_df.columns:
            raw_df["exit_confirmation_days"] = (
                pd.to_numeric(raw_df["exit_confirmation_days"], errors="coerce")
                .fillna(0)
                .astype(int)
            )

    if not trades_df.empty:
        if "entry_filter" in trades_df.columns:
            trades_df["entry_filter"] = trades_df["entry_filter"].fillna("off")
        if "buy_fill_mode" in trades_df.columns:
            trades_df["buy_fill_mode"] = trades_df["buy_fill_mode"].fillna("next_open")
        else:
            trades_df["buy_fill_mode"] = "next_open"
        if "entry_reference_mode" in trades_df.columns:
            trades_df["entry_reference_mode"] = trades_df["entry_reference_mode"].fillna("raw_fill")
        else:
            trades_df["entry_reference_mode"] = "raw_fill"
        if "fill_buffer_enabled" in trades_df.columns:
            trades_df["fill_buffer_enabled"] = trades_df["fill_buffer_enabled"].fillna(False).astype(bool)
        else:
            trades_df["fill_buffer_enabled"] = False
        if "fill_buffer_pct" in trades_df.columns:
            trades_df["fill_buffer_pct"] = pd.to_numeric(
                trades_df["fill_buffer_pct"], errors="coerce"
            ).fillna(0.0)
        else:
            trades_df["fill_buffer_pct"] = 0.0
        if "exit_confirmation_days" in trades_df.columns:
            trades_df["exit_confirmation_days"] = (
                pd.to_numeric(trades_df["exit_confirmation_days"], errors="coerce")
                .fillna(0)
                .astype(int)
            )
        if "exit_urgency" in trades_df.columns:
            trades_df["exit_urgency"] = trades_df["exit_urgency"].fillna("未定义")
        if "ticker" in trades_df.columns:
            trades_df["ticker_key"] = trades_df["ticker"].map(_normalize_result_ticker)
            trades_df["sector_name"] = (
                trades_df["ticker_key"].map(sector_by_ticker).fillna("未分类")
            )
        else:
            trades_df["sector_name"] = "未分类"

    return raw_df, trades_df


def _review_combo_columns(segmented_raw_df: pd.DataFrame, continuous_raw_df: pd.DataFrame) -> List[str]:
    candidate_columns = [
        "entry_strategy",
        "exit_strategy",
        "entry_filter",
        "exit_confirmation_days",
        "buy_fill_mode",
        "entry_reference_mode",
        "fill_buffer_enabled",
        "fill_buffer_pct",
    ]
    return [
        column
        for column in candidate_columns
        if column in segmented_raw_df.columns or column in continuous_raw_df.columns
    ]


def _build_combo_mask(
    df: pd.DataFrame,
    combo_row: pd.Series,
    combo_columns: List[str],
) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series([True] * len(df), index=df.index)
    for column in combo_columns:
        if column not in df.columns:
            continue
        mask &= df[column].astype(str) == str(combo_row.get(column, ""))
    return mask


def _review_period_order(raw_df: pd.DataFrame) -> List[str]:
    if raw_df.empty or "period" not in raw_df.columns:
        return []

    ordering_df = raw_df[["period"]].copy()
    ordering_df["period"] = ordering_df["period"].astype(str)

    if "start_date" in raw_df.columns:
        ordering_df["start_date"] = pd.to_datetime(raw_df["start_date"], errors="coerce")
        ordering_df = ordering_df.sort_values(["start_date", "period"], kind="mergesort")
    else:
        ordering_df = ordering_df.sort_values(["period"], kind="mergesort")

    return _dedupe_preserve_order(ordering_df["period"].tolist())


def _review_combo_column_label(column: str) -> str:
    labels = {
        "entry_strategy": "入场策略",
        "exit_strategy": "出场策略",
        "entry_filter": "入场过滤器",
        "exit_confirmation_days": "出场确认天数",
        "buy_fill_mode": "买入成交模式",
        "entry_reference_mode": "入场参考价模式",
        "fill_buffer_enabled": "成交价缓冲",
        "fill_buffer_pct": "缓冲比例",
    }
    return labels.get(column, column)


def _format_review_combo_value(column: str, value: object) -> str:
    if column == "exit_confirmation_days":
        return _format_count(value)

    if column == "fill_buffer_enabled":
        return "on" if bool(value) else "off"

    if column == "fill_buffer_pct":
        numeric = _coerce_float(value)
        if numeric is None:
            return "-"
        return f"{numeric:.2%}"

    if value is None or pd.isna(value):
        return "-"

    text = str(value).strip()
    if not text:
        return "off" if column == "entry_filter" else "-"
    return text


def _build_review_metric_matrix_rows(
    segmented_raw_df: pd.DataFrame,
    combo_df: pd.DataFrame,
    combo_columns: List[str],
    metric_column: str,
    average_label: str,
) -> Tuple[List[Dict[str, str]], List[str]]:
    display_combo_columns = [_review_combo_column_label(column) for column in combo_columns]

    if segmented_raw_df.empty or not combo_columns or metric_column not in segmented_raw_df.columns:
        return [], [*display_combo_columns, average_label]

    period_order = _review_period_order(segmented_raw_df)
    if not period_order:
        return [], [*display_combo_columns, average_label]

    metric_df = segmented_raw_df[combo_columns + ["period", metric_column]].copy()
    metric_df["period"] = metric_df["period"].astype(str)
    metric_df[metric_column] = pd.to_numeric(metric_df[metric_column], errors="coerce")

    metric_pivot = (
        metric_df.pivot_table(
            index=combo_columns,
            columns="period",
            values=metric_column,
            aggfunc="first",
        )
        .reset_index()
    )

    base_combo_df = combo_df[combo_columns].drop_duplicates().copy()
    merged_df = base_combo_df.merge(metric_pivot, on=combo_columns, how="left")

    for period in period_order:
        if period not in merged_df.columns:
            merged_df[period] = pd.NA

    merged_df[average_label] = (
        merged_df[period_order].apply(pd.to_numeric, errors="coerce").mean(axis=1)
    )

    rows: List[Dict[str, str]] = []
    for _, row in merged_df.iterrows():
        display_row: Dict[str, str] = {}
        for column in combo_columns:
            display_row[_review_combo_column_label(column)] = _format_review_combo_value(
                column,
                row.get(column),
            )
        for period in period_order:
            display_row[period] = _format_pct(row.get(period))
        display_row[average_label] = _format_pct(row.get(average_label))
        rows.append(display_row)

    return rows, [*display_combo_columns, *period_order, average_label]


def _summarize_trade_slice(trades_subset: pd.DataFrame) -> Dict[str, float]:
    if trades_subset.empty or "return_jpy" not in trades_subset.columns:
        return {
            "exit_actions": 0.0,
            "net_return_jpy": 0.0,
            "gross_profit_jpy": 0.0,
            "gross_loss_jpy": 0.0,
        }

    gross_profit = float(trades_subset.loc[trades_subset["return_jpy"] > 0, "return_jpy"].sum())
    gross_loss = float(trades_subset.loc[trades_subset["return_jpy"] < 0, "return_jpy"].sum())
    return {
        "exit_actions": float(len(trades_subset)),
        "net_return_jpy": float(trades_subset["return_jpy"].sum()),
        "gross_profit_jpy": gross_profit,
        "gross_loss_jpy": gross_loss,
    }


def _resolve_market_regime_label(topix_return_pct: object) -> str:
    numeric = _coerce_float(topix_return_pct)
    if numeric is None:
        return "-"
    return str(MarketRegime.classify(numeric))


def _build_exit_breakdown_rows(trades_subset: pd.DataFrame) -> List[Dict[str, str]]:
    if trades_subset.empty or "exit_urgency" not in trades_subset.columns:
        return []

    total_actions = len(trades_subset)
    total_net_return = float(trades_subset["return_jpy"].sum())

    grouped = (
        trades_subset.groupby("exit_urgency", dropna=False)
        .agg(
            action_count=("return_jpy", "size"),
            net_return_jpy=("return_jpy", "sum"),
        )
        .reset_index()
    )

    profit_map = (
        trades_subset.assign(gross_profit_jpy=trades_subset["return_jpy"].clip(lower=0))
        .groupby("exit_urgency")["gross_profit_jpy"]
        .sum()
    )
    loss_map = (
        trades_subset.assign(gross_loss_jpy=trades_subset["return_jpy"].clip(upper=0))
        .groupby("exit_urgency")["gross_loss_jpy"]
        .sum()
    )

    grouped["gross_profit_jpy"] = grouped["exit_urgency"].map(profit_map).fillna(0.0)
    grouped["gross_loss_jpy"] = grouped["exit_urgency"].map(loss_map).fillna(0.0)
    grouped["action_ratio"] = grouped["action_count"] / total_actions if total_actions else 0.0
    grouped["net_return_share"] = (
        grouped["net_return_jpy"] / total_net_return if total_net_return else 0.0
    )
    grouped = grouped.sort_values(
        ["action_count", "net_return_jpy"],
        ascending=[False, False],
        kind="mergesort",
    )

    rows: List[Dict[str, str]] = []
    for _, row in grouped.iterrows():
        rows.append(
            {
                "退场条件": str(row["exit_urgency"]),
                "数量": _format_count(row["action_count"]),
                "数量占比": _format_ratio(row["action_ratio"]),
                "净收益(JPY)": _format_jpy(row["net_return_jpy"]),
                "净收益占比": _format_ratio(row["net_return_share"]),
                "总盈利(JPY)": _format_jpy(row["gross_profit_jpy"]),
                "总亏损(JPY)": _format_jpy(row["gross_loss_jpy"]),
            }
        )
    return rows


def _build_industry_breakdown_rows(trades_subset: pd.DataFrame) -> List[Dict[str, str]]:
    if trades_subset.empty or "sector_name" not in trades_subset.columns:
        return []

    total_actions = len(trades_subset)
    total_net_return = float(trades_subset["return_jpy"].sum())

    grouped = (
        trades_subset.groupby("sector_name", dropna=False)
        .agg(
            action_count=("return_jpy", "size"),
            net_return_jpy=("return_jpy", "sum"),
        )
        .reset_index()
    )

    profit_map = (
        trades_subset.assign(gross_profit_jpy=trades_subset["return_jpy"].clip(lower=0))
        .groupby("sector_name")["gross_profit_jpy"]
        .sum()
    )
    loss_map = (
        trades_subset.assign(gross_loss_jpy=trades_subset["return_jpy"].clip(upper=0))
        .groupby("sector_name")["gross_loss_jpy"]
        .sum()
    )

    grouped["gross_profit_jpy"] = grouped["sector_name"].map(profit_map).fillna(0.0)
    grouped["gross_loss_jpy"] = grouped["sector_name"].map(loss_map).fillna(0.0)
    grouped["action_ratio"] = grouped["action_count"] / total_actions if total_actions else 0.0
    grouped["net_return_share"] = (
        grouped["net_return_jpy"] / total_net_return if total_net_return else 0.0
    )
    grouped = grouped.sort_values(
        ["action_count", "net_return_jpy"],
        ascending=[False, False],
        kind="mergesort",
    )

    rows: List[Dict[str, str]] = []
    for _, row in grouped.iterrows():
        rows.append(
            {
                "33业种": str(row["sector_name"]),
                "数量": _format_count(row["action_count"]),
                "数量占比": _format_ratio(row["action_ratio"]),
                "净收益(JPY)": _format_jpy(row["net_return_jpy"]),
                "净收益占比": _format_ratio(row["net_return_share"]),
                "总盈利(JPY)": _format_jpy(row["gross_profit_jpy"]),
                "总亏损(JPY)": _format_jpy(row["gross_loss_jpy"]),
            }
        )
    return rows


def _build_period_overview_rows(
    raw_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    first_column_label: str,
) -> List[Dict[str, str]]:
    if raw_df.empty:
        return []

    rows: List[Dict[str, str]] = []
    ordered_df = raw_df.sort_values(["start_date", "end_date", "period"], kind="mergesort")
    for _, raw_row in ordered_df.iterrows():
        period_label = str(raw_row.get("period", ""))
        trades_subset = (
            trades_df.loc[trades_df["period"].astype(str) == period_label].copy()
            if "period" in trades_df.columns
            else pd.DataFrame()
        )
        stats = _summarize_trade_slice(trades_subset)
        rows.append(
            {
                first_column_label: period_label,
                "市场环境": _resolve_market_regime_label(raw_row.get("topix_return_pct")),
                "净收益(JPY)": _format_jpy(stats["net_return_jpy"]),
                "收益率": _format_pct(raw_row.get("return_pct")),
                "超额收益Alpha": _format_pct(raw_row.get("alpha")),
                "夏普比率": _format_number(raw_row.get("sharpe_ratio")),
                "最大回撤": _format_pct(raw_row.get("max_drawdown_pct")),
                "交易数": _format_count(raw_row.get("num_trades")),
                "退出动作数": _format_count(stats["exit_actions"]),
                "胜率": _format_pct(raw_row.get("win_rate_pct")),
                "总盈利(JPY)": _format_jpy(stats["gross_profit_jpy"]),
                "总亏损(JPY)": _format_jpy(stats["gross_loss_jpy"]),
            }
        )
    return rows


def _append_period_detail_sections(
    lines: List[str],
    raw_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    section_label: str,
) -> None:
    if raw_df.empty:
        return

    ordered_df = raw_df.sort_values(["start_date", "end_date", "period"], kind="mergesort")
    for _, raw_row in ordered_df.iterrows():
        period_label = str(raw_row.get("period", ""))
        trades_subset = (
            trades_df.loc[trades_df["period"].astype(str) == period_label].copy()
            if "period" in trades_df.columns
            else pd.DataFrame()
        )
        stats = _summarize_trade_slice(trades_subset)

        snapshot_rows = [
            {
                "开始日期": str(raw_row.get("start_date", "-")),
                "结束日期": str(raw_row.get("end_date", "-")),
                "市场环境": _resolve_market_regime_label(raw_row.get("topix_return_pct")),
                "净收益(JPY)": _format_jpy(stats["net_return_jpy"]),
                "收益率": _format_pct(raw_row.get("return_pct")),
                "超额收益Alpha": _format_pct(raw_row.get("alpha")),
                "夏普比率": _format_number(raw_row.get("sharpe_ratio")),
                "最大回撤": _format_pct(raw_row.get("max_drawdown_pct")),
                "交易数": _format_count(raw_row.get("num_trades")),
                "退出动作数": _format_count(stats["exit_actions"]),
                "胜率": _format_pct(raw_row.get("win_rate_pct")),
                "平均盈利": _format_pct(raw_row.get("avg_gain_pct")),
                "平均亏损": _format_pct(raw_row.get("avg_loss_pct")),
            }
        ]

        lines.extend(
            [
                f"### {section_label}明细：{period_label}",
                "",
                "#### 表现快照",
                "",
                _markdown_table_from_rows(
                    snapshot_rows,
                    [
                        "开始日期",
                        "结束日期",
                        "市场环境",
                        "净收益(JPY)",
                        "收益率",
                        "超额收益Alpha",
                        "夏普比率",
                        "最大回撤",
                        "交易数",
                        "退出动作数",
                        "胜率",
                        "平均盈利",
                        "平均亏损",
                    ],
                ),
                "",
                "#### 退场条件分布",
                "",
                _markdown_table_from_rows(
                    _build_exit_breakdown_rows(trades_subset),
                    [
                        "退场条件",
                        "数量",
                        "数量占比",
                        "净收益(JPY)",
                        "净收益占比",
                        "总盈利(JPY)",
                        "总亏损(JPY)",
                    ],
                ),
                "",
                "#### 33业种分布",
                "",
                _markdown_table_from_rows(
                    _build_industry_breakdown_rows(trades_subset),
                    [
                        "33业种",
                        "数量",
                        "数量占比",
                        "净收益(JPY)",
                        "净收益占比",
                        "总盈利(JPY)",
                        "总亏损(JPY)",
                    ],
                ),
                "",
            ]
        )


def _write_localized_final_review_report(
    args,
    output_dir: str,
    prefix: str,
    bundle: EvaluationOutputBundle,
) -> Optional[str]:
    mode = getattr(args, "mode", None)
    if mode not in {"annual", "quarterly"}:
        return None

    sector_by_ticker = _load_sector_by_ticker()
    segmented_raw_df, segmented_trades_df = _prepare_review_frames(
        bundle.segmented.get("raw"),
        bundle.segmented.get("trades"),
        sector_by_ticker,
    )
    if segmented_raw_df.empty:
        return None

    continuous_raw_df, continuous_trades_df = _prepare_review_frames(
        bundle.continuous.get("raw") if bundle.continuous else None,
        bundle.continuous.get("trades") if bundle.continuous else None,
        sector_by_ticker,
    )

    combo_columns = _review_combo_columns(segmented_raw_df, continuous_raw_df)
    combo_frames = []
    if combo_columns:
        if not segmented_raw_df.empty:
            combo_frames.append(segmented_raw_df[combo_columns].copy())
        if not continuous_raw_df.empty:
            combo_frames.append(continuous_raw_df[combo_columns].copy())
    if not combo_frames:
        return None

    combo_df = pd.concat(combo_frames, ignore_index=True).drop_duplicates().reset_index(drop=True)
    segmented_label = _segmented_mode_label(mode)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = Path(output_dir) / f"{prefix}_{mode}_final_review_{timestamp}.md"

    lines = [
        f"# {segmented_label}策略评估整合最终报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"分段模式：{segmented_label}",
        f"输出目录：{output_dir}",
        f"分段参数快照：{Path(bundle.segmented.get('parameters', '')).name if bundle.segmented.get('parameters') else '-'}",
        f"分段原始结果：{Path(bundle.segmented.get('raw', '')).name if bundle.segmented.get('raw') else '-'}",
        f"分段交易明细：{Path(bundle.segmented.get('trades', '')).name if bundle.segmented.get('trades') else '-'}",
        f"连续参数快照：{Path(bundle.continuous.get('parameters', '')).name if bundle.continuous and bundle.continuous.get('parameters') else '-'}",
        f"连续原始结果：{Path(bundle.continuous.get('raw', '')).name if bundle.continuous and bundle.continuous.get('raw') else '-'}",
        f"连续交易明细：{Path(bundle.continuous.get('trades', '')).name if bundle.continuous and bundle.continuous.get('trades') else '-'}",
        "",
        "## 说明",
        "",
        f"- 本报告按策略组合汇总；分段部分按{segmented_label}展开。",
        "- 收益率、超额收益Alpha、夏普比率、最大回撤、交易数、胜率来自原始结果汇总文件。",
        "- 净收益、总盈利、总亏损，以及退场条件/33业种分布来自交易明细文件。",
        "- 数量统计按退出动作行计数，部分止盈或减仓会单独计数。",
        "- 净收益占比按该周期净收益合计计算；负值表示该项在拖累整体净收益。",
        "- 33业种映射来自 data/jpx_final_list.csv，无法映射的代码记为“未分类”。",
        "",
    ]

    if mode == "annual":
        return_rows, return_columns = _build_review_metric_matrix_rows(
            segmented_raw_df=segmented_raw_df,
            combo_df=combo_df,
            combo_columns=combo_columns,
            metric_column="return_pct",
            average_label="全期间平均收益率",
        )
        win_rate_rows, win_rate_columns = _build_review_metric_matrix_rows(
            segmented_raw_df=segmented_raw_df,
            combo_df=combo_df,
            combo_columns=combo_columns,
            metric_column="win_rate_pct",
            average_label="全期间平均胜率",
        )
        max_drawdown_rows, max_drawdown_columns = _build_review_metric_matrix_rows(
            segmented_raw_df=segmented_raw_df,
            combo_df=combo_df,
            combo_columns=combo_columns,
            metric_column="max_drawdown_pct",
            average_label="全期间平均最大回撤",
        )
        lines.extend(
            [
                "## 全策略组合年度总览",
                "",
                "### 全策略组合 × 年度收益率",
                "",
                _markdown_table_from_rows(return_rows, return_columns),
                "",
                "### 全策略组合 × 年度胜率",
                "",
                _markdown_table_from_rows(win_rate_rows, win_rate_columns),
                "",
                "### 全策略组合 × 年度最大回撤",
                "",
                _markdown_table_from_rows(max_drawdown_rows, max_drawdown_columns),
                "",
            ]
        )

    for index, combo_row in combo_df.iterrows():
        segmented_combo_raw = segmented_raw_df.loc[
            _build_combo_mask(segmented_raw_df, combo_row, combo_columns)
        ].copy()
        segmented_combo_trades = segmented_trades_df.loc[
            _build_combo_mask(segmented_trades_df, combo_row, combo_columns)
        ].copy()
        continuous_combo_raw = continuous_raw_df.loc[
            _build_combo_mask(continuous_raw_df, combo_row, combo_columns)
        ].copy()
        continuous_combo_trades = continuous_trades_df.loc[
            _build_combo_mask(continuous_trades_df, combo_row, combo_columns)
        ].copy()

        lines.extend(
            [
                f"## 策略组合 {index + 1}",
                "",
                f"- 入场策略：{combo_row.get('entry_strategy', '-')}",
                f"- 出场策略：{combo_row.get('exit_strategy', '-')}",
                f"- 入场过滤器：{combo_row.get('entry_filter', 'off')}",
                f"- 出场确认天数：{_format_count(combo_row.get('exit_confirmation_days', 0))}",
                f"- 买入成交模式：{combo_row.get('buy_fill_mode', 'next_open')}",
                f"- 入场参考价模式：{combo_row.get('entry_reference_mode', 'raw_fill')}",
                f"- 成交价缓冲：{'on' if bool(combo_row.get('fill_buffer_enabled', False)) else 'off'}",
                f"- 缓冲比例：{_format_review_combo_value('fill_buffer_pct', combo_row.get('fill_buffer_pct', 0.0))}",
                "",
                f"### {segmented_label}总览",
                "",
                _markdown_table_from_rows(
                    _build_period_overview_rows(segmented_combo_raw, segmented_combo_trades, segmented_label),
                    [
                        segmented_label,
                        "市场环境",
                        "净收益(JPY)",
                        "收益率",
                        "超额收益Alpha",
                        "夏普比率",
                        "最大回撤",
                        "交易数",
                        "退出动作数",
                        "胜率",
                        "总盈利(JPY)",
                        "总亏损(JPY)",
                    ],
                ),
                "",
            ]
        )
        _append_period_detail_sections(lines, segmented_combo_raw, segmented_combo_trades, segmented_label)

        if not continuous_combo_raw.empty:
            lines.extend(
                [
                    "### 连续区间总览",
                    "",
                    _markdown_table_from_rows(
                        _build_period_overview_rows(
                            continuous_combo_raw,
                            continuous_combo_trades,
                            "连续区间",
                        ),
                        [
                            "连续区间",
                            "市场环境",
                            "净收益(JPY)",
                            "收益率",
                            "净收益占比",
                            "超额收益Alpha",
                            "最大回撤",
                            "退出动作数",
                            "胜率",
                            "总盈利(JPY)",
                            "总亏损(JPY)",
                        ],
                    ),
                    "",
                ]
            )
            _append_period_detail_sections(lines, continuous_combo_raw, continuous_combo_trades, "连续区间")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ 中文整合最终报告已保存: {report_path}")
    return str(report_path)


def _append_combined_context_frame(
    file_path: Optional[str],
    meta: Dict[str, Any],
    collector: List[pd.DataFrame],
    label: str,
):
    if not file_path:
        return

    try:
        frame = pd.read_csv(file_path)
        for key, value in meta.items():
            frame[key] = value
        collector.append(frame)
    except Exception as e:
        print(
            f"⚠️ 合并{label}失败 ("
            f"{meta.get('overlay_mode', 'n/a')}/"
            f"{meta.get('universe_name', 'n/a')}): {e}"
        )


def _write_combined_position_output_family(
    output_dir: str,
    data_root: str,
    family_prefix: str,
    raw_frames: List[pd.DataFrame],
    regime_frames: List[pd.DataFrame],
    trade_frames: List[pd.DataFrame],
):
    files: Dict[str, str] = {}
    if not raw_frames and not regime_frames and not trade_frames:
        return files

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path(output_dir)

    if raw_frames:
        combined_raw = pd.concat(raw_frames, ignore_index=True)
        combined_raw_path = output_root / f"{family_prefix}_raw_{ts}.csv"
        combined_raw.to_csv(combined_raw_path, index=False, encoding="utf-8-sig")
        print(f"\n📦 合并Raw结果: {combined_raw_path}")
        files["raw"] = str(combined_raw_path)

    if regime_frames:
        combined_regime = pd.concat(regime_frames, ignore_index=True)
        combined_regime_path = output_root / f"{family_prefix}_by_regime_{ts}.csv"
        combined_regime.to_csv(combined_regime_path, index=False, encoding="utf-8-sig")
        print(f"📦 合并Regime结果: {combined_regime_path}")
        files["regime"] = str(combined_regime_path)

    if trade_frames:
        combined_trades = pd.concat(trade_frames, ignore_index=True)
        combined_trades_path = output_root / f"{family_prefix}_trades_{ts}.csv"
        combined_trades.to_csv(combined_trades_path, index=False, encoding="utf-8-sig")
        print(f"📦 合并Trade结果: {combined_trades_path}")
        files["trades"] = str(combined_trades_path)

        try:
            indicator_file = write_enriched_trades_sidecar(
                trades_csv=combined_trades_path,
                data_root=data_root,
                trades_df=combined_trades,
            )
        except Exception as e:
            print(f"⚠️ 合并Trade指标 sidecar 生成失败: {e}")
        else:
            print(f"📦 合并Trade指标快照: {indicator_file}")
            files["trades_indicators"] = str(indicator_file)

        combined_reason_detail = StrategyEvaluator.build_exit_reason_detail_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_trigger_summary_path = output_root / f"{family_prefix}_exit_trigger_summary_{ts}.csv"
        combined_reason_detail.to_csv(
            combined_trigger_summary_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第一层退出原因明细: {combined_trigger_summary_path}")
        files["exit_trigger_summary"] = str(combined_trigger_summary_path)

        combined_urgency_summary = StrategyEvaluator.build_exit_urgency_summary_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_urgency_summary_path = output_root / f"{family_prefix}_exit_urgency_summary_{ts}.csv"
        combined_urgency_summary.to_csv(
            combined_urgency_summary_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第二层退出类型汇总: {combined_urgency_summary_path}")
        files["exit_urgency_summary"] = str(combined_urgency_summary_path)

        combined_urgency_contribution = StrategyEvaluator.build_exit_urgency_contribution_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_urgency_contribution_path = output_root / f"{family_prefix}_exit_urgency_contribution_{ts}.csv"
        combined_urgency_contribution.to_csv(
            combined_urgency_contribution_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第三层退出贡献汇总: {combined_urgency_contribution_path}")
        files["exit_urgency_contribution"] = str(combined_urgency_contribution_path)

        combined_exit_summary_report_path = output_root / f"{family_prefix}_exit_summary_report_{ts}.md"
        StrategyEvaluator.write_exit_summary_markdown(
            combined_exit_summary_report_path,
            combined_reason_detail,
            combined_urgency_summary,
            combined_urgency_contribution,
        )
        print(f"📦 合并退出结果总结报告: {combined_exit_summary_report_path}")
        files["exit_summary_report"] = str(combined_exit_summary_report_path)

    return files


def _select_rank_df(results_df: pd.DataFrame, ranking_mode: str):
    """Return the ranking table and the primary score column for the chosen mode."""
    return select_rank_df_for_mode(
        results_df,
        ranking_mode,
        complexity_penalty_resolver=get_strategy_complexity_penalty,
    )


def _precompute_walk_forward_panel(
    args,
    config,
    base_periods,
    output_dir,
    monitor_list_file,
    portfolio_overrides,
    enable_overlay: Optional[bool],
    exit_confirm_days: int,
    entry_filter_variants,
):
    eval_cfg = config.get("evaluation", {})
    entry_strategies, exit_strategies = _resolve_entry_exit_strategies(args, eval_cfg)
    evaluator = _build_evaluator(
        args=args,
        config=config,
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        exit_confirm_days=exit_confirm_days,
        entry_filter_variants=entry_filter_variants,
        replay_seed=None,
    )

    _log_step(
        "walk-forward: 开始预计算全量 period 面板 "
        f"(periods={len(base_periods)})"
    )
    results_df = evaluator.run_evaluation(
        periods=base_periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )
    if results_df.empty:
        return entry_strategies, exit_strategies, pd.DataFrame(), pd.DataFrame()

    trades_df = evaluator._create_trade_results_dataframe().copy()
    print(
        "📦 Walk-forward 全量 period 面板已生成: "
        f"rows={len(results_df)}, trades={len(trades_df)}"
    )
    return entry_strategies, exit_strategies, results_df.copy(), trades_df


def _resolve_walk_forward_mode(args) -> str:
    mode = str(getattr(args, "mode", "annual") or "annual")
    if mode not in {"annual", "quarterly"}:
        raise ValueError(f"walk-forward 不支持的 mode: {mode}")
    return mode


def _build_walk_forward_base_periods(
    walk_forward_mode: str,
    years: List[int],
) -> List[Tuple[str, str, str]]:
    if walk_forward_mode == "annual":
        return create_annual_periods(years)
    if walk_forward_mode == "quarterly":
        return create_quarterly_periods(years)
    raise ValueError(f"walk-forward 不支持的 mode: {walk_forward_mode}")


def _resolve_walk_forward_min_train_periods(
    walk_forward_mode: str,
    min_train_years: int,
) -> int:
    if walk_forward_mode == "quarterly":
        return min_train_years * 4
    return min_train_years


def _format_walk_forward_train_label(
    train_periods: List[Tuple[str, str, str]],
    walk_forward_mode: str,
) -> str:
    if not train_periods:
        return ""

    start_label = str(train_periods[0][0])
    end_label = str(train_periods[-1][0])
    if start_label == end_label:
        return start_label
    if walk_forward_mode == "quarterly":
        return f"{start_label} -> {end_label}"
    return f"{start_label}-{end_label}"


def _build_walk_forward_windows(
    periods: List[Tuple[str, str, str]],
    min_train_periods: int,
    walk_forward_mode: str,
):
    windows = []
    for idx in range(min_train_periods, len(periods)):
        train_periods = periods[:idx]
        test_period = periods[idx]
        test_label, test_start, test_end = test_period
        windows.append(
            {
                "window_index": len(windows) + 1,
                "train_periods": train_periods,
                "train_label": _format_walk_forward_train_label(
                    train_periods,
                    walk_forward_mode,
                ),
                "test_period": test_period,
                "test_period_label": str(test_label),
                "test_period_start": str(test_start),
                "test_period_end": str(test_end),
                "test_year": int(str(test_start)[:4]),
            }
        )
    return windows


def _insert_walk_forward_window_columns(
    df: pd.DataFrame,
    window,
) -> pd.DataFrame:
    window_df = df.copy()
    window_df.insert(0, "window_index", window["window_index"])
    window_df.insert(1, "train_label", window["train_label"])
    window_df.insert(2, "test_period", window["test_period_label"])
    window_df.insert(3, "test_year", window["test_year"])
    return window_df


def _walk_forward_period_section_label(walk_forward_mode: str) -> str:
    if walk_forward_mode == "quarterly":
        return "测试季度"
    return "测试年"


def _df_to_markdown(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _build_walk_forward_regime_summary(oos_df: pd.DataFrame) -> pd.DataFrame:
    if oos_df.empty:
        return pd.DataFrame()

    regime_df = oos_df.copy()
    regime_df["market_regime"] = regime_df["topix_return_pct"].apply(MarketRegime.classify)
    summary = (
        regime_df.groupby("market_regime", dropna=False)
        .agg(
            sample_count=("period", "nunique"),
            avg_return_pct=("return_pct", "mean"),
            avg_alpha_pct=("alpha", "mean"),
            positive_alpha_ratio=("alpha", lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean())),
            worst_test_return_pct=("return_pct", "min"),
            avg_max_drawdown_pct=("max_drawdown_pct", "mean"),
        )
        .reset_index()
    )
    return summary


def _candidate_match_mask(
    df: pd.DataFrame,
    candidate_row: pd.Series,
    key_cols: List[str],
) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=bool)

    mask = pd.Series(True, index=df.index)
    for column in key_cols:
        if column not in df.columns:
            continue
        selected_value = candidate_row.get(column)
        left = df[column].fillna("").astype(str)
        right = "" if pd.isna(selected_value) else str(selected_value)
        mask &= left == right
    return mask


def _walk_forward_candidate_columns(df: pd.DataFrame) -> List[str]:
    candidate_columns = [
        "entry_strategy",
        "exit_strategy",
        "entry_filter",
        "ranking_strategy",
    ]
    return [column for column in candidate_columns if column in df.columns]


def _build_walk_forward_candidate_summary_df(
    oos_panel_df: pd.DataFrame,
    selection_df: pd.DataFrame,
) -> pd.DataFrame:
    if oos_panel_df.empty:
        return pd.DataFrame()

    candidate_columns = _walk_forward_candidate_columns(oos_panel_df)
    if not candidate_columns:
        return pd.DataFrame()

    summary_df = (
        oos_panel_df.groupby(candidate_columns, dropna=False)
        .agg(
            oos_fold_count=("window_index", "nunique"),
            mean_oos_return=("return_pct", "mean"),
            mean_oos_alpha=("alpha", "mean"),
            avg_oos_mdd=("max_drawdown_pct", "mean"),
            worst_oos_year_alpha=("alpha", "min"),
            oos_positive_alpha_ratio=(
                "alpha",
                lambda s: float((pd.to_numeric(s, errors="coerce") > 0).mean()),
            ),
        )
        .reset_index()
    )

    selection_key_map = {
        "entry_strategy": "selected_entry_strategy",
        "exit_strategy": "selected_exit_strategy",
        "entry_filter": "selected_entry_filter",
        "ranking_strategy": "selected_ranking_strategy",
    }
    selection_group_cols = [
        selection_key_map[column]
        for column in candidate_columns
        if selection_key_map[column] in selection_df.columns
    ]
    selected_period_column = "test_period" if "test_period" in selection_df.columns else "test_year"
    if not selection_df.empty and selection_group_cols:
        selection_counts_df = (
            selection_df.groupby(selection_group_cols, dropna=False)
            .agg(
                selected_windows=("window_index", "count"),
                selected_test_periods=(selected_period_column, lambda s: ", ".join(map(str, s))),
            )
            .reset_index()
            .rename(columns={selection_key_map[column]: column for column in candidate_columns})
        )
        summary_df = summary_df.merge(
            selection_counts_df,
            on=candidate_columns,
            how="left",
        )

    best_rows: List[Dict[str, Any]] = []
    for _, window_df in oos_panel_df.groupby("window_index", sort=True):
        alpha_series = pd.to_numeric(window_df["alpha"], errors="coerce")
        if alpha_series.notna().any():
            best_idx = alpha_series.idxmax()
        else:
            return_series = pd.to_numeric(window_df["return_pct"], errors="coerce")
            if not return_series.notna().any():
                continue
            best_idx = return_series.idxmax()

        best_row = window_df.loc[best_idx]
        best_rows.append({column: best_row.get(column) for column in candidate_columns})

    if best_rows:
        best_count_df = (
            pd.DataFrame(best_rows)
            .groupby(candidate_columns, dropna=False)
            .size()
            .rename("actual_oos_best_windows")
            .reset_index()
        )
        summary_df = summary_df.merge(best_count_df, on=candidate_columns, how="left")

    if "window_index" in oos_panel_df.columns:
        window_index_series = pd.to_numeric(oos_panel_df["window_index"], errors="coerce")
        if window_index_series.notna().any():
            recent_window_index = int(window_index_series.max())
            recent_df = oos_panel_df.loc[window_index_series == recent_window_index].copy()
            recent_period_column = "test_period" if "test_period" in recent_df.columns else "period"
            recent_summary_df = (
                recent_df.groupby(candidate_columns, dropna=False)
                .agg(
                    recent_test_period=(recent_period_column, "first"),
                    recent_oos_return=("return_pct", "mean"),
                    recent_oos_alpha=("alpha", "mean"),
                )
                .reset_index()
            )
            summary_df = summary_df.merge(
                recent_summary_df,
                on=candidate_columns,
                how="left",
            )

    for column in ["selected_windows", "actual_oos_best_windows"]:
        if column in summary_df.columns:
            summary_df[column] = (
                pd.to_numeric(summary_df[column], errors="coerce").fillna(0).astype(int)
            )
    if "selected_test_periods" in summary_df.columns:
        summary_df["selected_test_periods"] = summary_df["selected_test_periods"].fillna("-")

    return summary_df.sort_values(
        ["selected_windows", "actual_oos_best_windows", "mean_oos_alpha", "avg_oos_mdd"],
        ascending=[False, False, False, True],
        kind="mergesort",
    ).reset_index(drop=True)


def _build_walk_forward_window_diagnostic_df(
    selection_df: pd.DataFrame,
    oos_panel_df: pd.DataFrame,
) -> pd.DataFrame:
    if selection_df.empty or oos_panel_df.empty:
        return pd.DataFrame()

    candidate_columns = _walk_forward_candidate_columns(oos_panel_df)
    selection_key_map = {
        "entry_strategy": "selected_entry_strategy",
        "exit_strategy": "selected_exit_strategy",
        "entry_filter": "selected_entry_filter",
        "ranking_strategy": "selected_ranking_strategy",
    }

    rows: List[Dict[str, Any]] = []
    ordered_selection_df = selection_df.sort_values("window_index", kind="mergesort")
    for _, selection_row in ordered_selection_df.iterrows():
        window_index = selection_row.get("window_index")
        window_df = oos_panel_df.loc[oos_panel_df["window_index"] == window_index].copy()
        if window_df.empty:
            continue

        selected_candidate = pd.Series(
            {
                column: selection_row.get(selection_key_map[column])
                for column in candidate_columns
            }
        )
        selected_mask = _candidate_match_mask(window_df, selected_candidate, candidate_columns)
        selected_rows = window_df.loc[selected_mask]
        selected_oos_row = selected_rows.iloc[0] if not selected_rows.empty else None

        alpha_series = pd.to_numeric(window_df["alpha"], errors="coerce")
        if alpha_series.notna().any():
            best_idx = alpha_series.idxmax()
        else:
            return_series = pd.to_numeric(window_df["return_pct"], errors="coerce")
            if not return_series.notna().any():
                continue
            best_idx = return_series.idxmax()
        best_oos_row = window_df.loc[best_idx]

        selected_alpha = (
            _coerce_float(selected_oos_row.get("alpha")) if selected_oos_row is not None else None
        )
        selected_return = (
            _coerce_float(selected_oos_row.get("return_pct")) if selected_oos_row is not None else None
        )
        best_alpha = _coerce_float(best_oos_row.get("alpha"))
        best_return = _coerce_float(best_oos_row.get("return_pct"))

        rows.append(
            {
                "window_index": int(window_index),
                "train_label": selection_row.get("train_label"),
                "test_period": selection_row.get("test_period", selection_row.get("test_year")),
                "test_year": selection_row.get("test_year"),
                "selected_entry_strategy": selection_row.get("selected_entry_strategy"),
                "selected_alpha": selected_alpha,
                "selected_return": selected_return,
                "best_actual_entry_strategy": best_oos_row.get("entry_strategy"),
                "best_actual_alpha": best_alpha,
                "best_actual_return": best_return,
                "alpha_regret": (
                    best_alpha - selected_alpha
                    if best_alpha is not None and selected_alpha is not None
                    else None
                ),
                "return_regret": (
                    best_return - selected_return
                    if best_return is not None and selected_return is not None
                    else None
                ),
                "selected_is_actual_oos_best": (
                    "是"
                    if selected_oos_row is not None
                    and str(selection_row.get("selected_entry_strategy", ""))
                    == str(best_oos_row.get("entry_strategy", ""))
                    else "否"
                ),
            }
        )

    return pd.DataFrame(rows)


def _format_walk_forward_prs_view(final_prs_df: pd.DataFrame) -> pd.DataFrame:
    prs_cols = ["rank", "entry_strategy", "exit_strategy"]
    if "ranking_strategy" in final_prs_df.columns:
        prs_cols.append("ranking_strategy")
    prs_cols.extend(
        [
            "entry_filter",
            "final_prs_score",
            "mean_oos_return",
            "recent_oos_return",
            "mean_oos_win_rate",
            "avg_oos_mdd",
            "worst_oos_mdd",
            "mean_oos_sharpe",
            "mean_oos_alpha",
            "oos_positive_alpha_ratio",
        ]
    )
    prs_view = final_prs_df[prs_cols].head(10).copy()
    for col in [
        "mean_oos_return",
        "recent_oos_return",
        "mean_oos_win_rate",
        "avg_oos_mdd",
        "worst_oos_mdd",
        "mean_oos_alpha",
    ]:
        prs_view[col] = pd.to_numeric(prs_view[col], errors="coerce").map(
            lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
        )
    prs_view["final_prs_score"] = pd.to_numeric(
        prs_view["final_prs_score"], errors="coerce"
    ).map(lambda v: f"{v:.2f}" if pd.notna(v) else "N/A")
    prs_view["mean_oos_sharpe"] = pd.to_numeric(
        prs_view["mean_oos_sharpe"], errors="coerce"
    ).map(lambda v: f"{v:.2f}" if pd.notna(v) else "N/A")
    for col in ["oos_positive_alpha_ratio"]:
        prs_view[col] = pd.to_numeric(prs_view[col], errors="coerce").map(
            lambda v: f"{v:.1%}" if pd.notna(v) else "N/A"
        )
    return prs_view


def _write_walk_forward_final_review_report(
    output_file: Path,
    output_dir: str,
    walk_forward_mode: str,
    years: List[int],
    min_train_years: int,
    ranking_mode: str,
    buy_fill_mode: str,
    entry_reference_mode: str,
    fill_buffer_enabled: bool,
    fill_buffer_pct: float,
    selection_df: pd.DataFrame,
    selection_freq_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    oos_panel_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    final_prs_df: pd.DataFrame,
    oos_raw_path: Optional[str],
    oos_trades_path: Optional[str],
) -> None:
    sector_by_ticker = _load_sector_by_ticker()
    selected_oos_raw_df, selected_oos_trades_df = _prepare_review_frames(
        oos_raw_path,
        oos_trades_path,
        sector_by_ticker,
    )
    candidate_summary_df = _build_walk_forward_candidate_summary_df(oos_panel_df, selection_df)
    window_diag_df = _build_walk_forward_window_diagnostic_df(selection_df, oos_panel_df)
    period_section_label = _walk_forward_period_section_label(walk_forward_mode)

    lines = [
        "# Anchored Walk-Forward 整合最终报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"评估模式：{walk_forward_mode}",
        f"评估年份：{', '.join(map(str, years))}",
        f"最少训练年份数：{min_train_years}",
        f"训练排序模式：{ranking_mode}",
        f"买入成交模式：{buy_fill_mode}",
        f"入场参考价模式：{entry_reference_mode}",
        f"成交价缓冲：{'on' if fill_buffer_enabled else 'off'}",
        f"缓冲比例：{fill_buffer_pct:.2%}",
        f"输出目录：{output_dir}",
        f"OOS原始结果：{Path(oos_raw_path).name if oos_raw_path else '-'}",
        f"OOS交易明细：{Path(oos_trades_path).name if oos_trades_path else '-'}",
        "",
        "## 说明",
        "",
        "- 本报告面向 anchored walk-forward：训练窗逐步扩展，下一个 period 作为 OOS 测试。",
        "- 详细交易/退出/行业分析仅针对每个窗口最终被选中的 OOS 策略。",
        "- 候选对比与窗口诊断使用 OOS panel，全量纳入同窗所有候选策略。",
        "- 同窗最佳策略默认按 OOS Alpha 比较；若 Alpha 缺失，则退回 OOS Return。",
        "",
    ]

    if not selection_freq_df.empty:
        dominant_row = selection_freq_df.iloc[0]
        lines.extend(
            [
                "## 快速结论",
                "",
                f"- 训练窗口最常选中：{dominant_row.get('selected_entry_strategy', '-')}（{_format_count(dominant_row.get('selected_windows', 0))} 个窗口）",
                f"- Final PRS 第一名：{final_prs_df.iloc[0]['entry_strategy'] if not final_prs_df.empty else '-'}",
                f"- OOS 窗口数：{_format_count(oos_df['period'].nunique()) if not oos_df.empty and 'period' in oos_df.columns else '0'}",
                "",
            ]
        )

    if not selection_df.empty:
        selection_view = selection_df.copy()
        if "train_selection_score" in selection_view.columns:
            selection_view["train_selection_score"] = pd.to_numeric(
                selection_view["train_selection_score"], errors="coerce"
            ).map(lambda v: f"{v:.4f}" if pd.notna(v) else "N/A")
        lines.extend([
            "## 窗口选择路径",
            "",
            _df_to_markdown(selection_view),
            "",
        ])

    if not selection_freq_df.empty:
        lines.extend([
            "## 选择频率",
            "",
            _df_to_markdown(selection_freq_df),
            "",
        ])

    if not candidate_summary_df.empty:
        candidate_view = candidate_summary_df.copy()
        for col in [
            "mean_oos_return",
            "mean_oos_alpha",
            "avg_oos_mdd",
            "worst_oos_year_alpha",
            "recent_oos_return",
            "recent_oos_alpha",
        ]:
            if col in candidate_view.columns:
                candidate_view[col] = pd.to_numeric(candidate_view[col], errors="coerce").map(
                    lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
                )
        if "oos_positive_alpha_ratio" in candidate_view.columns:
            candidate_view["oos_positive_alpha_ratio"] = pd.to_numeric(
                candidate_view["oos_positive_alpha_ratio"], errors="coerce"
            ).map(lambda v: f"{v:.1%}" if pd.notna(v) else "N/A")
        lines.extend([
            "## 候选策略 OOS 聚合对比",
            "",
            _df_to_markdown(candidate_view),
            "",
        ])

    if not window_diag_df.empty:
        diag_view = window_diag_df.copy()
        for col in [
            "selected_alpha",
            "selected_return",
            "best_actual_alpha",
            "best_actual_return",
            "alpha_regret",
            "return_regret",
        ]:
            diag_view[col] = pd.to_numeric(diag_view[col], errors="coerce").map(
                lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
            )
        lines.extend([
            "## 选中策略 vs 同窗实际最佳",
            "",
            _df_to_markdown(diag_view),
            "",
        ])

    if not selected_oos_raw_df.empty:
        lines.extend([
            "## 已选策略 OOS 总览",
            "",
            _markdown_table_from_rows(
                _build_period_overview_rows(selected_oos_raw_df, selected_oos_trades_df, period_section_label),
                [
                    period_section_label,
                    "市场环境",
                    "净收益(JPY)",
                    "收益率",
                    "超额收益Alpha",
                    "夏普比率",
                    "最大回撤",
                    "交易数",
                    "退出动作数",
                    "胜率",
                    "总盈利(JPY)",
                    "总亏损(JPY)",
                ],
            ),
            "",
        ])
        _append_period_detail_sections(
            lines,
            selected_oos_raw_df,
            selected_oos_trades_df,
            period_section_label,
        )

    if not final_prs_df.empty:
        lines.extend([
            "## Final PRS 排名",
            "",
            _df_to_markdown(_format_walk_forward_prs_view(final_prs_df)),
            "",
        ])

    if not regime_df.empty:
        regime_view = regime_df.copy()
        for col in ["avg_return_pct", "avg_alpha_pct", "worst_test_return_pct", "avg_max_drawdown_pct"]:
            regime_view[col] = pd.to_numeric(regime_view[col], errors="coerce").map(
                lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
            )
        regime_view["positive_alpha_ratio"] = pd.to_numeric(
            regime_view["positive_alpha_ratio"], errors="coerce"
        ).map(lambda v: f"{v:.1%}" if pd.notna(v) else "N/A")
        lines.extend([
            "## OOS 市场环境汇总",
            "",
            _df_to_markdown(regime_view),
            "",
        ])

    output_file.write_text("\n".join(lines), encoding="utf-8")


def _write_walk_forward_report(
    output_file: Path,
    walk_forward_mode: str,
    ranking_mode: str,
    years: List[int],
    min_train_years: int,
    buy_fill_mode: str,
    entry_reference_mode: str,
    fill_buffer_enabled: bool,
    fill_buffer_pct: float,
    selection_df: pd.DataFrame,
    selection_freq_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    regime_df: pd.DataFrame,
    final_prs_df: pd.DataFrame,
):
    lines = [
        "# Anchored Walk-Forward Evaluation",
        "",
        f"- Mode: {walk_forward_mode}",
        f"- Years: {', '.join(map(str, years))}",
        f"- Minimum train years: {min_train_years}",
        f"- Ranking mode: {ranking_mode}",
        f"- Buy fill mode: {buy_fill_mode}",
        f"- Entry reference mode: {entry_reference_mode}",
        f"- Fill buffer: {'on' if fill_buffer_enabled else 'off'}",
        f"- Fill buffer pct: {fill_buffer_pct:.2%}",
        "- Selection protocol: expanding train window, next-period out-of-sample test, report only test windows.",
        "",
    ]

    if not selection_df.empty:
        selection_cols = [
            "window_index",
            "train_label",
            "test_period",
            "selected_entry_strategy",
            "selected_exit_strategy",
        ]
        if "selected_ranking_strategy" in selection_df.columns:
            selection_cols.append("selected_ranking_strategy")
        selection_cols.extend([
            "selected_entry_filter",
            "train_selection_score",
        ])
        selection_view = selection_df[selection_cols].copy()
        selection_view["train_selection_score"] = pd.to_numeric(
            selection_view["train_selection_score"], errors="coerce"
        ).map(lambda v: f"{v:.4f}" if pd.notna(v) else "N/A")
        lines.extend([
            "## Window Selections",
            "",
            _df_to_markdown(selection_view),
            "",
        ])

    if not selection_freq_df.empty:
        freq_view = selection_freq_df.copy()
        lines.extend([
            "## Selection Frequency",
            "",
            _df_to_markdown(freq_view),
            "",
        ])

    if not oos_df.empty:
        oos_cols = [
            "window_index",
            "train_label",
            "period",
            "entry_strategy",
            "exit_strategy",
        ]
        if "ranking_strategy" in oos_df.columns:
            oos_cols.append("ranking_strategy")
        oos_cols.extend([
            "entry_filter",
            "return_pct",
            "alpha",
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate_pct",
        ])
        oos_view = oos_df[oos_cols].copy()
        for col in ["return_pct", "alpha", "max_drawdown_pct", "win_rate_pct"]:
            oos_view[col] = pd.to_numeric(oos_view[col], errors="coerce").map(
                lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
            )
        oos_view["sharpe_ratio"] = pd.to_numeric(
            oos_view["sharpe_ratio"], errors="coerce"
        ).map(lambda v: f"{v:.2f}" if pd.notna(v) else "N/A")

        overall = {
            "test_window_count": int(oos_df["period"].nunique()),
            "avg_return_pct": float(pd.to_numeric(oos_df["return_pct"], errors="coerce").mean()),
            "avg_alpha_pct": float(pd.to_numeric(oos_df["alpha"], errors="coerce").mean()),
            "positive_alpha_ratio": float((pd.to_numeric(oos_df["alpha"], errors="coerce") > 0).mean()),
            "worst_test_return_pct": float(pd.to_numeric(oos_df["return_pct"], errors="coerce").min()),
            "avg_max_drawdown_pct": float(pd.to_numeric(oos_df["max_drawdown_pct"], errors="coerce").mean()),
        }
        lines.extend([
            "## Out-Of-Sample Summary",
            "",
            f"- Test windows: {overall['test_window_count']}",
            f"- Avg test return: {overall['avg_return_pct']:.2f}%",
            f"- Avg alpha: {overall['avg_alpha_pct']:.2f}%",
            f"- Positive alpha ratio: {overall['positive_alpha_ratio']:.1%}",
            f"- Worst test return: {overall['worst_test_return_pct']:.2f}%",
            f"- Avg max drawdown: {overall['avg_max_drawdown_pct']:.2f}%",
            "",
            "## Out-Of-Sample Window Results",
            "",
            _df_to_markdown(oos_view),
            "",
        ])

    if not final_prs_df.empty:
        lines.extend([
            "## Final PRS Ranking",
            "",
            _df_to_markdown(_format_walk_forward_prs_view(final_prs_df)),
            "",
        ])

    if not regime_df.empty:
        regime_view = regime_df.copy()
        for col in ["avg_return_pct", "avg_alpha_pct", "worst_test_return_pct", "avg_max_drawdown_pct"]:
            regime_view[col] = pd.to_numeric(regime_view[col], errors="coerce").map(
                lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A"
            )
        regime_view["positive_alpha_ratio"] = pd.to_numeric(
            regime_view["positive_alpha_ratio"], errors="coerce"
        ).map(lambda v: f"{v:.1%}" if pd.notna(v) else "N/A")
        lines.extend([
            "## Out-Of-Sample Regime Summary",
            "",
            _df_to_markdown(regime_view),
        ])

    output_file.write_text("\n".join(lines), encoding="utf-8")


def _run_walk_forward_once(
    args,
    config,
    years,
    walk_forward_mode,
    base_periods,
    min_train_years,
    entry_filter_variants,
    output_dir,
    prefix,
    monitor_list_file=None,
    portfolio_overrides=None,
    enable_overlay: bool = None,
    ranking_mode: str = "target20",
):
    _log_step("walk-forward: 开始解析本轮参数")
    eval_cfg = config.get("evaluation", {})
    entry_filter_variants = _dedupe_filter_variants(entry_filter_variants)
    exit_confirm_days = _resolve_exit_confirm_days(args, eval_cfg)

    use_overlay, _ = _resolve_overlay_config(
        config=config,
        args=args,
        enable_overlay_override=enable_overlay,
    )
    _log_step(f"walk-forward: overlay={'on' if use_overlay else 'off'}")

    entry_strategies, exit_strategies, base_results_df, base_trade_df = _precompute_walk_forward_panel(
        args=args,
        config=config,
        base_periods=base_periods,
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        exit_confirm_days=exit_confirm_days,
        entry_filter_variants=entry_filter_variants,
    )
    if base_results_df.empty:
        print("⚠️ Walk-forward 全量 period 面板为空，终止")
        return None

    results_panel_df = base_results_df.copy()
    results_panel_df["_wf_period_key"] = results_panel_df["period"].astype(str)
    trade_panel_df = base_trade_df.copy()
    if not trade_panel_df.empty:
        trade_panel_df["_wf_period_key"] = trade_panel_df["period"].astype(str)

    min_train_periods = _resolve_walk_forward_min_train_periods(
        walk_forward_mode,
        min_train_years,
    )
    windows = _build_walk_forward_windows(base_periods, min_train_periods, walk_forward_mode)
    out_dir = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    train_rank_frames = []
    selection_rows = []
    oos_frames = []
    oos_panel_frames = []
    oos_trade_frames = []

    print(f"🧷 Exit确认天数: {exit_confirm_days}")
    print(
        "🎯 入场参考价模式: "
        f"{normalize_entry_reference_mode(getattr(args, 'entry_reference_mode', 'raw_fill'))}"
    )
    print(
        "🪙 成交价缓冲: "
        f"{'开启' if getattr(args, 'fill_buffer_enabled', False) else '关闭'} "
        f"({normalize_fill_buffer_pct(getattr(args, 'fill_buffer_pct', 0.02)):.2%})"
    )
    print(f"🗓️ Walk-forward粒度: {walk_forward_mode}")
    print(f"🪟 Walk-forward窗口数: {len(windows)}")

    for window in windows:
        train_periods = list(window["train_periods"])
        train_period_labels = {str(label) for label, _, _ in train_periods}
        print(
            f"\n[WF {window['window_index']}/{len(windows)}] 训练 {window['train_label']} -> 测试 {window['test_period_label']}",
            flush=True,
        )

        train_df = results_panel_df.loc[
            results_panel_df["_wf_period_key"].isin(train_period_labels)
        ].drop(columns=["_wf_period_key"]).copy()
        if train_df.empty:
            print("⚠️ 训练结果为空，跳过该窗口")
            continue

        train_summary_df = summarize_prs_train_metrics(train_df)

        train_rank_df, score_col = _select_rank_df(train_df, ranking_mode)
        if train_rank_df.empty:
            print("⚠️ 训练排名为空，跳过该窗口")
            continue

        train_rank_df = _insert_walk_forward_window_columns(train_rank_df, window)
        train_rank_frames.append(train_rank_df)

        selected = train_rank_df.iloc[0]
        selected_filter_name = str(selected["entry_filter"])
        selection_rows.append(
            {
                "window_index": window["window_index"],
                "train_label": window["train_label"],
                "test_period": window["test_period_label"],
                "test_year": window["test_year"],
                "selected_entry_strategy": selected["entry_strategy"],
                "selected_exit_strategy": selected["exit_strategy"],
                "selected_ranking_strategy": selected.get("ranking_strategy"),
                "selected_entry_filter": selected_filter_name,
                "train_score_metric": score_col,
                "train_selection_score": selected.get(score_col),
            }
        )

        print(
            "   训练期选中: "
            f"{selected['entry_strategy']} × {selected['exit_strategy']}"
            f" × rank:{selected.get('ranking_strategy', 'default')} × {selected_filter_name} "
            f"({score_col}={selected.get(score_col)})",
            flush=True,
        )

        test_df = results_panel_df.loc[
            results_panel_df["_wf_period_key"] == window["test_period_label"]
        ].drop(columns=["_wf_period_key"]).copy()
        if test_df.empty:
            print("⚠️ 测试结果为空，跳过该窗口")
            continue

        candidate_cols = [
            column
            for column in candidate_key_columns(test_df)
            if column in train_rank_df.columns and column in train_summary_df.columns
        ]

        test_panel_df = _insert_walk_forward_window_columns(test_df, window)
        test_panel_df = test_panel_df.merge(
            train_summary_df,
            on=candidate_cols,
            how="left",
        )
        train_rank_context_df = train_rank_df[candidate_cols + ["rank", score_col]].copy()
        train_rank_context_df = train_rank_context_df.rename(
            columns={
                "rank": "train_candidate_rank",
                score_col: "train_candidate_score",
            }
        )
        test_panel_df = test_panel_df.merge(
            train_rank_context_df,
            on=candidate_cols,
            how="left",
        )
        test_panel_df["train_score_metric"] = score_col
        test_panel_df["train_selection_score"] = selected.get(score_col)
        test_panel_df["is_train_selected"] = _candidate_match_mask(
            test_panel_df,
            selected,
            candidate_cols,
        )
        oos_panel_frames.append(test_panel_df)

        winner_test_df = test_panel_df[test_panel_df["is_train_selected"]].copy()
        if not winner_test_df.empty:
            oos_frames.append(winner_test_df)

        if not trade_panel_df.empty:
            trade_df = trade_panel_df.loc[
                trade_panel_df["_wf_period_key"] == window["test_period_label"]
            ].drop(columns=["_wf_period_key"]).copy()
            trade_df = _insert_walk_forward_window_columns(trade_df, window)
            trade_df["train_score_metric"] = score_col
            trade_df["train_selection_score"] = selected.get(score_col)
            trade_mask = _candidate_match_mask(trade_df, selected, candidate_cols)
            oos_trade_frames.append(trade_df[trade_mask].copy())

    selection_df = pd.DataFrame(selection_rows)
    train_rank_all_df = pd.concat(train_rank_frames, ignore_index=True) if train_rank_frames else pd.DataFrame()
    oos_df = pd.concat(oos_frames, ignore_index=True) if oos_frames else pd.DataFrame()
    oos_panel_df = pd.concat(oos_panel_frames, ignore_index=True) if oos_panel_frames else pd.DataFrame()
    oos_trade_df = pd.concat(oos_trade_frames, ignore_index=True) if oos_trade_frames else pd.DataFrame()

    selection_freq_df = pd.DataFrame()
    if not selection_df.empty:
        selection_group_cols = [
            "selected_entry_strategy",
            "selected_exit_strategy",
        ]
        if "selected_ranking_strategy" in selection_df.columns:
            selection_group_cols.append("selected_ranking_strategy")
        selection_group_cols.append("selected_entry_filter")
        selection_freq_df = (
            selection_df.groupby(
                selection_group_cols,
                dropna=False,
            )
            .agg(
                selected_windows=("test_period", "count"),
                test_periods=("test_period", lambda s: ", ".join(map(str, s))),
            )
            .reset_index()
            .sort_values(
                ["selected_windows", "selected_entry_strategy"],
                ascending=[False, True],
            )
        )

    regime_df = _build_walk_forward_regime_summary(oos_df)
    final_prs_df = rank_final_prs(
        oos_panel_df,
        complexity_penalty_resolver=get_strategy_complexity_penalty,
    )

    files = {}
    selection_file = out_dir / f"{prefix}_selection_{timestamp}.csv"
    selection_df.to_csv(selection_file, index=False, encoding="utf-8-sig")
    files["selection"] = str(selection_file)

    train_rank_file = out_dir / f"{prefix}_train_rank_{timestamp}.csv"
    train_rank_all_df.to_csv(train_rank_file, index=False, encoding="utf-8-sig")
    files["train_rank"] = str(train_rank_file)

    oos_raw_file = out_dir / f"{prefix}_oos_raw_{timestamp}.csv"
    oos_df.to_csv(oos_raw_file, index=False, encoding="utf-8-sig")
    files["oos_raw"] = str(oos_raw_file)

    oos_panel_file = out_dir / f"{prefix}_oos_panel_{timestamp}.csv"
    oos_panel_df.to_csv(oos_panel_file, index=False, encoding="utf-8-sig")
    files["oos_panel"] = str(oos_panel_file)

    regime_file = out_dir / f"{prefix}_oos_by_regime_{timestamp}.csv"
    regime_df.to_csv(regime_file, index=False, encoding="utf-8-sig")
    files["oos_regime"] = str(regime_file)

    final_prs_file = out_dir / f"{prefix}_final_prs_{timestamp}.csv"
    final_prs_df.to_csv(final_prs_file, index=False, encoding="utf-8-sig")
    files["final_prs"] = str(final_prs_file)

    selection_freq_file = out_dir / f"{prefix}_selection_frequency_{timestamp}.csv"
    selection_freq_df.to_csv(selection_freq_file, index=False, encoding="utf-8-sig")
    files["selection_frequency"] = str(selection_freq_file)

    trades_file = out_dir / f"{prefix}_oos_trades_{timestamp}.csv"
    oos_trade_df.to_csv(trades_file, index=False, encoding="utf-8-sig")
    files["oos_trades"] = str(trades_file)

    report_file = out_dir / f"{prefix}_report_{timestamp}.md"
    _write_walk_forward_report(
        output_file=report_file,
        walk_forward_mode=walk_forward_mode,
        ranking_mode=ranking_mode,
        years=years,
        min_train_years=min_train_years,
        buy_fill_mode=getattr(args, "buy_fill_mode", "next_open"),
        entry_reference_mode=normalize_entry_reference_mode(
            getattr(args, "entry_reference_mode", "raw_fill")
        ),
        fill_buffer_enabled=getattr(args, "fill_buffer_enabled", False),
        fill_buffer_pct=normalize_fill_buffer_pct(getattr(args, "fill_buffer_pct", 0.02)),
        selection_df=selection_df,
        selection_freq_df=selection_freq_df,
        oos_df=oos_df,
        regime_df=regime_df,
        final_prs_df=final_prs_df,
    )
    files["report"] = str(report_file)

    final_review_file = out_dir / f"{prefix}_final_review_{timestamp}.md"
    _write_walk_forward_final_review_report(
        output_file=final_review_file,
        output_dir=str(out_dir),
        walk_forward_mode=walk_forward_mode,
        years=years,
        min_train_years=min_train_years,
        ranking_mode=ranking_mode,
        buy_fill_mode=getattr(args, "buy_fill_mode", "next_open"),
        entry_reference_mode=normalize_entry_reference_mode(
            getattr(args, "entry_reference_mode", "raw_fill")
        ),
        fill_buffer_enabled=getattr(args, "fill_buffer_enabled", False),
        fill_buffer_pct=normalize_fill_buffer_pct(getattr(args, "fill_buffer_pct", 0.02)),
        selection_df=selection_df,
        selection_freq_df=selection_freq_df,
        oos_df=oos_df,
        oos_panel_df=oos_panel_df,
        regime_df=regime_df,
        final_prs_df=final_prs_df,
        oos_raw_path=str(oos_raw_file),
        oos_trades_path=str(trades_file),
    )
    files["final_review"] = str(final_review_file)

    print(f"✅ Walk-forward 选择结果已保存: {selection_file}")
    print(f"✅ Walk-forward 训练排名已保存: {train_rank_file}")
    print(f"✅ Walk-forward 测试结果已保存: {oos_raw_file}")
    print(f"✅ Walk-forward 全候选OOS结果已保存: {oos_panel_file}")
    print(f"✅ Walk-forward 市场环境结果已保存: {regime_file}")
    print(f"✅ Walk-forward Final PRS已保存: {final_prs_file}")
    print(f"✅ Walk-forward 报告已保存: {report_file}")
    print(f"✅ Walk-forward 中文整合最终报告已保存: {final_review_file}")

    return files


def _run_contexts(
    args,
    config,
    periods,
    entry_filter_variants,
    output_dir,
    contexts: List[EvaluationRunContext],
    ranking_mode: str,
):
    """Run all contexts and return list of successful segmented/continuous bundles."""
    results: List[Tuple[EvaluationRunContext, EvaluationOutputBundle]] = []
    for context in contexts:
        bundle = _run_context_bundle(
            args=args,
            config=config,
            periods=periods,
            entry_filter_variants=entry_filter_variants,
            output_dir=output_dir,
            prefix=context.prefix,
            monitor_list_file=context.monitor_list_file,
            portfolio_overrides=context.portfolio_overrides,
            enable_overlay=context.enable_overlay,
            ranking_mode=ranking_mode,
            replay_seed=None,
            context_metadata=context.metadata,
        )
        if bundle:
            results.append((context, bundle))
    return results


def _run_context_bundle(
    args,
    config,
    periods,
    entry_filter_variants,
    output_dir,
    prefix,
    monitor_list_file=None,
    portfolio_overrides=None,
    enable_overlay: bool = None,
    ranking_mode: str = "target20",
    replay_seed: Optional[ReplaySeed] = None,
    context_metadata: Optional[Dict[str, Any]] = None,
):
    segmented_files = _run_once(
        args=args,
        config=config,
        periods=periods,
        entry_filter_variants=entry_filter_variants,
        output_dir=output_dir,
        prefix=prefix,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        ranking_mode=ranking_mode,
        replay_seed=replay_seed,
        context_metadata=context_metadata,
    )
    if not segmented_files:
        return None

    bundle = EvaluationOutputBundle(segmented=segmented_files)
    eval_cfg = config.get("evaluation", {})
    if not _resolve_include_continuous(args, eval_cfg):
        bundle.final_report = _write_localized_final_review_report(
            args=args,
            output_dir=output_dir,
            prefix=prefix,
            bundle=bundle,
        )
        return bundle

    continuous_periods = _build_segmented_continuous_periods(args, periods)
    if not continuous_periods:
        bundle.final_report = _write_localized_final_review_report(
            args=args,
            output_dir=output_dir,
            prefix=prefix,
            bundle=bundle,
        )
        return bundle

    continuous_label, continuous_start, continuous_end = continuous_periods[0]
    print(
        f"♾️ 追加全区间连续聚合: {continuous_label} "
        f"({continuous_start} ~ {continuous_end})"
    )
    _log_step(
        f"segmented-continuous: 开始 {continuous_label} ({continuous_start} ~ {continuous_end})"
    )
    continuous_files = _run_once(
        args=args,
        config=config,
        periods=continuous_periods,
        entry_filter_variants=entry_filter_variants,
        output_dir=output_dir,
        prefix=f"{prefix}_continuous",
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        ranking_mode=ranking_mode,
        replay_seed=replay_seed,
        context_metadata=context_metadata,
    )
    if continuous_files:
        bundle.continuous = continuous_files
        if getattr(args, "mode", None) == "annual":
            bundle.annual_companion = _write_annual_continuous_stability_rank(
                output_dir=output_dir,
                prefix=prefix,
                segmented_raw_path=segmented_files.get("raw"),
                continuous_raw_path=continuous_files.get("raw"),
            )
    bundle.final_report = _write_localized_final_review_report(
        args=args,
        output_dir=output_dir,
        prefix=prefix,
        bundle=bundle,
    )
    return bundle


def _load_position_profiles(args, eval_cfg):
    """Load and normalize position profiles used by pos-evaluation."""
    position_file_arg = args.position_file
    default_position_file = eval_cfg.get("default_position_file")
    if (
        default_position_file
        and position_file_arg == "evaluation-position.json"
        and Path(default_position_file).exists()
    ):
        position_file_arg = default_position_file

    position_file = Path(position_file_arg)
    if not position_file.exists():
        raise ValueError(f"仓位配置文件不存在: {position_file}")

    try:
        with open(position_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        raise ValueError(f"读取仓位配置失败: {e}")

    if isinstance(payload, list):
        profiles = payload
    elif isinstance(payload, dict):
        profiles = (
            payload.get("portfolios")
            or payload.get("profiles")
            or payload.get("positions")
            or []
        )
    else:
        profiles = []

    if not profiles:
        raise ValueError("未找到可用仓位组合（支持 list 或 {portfolios:[...]}）")

    selected_profile_names = set(args.profile_name or eval_cfg.get("default_profile_names", []))
    normalized_profiles = []
    for idx, item in enumerate(profiles, 1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or f"p{idx}")
        if selected_profile_names and name not in selected_profile_names:
            continue
        position_sizing_mode = normalize_position_sizing_mode(
            item.get("position_sizing_mode", "fixed")
        )
        if position_sizing_mode == "fixed" and (
            "max_positions" not in item or "max_position_pct" not in item
        ):
            print(f"⚠️ 跳过 {name}: 缺少 max_positions 或 max_position_pct")
            continue
        atr_position_sizing = item.get("atr_position_sizing") or {}
        if not isinstance(atr_position_sizing, dict):
            atr_position_sizing = {}
        for key in ("risk_per_trade_pct", "atr_stop_multiple", "min_position_value_jpy"):
            if key in item:
                atr_position_sizing[key] = item[key]
        normalized_profiles.append(
            {
                "name": name,
                "position_sizing_mode": position_sizing_mode,
                "max_positions": int(item.get("max_positions", 7)),
                "max_position_pct": float(item.get("max_position_pct", 0.18)),
                "atr_position_sizing": atr_position_sizing,
                "starting_capital_jpy": (
                    int(item["starting_capital_jpy"])
                    if item.get("starting_capital_jpy") is not None
                    else None
                ),
            }
        )

    if not normalized_profiles:
        raise ValueError("无有效仓位组合")

    return normalized_profiles


def _run_once(
    args,
    config,
    periods,
    entry_filter_variants,
    output_dir,
    prefix,
    monitor_list_file=None,
    portfolio_overrides=None,
    enable_overlay: bool = None,
    ranking_mode: str = "target20",
    replay_seed: Optional[ReplaySeed] = None,
    context_metadata: Optional[Dict[str, Any]] = None,
):
    _log_step("_run_once: 开始解析本轮参数")
    run_started = time.perf_counter()
    eval_cfg = config.get("evaluation", {})
    original_filter_variant_count = len(entry_filter_variants) if entry_filter_variants else 0
    entry_filter_variants = _dedupe_filter_variants(entry_filter_variants)
    if entry_filter_variants and len(entry_filter_variants) != original_filter_variant_count:
        print(
            f"⚠️ Entry Filter 变体去重: {original_filter_variant_count} -> {len(entry_filter_variants)}"
        )
    exit_confirm_days = _resolve_exit_confirm_days(args, eval_cfg)
    use_overlay = _resolve_effective_overlay_enabled(config=config, args=args, override=enable_overlay)
    if use_overlay:
        _, overlay_config = _resolve_overlay_config(
            config=config,
            args=args,
            enable_overlay_override=enable_overlay,
        )
    else:
        _, overlay_config = _resolve_overlay_config(
            config=config,
            args=args,
            enable_overlay_override=enable_overlay,
        )
    _log_step(f"_run_once: overlay={'on' if use_overlay else 'off'}")

    entry_strategies, exit_strategies = _resolve_entry_exit_strategies(args, eval_cfg)
    run_metadata = _build_run_metadata(
        run_kind="evaluate",
        args=args,
        periods=periods,
        prefix=prefix,
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=use_overlay,
        ranking_mode=ranking_mode,
        entry_filter_variants=entry_filter_variants,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
        context_metadata=context_metadata,
    )

    evaluator = _build_evaluator(
        args=args,
        config=config,
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        exit_confirm_days=exit_confirm_days,
        entry_filter_variants=entry_filter_variants,
        replay_seed=replay_seed,
        run_metadata=run_metadata,
    )
    _log_step("_run_once: StrategyEvaluator 初始化完成")

    print(f"🧷 Exit确认天数: {exit_confirm_days}")
    print(
        "🎯 入场参考价模式: "
        f"{normalize_entry_reference_mode(getattr(args, 'entry_reference_mode', 'raw_fill'))}"
    )
    print(
        "🪙 成交价缓冲: "
        f"{'开启' if getattr(args, 'fill_buffer_enabled', False) else '关闭'} "
        f"({normalize_fill_buffer_pct(getattr(args, 'fill_buffer_pct', 0.02)):.2%})"
    )

    _log_step(
        "_run_once: 执行评估 "
        f"(periods={len(periods)}, entry={len(entry_strategies) if entry_strategies else 0}, "
        f"exit={len(exit_strategies) if exit_strategies else 0}, filters={len(entry_filter_variants)})"
    )

    eval_started = time.perf_counter()
    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )
    eval_elapsed = time.perf_counter() - eval_started
    _log_step("_run_once: run_evaluation 返回")

    if df_results.empty:
        _log_step("_run_once: 结果为空，结束")
        return None

    _log_step("_run_once: 开始保存结果文件")
    save_started = time.perf_counter()
    files = evaluator.save_results(prefix=prefix, ranking_mode=ranking_mode)
    save_elapsed = time.perf_counter() - save_started
    total_elapsed = time.perf_counter() - run_started
    _log_step("_run_once: 结果文件保存完成")

    print("\n⏱️ 本轮运行计时汇总:")
    print(f"   - evaluate阶段: {eval_elapsed:.2f}s")
    print(f"   - save_results阶段: {save_elapsed:.2f}s")
    print(f"   - _run_once总耗时: {total_elapsed:.2f}s")

    timing_summary = getattr(evaluator, "last_timing_summary", None)
    if isinstance(timing_summary, dict) and timing_summary:
        total_eval_sec = float(timing_summary.get("total_elapsed_sec", 0.0) or 0.0)
        completed = int(timing_summary.get("completed_tasks", 0) or 0)
        ok = int(timing_summary.get("success_count", 0) or 0)
        err = int(timing_summary.get("error_count", 0) or 0)
        print("\n⏱️ evaluator内部计时摘要:")
        print(
            f"   - total_elapsed_sec={total_eval_sec:.2f}, tasks={completed}, ok={ok}, err={err}"
        )

    return files


def cmd_evaluate(args):
    """策略综合评价命令"""
    print("\n" + "=" * 80)
    print("🔬 策略综合评价系统")
    print("=" * 80 + "\n")
    _log_step("evaluate: 命令开始")

    config = load_config()
    eval_cfg = config.get("evaluation", {})
    _log_step("evaluate: 配置加载完成")

    try:
        _log_step("evaluate: 解析公共输入参数")
        resolved = _prepare_common_evaluation_inputs(args, config)
        if resolved is None:
            return
        entry_filter_variants, periods, universe_variants = resolved
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir("evaluate", args, args.output_dir, eval_cfg)
    ranking_mode = _resolve_ranking_mode(config, args)
    _log_step(f"evaluate: 输出目录就绪 -> {output_dir}")
    _log_step(f"evaluate: 排名模式 -> {ranking_mode}")

    effective_overlay_on = _resolve_effective_overlay_enabled(config, args)
    runtime_portfolio_overrides = merge_portfolio_runtime_overrides(args)

    contexts = []
    for universe_name, universe_file in universe_variants:
        prefix = "strategy_evaluation"
        if len(universe_variants) > 1 or universe_file is not None:
            prefix = f"strategy_evaluation_universe_{_sanitize_name(universe_name)}"
        contexts.append(
            EvaluationRunContext(
                name=universe_name,
                prefix=prefix,
                monitor_list_file=universe_file,
                portfolio_overrides=runtime_portfolio_overrides,
                enable_overlay=effective_overlay_on,
                metadata={
                    "universe_name": universe_name,
                    "universe_file": universe_file,
                },
            )
        )

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🗂️ 股票池变体: {len(universe_variants)} 个")
    print(f"   {', '.join(name for name, _ in universe_variants)}")
    print(f"🧭 Overlay: {'ENABLED' if effective_overlay_on else 'DISABLED'}")
    print(f"🏁 Ranking Mode: {ranking_mode}")
    print("\n🚀 开始策略评估...")
    _log_step("evaluate: 进入按股票池循环")

    for context in contexts:
        print("\n" + "-" * 80)
        print(
            f"🧺 股票池: {context.name}"
            + (
                f" ({context.monitor_list_file})"
                if context.monitor_list_file
                else " (config默认)"
            )
        )
        print("-" * 80)
        _log_step(f"evaluate: 开始运行股票池 {context.name}")

    all_files = _run_contexts(
        args=args,
        config=config,
        periods=periods,
        entry_filter_variants=entry_filter_variants,
        output_dir=output_dir,
        contexts=contexts,
        ranking_mode=ranking_mode,
    )
    for context, _ in all_files:
        _log_step(f"evaluate: 股票池 {context.name} 运行完成")

    if not all_files:
        print("❌ 评估失败: 没有生成任何结果")
        return

    _log_step("evaluate: 所有股票池运行完成，开始汇总输出")

    segmented_result_label = "按年分段结果"
    if getattr(args, "mode", None) == "quarterly":
        segmented_result_label = "按季分段结果"

    print(f"\n{'=' * 80}")
    print("✅ 策略评价完成！")
    print(f"{'=' * 80}")
    for context, bundle in all_files:
        universe_file = context.metadata.get("universe_file")
        print(f"[股票池: {context.name}] {universe_file or '(config默认)'}")
        print(f"  🧩 {segmented_result_label}:")
        _print_saved_files(bundle.segmented, indent="    ")
        if bundle.continuous:
            print("  ♾️ 全区间连续聚合结果:")
            _print_saved_files(bundle.continuous, indent="    ")
        if bundle.annual_companion:
            print("  🏆 Continuous+Stability结果:")
            _print_companion_files(bundle.annual_companion, indent="    ")
        if bundle.final_report:
            print(f"  📘 中文整合最终报告: {bundle.final_report}")
    print(f"{'=' * 80}\n")


def cmd_walk_forward_evaluate(args):
    """Anchored walk-forward strategy evaluation command."""
    print("\n" + "=" * 80)
    print("🧭 Anchored Walk-Forward 评价系统")
    print("=" * 80 + "\n")
    _log_step("walk-forward: 命令开始")

    config = load_config()
    eval_cfg = config.get("evaluation", {})
    _log_step("walk-forward: 配置加载完成")

    try:
        _log_step("walk-forward: 解析公共输入参数")
        resolved = _prepare_walk_forward_inputs(args, config)
        if resolved is None:
            return
        entry_filter_variants, years, base_periods, universe_variants = resolved
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir(
        "walk-forward-evaluate", args, args.output_dir, eval_cfg
    )
    ranking_mode = _resolve_ranking_mode(config, args)
    effective_overlay_on = _resolve_effective_overlay_enabled(config, args)
    walk_forward_mode = _resolve_walk_forward_mode(args)
    min_train_years = max(1, int(args.min_train_years))
    runtime_portfolio_overrides = merge_portfolio_runtime_overrides(args)

    contexts = []
    for universe_name, universe_file in universe_variants:
        prefix = "walk_forward_evaluation"
        if len(universe_variants) > 1 or universe_file is not None:
            prefix = f"walk_forward_evaluation_universe_{_sanitize_name(universe_name)}"
        contexts.append(
            EvaluationRunContext(
                name=universe_name,
                prefix=prefix,
                monitor_list_file=universe_file,
                portfolio_overrides=runtime_portfolio_overrides,
                enable_overlay=effective_overlay_on,
                metadata={"universe_file": universe_file},
            )
        )

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🗂️ 股票池变体: {len(universe_variants)} 个")
    print(f"   {', '.join(name for name, _ in universe_variants)}")
    print(f"🧭 Overlay: {'ENABLED' if effective_overlay_on else 'DISABLED'}")
    print(f"🏁 Ranking Mode: {ranking_mode}")
    print("\n🚀 开始 anchored walk-forward 评估...")

    all_files = []
    for context in contexts:
        print("\n" + "-" * 80)
        print(
            f"🧺 股票池: {context.name}"
            + (
                f" ({context.monitor_list_file})"
                if context.monitor_list_file
                else " (config默认)"
            )
        )
        print("-" * 80)
        files = _run_walk_forward_once(
            args=args,
            config=config,
            years=years,
            walk_forward_mode=walk_forward_mode,
            base_periods=base_periods,
            min_train_years=min_train_years,
            entry_filter_variants=entry_filter_variants,
            output_dir=output_dir,
            prefix=context.prefix,
            monitor_list_file=context.monitor_list_file,
            portfolio_overrides=context.portfolio_overrides,
            enable_overlay=context.enable_overlay,
            ranking_mode=ranking_mode,
        )
        if files:
            all_files.append((context, files))

    if not all_files:
        print("❌ Walk-forward 评估失败: 没有生成任何结果")
        return

    print(f"\n{'=' * 80}")
    print("✅ Anchored Walk-Forward 评价完成！")
    print(f"{'=' * 80}")
    for context, files in all_files:
        universe_file = context.metadata.get("universe_file")
        print(f"[股票池: {context.name}] {universe_file or '(config默认)'}")
        print(f"  🧭 选择明细: {files['selection']}")
        print(f"  🏁 训练排名: {files['train_rank']}")
        print(f"  📄 OOS原始结果: {files['oos_raw']}")
        print(f"  🧪 OOS全候选面板: {files['oos_panel']}")
        print(f"  📊 OOS市场环境分析: {files['oos_regime']}")
        print(f"  🛡️ Final PRS: {files['final_prs']}")
        print(f"  🧾 OOS交易明细: {files['oos_trades']}")
        print(f"  🔁 选择频率: {files['selection_frequency']}")
        print(f"  📝 综合报告: {files['report']}")
        if files.get("final_review"):
            print(f"  📘 中文整合最终报告: {files['final_review']}")
    print(f"{'=' * 80}\n")


def cmd_replay_evaluation(args):
    """Replay historical production state forward from a report anchor."""
    print("\n" + "=" * 80)
    print("⏪ Replay Evaluation")
    print("=" * 80 + "\n")
    _log_step("replay-evaluation: 命令开始")

    config = load_config()
    eval_cfg = config.get("evaluation", {})

    try:
        resolved = _prepare_replay_inputs(args, config)
        if resolved is None:
            return
        entry_filter_variants, universe_variants = resolved
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    report_files = _resolve_replay_report_files(args)
    if not report_files:
        print("❌ 错误: replay 至少需要一个 report 文件")
        return

    config_mgr = ConfigManager(str(get_config_file_path()))
    prod_cfg = config_mgr.get_production_config()

    output_dir = _resolve_output_dir(
        "replay-evaluation",
        args,
        args.output_dir,
        eval_cfg,
    )
    ranking_mode = _resolve_ranking_mode(config, args)
    effective_overlay_on = _resolve_effective_overlay_enabled(config, args)
    runtime_portfolio_overrides = merge_portfolio_runtime_overrides(args)

    all_files: List[
        Tuple[Path, ReplaySeed, EvaluationRunContext, EvaluationOutputBundle, Tuple[str, str, str]]
    ] = []
    for report_file in report_files:
        if not is_local_path(str(report_file)):
            print(f"❌ 错误: replay 仅支持本地 report 文件: {report_file}")
            continue

        try:
            report_date = extract_report_date(report_file)
            prior_signal_file = Path(
                str(prod_cfg.signal_file_pattern).replace("{date}", report_date)
            )
            replay_seed = load_replay_seed(
                report_file=report_file,
                state_file=Path(prod_cfg.state_file),
                history_file=Path(prod_cfg.history_file),
                cash_history_file=Path(prod_cfg.cash_history_file),
                prior_signal_file=prior_signal_file,
                data_root="data",
            )
        except ValueError as e:
            print(f"❌ 错误: {e}")
            continue

        run_args, strategy_context = _build_replay_report_run_args(args, report_file)
        report_prefix_root = f"replay_evaluation_anchor_{_sanitize_name(report_file.stem)}"

        contexts = []
        for universe_name, universe_file in universe_variants:
            prefix = report_prefix_root
            if len(universe_variants) > 1 or universe_file is not None:
                prefix = f"{report_prefix_root}_universe_{_sanitize_name(universe_name)}"
            contexts.append(
                EvaluationRunContext(
                    name=universe_name,
                    prefix=prefix,
                    monitor_list_file=universe_file,
                    portfolio_overrides=runtime_portfolio_overrides,
                    enable_overlay=effective_overlay_on,
                    metadata={"universe_file": universe_file},
                )
            )

        print(f"\n📄 Report anchor: {report_file}")
        print(f"📅 Report date: {replay_seed.report_date}")
        print(f"▶️ Replay start: {replay_seed.replay_start_date}")
        print(f"💼 Seed group: {replay_seed.group_id} ({replay_seed.group_name})")
        print(f"💰 Seed cash: ¥{replay_seed.starting_cash_jpy:,.0f}")
        print(f"📊 Seed baseline equity: ¥{replay_seed.baseline_total_equity_jpy:,.0f}")
        print(f"📦 Seed positions: {len(replay_seed.positions)}")
        print(f"📨 Prior-day signals: {replay_seed.prior_signal_file}")
        print(f"🧾 Pending replay orders: {len(replay_seed.pending_orders)}")
        if strategy_context:
            if strategy_context.get("entry_strategy"):
                print(f"🧭 Auto entry strategy: {strategy_context['entry_strategy']}")
            if strategy_context.get("exit_strategy"):
                print(f"🛑 Auto exit strategy: {strategy_context['exit_strategy']}")
        print(f"🧺 股票池变体: {len(universe_variants)} 个")
        print(f"   {', '.join(name for name, _ in universe_variants)}")
        print(f"🧭 Overlay: {'ENABLED' if effective_overlay_on else 'DISABLED'}")
        print(f"🏁 Ranking Mode: {ranking_mode}")

        for context in contexts:
            temp_evaluator = StrategyEvaluator(
                data_root="data",
                output_dir=output_dir,
                monitor_list_file=context.monitor_list_file,
                replay_seed=replay_seed,
            )
            tickers = temp_evaluator._load_monitor_list()
            try:
                replay_end_date = resolve_latest_available_end_date(tickers, data_root="data")
            except ValueError as e:
                print(f"❌ 股票池 {context.name} 无法解析最新可用日期: {e}")
                continue

            if replay_end_date < replay_seed.replay_start_date:
                print(
                    "❌ 错误: replay 终点早于起点: "
                    f"start={replay_seed.replay_start_date}, end={replay_end_date}"
                )
                continue

            periods = [
                (
                    f"replay_{replay_seed.replay_start_date}_to_{replay_end_date}",
                    replay_seed.replay_start_date,
                    replay_end_date,
                )
            ]

            print("\n" + "-" * 80)
            print(
                f"🧺 股票池: {context.name}"
                + (
                    f" ({context.monitor_list_file})"
                    if context.monitor_list_file
                    else " (config默认 + seeded)"
                )
            )
            print(f"📅 Replay 区间: {periods[0][1]} ~ {periods[0][2]}")
            print("-" * 80)

            bundle = _run_context_bundle(
                args=run_args,
                config=config,
                periods=periods,
                entry_filter_variants=entry_filter_variants,
                output_dir=output_dir,
                prefix=context.prefix,
                monitor_list_file=context.monitor_list_file,
                portfolio_overrides=context.portfolio_overrides,
                enable_overlay=context.enable_overlay,
                ranking_mode=ranking_mode,
                replay_seed=replay_seed,
            )
            if bundle:
                all_files.append((report_file, replay_seed, context, bundle, periods[0]))

    if not all_files:
        print("❌ Replay evaluation 失败: 没有生成任何结果")
        return

    print(f"\n{'=' * 80}")
    print("✅ Replay evaluation 完成！")
    print(f"{'=' * 80}")
    current_report: str | None = None
    for report_file, replay_seed, context, bundle, period in all_files:
        if current_report != str(report_file):
            current_report = str(report_file)
            print(f"[Report: {report_file}]")
            print(f"  📅 Report date: {replay_seed.report_date}")
            print(f"  ▶️ Replay start: {replay_seed.replay_start_date}")
        universe_file = context.metadata.get("universe_file")
        print(f"[股票池: {context.name}] {universe_file or '(config默认 + seeded)'}")
        print(f"  ⏱️ Replay区间: {period[1]} ~ {period[2]}")
        print(f"  📄 原始结果: {bundle.segmented['raw']}")
        print(f"  📊 市场环境分析: {bundle.segmented['regime']}")
        print(f"  🧾 原始交易明细: {bundle.segmented['trades']}")
        print(f"  📝 综合报告: {bundle.segmented['report']}")
        if bundle.final_report:
            print(f"  📘 中文整合最终报告: {bundle.final_report}")
    print(f"{'=' * 80}\n")


def cmd_pos_evaluation(args):
    """仓位参数批量评价命令（读取 evaluation-position.json）"""
    print("\n" + "=" * 80)
    print("📦 仓位参数批量评价系统 (pos-evaluation)")
    print("=" * 80 + "\n")

    config = load_config()
    eval_cfg = config.get("evaluation", {})
    try:
        resolved = _prepare_common_evaluation_inputs(args, config)
        if resolved is None:
            return
        entry_filter_variants, periods, universe_variants = resolved
        normalized_profiles = _load_position_profiles(args, eval_cfg)
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir(
        "pos-evaluation", args, args.output_dir, eval_cfg
    )
    ranking_mode = _resolve_ranking_mode(config, args)

    if args.overlay_modes:
        overlay_modes = args.overlay_modes
    else:
        overlay_default_on = _resolve_effective_overlay_enabled(config, args)
        overlay_modes = ["on"] if overlay_default_on else ["off"]
    overlay_modes = [m.lower() for m in overlay_modes]

    contexts: List[EvaluationRunContext] = []
    for profile in normalized_profiles:
        name = profile["name"]
        overrides = {
            "position_sizing_mode": profile["position_sizing_mode"],
            "max_positions": profile["max_positions"],
            "max_position_pct": profile["max_position_pct"],
        }
        if profile.get("atr_position_sizing"):
            overrides["atr_position_sizing"] = profile["atr_position_sizing"]
        if profile["starting_capital_jpy"] is not None:
            overrides["starting_capital_jpy"] = profile["starting_capital_jpy"]
        overrides = merge_portfolio_runtime_overrides(args, overrides) or overrides

        for overlay_mode in overlay_modes:
            for universe_name, universe_file in universe_variants:
                contexts.append(
                    EvaluationRunContext(
                        name=f"{name}|overlay={overlay_mode}|universe={universe_name}",
                        prefix=(
                            f"position_eval_{_sanitize_name(name)}_overlay_{overlay_mode}"
                            f"_univ_{_sanitize_name(universe_name)}"
                        ),
                        monitor_list_file=universe_file,
                        portfolio_overrides=overrides,
                        enable_overlay=(overlay_mode == "on"),
                        metadata={
                            "position_profile": name,
                            "position_sizing_mode": overrides["position_sizing_mode"],
                            "overlay_mode": overlay_mode,
                            "universe_name": universe_name,
                            "universe_file": universe_file or "",
                            "max_positions": overrides["max_positions"],
                            "max_position_pct": overrides["max_position_pct"],
                            "starting_capital_jpy": int(
                                overrides.get("starting_capital_jpy", 8_000_000)
                            ),
                        },
                    )
                )

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🗂️ 股票池变体: {len(universe_variants)} 个")
    print(f"   {', '.join(name for name, _ in universe_variants)}")
    print(f"🧭 Overlay Modes: {', '.join(overlay_modes)}")
    print(f"🏁 Ranking Mode: {ranking_mode}")
    print(f"\n📚 仓位组合: {len(normalized_profiles)} 个")

    all_files: List[Tuple[EvaluationRunContext, EvaluationOutputBundle]] = []
    combined_raw_frames = []
    combined_regime_frames = []
    combined_trade_frames = []
    combined_continuous_raw_frames = []
    combined_continuous_regime_frames = []
    combined_continuous_trade_frames = []
    for context in contexts:
        meta = context.metadata
        print("\n" + "-" * 80)
        print(
            f"🚀 运行组合 {meta['position_profile']} [{meta['overlay_mode'].upper()}] × "
            f"股票池 {meta['universe_name']}: "
            f"sizing={meta['position_sizing_mode']}, "
            f"max_positions={meta['max_positions']}, "
            f"max_position_pct={meta['max_position_pct']}, "
            f"starting_capital_jpy={meta['starting_capital_jpy']}"
        )
        if context.monitor_list_file:
            print(f"   股票池文件: {context.monitor_list_file}")
        else:
            print("   股票池文件: (config默认)")
        print("-" * 80)

        results = _run_contexts(
            args=args,
            config=config,
            periods=periods,
            entry_filter_variants=entry_filter_variants,
            output_dir=output_dir,
            contexts=[context],
            ranking_mode=ranking_mode,
        )
        if not results:
            print(
                f"❌ 组合 {meta['position_profile']} [{meta['overlay_mode'].upper()}] × "
                f"股票池 {meta['universe_name']} 未生成结果"
            )
            continue

        context_result, bundle = results[0]
        all_files.append((context_result, bundle))
        print(
            f"✅ 组合 {meta['position_profile']} [{meta['overlay_mode'].upper()}] × "
            f"股票池 {meta['universe_name']} 完成"
        )

        _append_combined_context_frame(
            bundle.segmented.get("raw"),
            meta,
            combined_raw_frames,
            "segmented raw",
        )
        _append_combined_context_frame(
            bundle.segmented.get("regime"),
            meta,
            combined_regime_frames,
            "segmented regime",
        )
        _append_combined_context_frame(
            bundle.segmented.get("trades"),
            meta,
            combined_trade_frames,
            "segmented trades",
        )

        if bundle.continuous:
            _append_combined_context_frame(
                bundle.continuous.get("raw"),
                meta,
                combined_continuous_raw_frames,
                "continuous raw",
            )
            _append_combined_context_frame(
                bundle.continuous.get("regime"),
                meta,
                combined_continuous_regime_frames,
                "continuous regime",
            )
            _append_combined_context_frame(
                bundle.continuous.get("trades"),
                meta,
                combined_continuous_trade_frames,
                "continuous trades",
            )

    if not all_files:
        print("\n❌ 全部组合执行失败")
        return

    print(f"\n{'=' * 80}")
    print("✅ pos-evaluation 完成")
    print(f"{'=' * 80}")
    for context, bundle in all_files:
        print(f"[{context.name}]")
        print("  🧩 按年分段结果:")
        _print_saved_files(bundle.segmented, indent="    ")
        if bundle.continuous:
            print("  ♾️ 全年连续聚合结果:")
            _print_saved_files(bundle.continuous, indent="    ")
        if bundle.annual_companion:
            print("  🏆 Continuous+Stability结果:")
            _print_companion_files(bundle.annual_companion, indent="    ")

    combined_segmented_files = _write_combined_position_output_family(
        output_dir=output_dir,
        data_root="data",
        family_prefix="position_eval_combined",
        raw_frames=combined_raw_frames,
        regime_frames=combined_regime_frames,
        trade_frames=combined_trade_frames,
    )
    combined_continuous_files = _write_combined_position_output_family(
        output_dir=output_dir,
        data_root="data",
        family_prefix="position_eval_combined_continuous",
        raw_frames=combined_continuous_raw_frames,
        regime_frames=combined_continuous_regime_frames,
        trade_frames=combined_continuous_trade_frames,
    )
    combined_companion_files = _write_annual_continuous_stability_rank(
        output_dir=output_dir,
        prefix="position_eval_combined",
        segmented_raw_path=combined_segmented_files.get("raw"),
        continuous_raw_path=combined_continuous_files.get("raw"),
    )
    if combined_companion_files:
        print("📦 合并Continuous+Stability结果:")
        _print_companion_files(combined_companion_files, indent="   ")

    print(f"{'=' * 80}\n")
