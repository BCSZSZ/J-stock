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


def _resolve_output_dir(user_output_dir):
    if user_output_dir:
        return user_output_dir

    cfg = load_config()
    configured = cfg.get("evaluation", {}).get("output_dir")
    if configured:
        if is_local_path(configured):
            Path(configured).mkdir(parents=True, exist_ok=True)
        print(f"📁 输出目录: {configured} (from config)")
        return str(configured)

    DEFAULT_EVALUATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"📁 输出目录: {DEFAULT_EVALUATION_OUTPUT_DIR}")
    return str(DEFAULT_EVALUATION_OUTPUT_DIR)


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
    """Resolve final overlay switch from CLI/config/override in one place."""
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


def _resolve_entry_exit_strategies(args, eval_cfg):
    """Resolve entry and exit strategy lists from CLI/config with de-duplication."""
    entry_strategies = args.entry_strategies
    if not entry_strategies:
        entry_strategies = eval_cfg.get("default_entry_strategies")
        if entry_strategies:
            print("\n🧭 使用 evaluation.default_entry_strategies")
            print(f"   入场策略: {', '.join(entry_strategies)}")

    original_entry_count = len(entry_strategies) if entry_strategies else 0
    entry_strategies = _dedupe_preserve_order(entry_strategies)
    if entry_strategies and len(entry_strategies) != original_entry_count:
        print(f"⚠️ 入场策略去重: {original_entry_count} -> {len(entry_strategies)}")

    exit_strategies = args.exit_strategies
    if not exit_strategies:
        exit_strategies = eval_cfg.get("default_exit_strategies")
        if exit_strategies:
            print("\n🧭 使用 evaluation.default_exit_strategies")
            print(f"   出场策略: {', '.join(exit_strategies)}")

    if not exit_strategies:
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
    )


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

    exit_confirm_days = getattr(args, "exit_confirm_days", None)
    if exit_confirm_days is None:
        exit_confirm_days = int(eval_cfg.get("exit_confirmation_days", 1))
    exit_confirm_days = max(1, int(exit_confirm_days))

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
    """Run all contexts and return list of successful (context, files)."""
    results: List[Tuple[EvaluationRunContext, Dict[str, str]]] = []
    for context in contexts:
        files = _run_once(
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
        if files:
            results.append((context, files))
    return results


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
    exit_confirm_days = getattr(args, "exit_confirm_days", None)
    if exit_confirm_days is None:
        exit_confirm_days = int(eval_cfg.get("exit_confirmation_days", 1))
    exit_confirm_days = max(1, int(exit_confirm_days))
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

    output_dir = _resolve_output_dir(args.output_dir)
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

    print(f"\n{'=' * 80}")
    print("✅ 策略评价完成！")
    print(f"{'=' * 80}")
    for context, files in all_files:
        universe_file = context.metadata.get("universe_file")
        print(f"[股票池: {context.name}] {universe_file or '(config默认)'}")
        print(f"  📄 原始结果: {files['raw']}")
        print(f"  📊 市场环境分析: {files['regime']}")
        if files.get("trades"):
            print(f"  🧾 原始交易明细: {files['trades']}")
        if files.get("exit_trigger_summary"):
            print(f"  🚪 第一层退出原因明细: {files['exit_trigger_summary']}")
        if files.get("exit_urgency_summary"):
            print(f"  📚 第二层退出类型汇总: {files['exit_urgency_summary']}")
        if files.get("exit_urgency_contribution"):
            print(f"  📈 第三层退出贡献汇总: {files['exit_urgency_contribution']}")
        if files.get("exit_summary_report"):
            print(f"  🧠 退出结果总结报告: {files['exit_summary_report']}")
        if files.get("legacy_rank"):
            print(f"  🏁 Legacy排名: {files['legacy_rank']}")
        if files.get("target20_rank"):
            print(f"  🎯 Target20排名: {files['target20_rank']}")
        if files.get("risk60_profit40_rank"):
            print(f"  ⚖️ Risk60/Profit40排名: {files['risk60_profit40_rank']}")
        print(f"  📝 综合报告: {files['report']}")
    print(f"{'=' * 80}\n")


def cmd_walk_forward_evaluate(args):
    """Anchored walk-forward strategy evaluation command."""
    print("\n" + "=" * 80)
    print("🧭 Anchored Walk-Forward 评价系统")
    print("=" * 80 + "\n")
    _log_step("walk-forward: 命令开始")

    config = load_config()
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

    output_dir = _resolve_output_dir(args.output_dir)
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

    output_dir = _resolve_output_dir(args.output_dir)
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

    all_files: List[Tuple[EvaluationRunContext, Dict[str, str]]] = []
    combined_raw_frames = []
    combined_regime_frames = []
    combined_trade_frames = []
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

        context_result, files = results[0]
        all_files.append((context_result, files))
        print(
            f"✅ 组合 {meta['position_profile']} [{meta['overlay_mode'].upper()}] × "
            f"股票池 {meta['universe_name']} 完成"
        )

        try:
            raw_df = pd.read_csv(files["raw"])
            for key, value in meta.items():
                raw_df[key] = value
            combined_raw_frames.append(raw_df)
        except Exception as e:
            print(
                f"⚠️ 合并raw失败 ({meta['position_profile']}/{meta['overlay_mode']}/{meta['universe_name']}): {e}"
            )

        try:
            regime_df = pd.read_csv(files["regime"])
            for key, value in meta.items():
                regime_df[key] = value
            combined_regime_frames.append(regime_df)
        except Exception as e:
            print(
                f"⚠️ 合并regime失败 ({meta['position_profile']}/{meta['overlay_mode']}/{meta['universe_name']}): {e}"
            )

        try:
            if files.get("trades"):
                trades_df = pd.read_csv(files["trades"])
                for key, value in meta.items():
                    trades_df[key] = value
                combined_trade_frames.append(trades_df)
        except Exception as e:
            print(
                f"⚠️ 合并trades失败 ({meta['position_profile']}/{meta['overlay_mode']}/{meta['universe_name']}): {e}"
            )

    if not all_files:
        print("\n❌ 全部组合执行失败")
        return

    print(f"\n{'=' * 80}")
    print("✅ pos-evaluation 完成")
    print(f"{'=' * 80}")
    for context, files in all_files:
        print(f"[{context.name}]")
        print(f"  📄 原始结果: {files['raw']}")
        print(f"  📊 市场环境分析: {files['regime']}")
        if files.get("trades"):
            print(f"  🧾 原始交易明细: {files['trades']}")
        if files.get("exit_trigger_summary"):
            print(f"  🚪 第一层退出原因明细: {files['exit_trigger_summary']}")
        if files.get("exit_urgency_summary"):
            print(f"  📚 第二层退出类型汇总: {files['exit_urgency_summary']}")
        if files.get("exit_urgency_contribution"):
            print(f"  📈 第三层退出贡献汇总: {files['exit_urgency_contribution']}")
        if files.get("exit_summary_report"):
            print(f"  🧠 退出结果总结报告: {files['exit_summary_report']}")
        if files.get("legacy_rank"):
            print(f"  🏁 Legacy排名: {files['legacy_rank']}")
        if files.get("target20_rank"):
            print(f"  🎯 Target20排名: {files['target20_rank']}")
        if files.get("risk60_profit40_rank"):
            print(f"  ⚖️ Risk60/Profit40排名: {files['risk60_profit40_rank']}")
        print(f"  📝 综合报告: {files['report']}")

    if combined_raw_frames:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_raw = pd.concat(combined_raw_frames, ignore_index=True)
        combined_raw_path = Path(output_dir) / f"position_eval_combined_raw_{ts}.csv"
        combined_raw.to_csv(combined_raw_path, index=False, encoding="utf-8-sig")
        print(f"\n📦 合并Raw结果: {combined_raw_path}")

    if combined_regime_frames:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_regime = pd.concat(combined_regime_frames, ignore_index=True)
        combined_regime_path = Path(output_dir) / f"position_eval_combined_by_regime_{ts}.csv"
        combined_regime.to_csv(combined_regime_path, index=False, encoding="utf-8-sig")
        print(f"📦 合并Regime结果: {combined_regime_path}")

    if combined_trade_frames:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        combined_trades = pd.concat(combined_trade_frames, ignore_index=True)
        combined_trades_path = Path(output_dir) / f"position_eval_combined_trades_{ts}.csv"
        combined_trades.to_csv(combined_trades_path, index=False, encoding="utf-8-sig")
        print(f"📦 合并Trade结果: {combined_trades_path}")

        combined_reason_detail = StrategyEvaluator.build_exit_reason_detail_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_trigger_summary_path = Path(output_dir) / f"position_eval_combined_exit_trigger_summary_{ts}.csv"
        combined_reason_detail.to_csv(
            combined_trigger_summary_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第一层退出原因明细: {combined_trigger_summary_path}")

        combined_urgency_summary = StrategyEvaluator.build_exit_urgency_summary_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_urgency_summary_path = Path(output_dir) / f"position_eval_combined_exit_urgency_summary_{ts}.csv"
        combined_urgency_summary.to_csv(
            combined_urgency_summary_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第二层退出类型汇总: {combined_urgency_summary_path}")

        combined_urgency_contribution = StrategyEvaluator.build_exit_urgency_contribution_df(
            combined_trades,
            full_exit_only=False,
        )
        combined_urgency_contribution_path = Path(output_dir) / f"position_eval_combined_exit_urgency_contribution_{ts}.csv"
        combined_urgency_contribution.to_csv(
            combined_urgency_contribution_path,
            index=False,
            encoding="utf-8-sig",
        )
        print(f"📦 合并第三层退出贡献汇总: {combined_urgency_contribution_path}")

        combined_exit_summary_report_path = Path(output_dir) / f"position_eval_combined_exit_summary_report_{ts}.md"
        StrategyEvaluator.write_exit_summary_markdown(
            combined_exit_summary_report_path,
            combined_reason_detail,
            combined_urgency_summary,
            combined_urgency_contribution,
        )
        print(f"📦 合并退出结果总结报告: {combined_exit_summary_report_path}")

    print(f"{'=' * 80}\n")
