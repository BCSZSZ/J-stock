from datetime import datetime
import json
import os
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from dotenv import load_dotenv


def _load_monitor_tickers(monitor_list_file: str) -> List[str]:
    """Load monitor tickers from JSON/TXT file."""
    path = Path(monitor_list_file)
    if not path.exists():
        raise FileNotFoundError(f"Monitor list not found: {monitor_list_file}")

    if path.suffix.lower() == ".json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        raw = data.get("tickers", []) if isinstance(data, dict) else data
        tickers = [item.get("code") if isinstance(item, dict) else str(item) for item in raw]
        return [ticker for ticker in tickers if ticker]

    tickers = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                tickers.append(line)
    return tickers


def _ensure_groups(state, config_mgr, prod_cfg) -> None:
    """Ensure strategy groups exist in state."""
    if len(state.get_all_groups()) > 0:
        return

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


def _get_signal_date_from_path(path: Path) -> Optional[str]:
    stem = path.stem
    if stem.startswith("signals_"):
        return stem.replace("signals_", "")
    return stem


def _find_latest_signal_file(pattern: str, signal_date: Optional[str]) -> Optional[Path]:
    if signal_date:
        candidate = Path(pattern.replace("{date}", signal_date))
        return candidate if candidate.exists() else None

    pattern_path = Path(pattern)
    parent = pattern_path.parent if str(pattern_path.parent) not in ["", "."] else Path(".")
    if not parent.exists():
        return None

    files = sorted(parent.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def _parse_signal_payload(filepath: Path) -> List[Dict]:
    with open(filepath, "r", encoding="utf-8") as f:
        payload = json.load(f)

    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict) and "signals" in payload:
        flattened = []
        signal_dict = payload.get("signals", {})
        for group_id, group_signals in signal_dict.items():
            for sig in group_signals:
                sig = dict(sig)
                sig.setdefault("group_id", group_id)
                flattened.append(sig)
        return flattened

    return []


def _run_daily_workflow(args, prod_cfg, state) -> None:
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

    monitor_tickers = _load_monitor_tickers(prod_cfg.monitor_list_file)

    def _has_today_data(tickers: List[str], expected_date: str):
        expected = pd.Timestamp(expected_date).date()
        latest_seen = None
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

            latest = market_data.current_date.date()
            data_ready_count += 1
            if latest_seen is None or latest > latest_seen:
                latest_seen = latest

            if latest >= expected:
                return True, checked, data_ready_count, latest_seen

        return False, checked, data_ready_count, latest_seen

    if not args.skip_fetch:
        print("\n[Data Update] Fetching latest market data...")
        from src.client.jquants_client import JQuantsV2Client
        from src.data.benchmark_manager import update_benchmarks
        from src.data.pipeline import StockETLPipeline

        if not api_key:
            print("[ERROR] JQUANTS_API_KEY not found (required when fetch is enabled)")
            return

        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client)
        if benchmark_result["success"]:
            print(f"  TOPIX updated: {benchmark_result['topix_records']} records")

        pipeline = StockETLPipeline(api_key)
        summary = pipeline.run_batch(monitor_tickers, fetch_aux_data=True)
        print(f"  Updated {summary['successful']}/{summary['total']} stocks")
    else:
        print("\n[Data Update] Skipped (--skip-fetch flag)")

    print("\n[Signal] Generating end-of-day signals...")
    Path("output/signals").mkdir(parents=True, exist_ok=True)
    Path("output/report").mkdir(parents=True, exist_ok=True)

    data_manager = StockDataManager(api_key=api_key)
    print(f"  Monitoring {len(monitor_tickers)} stocks")

    today = datetime.now().strftime("%Y-%m-%d")
    ready, checked, ready_count, latest_seen = _has_today_data(monitor_tickers, today)
    if not ready:
        latest_txt = latest_seen.strftime("%Y-%m-%d") if latest_seen else "N/A"
        print("\n[WARN] No same-day market data detected.")
        print(f"  Today: {today} | Latest available: {latest_txt}")
        print(f"  Checked tickers: {checked}, with feature data: {ready_count}")
        print("  It may be too early (before EOD data is published). Workflow aborted.")
        return

    all_signals = []
    groups = state.get_all_groups()
    group_configs = {g["id"]: g for g in (prod_cfg.strategy_groups or [])}
    entry_strategy_names = set()
    for group in groups:
        cfg = group_configs.get(group.id, {})
        entry_strategy_names.add(cfg.get("entry_strategy", prod_cfg.default_entry_strategy))

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
        entry_strategy_name = group_cfg.get("entry_strategy", prod_cfg.default_entry_strategy)
        exit_strategy_name = group_cfg.get("exit_strategy", prod_cfg.default_exit_strategy)

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

    signal_file = prod_cfg.signal_file_pattern.replace("{date}", today)
    Path(signal_file).parent.mkdir(parents=True, exist_ok=True)
    with open(signal_file, "w", encoding="utf-8") as f:
        json.dump([s.__dict__ for s in all_signals], f, indent=2, ensure_ascii=False)

    print(f"\n[Output] Total signals: {len(all_signals)}")
    print(f"  BUY: {total_buy_signals}, SELL: {total_sell_signals}")
    print(f"  Signals saved: {signal_file}")

    builder = ReportBuilder(state, data_manager)
    report_md = builder.generate_daily_report(
        signals=all_signals,
        report_date=today,
        comprehensive_evaluations=comprehensive_evals,
    )
    report_file = prod_cfg.report_file_pattern.replace("{date}", today)
    builder.save_report(report_md, report_file)
    print(f"  Report saved: {report_file}")


