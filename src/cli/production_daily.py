import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
from dotenv import load_dotenv

from src.cli.production_utils import load_monitor_tickers
from src.data.fetch_universe_builder import build_fetch_universe_file


def run_daily_workflow(args, prod_cfg, state) -> None:
    from src.analysis.signals import Position, SignalAction
    from src.data.market_data_builder import MarketDataBuilder
    from src.data.stock_data_manager import StockDataManager
    from src.overlays import OverlayContext, OverlayManager
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
    prod_runtime_cfg = raw_config.get("production", {})
    buy_price_buffer_pct = float(
        prod_runtime_cfg.get("report_buy_price_buffer_pct", 0.02)
    )
    sell_price_buffer_pct = float(
        prod_runtime_cfg.get("report_sell_price_buffer_pct", 0.02)
    )
    buy_price_buffer_pct = min(max(buy_price_buffer_pct, 0.0), 0.20)
    sell_price_buffer_pct = min(max(sell_price_buffer_pct, 0.0), 0.20)

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

        fetch_universe_file, merged_count, sector_count = build_fetch_universe_file(
            monitor_list_file=prod_cfg.monitor_list_file,
            output_file=prod_cfg.fetch_universe_file,
            sector_pool_file=prod_cfg.sector_pool_file,
        )
        print(
            "  Fetch universe prepared: "
            f"{merged_count} tickers (sector pool contribution: {sector_count})"
        )

        summary = run_fetch(monitor_list_file=fetch_universe_file)
        if summary:
            print(f"  Updated {summary['successful']}/{summary['total']} stocks")
    else:
        print("\n[Data Update] Skipped (--skip-fetch flag)")

    print("\n[Signal] Generating end-of-day signals...")
    Path("output/signals").mkdir(parents=True, exist_ok=True)
    Path("output/report").mkdir(parents=True, exist_ok=True)

    data_manager = StockDataManager(api_key=api_key)
    overlay_manager = OverlayManager.from_config(raw_config, data_root="data")
    print(f"  Monitoring {len(monitor_tickers)} stocks for signal evaluation")

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
        total_portfolio_value: float,
        max_position_pct: float,
    ):
        lot_size = int(lot_sizes.get(ticker, default_lot_size) or default_lot_size)
        if current_price <= 0 or lot_size <= 0:
            return 0, 0.0, lot_size

        target_position_value = total_portfolio_value * max_position_pct
        max_position_value = min(target_position_value, available_cash)
        lot_value = current_price * lot_size
        lots = int(max_position_value // lot_value)
        qty = lots * lot_size
        required_capital = qty * current_price
        return qty, required_capital, lot_size

    def _estimate_buy_price(close_price: float) -> float:
        return float(close_price) * (1.0 + buy_price_buffer_pct)

    def _estimate_sell_price(close_price: float) -> float:
        return float(close_price) * (1.0 - sell_price_buffer_pct)

    def _parse_sell_pct(action: str) -> float:
        normalized = (action or "").upper()
        if "25" in normalized:
            return 0.25
        if "50" in normalized:
            return 0.5
        if "75" in normalized:
            return 0.75
        return 1.0

    def _calculate_sell_quantity(ticker: str, total_qty: int, sell_pct: float) -> int:
        lot_size = int(lot_sizes.get(ticker, default_lot_size) or default_lot_size)
        if total_qty <= 0:
            return 0
        if sell_pct >= 0.999:
            return total_qty
        raw_qty = total_qty * max(sell_pct, 0.0)
        lots = int((raw_qty + lot_size - 1) // lot_size)
        qty = lots * lot_size
        return min(total_qty, qty)

    overlay_summaries = []

    def _get_group_current_prices(group):
        prices = {}
        for pos in group.positions:
            if pos.quantity <= 0:
                continue
            try:
                market_data = MarketDataBuilder.build_from_manager(
                    data_manager=data_manager,
                    ticker=pos.ticker,
                    current_date=pd.Timestamp.now(),
                )
            except Exception:
                continue
            if market_data is None or market_data.df_features.empty:
                continue
            latest_row = market_data.df_features.iloc[-1]
            prices[pos.ticker] = float(latest_row.get("Close", 0.0))
        return prices

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
        current_prices = _get_group_current_prices(group)
        total_value = group.cash + sum(
            pos.quantity * current_prices.get(pos.ticker, pos.entry_price)
            for pos in group.positions
            if pos.quantity > 0
        )

        overlay_decision = None
        if overlay_manager.overlays:
            overlay_context = OverlayContext(
                current_date=pd.Timestamp(signal_date),
                portfolio_cash=group.cash,
                portfolio_value=total_value,
                positions={pos.ticker: pos for pos in group.positions},
                current_prices=current_prices,
                group_id=group.id,
            )
            overlay_decision, per_overlay = overlay_manager.evaluate(overlay_context)
            overlay_summaries.append(
                {
                    "group_id": group.id,
                    "group_name": group.name,
                    **overlay_manager.summarize(overlay_decision, per_overlay),
                }
            )
        buy_count = 0
        new_positions_opened = 0
        max_new_positions = (
            overlay_decision.max_new_positions if overlay_decision else None
        )

        # Step 1) Build SELL/HOLD signals first (for projected cash release)
        sell_count = 0
        projected_sell_proceeds = 0.0
        projected_position_count = len(current_tickers)
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
                unrealized_pl = (
                    (current_price - position.entry_price) / position.entry_price
                ) * 100
                md = market_data.metadata if market_data else {}
                overlay_reason = None
                if overlay_decision and overlay_decision.force_exit:
                    overlay_reason = "Overlay force exit"
                elif (
                    overlay_decision
                    and overlay_decision.exit_overrides
                    and ticker in overlay_decision.exit_overrides
                ):
                    overlay_reason = overlay_decision.exit_overrides[ticker]

                if overlay_reason:
                    signal = Signal(
                        group_id=group.id,
                        ticker=ticker,
                        ticker_name=md.get("company_name", ticker) if md else ticker,
                        signal_type="SELL",
                        action="SELL",
                        confidence=1.0,
                        score=0,
                        reason=overlay_reason,
                        current_price=float(current_price),
                        position_qty=position.quantity,
                        entry_price=position.entry_price,
                        entry_date=position.entry_date,
                        holding_days=(pd.Timestamp(signal_date) - entry_date_ts).days,
                        unrealized_pl_pct=float(unrealized_pl),
                        strategy_name="Overlay",
                    )
                    all_signals.append(signal)
                    sell_count += 1
                    total_sell_signals += 1
                    continue
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

                # Get evaluation details for reporting (for both SELL and HOLD)
                evaluation_details = None
                if hasattr(exit_strategy, "get_evaluation_details"):
                    try:
                        evaluation_details = exit_strategy.get_evaluation_details(
                            signals_position, market_data
                        )
                    except Exception as e:
                        if args.verbose:
                            print(f"        Evaluation details error for {ticker}: {e}")

                # Process SELL signals
                if exit_signal.action == SignalAction.SELL:
                    action_str = (
                        exit_signal.action.value
                        if hasattr(exit_signal.action, "value")
                        else "SELL"
                    )
                    signal_type = "SELL"
                elif exit_signal.action == SignalAction.HOLD:
                    # Generate HOLD signal for reporting
                    action_str = "HOLD"
                    signal_type = "HOLD"
                else:
                    action_str = (
                        exit_signal.action.value
                        if hasattr(exit_signal.action, "value")
                        else str(exit_signal.action)
                    )
                    signal_type = "SELL"

                holding_days = (pd.Timestamp(signal_date) - entry_date_ts).days
                unrealized_pl = (
                    (current_price - position.entry_price) / position.entry_price
                ) * 100
                md = market_data.metadata if market_data else {}

                signal = Signal(
                    group_id=group.id,
                    ticker=ticker,
                    ticker_name=md.get("company_name", ticker) if md else ticker,
                    signal_type=signal_type,
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
                    evaluation_details=evaluation_details,
                )
                all_signals.append(signal)

                # Count only SELL signals for statistics
                if signal_type == "SELL":
                    sell_pct = 1.0
                    if exit_signal.metadata:
                        sell_pct = float(
                            exit_signal.metadata.get("sell_percentage", 1.0)
                        )
                    if action_str and action_str != "SELL":
                        sell_pct = _parse_sell_pct(action_str)
                    qty_to_sell = _calculate_sell_quantity(
                        ticker=ticker,
                        total_qty=position.quantity,
                        sell_pct=sell_pct,
                    )
                    estimated_sell_price = _estimate_sell_price(float(current_price))
                    projected_sell_proceeds += qty_to_sell * estimated_sell_price
                    if qty_to_sell >= position.quantity:
                        projected_position_count -= 1
                    sell_count += 1
                    total_sell_signals += 1
            except Exception:
                continue

        # Step 2) Build BUY signals using projected post-sell cash/exposure
        invested_value = sum(
            pos.quantity * current_prices.get(pos.ticker, pos.entry_price)
            for pos in group.positions
            if pos.quantity > 0
        )
        planning_cash = float(group.cash) + projected_sell_proceeds
        planning_invested_value = max(0.0, invested_value - projected_sell_proceeds)

        for ticker, eval_obj in comprehensive_evals.items():
            if ticker in current_tickers:
                continue
            strategy_eval = eval_obj.evaluations.get(entry_strategy_name)
            if not strategy_eval or strategy_eval.signal_action != "BUY":
                continue

            # Check if adding new position would exceed max_positions_per_group
            if (
                projected_position_count + new_positions_opened
                >= prod_cfg.max_positions_per_group
            ):
                break

            if (
                max_new_positions is not None
                and new_positions_opened >= max_new_positions
            ):
                break

            max_position_pct = float(prod_cfg.max_position_pct)
            if overlay_decision and overlay_decision.position_scale is not None:
                max_position_pct *= overlay_decision.position_scale

            available_cash = planning_cash
            if overlay_decision and overlay_decision.target_exposure is not None:
                max_invested = total_value * overlay_decision.target_exposure
                available_exposure = max(0.0, max_invested - planning_invested_value)
                available_cash = min(available_cash, available_exposure)

            estimated_buy_price = _estimate_buy_price(float(eval_obj.current_price))
            suggested_qty, required_capital, lot_size = _calc_suggested_qty(
                ticker=ticker,
                current_price=estimated_buy_price,
                available_cash=available_cash,
                total_portfolio_value=total_value,
                max_position_pct=max_position_pct,
            )

            buy_reason = strategy_eval.reason
            if overlay_decision and overlay_decision.block_new_entries:
                suggested_qty = 0
                required_capital = 0.0
                buy_reason = f"{buy_reason}; Overlay blocked new entries"
            elif suggested_qty <= 0:
                buy_reason = (
                    f"{buy_reason}; SuggestedQty=0: projected cash/exposure insufficient "
                    f"for lot size {lot_size}"
                )

            buy_reason = (
                f"{buy_reason}; PlanningPrice=Close*{1.0 + buy_price_buffer_pct:.2f}, "
                f"SellPrice=Close*{1.0 - sell_price_buffer_pct:.2f}"
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
                current_price=estimated_buy_price,
                suggested_qty=suggested_qty,
                required_capital=required_capital,
                strategy_name=entry_strategy_name,
            )
            all_signals.append(signal)
            buy_count += 1
            total_buy_signals += 1
            if suggested_qty > 0:
                new_positions_opened += 1
                planning_cash = max(0.0, planning_cash - required_capital)
                planning_invested_value += required_capital

        print(f"      BUY: {buy_count}, SELL: {sell_count}")

    signal_file = prod_cfg.signal_file_pattern.replace("{date}", signal_date)
    Path(signal_file).parent.mkdir(parents=True, exist_ok=True)

    # Custom JSON encoder to handle numpy/pandas types
    class CustomJSONEncoder(json.JSONEncoder):
        def default(self, obj):
            import numpy as np
            import pandas as pd

            if isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            elif isinstance(obj, (pd.Timestamp, datetime)):
                return obj.isoformat()
            elif isinstance(obj, np.bool_):
                return bool(obj)
            return super().default(obj)

    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump(
            [s.__dict__ for s in all_signals],
            f,
            indent=2,
            ensure_ascii=False,
            cls=CustomJSONEncoder,
        )

    print(f"\n[Output] Total signals: {len(all_signals)}")
    print(f"  BUY: {total_buy_signals}, SELL: {total_sell_signals}")
    print(f"  Signals saved: {signal_file}")

    builder = ReportBuilder(state, data_manager)
    report_md = builder.generate_daily_report(
        signals=all_signals,
        report_date=signal_date,
        comprehensive_evaluations=comprehensive_evals,
        overlay_summary=overlay_summaries,
    )
    report_file = prod_cfg.report_file_pattern.replace("{date}", signal_date)
    builder.save_report(report_md, report_file)
    print(f"  Report saved: {report_file}")
