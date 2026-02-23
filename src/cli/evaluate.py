def cmd_evaluate(args):
    """策略综合评价命令"""
    import json
    from pathlib import Path

    from src.evaluation import (
        StrategyEvaluator,
        create_annual_periods,
        create_monthly_periods,
        create_quarterly_periods,
    )

    from .common import load_config

    def resolve_output_dir(user_output_dir):
        local_fallback = Path("strategy_evaluation")

        if user_output_dir:
            return user_output_dir

        cloud_default = Path(r"G:\My Drive\AI-Stock-Sync\strategy_evaluation")
        try:
            cloud_default.mkdir(parents=True, exist_ok=True)
            probe = cloud_default / ".write_probe.tmp"
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            probe.unlink(missing_ok=True)
            print(f"📁 输出目录: {cloud_default} (Google Drive)")
            return str(cloud_default)
        except Exception as e:
            local_fallback.mkdir(parents=True, exist_ok=True)
            print(f"⚠️ Google Drive输出目录不可写，已回退到本地目录: {local_fallback}")
            print(f"   原因: {e}")
            return str(local_fallback)

    print("\n" + "=" * 80)
    print("🔬 策略综合评价系统")
    print("=" * 80 + "\n")

    periods = []

    if args.mode == "annual":
        if not args.years:
            print("❌ 错误: annual模式需要指定--years参数")
            return
        periods = create_annual_periods(args.years)
        print("📅 评估模式: 整年")
        print(f"   年份: {', '.join(map(str, args.years))}")

    elif args.mode == "quarterly":
        if not args.years:
            print("❌ 错误: quarterly模式需要指定--years参数")
            return
        periods = create_quarterly_periods(args.years)
        print("📅 评估模式: 季度")
        print(f"   年份: {', '.join(map(str, args.years))}")

    elif args.mode == "monthly":
        if not args.years:
            print("❌ 错误: monthly模式需要指定--years参数")
            return

        months = args.months if args.months else list(range(1, 13))
        for year in args.years:
            periods.extend(create_monthly_periods(year, months))

        print("📅 评估模式: 月度")
        print(f"   年份: {', '.join(map(str, args.years))}")
        print(f"   月份: {', '.join(map(str, months))}")

    elif args.mode == "custom":
        if not args.custom_periods:
            print("❌ 错误: custom模式需要指定--custom-periods参数")
            print('   格式: [["标签","开始日期","结束日期"], ...]')
            print(
                '   示例: [["2021-Q1","2021-01-01","2021-03-31"], ["2021-Q2","2021-04-01","2021-06-30"]]'
            )
            return

        try:
            periods = json.loads(args.custom_periods)
            print("📅 评估模式: 自定义")
            print(f"   时间段数: {len(periods)}")
        except json.JSONDecodeError as e:
            print(f"❌ 错误: custom_periods JSON解析失败: {e}")
            return

    if not periods:
        print("❌ 错误: 没有有效的时间段")
        return

    print("\n📊 时间段列表:")
    for label, start, end in periods[:5]:
        print(f"   {label}: {start} ~ {end}")
    if len(periods) > 5:
        print(f"   ... 共 {len(periods)} 个时间段")

    output_dir = resolve_output_dir(args.output_dir)

    config = load_config()

    evaluator = StrategyEvaluator(
        data_root="data",
        output_dir=output_dir,
        verbose=args.verbose,
        overlay_config=config,
    )

    entry_strategies = args.entry_strategies
    exit_strategies = args.exit_strategies

    # 当没有显式指定出场策略时，优先使用配置文件中的默认出场策略
    if not exit_strategies:
        exit_strategies = config.get("entry_eval_exit_strategies")
        if exit_strategies:
            print("\n🧭 使用配置文件中的评估出场策略 (entry_eval_exit_strategies)")
            print(f"   出场策略: {', '.join(exit_strategies)}")
        else:
            print(
                "\n⚠️ 警告: 配置文件中未定义entry_eval_exit_strategies，将使用所有可用策略"
            )

    print("\n🚀 开始策略评估...")
    df_results = evaluator.run_evaluation(
        periods=periods,
        entry_strategies=entry_strategies,
        exit_strategies=exit_strategies,
    )

    if df_results.empty:
        print("❌ 评估失败: 没有生成任何结果")
        return

    print("\n💾 保存结果...")
    files = evaluator.save_results(prefix="strategy_evaluation")

    print(f"\n{'=' * 80}")
    print("✅ 策略评价完成！")
    print(f"{'=' * 80}")
    print(f"📄 原始结果: {files['raw']}")
    print(f"📊 市场环境分析: {files['regime']}")
    print(f"📝 综合报告: {files['report']}")
    print(f"{'=' * 80}\n")
