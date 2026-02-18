from datetime import datetime


def run_status(prod_cfg, state) -> None:
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


def run_set_cash(args, state) -> None:
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


def run_set_position(args, state) -> None:
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
