import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.evaluation import (
    MarketRegime,
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods,
)
from src.config.runtime import is_local_path

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

    if run_kind == "pos-evaluation":
        profile_names = _dedupe_preserve_order(
            getattr(args, "profile_name", None)
            or eval_cfg.get("default_profile_names", [])
        )
        parts.append(_summarize_selection_for_dir("profile", profile_names))

    slug = "__".join(part for part in parts if part)
    return slug[:180].rstrip("_")


def _resolve_output_dir(run_kind: str, args, user_output_dir, eval_cfg):
    output_root = _resolve_output_root(user_output_dir)

    if not is_local_path(output_root):
        print(f"📁 输出目录: {output_root}")
        return output_root

    now = datetime.now()
    date_dir = Path(output_root) / now.strftime("%Y%m%d")
    run_slug = _build_output_run_slug(run_kind, args, eval_cfg)
    run_dir = date_dir / f"{run_slug}__{now.strftime('%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"📁 输出根目录: {output_root}")
    print(f"📁 本次输出目录: {run_dir}")
    return str(run_dir)


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

    print("\n📊 时间段列表:")
    for label, start, end in periods[:5]:
        print(f"   {label}: {start} ~ {end}")
    if len(periods) > 5:
        print(f"   ... 共 {len(periods)} 个时间段")

    return periods


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
    if arg_mode in {"legacy", "target20", "risk60_profit40"}:
        return arg_mode

    cfg_mode = config.get("evaluation", {}).get("ranking", {}).get("mode")
    if cfg_mode == "risk60_profit40_v2":
        return "risk60_profit40"
    if cfg_mode in {"legacy", "target20", "risk60_profit40"}:
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
    periods = _build_periods(args)
    universe_variants = _resolve_universe_variants(args.universe_file)

    return entry_filter_variants, periods, universe_variants


def _prepare_walk_forward_inputs(args, config):
    """Resolve entry filters, annual years and universe variants for walk-forward."""
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return None

    entry_filter_variants = _resolve_entry_filter_variants(
        config,
        mode=args.entry_filter_mode,
        selected_names=selected_filter_names,
    )

    years = sorted({int(year) for year in (args.years or [])})
    if not years:
        raise ValueError("walk-forward模式需要指定--years参数")

    min_train_years = max(1, int(args.min_train_years))
    if len(years) < min_train_years + 1:
        raise ValueError(
            f"至少需要 {min_train_years + 1} 个年份，当前仅提供 {len(years)} 个"
        )

    universe_variants = _resolve_universe_variants(args.universe_file)

    print("📅 Anchored Walk-Forward 模式")
    print(f"   年份: {', '.join(map(str, years))}")
    print(f"   最小训练年份数: {min_train_years}")
    print(f"   测试窗口数: {len(years) - min_train_years}")

    return entry_filter_variants, years, universe_variants


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
):
    """Create a StrategyEvaluator with the shared runtime settings."""
    _, overlay_config = _resolve_overlay_config(
        config=config,
        args=args,
        enable_overlay_override=enable_overlay,
    )

    ranking_strategies = getattr(args, "ranking_strategies", None)

    return StrategyEvaluator(
        data_root="data",
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        verbose=args.verbose,
        exit_confirmation_days=exit_confirm_days,
        overlay_config=overlay_config,
        entry_filter_config=config.get("evaluation", {}).get("filters", {}).get(
            "default", {}
        ),
        entry_filter_variants=entry_filter_variants,
        portfolio_overrides=portfolio_overrides,
        ranking_strategies=ranking_strategies,
    )


def _print_saved_files(files: Dict[str, str], indent: str = "  ") -> None:
    print(f"{indent}📄 原始结果: {files['raw']}")
    print(f"{indent}📊 市场环境分析: {files['regime']}")
    if files.get("trades"):
        print(f"{indent}🧾 原始交易明细: {files['trades']}")
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
        if "exit_confirmation_days" in raw_df.columns:
            raw_df["exit_confirmation_days"] = (
                pd.to_numeric(raw_df["exit_confirmation_days"], errors="coerce")
                .fillna(0)
                .astype(int)
            )

    if not trades_df.empty:
        if "entry_filter" in trades_df.columns:
            trades_df["entry_filter"] = trades_df["entry_filter"].fillna("off")
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
        f"分段原始结果：{Path(bundle.segmented.get('raw', '')).name if bundle.segmented.get('raw') else '-'}",
        f"分段交易明细：{Path(bundle.segmented.get('trades', '')).name if bundle.segmented.get('trades') else '-'}",
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


def _select_rank_df(evaluator: StrategyEvaluator, ranking_mode: str):
    """Return the ranking table and the primary score column for the chosen mode."""
    if ranking_mode == "legacy":
        return evaluator.rank_by_legacy_goal(), "avg_rank"
    if ranking_mode == "risk60_profit40":
        return evaluator.rank_by_risk60_profit40(), "risk60_profit40_score"
    return evaluator.rank_by_target20_goal(), "target20_score"


