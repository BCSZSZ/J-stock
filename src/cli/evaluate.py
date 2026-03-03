import json
from pathlib import Path

from src.evaluation import (
    StrategyEvaluator,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods,
)

from .common import load_config


def _resolve_output_dir(user_output_dir):
    if user_output_dir:
        return user_output_dir

    cloud_default = Path(r"G:\My Drive\AI-Stock-Sync\strategy_evaluation")
    cloud_default.mkdir(parents=True, exist_ok=True)
    probe = cloud_default / ".write_probe.tmp"
    with open(probe, "w", encoding="utf-8") as f:
        f.write("ok")
    probe.unlink(missing_ok=True)
    print(f"📁 输出目录: {cloud_default} (Google Drive)")
    return str(cloud_default)


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


def _run_once(
    args,
    config,
    periods,
    entry_filter_variants,
    output_dir,
    prefix,
    portfolio_overrides=None,
):
    use_overlay = bool(getattr(args, "enable_overlay", False))
    overlay_config = config if use_overlay else {}

    evaluator = StrategyEvaluator(
        data_root="data",
        output_dir=output_dir,
        verbose=args.verbose,
        overlay_config=overlay_config,
        entry_filter_config=config.get("evaluation", {}).get("entry_filter", {}),
        entry_filter_variants=entry_filter_variants,
        portfolio_overrides=portfolio_overrides,
    )

    entry_strategies = args.entry_strategies
    exit_strategies = args.exit_strategies

    if not exit_strategies:
        exit_strategies = config.get("entry_eval_exit_strategies")
        if exit_strategies:
            print("\n🧭 使用配置文件中的评估出场策略 (entry_eval_exit_strategies)")
            print(f"   出场策略: {', '.join(exit_strategies)}")
        else:
            print(
                "\n⚠️ 警告: 配置文件中未定义entry_eval_exit_strategies，将使用所有可用策略"
            )

    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )

    if df_results.empty:
        return None

    files = evaluator.save_results(prefix=prefix)
    return files


def cmd_evaluate(args):
    """策略综合评价命令"""
    print("\n" + "=" * 80)
    print("🔬 策略综合评价系统")
    print("=" * 80 + "\n")

    config = load_config()
    selected_filter_names = args.entry_filter_name or []

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
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    output_dir = _resolve_output_dir(args.output_dir)

    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🧭 Overlay: {'ENABLED' if getattr(args, 'enable_overlay', False) else 'DISABLED'}")
    print("\n🚀 开始策略评估...")

    files = _run_once(
        args=args,
        config=config,
        periods=periods,
        entry_filter_variants=entry_filter_variants,
        output_dir=output_dir,
        prefix="strategy_evaluation",
        portfolio_overrides=None,
    )

    if not files:
        print("❌ 评估失败: 没有生成任何结果")
        return

    print(f"\n{'=' * 80}")
    print("✅ 策略评价完成！")
    print(f"{'=' * 80}")
    print(f"📄 原始结果: {files['raw']}")
    print(f"📊 市场环境分析: {files['regime']}")
    print(f"📝 综合报告: {files['report']}")
    print(f"{'=' * 80}\n")


def cmd_pos_evaluation(args):
    """仓位参数批量评价命令（读取 evaluation-position.json）"""
    print("\n" + "=" * 80)
    print("📦 仓位参数批量评价系统 (pos-evaluation)")
    print("=" * 80 + "\n")

    config = load_config()
    selected_filter_names = args.entry_filter_name or []

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
    except ValueError as e:
        print(f"❌ 错误: {e}")
        return

    position_file = Path(args.position_file)
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

    selected_profile_names = set(args.profile_name or [])
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
    print(f"\n🧪 Entry Filter 变体: {len(entry_filter_variants)} 个")
    print(f"   {', '.join(name for name, _ in entry_filter_variants)}")
    print(f"🧭 Overlay: {'ENABLED' if getattr(args, 'enable_overlay', False) else 'DISABLED'}")
    print(f"\n📚 仓位组合: {len(normalized_profiles)} 个")

    all_files = []
    for profile in normalized_profiles:
        name = profile["name"]
        overrides = {
            "max_positions": profile["max_positions"],
            "max_position_pct": profile["max_position_pct"],
        }
        if profile["starting_capital_jpy"] is not None:
            overrides["starting_capital_jpy"] = profile["starting_capital_jpy"]

        prefix = f"position_eval_{_sanitize_name(name)}"
        print("\n" + "-" * 80)
        print(
            f"🚀 运行组合 {name}: max_positions={overrides['max_positions']}, "
            f"max_position_pct={overrides['max_position_pct']}, "
            f"starting_capital_jpy={overrides.get('starting_capital_jpy', 'config.portfolio')}"
        )
        print("-" * 80)

        files = _run_once(
            args=args,
            config=config,
            periods=periods,
            entry_filter_variants=entry_filter_variants,
            output_dir=output_dir,
            prefix=prefix,
            portfolio_overrides=overrides,
        )

        if files:
            all_files.append((name, files))
            print(f"✅ 组合 {name} 完成")
        else:
            print(f"❌ 组合 {name} 未生成结果")

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
    print(f"{'=' * 80}\n")
