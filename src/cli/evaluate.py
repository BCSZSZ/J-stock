import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.evaluation import (
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods,
)
from src.config.runtime import is_local_path

from .common import load_config


DEFAULT_EVALUATION_OUTPUT_DIR = Path("strategy_evaluation")


def _log_step(message: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")


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
    variants_cfg = eval_cfg.get("entry_filters")
    if isinstance(variants_cfg, list) and variants_cfg:
        variants = []
        for idx, item in enumerate(variants_cfg, 1):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or f"filter_{idx}")
            filter_cfg = {k: v for k, v in item.items() if k != "name"}
            variants.append((name, filter_cfg))
        if variants:
            return variants

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
    default_filter_cfg = eval_cfg.get("entry_filter", {})
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
                "grid模式需要在config.evaluation.entry_filters中定义至少1个过滤器"
            )
        if not selected_names:
            return named_variants
        missing = [name for name in selected_names if name not in named_map]
        if missing:
            raise ValueError(f"未找到entry filter: {', '.join(missing)}")
        return [(name, named_map[name]) for name in selected_names]

    if selected_names:
        if not named_variants:
            raise ValueError("当前配置未定义entry_filters，无法按名称选择")
        missing = [name for name in selected_names if name not in named_map]
        if missing:
            raise ValueError(f"未找到entry filter: {', '.join(missing)}")
        return [(name, named_map[name]) for name in selected_names]
    if named_variants:
        return named_variants
    return [("default", default_filter_cfg)]


def _print_available_entry_filters(cfg):
    eval_cfg = cfg.get("evaluation", {})
    default_filter_cfg = eval_cfg.get("entry_filter", {})
    named_variants = _load_entry_filter_variants(cfg)

    print("\n🧪 可用 Entry Filter:")
    print(
        f"   - default (fallback): enabled={default_filter_cfg.get('enabled', False)}"
    )
    if named_variants:
        for name, variant_cfg in named_variants:
            print(f"   - {name}: enabled={variant_cfg.get('enabled', False)}")
    else:
        print("   - (未定义 evaluation.entry_filters)")


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