def _build_walk_forward_windows(years: List[int], min_train_years: int):
    windows = []
    for idx in range(min_train_years, len(years)):
        train_years = years[:idx]
        test_year = years[idx]
        windows.append(
            {
                "window_index": len(windows) + 1,
                "train_years": train_years,
                "train_label": f"{train_years[0]}-{train_years[-1]}",
                "test_year": test_year,
            }
        )
    return windows


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


def _write_walk_forward_report(
    output_file: Path,
    ranking_mode: str,
    years: List[int],
    min_train_years: int,
    selection_df: pd.DataFrame,
    selection_freq_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    regime_df: pd.DataFrame,
):
    lines = [
        "# Anchored Walk-Forward Evaluation",
        "",
        f"- Years: {', '.join(map(str, years))}",
        f"- Minimum train years: {min_train_years}",
        f"- Ranking mode: {ranking_mode}",
        "- Selection protocol: expanding annual train window, next-year out-of-sample test, report only test windows.",
        "",
    ]

    if not selection_df.empty:
        selection_view = selection_df[[
            "window_index",
            "train_label",
            "test_year",
            "selected_entry_strategy",
            "selected_exit_strategy",
            "selected_entry_filter",
            "train_selection_score",
        ]].copy()
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
        oos_view = oos_df[[
            "window_index",
            "train_label",
            "period",
            "entry_strategy",
            "exit_strategy",
            "entry_filter",
            "return_pct",
            "alpha",
            "sharpe_ratio",
            "max_drawdown_pct",
            "win_rate_pct",
        ]].copy()
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

    entry_strategies, exit_strategies = _resolve_entry_exit_strategies(args, eval_cfg)
    windows = _build_walk_forward_windows(years, min_train_years)
    filter_cfg_map = {name: (cfg or {}) for name, cfg in entry_filter_variants}
    out_dir = Path(output_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    train_rank_frames = []
    selection_rows = []
    oos_frames = []
    oos_trade_frames = []

    print(f"🧷 Exit确认天数: {exit_confirm_days}")
    print(f"🪟 Walk-forward窗口数: {len(windows)}")

    for window in windows:
        train_periods = create_annual_periods(window["train_years"])
        test_periods = create_annual_periods([window["test_year"]])
        print(
            f"\n[WF {window['window_index']}/{len(windows)}] 训练 {window['train_label']} -> 测试 {window['test_year']}",
            flush=True,
        )

        train_evaluator = _build_evaluator(
            args=args,
            config=config,
            output_dir=output_dir,
            monitor_list_file=monitor_list_file,
            portfolio_overrides=portfolio_overrides,
            enable_overlay=enable_overlay,
            exit_confirm_days=exit_confirm_days,
            entry_filter_variants=entry_filter_variants,
        )
        train_df = train_evaluator.run_evaluation(
            periods=train_periods,
            entry_strategies=entry_strategies,
            exit_strategies=exit_strategies,
        )
        if train_df.empty:
            print("⚠️ 训练结果为空，跳过该窗口")
            continue

        train_rank_df, score_col = _select_rank_df(train_evaluator, ranking_mode)
        if train_rank_df.empty:
            print("⚠️ 训练排名为空，跳过该窗口")
            continue

        train_rank_df = train_rank_df.copy()
        train_rank_df.insert(0, "window_index", window["window_index"])
        train_rank_df.insert(1, "train_label", window["train_label"])
        train_rank_df.insert(2, "test_year", window["test_year"])
        train_rank_frames.append(train_rank_df)

        selected = train_rank_df.iloc[0]
        selected_filter_name = str(selected["entry_filter"])
        selected_filter_cfg = filter_cfg_map.get(selected_filter_name, {})
        selection_rows.append(
            {
                "window_index": window["window_index"],
                "train_label": window["train_label"],
                "test_year": window["test_year"],
                "selected_entry_strategy": selected["entry_strategy"],
                "selected_exit_strategy": selected["exit_strategy"],
                "selected_entry_filter": selected_filter_name,
                "train_score_metric": score_col,
                "train_selection_score": selected.get(score_col),
            }
        )

        print(
            "   训练期选中: "
            f"{selected['entry_strategy']} × {selected['exit_strategy']} × {selected_filter_name} "
            f"({score_col}={selected.get(score_col)})",
            flush=True,
        )

        test_evaluator = _build_evaluator(
            args=args,
            config=config,
            output_dir=output_dir,
            monitor_list_file=monitor_list_file,
            portfolio_overrides=portfolio_overrides,
            enable_overlay=enable_overlay,
            exit_confirm_days=exit_confirm_days,
            entry_filter_variants=[(selected_filter_name, selected_filter_cfg)],
        )
        test_df = test_evaluator.run_evaluation(
            periods=test_periods,
            entry_strategies=[selected["entry_strategy"]],
            exit_strategies=[selected["exit_strategy"]],
        )
        if test_df.empty:
            print("⚠️ 测试结果为空，跳过该窗口")
            continue

        test_df = test_df.copy()
        test_df.insert(0, "window_index", window["window_index"])
        test_df.insert(1, "train_label", window["train_label"])
        test_df.insert(2, "test_year", window["test_year"])
        test_df["train_score_metric"] = score_col
        test_df["train_selection_score"] = selected.get(score_col)
        oos_frames.append(test_df)

        trade_df = test_evaluator._create_trade_results_dataframe()
        if not trade_df.empty:
            trade_df = trade_df.copy()
            trade_df.insert(0, "window_index", window["window_index"])
            trade_df.insert(1, "train_label", window["train_label"])
            trade_df.insert(2, "test_year", window["test_year"])
            oos_trade_frames.append(trade_df)

    selection_df = pd.DataFrame(selection_rows)
    train_rank_all_df = pd.concat(train_rank_frames, ignore_index=True) if train_rank_frames else pd.DataFrame()
    oos_df = pd.concat(oos_frames, ignore_index=True) if oos_frames else pd.DataFrame()
    oos_trade_df = pd.concat(oos_trade_frames, ignore_index=True) if oos_trade_frames else pd.DataFrame()

    selection_freq_df = pd.DataFrame()
    if not selection_df.empty:
        selection_freq_df = (
            selection_df.groupby(
                ["selected_entry_strategy", "selected_exit_strategy", "selected_entry_filter"],
                dropna=False,
            )
            .agg(
                selected_windows=("test_year", "count"),
                test_years=("test_year", lambda s: ", ".join(map(str, s))),
            )
            .reset_index()
            .sort_values(["selected_windows", "selected_entry_strategy"], ascending=[False, True])
        )

    regime_df = _build_walk_forward_regime_summary(oos_df)

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

    regime_file = out_dir / f"{prefix}_oos_by_regime_{timestamp}.csv"
    regime_df.to_csv(regime_file, index=False, encoding="utf-8-sig")
    files["oos_regime"] = str(regime_file)

    selection_freq_file = out_dir / f"{prefix}_selection_frequency_{timestamp}.csv"
    selection_freq_df.to_csv(selection_freq_file, index=False, encoding="utf-8-sig")
    files["selection_frequency"] = str(selection_freq_file)

    trades_file = out_dir / f"{prefix}_oos_trades_{timestamp}.csv"
    oos_trade_df.to_csv(trades_file, index=False, encoding="utf-8-sig")
    files["oos_trades"] = str(trades_file)

    report_file = out_dir / f"{prefix}_report_{timestamp}.md"
    _write_walk_forward_report(
        output_file=report_file,
        ranking_mode=ranking_mode,
        years=years,
        min_train_years=min_train_years,
        selection_df=selection_df,
        selection_freq_df=selection_freq_df,
        oos_df=oos_df,
        regime_df=regime_df,
    )
    files["report"] = str(report_file)

    print(f"✅ Walk-forward 选择结果已保存: {selection_file}")
    print(f"✅ Walk-forward 训练排名已保存: {train_rank_file}")
    print(f"✅ Walk-forward 测试结果已保存: {oos_raw_file}")
    print(f"✅ Walk-forward 市场环境结果已保存: {regime_file}")
    print(f"✅ Walk-forward 报告已保存: {report_file}")

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
    )
    if not segmented_files:
        return None

    bundle = EvaluationOutputBundle(segmented=segmented_files)
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
        if "max_positions" not in item or "max_position_pct" not in item:
            print(f"⚠️ 跳过 {name}: 缺少 max_positions 或 max_position_pct")
            continue
        normalized_profiles.append(
            {
                "name": name,
                "max_positions": int(item["max_positions"]),
                "max_position_pct": float(item["max_position_pct"]),
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

    evaluator = _build_evaluator(
        args=args,
        config=config,
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        portfolio_overrides=portfolio_overrides,
        enable_overlay=enable_overlay,
        exit_confirm_days=exit_confirm_days,
        entry_filter_variants=entry_filter_variants,
    )
    _log_step("_run_once: StrategyEvaluator 初始化完成")

    print(f"🧷 Exit确认天数: {exit_confirm_days}")

    entry_strategies, exit_strategies = _resolve_entry_exit_strategies(args, eval_cfg)

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
                portfolio_overrides=None,
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
        entry_filter_variants, years, universe_variants = resolved
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir(
        "walk-forward-evaluate", args, args.output_dir, eval_cfg
    )
    ranking_mode = _resolve_ranking_mode(config, args)
    effective_overlay_on = _resolve_effective_overlay_enabled(config, args)
    min_train_years = max(1, int(args.min_train_years))

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
                portfolio_overrides=None,
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
        print(f"  📊 OOS市场环境分析: {files['oos_regime']}")
        print(f"  🧾 OOS交易明细: {files['oos_trades']}")
        print(f"  🔁 选择频率: {files['selection_frequency']}")
        print(f"  📝 综合报告: {files['report']}")
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
            "max_positions": profile["max_positions"],
            "max_position_pct": profile["max_position_pct"],
        }
        if profile["starting_capital_jpy"] is not None:
            overrides["starting_capital_jpy"] = profile["starting_capital_jpy"]

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
        family_prefix="position_eval_combined",
        raw_frames=combined_raw_frames,
        regime_frames=combined_regime_frames,
        trade_frames=combined_trade_frames,
    )
    combined_continuous_files = _write_combined_position_output_family(
        output_dir=output_dir,
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