def _parse_sell_action_to_pct(action: str) -> float:
    if "100" in action:
        return 1.0
    if "75" in action:
        return 0.75
    if "50" in action:
        return 0.5
    if "25" in action:
        return 0.25
    return 1.0


def _run_input_workflow(args, prod_cfg, state) -> None:
    from src.production import TradeHistoryManager

    signal_path = _find_latest_signal_file(prod_cfg.signal_file_pattern, args.signal_date)
    if not signal_path:
        print("[ERROR] Signal file not found. Run 'production --daily' first.")
        return

    signal_date = args.signal_date or _get_signal_date_from_path(signal_path)
    trade_date = args.trade_date or datetime.now().strftime("%Y-%m-%d")

    print(f"\n[Input] Loading signal file: {signal_path}")
    print(f"  Signal date: {signal_date} | Trade date: {trade_date}")
    signals = _parse_signal_payload(signal_path)
    if not signals:
        print("  No signals found in file.")
        return

    history = TradeHistoryManager(history_file=prod_cfg.history_file)
    groups = {g.id: g for g in state.get_all_groups()}

    buy_signals = [s for s in signals if s.get("signal_type") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal_type") in ["SELL", "EXIT"]]
    print(f"  Signals loaded: {len(buy_signals)} BUY, {len(sell_signals)} SELL")

    if not args.yes:
        confirm = input("Continue manual trade input? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    recorded = 0

    print("\n[BUY Input]")
    for sig in buy_signals:
        group_id = sig.get("group_id")
        group = groups.get(group_id)
        if not group:
            continue

        ticker = sig.get("ticker")
        ref_price = float(sig.get("current_price", 0) or 0)
        ans = input(f"BUY {group_id} {ticker} ({sig.get('ticker_name', ticker)}) executed? [y/N]: ").strip().lower()
        if ans != "y":
            continue

        qty_raw = input("  quantity: ").strip()
        price_raw = input(f"  price (default {ref_price:.2f}): ").strip()
        try:
            qty = int(qty_raw)
            price = float(price_raw) if price_raw else ref_price
            if qty <= 0 or price <= 0:
                print("  ⚠️ invalid quantity/price, skipped")
                continue
        except ValueError:
            print("  ⚠️ invalid input, skipped")
            continue

        group.add_position(
            ticker=ticker,
            quantity=qty,
            entry_price=price,
            entry_date=trade_date,
            entry_score=float(sig.get("score", 0) or 0),
        )
        history.record_trade(
            date=trade_date,
            group_id=group_id,
            ticker=ticker,
            action="BUY",
            quantity=qty,
            price=price,
            entry_score=float(sig.get("score", 0) or 0),
        )
        recorded += 1
        print(f"  ✅ BUY recorded: {qty} @ {price}")

    print("\n[SELL Input]")
    for sig in sell_signals:
        group_id = sig.get("group_id")
        group = groups.get(group_id)
        if not group:
            continue

        ticker = sig.get("ticker")
        positions = group.get_positions_by_ticker(ticker)
        held_qty = sum(p.quantity for p in positions)
        if held_qty <= 0:
            continue

        ref_price = float(sig.get("current_price", 0) or 0)
        default_qty = max(1, int(held_qty * _parse_sell_action_to_pct(sig.get("action", "SELL_100%"))))
        ans = input(
            f"SELL {group_id} {ticker} held={held_qty} action={sig.get('action', 'SELL_100%')} executed? [y/N]: "
        ).strip().lower()
        if ans != "y":
            continue

        qty_raw = input(f"  quantity (default {default_qty}): ").strip()
        price_raw = input(f"  price (default {ref_price:.2f}): ").strip()
        try:
            qty = int(qty_raw) if qty_raw else default_qty
            price = float(price_raw) if price_raw else ref_price
            if qty <= 0 or price <= 0:
                print("  ⚠️ invalid quantity/price, skipped")
                continue
            if qty > held_qty:
                print(f"  ⚠️ quantity > held ({held_qty}), skipped")
                continue
        except ValueError:
            print("  ⚠️ invalid input, skipped")
            continue

        group.partial_sell(ticker=ticker, quantity=qty, exit_price=price)
        history.record_trade(
            date=trade_date,
            group_id=group_id,
            ticker=ticker,
            action="SELL",
            quantity=qty,
            price=price,
            exit_reason=sig.get("reason"),
            exit_score=float(sig.get("confidence", 0) or 0) * 100,
        )
        recorded += 1
        print(f"  ✅ SELL recorded: {qty} @ {price}")

    state.save()
    history.save()
    print(f"\n✅ Manual input completed. Recorded trades: {recorded}")
    print(f"  State saved: {prod_cfg.state_file}")
    print(f"  History saved: {prod_cfg.history_file}")


def _run_status(prod_cfg, state) -> None:
    from src.production import TradeHistoryManager

    history = TradeHistoryManager(history_file=prod_cfg.history_file)
    status = state.get_portfolio_status()
    print("\n[Status]")
    print(f"  State file: {prod_cfg.state_file}")
    print(f"  History file: {prod_cfg.history_file}")
    print(f"  Last updated: {state.last_updated}")
    print(f"  Groups: {status['num_groups']} | Positions: {status['total_positions']}")
    print(f"  Total cash: ¥{status['total_cash']:,.0f}")
    print(f"  Trades recorded: {len(history.trades)}")

    for group in state.get_all_groups():
        g = group.get_status()
        print(
            f"    - {g['id']} {g['name']}: cash ¥{g['current_cash']:,.0f}, "
            f"positions {g['position_count']}"
        )


def _run_set_cash(args, state) -> None:
    group_id, amount_raw = args.set_cash
    group = state.get_group(group_id)
    if not group:
        print(f"[ERROR] Group not found: {group_id}")
        return

    try:
        amount = float(amount_raw)
    except ValueError:
        print("[ERROR] amount must be numeric")
        return

    old_cash = group.cash
    group.cash = amount
    state.save()
    print(f"✅ Cash updated: {group_id} ¥{old_cash:,.0f} -> ¥{amount:,.0f}")


def _run_set_position(args, state) -> None:
    from src.production.state_manager import Position

    group_id, ticker, qty_raw, price_raw = args.set_position
    group = state.get_group(group_id)
    if not group:
        print(f"[ERROR] Group not found: {group_id}")
        return

    try:
        qty = int(qty_raw)
        price = float(price_raw)
    except ValueError:
        print("[ERROR] qty must be int and price must be numeric")
        return

    entry_date = args.entry_date or datetime.now().strftime("%Y-%m-%d")

    existing = group.get_positions_by_ticker(ticker)
    for pos in list(existing):
        group.positions.remove(pos)

    if qty > 0:
        group.positions.append(
            Position(
                ticker=ticker,
                quantity=qty,
                entry_price=price,
                entry_date=entry_date,
                entry_score=0.0,
                peak_price=price,
            )
        )

    state.save()
    print(
        "✅ Position overwritten (admin fix): "
        f"{group_id} {ticker} qty={qty} price={price} entry_date={entry_date}"
    )
    print("⚠️ Note: cash is not auto-rebalanced in this admin command.")


def cmd_production(args):
    """Production workflows: daily signal generation / next-day manual input / tools."""
    from src.production import ConfigManager, ProductionState

    print("\n" + "=" * 70)
    print("PRODUCTION SIGNAL ENGINE")
    print("=" * 70)

    config_mgr = ConfigManager("config.json")
    prod_cfg = config_mgr.get_production_config()
    state = ProductionState(state_file=prod_cfg.state_file)
    _ensure_groups(state, config_mgr, prod_cfg)

    print(f"  State file: {prod_cfg.state_file}")
    print(f"  Monitor list: {prod_cfg.monitor_list_file}")
    print(f"  Signal pattern: {prod_cfg.signal_file_pattern}")

    if args.status:
        _run_status(prod_cfg, state)
        return

    if args.set_cash:
        _run_set_cash(args, state)
        return

    if args.set_position:
        _run_set_position(args, state)
        return

    if args.input:
        _run_input_workflow(args, prod_cfg, state)
        return

    _run_daily_workflow(args, prod_cfg, state)
