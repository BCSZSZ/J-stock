import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
from dotenv import load_dotenv

from src.cli.production_utils import load_monitor_tickers


def run_daily_workflow(args, prod_cfg, state) -> None:
    from src.analysis.signals import Position, SignalAction
    from src.data.market_data_builder import MarketDataBuilder
    from src.data.stock_data_manager import StockDataManager
    from src.production import ReportBuilder
    from src.production.comprehensive_evaluator import ComprehensiveEvaluator
    from src.production.signal_generator import Signal
    from src.utils.strategy_loader import load_exit_strategy

    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")
    with open("config.json", "r", encoding="utf-8") as f:
        raw_config = json.load(f)
    lot_sizes = raw_config.get("lot_sizes", {})
    default_lot_size = int(lot_sizes.get("default", 100) or 100)

    monitor_tickers = load_monitor_tickers(prod_cfg.monitor_list_file)

    def _get_latest_data_date_for_tickers(tickers: List[str]):
        """
        遍历所有股票，返回所有股票中最小的最新数据日（即全市场可用的最新日）
        """
        latest_dates = []
        for ticker in tickers:
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp.now(),
                )
                if market_data is not None and not market_data.df_features.empty:
                    latest_feature_date = market_data.df_features.index.max()
                    if pd.notna(latest_feature_date):
                        latest_dates.append(latest_feature_date.date())
            except Exception:
                continue
        if not latest_dates:
            return None
        return min(latest_dates)

    def _has_data_for_date(tickers: List[str], target_date: str):
        """
        检查所有股票是否有target_date的数据
        """
        expected = pd.Timestamp(target_date).date()
        checked = 0
        data_ready_count = 0
        for ticker in tickers:
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=ticker,
                    current_date=pd.Timestamp.now(),
                )
            except Exception:
                continue
            checked += 1
            if market_data is None or market_data.df_features.empty:
                continue
            latest_feature_date = market_data.df_features.index.max()
            if pd.isna(latest_feature_date):
                continue
            latest = latest_feature_date.date()
            data_ready_count += 1
            if latest < expected:
                return False, checked, data_ready_count, latest
        return True, checked, data_ready_count, expected

    if not args.skip_fetch:
        print("\n[Data Update] Fetching latest market data...")
        from src.data_fetch_manager import run_fetch

        summary = run_fetch(monitor_list_file=prod_cfg.monitor_list_file)
        if summary:
            print(f"  Updated {summary['successful']}/{summary['total']} stocks")
    else:
        print("\n[Data Update] Skipped (--skip-fetch flag)")

    print("\n[Signal] Generating end-of-day signals...")
    Path("output/signals").mkdir(parents=True, exist_ok=True)
    Path("output/report").mkdir(parents=True, exist_ok=True)

    data_manager = StockDataManager(api_key=api_key)
    print(f"  Monitoring {len(monitor_tickers)} stocks")

    # 自动检测全市场最新可用数据日
    latest_data_date = _get_latest_data_date_for_tickers(monitor_tickers)
    if latest_data_date is None:
        print("\n[ERROR] No available market data for any ticker. Workflow aborted.")
        return

    # 如果今天还没开盘，API只能拿到前一日数据，信号生成日应为latest_data_date
    today_str = datetime.now().strftime("%Y-%m-%d")
    signal_date = latest_data_date.strftime("%Y-%m-%d")
    if signal_date != today_str:
        print(
            f"\n[INFO] Using latest available data date for signal generation: {signal_date}"
        )
    else:
        print(f"\n[INFO] Using today as signal date: {signal_date}")

    ready, checked, ready_count, latest_seen = _has_data_for_date(
        monitor_tickers, signal_date
    )
    if not ready:
        latest_txt = latest_seen.strftime("%Y-%m-%d") if latest_seen else "N/A"
        print("\n[WARN] No market data detected for signal date.")
        print(f"  Signal date: {signal_date} | Latest available: {latest_txt}")
        print(f"  Checked tickers: {checked}, with feature data: {ready_count}")
        print("  It may be too early (before EOD data is published). Workflow aborted.")
        return

    all_signals = []
    groups = state.get_all_groups()
    group_configs = {g["id"]: g for g in (prod_cfg.strategy_groups or [])}
    entry_strategy_names = set()
    for group in groups:
        cfg = group_configs.get(group.id, {})
        entry_strategy_names.add(
            cfg.get("entry_strategy", prod_cfg.default_entry_strategy)
        )

    strategies_config = [{"name": name} for name in sorted(entry_strategy_names)]
    evaluator = ComprehensiveEvaluator(data_manager, strategies_config)

    print(f"  Evaluating all {len(monitor_tickers)} stocks...")
    comprehensive_evals = evaluator.evaluate_all_stocks(
        tickers=monitor_tickers,
        verbose=False,
    )
    print(f"  ✅ Evaluated {len(comprehensive_evals)} stocks")

    total_buy_signals = 0
    total_sell_signals = 0

    def _calc_suggested_qty(
        ticker: str,
        current_price: float,
        available_cash: float,
        max_position_pct: float,
    ):
        lot_size = int(lot_sizes.get(ticker, default_lot_size) or default_lot_size)
        if current_price <= 0 or lot_size <= 0:
            return 0, 0.0, lot_size

        max_position_value = available_cash * max_position_pct
        lot_value = current_price * lot_size
        lots = int(max_position_value // lot_value)
        qty = lots * lot_size
        required_capital = qty * current_price
        return qty, required_capital, lot_size

    for group in groups:
        group_cfg = group_configs.get(group.id, {})
        entry_strategy_name = group_cfg.get(
            "entry_strategy", prod_cfg.default_entry_strategy
        )
        exit_strategy_name = group_cfg.get(
            "exit_strategy", prod_cfg.default_exit_strategy
        )

        print(f"    Group: {group.name} ({entry_strategy_name} + {exit_strategy_name})")

        try:
            exit_strategy = load_exit_strategy(exit_strategy_name)
        except Exception as e:
            print(f"      ⚠️ Exit strategy load error: {e}")
            continue

        current_tickers = {pos.ticker for pos in group.positions if pos.quantity > 0}
        buy_count = 0
        for ticker, eval_obj in comprehensive_evals.items():
            if ticker in current_tickers:
                continue
            strategy_eval = eval_obj.evaluations.get(entry_strategy_name)
            if not strategy_eval or strategy_eval.signal_action != "BUY":
                continue

            suggested_qty, required_capital, lot_size = _calc_suggested_qty(
                ticker=ticker,
                current_price=float(eval_obj.current_price),
                available_cash=float(group.cash),
                max_position_pct=float(prod_cfg.max_position_pct),
            )

            buy_reason = strategy_eval.reason
            if suggested_qty <= 0:
                buy_reason = (
                    f"{buy_reason}; SuggestedQty=0: cash/position limit insufficient "
                    f"for lot size {lot_size}"
                )

            signal = Signal(
                group_id=group.id,
                ticker=ticker,
                ticker_name=eval_obj.ticker_name,
                signal_type="BUY",
                action="BUY",
                confidence=strategy_eval.confidence,
                score=strategy_eval.score,
                reason=buy_reason,
                current_price=eval_obj.current_price,
                suggested_qty=suggested_qty,
                required_capital=required_capital,
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

                latest_row = (
                    market_data.df_features.iloc[-1]
                    if not market_data.df_features.empty
                    else None
                )
                current_price = latest_row["Close"] if latest_row is not None else None
                if current_price is None:
                    continue

                entry_date_ts = pd.Timestamp(position.entry_date)
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

                if exit_signal.action == SignalAction.HOLD:
                    continue

                if exit_signal.action == SignalAction.SELL:
                    action_str = "SELL"
                else:
                    action_str = (
                        exit_signal.action.value
                        if hasattr(exit_signal.action, "value")
                        else str(exit_signal.action)
                    )

                holding_days = (pd.Timestamp(signal_date) - entry_date_ts).days
                unrealized_pl = (
                    (current_price - position.entry_price) / position.entry_price
                ) * 100
                md = market_data.metadata if market_data else {}

                signal = Signal(
                    group_id=group.id,
                    ticker=ticker,
                    ticker_name=md.get("company_name", ticker) if md else ticker,
                    signal_type="SELL",
                    action=action_str,
                    confidence=exit_signal.confidence,
                    score=0,
                    reason=(
                        "; ".join(exit_signal.reasons)
                        if exit_signal.reasons
                        else exit_signal.action.name
                    ),
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

    signal_file = prod_cfg.signal_file_pattern.replace("{date}", signal_date)
    Path(signal_file).parent.mkdir(parents=True, exist_ok=True)
    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump([s.__dict__ for s in all_signals], f, indent=2, ensure_ascii=False)

    print(f"\n[Output] Total signals: {len(all_signals)}")
    print(f"  BUY: {total_buy_signals}, SELL: {total_sell_signals}")
    print(f"  Signals saved: {signal_file}")

    builder = ReportBuilder(state, data_manager)
    report_md = builder.generate_daily_report(
        signals=all_signals,
        report_date=signal_date,
        comprehensive_evaluations=comprehensive_evals,
    )
    report_file = prod_cfg.report_file_pattern.replace("{date}", signal_date)
    builder.save_report(report_md, report_file)
    print(f"  Report saved: {report_file}")
