from .common import load_config


def cmd_backtest(args):
    """单股票回测命令"""
    config = load_config()
    from src.utils.strategy_loader import (
        get_all_strategy_combinations,
        get_strategy_combinations_from_lists,
        load_entry_strategy,
        load_exit_strategy,
        ENTRY_STRATEGIES,
        EXIT_STRATEGIES,
    )
    from src.backtest.engine import backtest_strategy
    from src.backtest.lot_size_manager import LotSizeManager
    from src.data.stock_data_manager import StockDataManager
    from src.overlays import OverlayManager
    from src.utils.output_logger import create_logger
    import pandas as pd

    if "lot_sizes" in config:
        LotSizeManager.load_from_config(config["lot_sizes"])

    logger = create_logger("backtest", ticker=args.ticker)
    with logger:
        if args.all_strategies:
            strategy_combinations = get_all_strategy_combinations()
            print(f"\n📊 单股票回测 - 所有策略组合")
            print(f"   股票代码: {args.ticker}")
            print(f"   策略组合数: {len(strategy_combinations)}")
        elif args.entry or args.exit:
            if args.entry:
                entry_names = args.entry if isinstance(args.entry, list) else [args.entry]
            else:
                entry_names = [config["default_strategies"]["entry"]]

            if args.exit:
                exit_names = args.exit if isinstance(args.exit, list) else [args.exit]
            else:
                exit_names = [config["default_strategies"]["exit"]]

            strategy_combinations = get_strategy_combinations_from_lists(entry_names, exit_names)

            if len(strategy_combinations) > 1:
                print(f"\n📊 单股票回测 - 多策略组合")
                print(f"   股票代码: {args.ticker}")
                print(f"   入场策略: {', '.join(entry_names)}")
                print(f"   出场策略: {', '.join(exit_names)}")
                print(f"   策略组合数: {len(strategy_combinations)}")
            else:
                print(f"\n📊 单股票回测")
                print(f"   股票代码: {args.ticker}")
                print(f"   入场策略: {entry_names[0]}")
                print(f"   出场策略: {exit_names[0]}")
        else:
            entry_name = config["default_strategies"]["entry"]
            exit_name = config["default_strategies"]["exit"]
            strategy_combinations = [(entry_name, exit_name)]
            print(f"\n📊 单股票回测")
            print(f"   股票代码: {args.ticker}")
            print(f"   入场策略: {entry_name}")
            print(f"   出场策略: {exit_name}")

        capital = args.capital or config["backtest"]["starting_capital_jpy"]

        if args.years:
            end_date = args.end or config["backtest"]["end_date"]
            from datetime import datetime
            from dateutil.relativedelta import relativedelta

            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            start_dt = end_dt - relativedelta(years=args.years)
            start_date = start_dt.strftime("%Y-%m-%d")
            print(f"   时间范围: 最近{args.years}年 ({start_date} → {end_date})")
        else:
            start_date = args.start or config["backtest"]["start_date"]
            end_date = args.end or config["backtest"]["end_date"]
            print(f"   时间范围: {start_date} → {end_date}")

        print(f"   起始资金: ¥{capital:,}")
        print(
            "   成交价缓冲: "
            f"{'开启' if args.fill_buffer_enabled else '关闭'} "
            f"({float(args.fill_buffer_pct):.2%})"
        )
        print("=" * 60)

        data_manager = StockDataManager()
        stock_data = data_manager.load_stock_features(args.ticker)

        if stock_data.empty:
            print(f"❌ 错误: 无法找到股票 {args.ticker} 的数据文件")
            print(f"   请先运行: python main.py fetch --tickers {args.ticker}")
            return

        results = []
        for i, (entry_name, exit_name) in enumerate(strategy_combinations, 1):
            if len(strategy_combinations) > 1:
                print(f"\n[{i}/{len(strategy_combinations)}] {entry_name} × {exit_name}")

            from src.utils.strategy_loader import load_strategy_pair

            entry_strategy, exit_strategy = load_strategy_pair(entry_name, exit_name)

            overlay_manager = OverlayManager.from_config(config)
            result = backtest_strategy(
                ticker=args.ticker,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date,
                starting_capital_jpy=capital,
                overlay_manager=overlay_manager,
                fill_buffer_enabled=args.fill_buffer_enabled,
                fill_buffer_pct=args.fill_buffer_pct,
            )

            results.append({
                "entry": entry_name,
                "exit": exit_name,
                "result": result,
            })

            if len(strategy_combinations) == 1:
                print(f"\n📈 回测结果")
                print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
                print(f"   总收益率: {result.total_return_pct:.2f}%")
                print(f"   交易次数: {result.num_trades}")
                print(f"   胜率: {result.win_rate_pct:.1f}%")
                print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
                if result.sharpe_ratio:
                    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
                print(f"\n   买入持有收益: {result.buy_hold_return_pct:.2f}%")
                print(f"   择时Alpha: {result.timing_alpha:.2f}%")
                if result.benchmark_return_pct:
                    print(f"   TOPIX收益: {result.benchmark_return_pct:.2f}%")
                    print(f"   选股Alpha: {result.stock_selection_alpha:.2f}%")
            else:
                print(
                    f"   收益率: {result.total_return_pct:6.2f}% | 夏普: {result.sharpe_ratio:5.2f} | 回撤: {result.max_drawdown_pct:5.2f}% | 交易: {result.num_trades:3d}次"
                )

        if len(results) > 1:
            print(f"\n\n{'=' * 80}")
            print("策略排名 (按收益率)")
            print(f"{'=' * 80}")
            sorted_results = sorted(results, key=lambda x: x["result"].total_return_pct, reverse=True)

            print(f"{'排名':<4} {'入场策略':<25} {'出场策略':<25} {'收益率':>10} {'夏普':>8} {'胜率':>8}")
            print("-" * 80)
            for i, item in enumerate(sorted_results, 1):
                r = item["result"]
                print(
                    f"{i:<4} {item['entry']:<25} {item['exit']:<25} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}%"
                )
