from pathlib import Path
from datetime import datetime
import pandas as pd


def cmd_production(args):
    """Phase 5: 生产环境每日工作流程"""
    from src.production import (
        ConfigManager,
        ProductionState,
        SignalGenerator,
        TradeExecutor,
        ReportBuilder,
        TradeHistoryManager,
    )
    from src.data.stock_data_manager import StockDataManager
    import os
    from dotenv import load_dotenv
    import json
    from pathlib import Path as PathlibPath
    from src.production.signal_generator import Signal
    from src.production.comprehensive_evaluator import ComprehensiveEvaluator
    from src.utils.strategy_loader import load_exit_strategy
    from src.analysis.signals import SignalAction, Position
    from src.data.market_data_builder import MarketDataBuilder

    print("\n" + "=" * 70)
    print("PRODUCTION WORKFLOW - Phase 5")
    print("=" * 70)

    # Phase 1: Load Configuration
    print("\n[Phase 1] Loading configuration...")
    config_mgr = ConfigManager("config.json")
    prod_cfg = config_mgr.get_production_config()
    print(f"  State file: {prod_cfg.state_file}")
    print(f"  Monitor list: {prod_cfg.monitor_list_file}")
    print(f"  Buy threshold: {prod_cfg.buy_threshold}")

    # Phase 2: Load/Initialize State
    print("\n[Phase 2] Loading production state...")
    state = ProductionState(state_file=prod_cfg.state_file)

    if len(state.get_all_groups()) == 0:
        print("  No strategy groups found. Creating default groups...")
        if prod_cfg.strategy_groups:
            for group_cfg in prod_cfg.strategy_groups:
                state.add_group(
                    group_id=group_cfg["id"],
                    name=group_cfg["name"],
                    initial_capital=group_cfg["initial_capital"],
                )
                print(f"    Created: {group_cfg['name']} (¥{group_cfg['initial_capital']:,})")
        else:
            initial_capital = config_mgr.get_initial_capital()
            state.add_group(
                group_id="default",
                name="Default Strategy",
                initial_capital=initial_capital,
            )
            print(f"    Created: Default Strategy (¥{initial_capital:,})")
        state.save()

    groups = state.get_all_groups()
    print(f"  Loaded {len(groups)} strategy group(s)")
    for group in groups:
        print(f"    {group.name}: ¥{group.cash:,.0f} cash, {len(group.positions)} positions")

    # Optional: Update data first
    if not args.skip_fetch:
        print("\n[Data Update] Fetching latest market data...")
        from src.data.pipeline import StockETLPipeline
        from src.data.benchmark_manager import update_benchmarks
        from src.client.jquants_client import JQuantsV2Client

        load_dotenv()
        api_key = os.getenv("JQUANTS_API_KEY")
        if not api_key:
            print("[ERROR] JQUANTS_API_KEY not found")
            return

        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client)
        if benchmark_result["success"]:
            print(f"  TOPIX updated: {benchmark_result['topix_records']} records")

        json_path = Path("data/monitor_list.json")
        if json_path.exists():
            with open(json_path, "r", encoding="utf-8") as f:
                monitor_data = json.load(f)
            fetch_tickers = [stock["code"] for stock in monitor_data.get("tickers", [])]

            pipeline = StockETLPipeline(api_key)
            summary = pipeline.run_batch(fetch_tickers, fetch_aux_data=True)
            print(f"  Updated {summary['successful']}/{summary['total']} stocks")
    else:
        print("\n[Data Update] Skipped (--skip-fetch flag)")

    print("\n[Phase 3] Generating trading signals...")

    PathlibPath("output/signals").mkdir(parents=True, exist_ok=True)
    PathlibPath("output/report").mkdir(parents=True, exist_ok=True)

    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")
    if not api_key:
        print("[ERROR] JQUANTS_API_KEY not found in environment")
        return

    data_manager = StockDataManager(api_key=api_key)

    json_path = PathlibPath("data/monitor_list.json")
    txt_path = PathlibPath(prod_cfg.monitor_list_file)

    if json_path.exists():
        with open(json_path, "r", encoding="utf-8") as f:
            monitor_data = json.load(f)
        monitor_tickers = [stock["code"] for stock in monitor_data.get("tickers", [])]
    elif txt_path.exists():
        monitor_tickers = []
        with open(txt_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    monitor_tickers.append(line)
    else:
        print("[ERROR] Monitor list not found")
        return

    print(f"  Monitoring {len(monitor_tickers)} stocks")

    print(f"\n[Phase 3] Generating comprehensive stock evaluation...")

    all_signals = []
    today = datetime.now().strftime("%Y-%m-%d")

    strategies_config = []
    all_strategy_names = set()

    for group_cfg in prod_cfg.strategy_groups:
        entry_strategy_name = group_cfg.get("entry_strategy", prod_cfg.default_entry_strategy)
        all_strategy_names.add(entry_strategy_name)

    for strategy_name in all_strategy_names:
        strategies_config.append({"name": strategy_name})

    print(f"  Strategies to evaluate: {', '.join(all_strategy_names)}")

    evaluator = ComprehensiveEvaluator(data_manager, strategies_config)
    print(f"  Evaluating all {len(monitor_tickers)} stocks...")
    comprehensive_evals = evaluator.evaluate_all_stocks(
        tickers=monitor_tickers,
        verbose=False,
    )
    print(f"  ✅ Evaluated {len(comprehensive_evals)} stocks\n")

    print("  Generating trading signals...")
    total_buy_signals = 0
    total_sell_signals = 0

    for group in groups:
        print(f"    Group: {group.name}")

        group_cfg = next((g for g in prod_cfg.strategy_groups if g["id"] == group.id), None)
        if not group_cfg:
            print("      ⚠️ Group config not found")
            continue

        entry_strategy_name = group_cfg.get("entry_strategy", prod_cfg.default_entry_strategy)
        exit_strategy_name = group_cfg.get("exit_strategy", prod_cfg.default_exit_strategy)

        try:
            exit_strategy = load_exit_strategy(exit_strategy_name)
        except Exception as e:
            print(f"      [ERROR] Failed to load exit strategy: {e}")
            continue

        current_tickers = {pos.ticker for pos in group.positions if pos.quantity > 0}
        buy_count = 0

        for ticker, eval_obj in comprehensive_evals.items():
            if ticker in current_tickers:
                continue

            strategy_eval = eval_obj.evaluations.get(entry_strategy_name)
            if not strategy_eval or strategy_eval.signal_action != "BUY":
                continue

            signal = Signal(
                group_id=group.id,
                ticker=ticker,
                ticker_name=eval_obj.ticker_name,
                signal_type="BUY",
                action="BUY",
                confidence=strategy_eval.confidence,
                score=strategy_eval.score,
                reason=strategy_eval.reason,
                current_price=eval_obj.current_price,
                suggested_qty=100,
                required_capital=eval_obj.current_price * 100,
                strategy_name=entry_strategy_name,
            )
            all_signals.append(signal)
            buy_count += 1
            total_buy_signals += 1

        sell_count = 0
        for position in group.positions:
            if position.quantity <= 0:
                continue

            ticker = position.ticker

            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp.now(),
                )

                if market_data is None:
                    continue

                latest_row = market_data.df_features.iloc[-1] if not market_data.df_features.empty else None
                current_price = latest_row["Close"] if latest_row is not None else None

                if current_price is None:
                    continue

                entry_date_ts = (
                    pd.Timestamp(position.entry_date)
                    if isinstance(position.entry_date, str)
                    else position.entry_date
                )

                signals_position = Position(
                    ticker=ticker,
                    entry_price=position.entry_price,
                    entry_date=entry_date_ts,
                    quantity=position.quantity,
                    entry_signal=None,
                    peak_price_since_entry=position.peak_price or position.entry_price,
                )

                if current_price > signals_position.peak_price_since_entry:
                    signals_position.peak_price_since_entry = current_price
                    position.peak_price = current_price

                exit_signal = exit_strategy.generate_exit_signal(
                    position=signals_position,
                    market_data=market_data,
                )

                if exit_signal.action != SignalAction.HOLD:
                    if exit_signal.action == SignalAction.SELL_100:
                        action_str = "SELL_100%"
                    elif exit_signal.action == SignalAction.SELL_75:
                        action_str = "SELL_75%"
                    elif exit_signal.action == SignalAction.SELL_50:
                        action_str = "SELL_50%"
                    elif exit_signal.action == SignalAction.SELL_25:
                        action_str = "SELL_25%"
                    else:
                        action_str = str(exit_signal.action)

                    holding_days = (pd.Timestamp(today) - entry_date_ts).days
                    unrealized_pl = ((current_price - position.entry_price) / position.entry_price) * 100

                    md = market_data.metadata if market_data else {}

                    signal = Signal(
                        group_id=group.id,
                        ticker=ticker,
                        ticker_name=md.get("company_name", ticker) if md else ticker,
                        signal_type="SELL",
                        action=action_str,
                        confidence=exit_signal.confidence,
                        score=0,
                        reason=exit_signal.reasons[0] if exit_signal.reasons else exit_signal.action.name,
                        current_price=float(current_price),
                        position_qty=position.quantity,
                        entry_price=position.entry_price,
                        entry_date=position.entry_date,
                        holding_days=holding_days,
                        unrealized_pl_pct=float(unrealized_pl),
                        strategy_name=exit_strategy_name,
                    )
                    all_signals.append(signal)
                    sell_count += 1
                    total_sell_signals += 1

            except Exception:
                continue

        print(f"      BUY: {buy_count}, SELL: {sell_count}")

    print(f"    Total: {total_buy_signals} BUY, {total_sell_signals} SELL")

    signal_file = prod_cfg.signal_file_pattern.replace("{date}", today)
    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump([s.__dict__ for s in all_signals], f, indent=2, ensure_ascii=False)
    print(f"\n  Signals saved to: {signal_file}")

    print("\n[Phase 4] Generating daily report...")

    history = TradeHistoryManager(history_file=prod_cfg.history_file)
    builder = ReportBuilder(state, data_manager)

    report_md = builder.generate_daily_report(
        signals=all_signals,
        report_date=today,
        comprehensive_evaluations=comprehensive_evals,
    )

    report_file = prod_cfg.report_file_pattern.replace("{date}", today)
    builder.save_report(report_md, report_file)
    print(f"  Report saved to: {report_file}")

    print("\n" + "=" * 70)
    print("✅ PRODUCTION WORKFLOW COMPLETE")
    print("=" * 70)
    print(f"  Strategy Groups: {len(groups)}")
    print(f"  Total Signals: {len(all_signals)}")
    print(f"  Signal File: {signal_file}")
    print(f"  Report File: {report_file}")
    print("=" * 70 + "\n")