def _resolve_effective_overlay_enabled(eval_cfg, args, override: bool = None) -> bool:
    """Resolve final overlay switch from CLI/config/override in one place."""
    if override is not None:
        return bool(override)

    arg_overlay = getattr(args, "enable_overlay", None)
    if arg_overlay is None:
        return bool(eval_cfg.get("default_overlay_enabled", False))
    return bool(arg_overlay)


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
    use_overlay = _resolve_effective_overlay_enabled(
        eval_cfg=eval_cfg,
        args=args,
        override=enable_overlay,
    )
    overlay_config = config if use_overlay else {}
    _log_step(f"_run_once: overlay={'on' if use_overlay else 'off'}")

    evaluator = StrategyEvaluator(
        data_root="data",
        output_dir=output_dir,
        monitor_list_file=monitor_list_file,
        verbose=args.verbose,
        exit_confirmation_days=exit_confirm_days,
        overlay_config=overlay_config,
        entry_filter_config=config.get("evaluation", {}).get("entry_filter", {}),
        entry_filter_variants=entry_filter_variants,
        portfolio_overrides=portfolio_overrides,
    )
    _log_step("_run_once: StrategyEvaluator 初始化完成")

    print(f"🧷 Exit确认天数: {exit_confirm_days}")

    entry_strategies = args.entry_strategies
    if not entry_strategies:
        entry_strategies = eval_cfg.get("default_entry_strategies")
        if entry_strategies:
            print("\n🧭 使用 evaluation.default_entry_strategies")
            print(f"   入场策略: {', '.join(entry_strategies)}")
    original_entry_count = len(entry_strategies) if entry_strategies else 0
    entry_strategies = _dedupe_preserve_order(entry_strategies)
    if entry_strategies and len(entry_strategies) != original_entry_count:
        print(
            f"⚠️ 入场策略去重: {original_entry_count} -> {len(entry_strategies)}"
        )

    exit_strategies = args.exit_strategies
    if not exit_strategies:
        exit_strategies = eval_cfg.get("default_exit_strategies")
        if exit_strategies:
            print("\n🧭 使用 evaluation.default_exit_strategies")
            print(f"   出场策略: {', '.join(exit_strategies)}")

    if not exit_strategies:
        exit_strategies = config.get("entry_eval_exit_strategies")
        if exit_strategies:
            print("\n🧭 使用配置文件中的评估出场策略 (entry_eval_exit_strategies)")
            print(f"   出场策略: {', '.join(exit_strategies)}")
        else:
            print(
                "\n⚠️ 警告: 配置文件中未定义entry_eval_exit_strategies，将使用所有可用策略"
            )
    original_exit_count = len(exit_strategies) if exit_strategies else 0
    exit_strategies = _dedupe_preserve_order(exit_strategies)
    if exit_strategies and len(exit_strategies) != original_exit_count:
        print(
            f"⚠️ 出场策略去重: {original_exit_count} -> {len(exit_strategies)}"
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
    files = evaluator.save_results(prefix=prefix)
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
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return

    try:
        _log_step("evaluate: 解析 entry filter 变体")
        entry_filter_variants = _resolve_entry_filter_variants(
            config,
            mode=args.entry_filter_mode,
            selected_names=selected_filter_names,
        )
        _log_step("evaluate: 构建时间段")
        periods = _build_periods(args)
        _log_step("evaluate: 解析股票池变体")
        universe_variants = _resolve_universe_variants(args.universe_file)
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir(args.output_dir)
    _log_step(f"evaluate: 输出目录就绪 -> {output_dir}")

    eval_cfg = config.get("evaluation", {})
    effective_overlay_on = _resolve_effective_overlay_enabled(eval_cfg, args)

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🗂️ 股票池变体: {len(universe_variants)} 个")
    print(f"   {', '.join(name for name, _ in universe_variants)}")
    print(f"🧭 Overlay: {'ENABLED' if effective_overlay_on else 'DISABLED'}")
    print("\n🚀 开始策略评估...")
    _log_step("evaluate: 进入按股票池循环")

    all_files = []
    for universe_name, universe_file in universe_variants:
        prefix = "strategy_evaluation"
        if len(universe_variants) > 1 or universe_file is not None:
            prefix = f"strategy_evaluation_universe_{_sanitize_name(universe_name)}"

        print("\n" + "-" * 80)
        print(
            f"🧺 股票池: {universe_name}"
            + (f" ({universe_file})" if universe_file else " (config默认)")
        )
        print("-" * 80)
        _log_step(f"evaluate: 开始运行股票池 {universe_name}")

        files = _run_once(
            args=args,
            config=config,
            periods=periods,
            entry_filter_variants=entry_filter_variants,
            output_dir=output_dir,
            prefix=prefix,
            monitor_list_file=universe_file,
            portfolio_overrides=None,
            enable_overlay=effective_overlay_on,
        )
        if files:
            all_files.append((universe_name, universe_file, files))
            _log_step(f"evaluate: 股票池 {universe_name} 运行完成")

    if not all_files:
        print("❌ 评估失败: 没有生成任何结果")
        return

    _log_step("evaluate: 所有股票池运行完成，开始汇总输出")

    print(f"\n{'=' * 80}")
    print("✅ 策略评价完成！")
    print(f"{'=' * 80}")
    for universe_name, universe_file, files in all_files:
        print(f"[股票池: {universe_name}] {universe_file or '(config默认)'}")
        print(f"  📄 原始结果: {files['raw']}")
        print(f"  📊 市场环境分析: {files['regime']}")
        print(f"  📝 综合报告: {files['report']}")
    print(f"{'=' * 80}\n")


def cmd_pos_evaluation(args):
    """仓位参数批量评价命令（读取 evaluation-position.json）"""
    print("\n" + "=" * 80)
    print("📦 仓位参数批量评价系统 (pos-evaluation)")
    print("=" * 80 + "\n")

    config = load_config()
    eval_cfg = config.get("evaluation", {})
    selected_filter_names = _dedupe_preserve_order(args.entry_filter_name or [])

    if args.list_entry_filters:
        _print_available_entry_filters(config)
        return

    try:
        entry_filter_variants = _resolve_entry_filter_variants(
            config,
            mode=args.entry_filter_mode,
            selected_names=selected_filter_names,
        )
        periods = _build_periods(args)
        universe_variants = _resolve_universe_variants(args.universe_file)
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

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
        print(f"❌ 错误: 仓位配置文件不存在: {position_file}")
        return

    try:
        with open(position_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        print(f"❌ 错误: 读取仓位配置失败: {e}")
        return

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
        print("❌ 错误: 未找到可用仓位组合（支持 list 或 {portfolios:[...]}）")
        return

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
        print("❌ 错误: 无有效仓位组合")
        return

    output_dir = _resolve_output_dir(args.output_dir)

    if args.overlay_modes:
        overlay_modes = args.overlay_modes
    else:
        overlay_default_on = (
            eval_cfg.get("default_overlay_enabled", False)
            if args.enable_overlay is None
            else bool(args.enable_overlay)
        )
        overlay_modes = ["on"] if overlay_default_on else ["off"]
    overlay_modes = [m.lower() for m in overlay_modes]

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🗂️ 股票池变体: {len(universe_variants)} 个")
    print(f"   {', '.join(name for name, _ in universe_variants)}")
    print(f"🧭 Overlay Modes: {', '.join(overlay_modes)}")
    print(f"\n📚 仓位组合: {len(normalized_profiles)} 个")

    all_files = []
    combined_raw_frames = []
    combined_regime_frames = []
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
                enable_overlay = overlay_mode == "on"
                prefix = (
                    f"position_eval_{_sanitize_name(name)}_overlay_{overlay_mode}"
                    f"_univ_{_sanitize_name(universe_name)}"
                )
                print("\n" + "-" * 80)
                print(
                    f"🚀 运行组合 {name} [{overlay_mode.upper()}] × 股票池 {universe_name}: "
                    f"max_positions={overrides['max_positions']}, "
                    f"max_position_pct={overrides['max_position_pct']}, "
                    f"starting_capital_jpy={overrides.get('starting_capital_jpy', 8000000)}"
                )
                if universe_file:
                    print(f"   股票池文件: {universe_file}")
                else:
                    print("   股票池文件: (config默认)")
                print("-" * 80)

                files = _run_once(
                    args=args,
                    config=config,
                    periods=periods,
                    entry_filter_variants=entry_filter_variants,
                    output_dir=output_dir,
                    prefix=prefix,
                    monitor_list_file=universe_file,
                    portfolio_overrides=overrides,
                    enable_overlay=enable_overlay,
                )

                if files:
                    all_files.append(
                        (
                            f"{name}|overlay={overlay_mode}|universe={universe_name}",
                            files,
                        )
                    )
                    print(
                        f"✅ 组合 {name} [{overlay_mode.upper()}] × 股票池 {universe_name} 完成"
                    )

                    try:
                        raw_df = pd.read_csv(files["raw"])
                        raw_df["position_profile"] = name
                        raw_df["overlay_mode"] = overlay_mode
                        raw_df["universe_name"] = universe_name
                        raw_df["universe_file"] = universe_file or ""
                        raw_df["max_positions"] = overrides["max_positions"]
                        raw_df["max_position_pct"] = overrides["max_position_pct"]
                        raw_df["starting_capital_jpy"] = int(
                            overrides.get("starting_capital_jpy", 8_000_000)
                        )
                        combined_raw_frames.append(raw_df)
                    except Exception as e:
                        print(
                            f"⚠️ 合并raw失败 ({name}/{overlay_mode}/{universe_name}): {e}"
                        )

                    try:
                        regime_df = pd.read_csv(files["regime"])
                        regime_df["position_profile"] = name
                        regime_df["overlay_mode"] = overlay_mode
                        regime_df["universe_name"] = universe_name
                        regime_df["universe_file"] = universe_file or ""
                        regime_df["max_positions"] = overrides["max_positions"]
                        regime_df["max_position_pct"] = overrides["max_position_pct"]
                        regime_df["starting_capital_jpy"] = int(
                            overrides.get("starting_capital_jpy", 8_000_000)
                        )
                        combined_regime_frames.append(regime_df)
                    except Exception as e:
                        print(
                            f"⚠️ 合并regime失败 ({name}/{overlay_mode}/{universe_name}): {e}"
                        )
                else:
                    print(
                        f"❌ 组合 {name} [{overlay_mode.upper()}] × 股票池 {universe_name} 未生成结果"
                    )

    if not all_files:
        print("\n❌ 全部组合执行失败")
        return

    print(f"\n{'=' * 80}")
    print("✅ pos-evaluation 完成")
    print(f"{'=' * 80}")
    for name, files in all_files:
        print(f"[{name}]")
        print(f"  📄 原始结果: {files['raw']}")
        print(f"  📊 市场环境分析: {files['regime']}")
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

    print(f"{'=' * 80}\n")
