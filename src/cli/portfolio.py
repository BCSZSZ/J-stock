from .common import load_config, load_monitor_list


def cmd_portfolio(args):
    """组合投资回测命令"""
    config = load_config()
    import pandas as pd

    from src.backtest.lot_size_manager import LotSizeManager
    from src.backtest.portfolio_engine import PortfolioBacktestEngine
    from src.data.stock_data_manager import StockDataManager
    from src.overlays import OverlayManager
    from src.utils.output_logger import create_logger
    from src.utils.strategy_loader import (
        get_all_strategy_combinations,
        get_strategy_combinations_from_lists,
        load_entry_strategy,
        load_exit_strategy,
    )

    if "lot_sizes" in config:
        LotSizeManager.load_from_config(config["lot_sizes"])

    logger = create_logger("portfolio")
    with logger:
        if args.all:
            tickers = load_monitor_list(config)
            print(f"📊 组合投资回测 - 监视列表所有股票 ({len(tickers)}只)")
        elif args.tickers:
            tickers = args.tickers
            print(f"📊 组合投资回测 - 指定股票 ({len(tickers)}只)")
        else:
            print("❌ 错误: 请指定 --all 或 --tickers")
            return

        if args.all_strategies:
            strategy_combinations = get_all_strategy_combinations()
            print(f"   策略组合数: {len(strategy_combinations)}")
        elif args.entry or args.exit:
            if args.entry:
                entry_names = (
                    args.entry if isinstance(args.entry, list) else [args.entry]
                )
            else:
                entry_names = [config["default_strategies"]["entry"]]

            if args.exit:
                exit_names = args.exit if isinstance(args.exit, list) else [args.exit]
            else:
                exit_names = [config["default_strategies"]["exit"]]

            strategy_combinations = get_strategy_combinations_from_lists(
                entry_names, exit_names
            )

            if len(strategy_combinations) > 1:
                print(f"   入场策略: {', '.join(entry_names)}")
                print(f"   出场策略: {', '.join(exit_names)}")
                print(f"   策略组合数: {len(strategy_combinations)}")
            else:
                print(f"   入场策略: {entry_names[0]}")
                print(f"   出场策略: {exit_names[0]}")
        else:
            entry_name = config["default_strategies"]["entry"]
            exit_name = config["default_strategies"]["exit"]
            strategy_combinations = [(entry_name, exit_name)]
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

        print(
            f"   股票代码: {', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''}"
        )
        print(f"   起始资金: ¥{capital:,}")
        print(f"   最大持仓: {config['portfolio']['max_positions']}只")
        print("=" * 60)

        data_manager = StockDataManager()
        all_data = {}

        for ticker in tickers:
            stock_data = data_manager.load_stock_features(ticker)

            if stock_data.empty:
                print(f"⚠️ 跳过 {ticker}: 数据文件不存在")
                continue

            if "Date" in stock_data.columns:
                stock_data = stock_data.rename(columns={"Date": "date"})
            stock_data["date"] = pd.to_datetime(stock_data["date"]).dt.strftime(
                "%Y-%m-%d"
            )

            stock_data = stock_data[
                (stock_data["date"] >= start_date) & (stock_data["date"] <= end_date)
            ]

            if not stock_data.empty:
                all_data[ticker] = stock_data

        print(f"\n✅ 成功加载 {len(all_data)}/{len(tickers)} 只股票数据")

        if len(all_data) == 0:
            print("❌ 错误: 无可用数据")
            return

        results = []
        for i, (entry_name, exit_name) in enumerate(strategy_combinations, 1):
            if len(strategy_combinations) > 1:
                print(
                    f"\n[{i}/{len(strategy_combinations)}] {entry_name} × {exit_name}"
                )

            entry_strategy = load_entry_strategy(entry_name)
            exit_strategy = load_exit_strategy(exit_name)

            overlay_manager = OverlayManager.from_config(config)
            engine = PortfolioBacktestEngine(
                starting_capital=capital,
                max_positions=config["portfolio"]["max_positions"],
                max_position_pct=config["portfolio"]["max_position_pct"],
                overlay_manager=overlay_manager,
            )

            result = engine.backtest_portfolio_strategy(
                tickers=tickers,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date,
            )

            results.append({"entry": entry_name, "exit": exit_name, "result": result})

            if len(strategy_combinations) == 1:
                print("\n📈 组合回测结果")
                print(f"   最终资金: ¥{result.final_capital_jpy:,.0f}")
                print(f"   总收益率: {result.total_return_pct:.2f}%")
                print(f"   交易次数: {result.num_trades}")
                print(f"   胜率: {result.win_rate_pct:.1f}%")
                print(f"   最大回撤: {result.max_drawdown_pct:.2f}%")
                if result.sharpe_ratio:
                    print(f"   夏普比率: {result.sharpe_ratio:.2f}")
                if result.benchmark_return_pct:
                    print(f"\n   TOPIX收益: {result.benchmark_return_pct:.2f}%")
                    print(
                        f"   超额收益: {result.total_return_pct - result.benchmark_return_pct:.2f}%"
                    )
            else:
                print(
                    f"   收益率: {result.total_return_pct:6.2f}% | 夏普: {result.sharpe_ratio:5.2f} | 回撤: {result.max_drawdown_pct:5.2f}% | 交易: {result.num_trades:3d}次"
                )

        if len(results) > 1:
            print(f"\n\n{'=' * 100}")
            print("策略排名 (按收益率)")
            print(f"{'=' * 100}")
            sorted_results = sorted(
                results, key=lambda x: x["result"].total_return_pct, reverse=True
            )

            has_benchmark = any(
                r["result"].benchmark_return_pct is not None for r in sorted_results
            )

            if has_benchmark:
                print(
                    f"{'排名':<4} {'入场策略':<22} {'出场策略':<22} {'收益率':>10} {'夏普':>8} {'胜率':>8} {'TOPIX%':>9} {'超额%':>9}"
                )
                print("-" * 100)
                for i, item in enumerate(sorted_results, 1):
                    r = item["result"]
                    topix_str = (
                        f"{r.benchmark_return_pct:>8.2f}%"
                        if r.benchmark_return_pct is not None
                        else "    N/A  "
                    )
                    alpha_str = (
                        f"{r.alpha:>8.2f}%" if r.alpha is not None else "    N/A  "
                    )
                    print(
                        f"{i:<4} {item['entry']:<22} {item['exit']:<22} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}% {topix_str} {alpha_str}"
                    )
            else:
                print(
                    f"{'排名':<4} {'入场策略':<25} {'出场策略':<25} {'收益率':>10} {'夏普':>8} {'胜率':>8}"
                )
                print("-" * 100)
                for i, item in enumerate(sorted_results, 1):
                    r = item["result"]
                    print(
                        f"{i:<4} {item['entry']:<25} {item['exit']:<25} {r.total_return_pct:>9.2f}% {r.sharpe_ratio:>7.2f} {r.win_rate_pct:>7.1f}%"
                    )
