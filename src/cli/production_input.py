import csv
from datetime import datetime
from pathlib import Path

from src.cli.production_utils import (
    find_latest_signal_file,
    get_signal_date_from_path,
    parse_signal_payload,
)


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


def _load_manual_trades_csv(file_path: str) -> list[dict]:
    path = Path(file_path)
    if not path.exists():
        print(f"[ERROR] Manual CSV not found: {file_path}")
        return []

    rows = []
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for raw in reader:
            if not raw or all(not cell.strip() for cell in raw):
                continue

            normalized = [cell.strip() for cell in raw]
            header_tokens = {c.lower() for c in normalized}
            if {"ticker", "action", "qty", "quantity", "price"} & header_tokens:
                continue

            rows.append(normalized)

    return rows


def _resolve_manual_group(groups: dict):
    if "group_main" in groups:
        return groups["group_main"]
    if len(groups) == 1:
        return next(iter(groups.values()))
    print("[WARN] Multiple groups detected; cannot resolve manual target group.")
    return None


def run_input_workflow(args, prod_cfg, state) -> None:
    from src.production import TradeHistoryManager

    history = TradeHistoryManager(history_file=prod_cfg.history_file)
    groups = {g.id: g for g in state.get_all_groups()}
    recorded = 0

    if args.manual:
        if not args.manual_file:
            print("[ERROR] --manual requires --manual-file")
            return

        trade_date = args.trade_date or datetime.now().strftime("%Y-%m-%d")
        print(f"\n[Manual Input] CSV: {args.manual_file}")
        print(f"  Trade date: {trade_date}")

        if not args.yes:
            confirm = input("Continue manual CSV input? [y/N]: ").strip().lower()
            if confirm != "y":
                print("Cancelled.")
                return

        manual_rows = _load_manual_trades_csv(args.manual_file)
        if not manual_rows:
            print("[Manual Input] No valid rows found")
            return

        target_group = _resolve_manual_group(groups)
        if target_group is None:
            print("[Manual Input] Skipped: group resolution failed")
            return

        for row in manual_rows:
            if len(row) < 4:
                print(f"  ⚠️ invalid row (need 4 columns): {row}")
                continue

            ticker = row[0]
            action = row[1].upper()
            qty_raw = row[2]
            price_raw = row[3]
            date_raw = row[4] if len(row) > 4 else ""

            try:
                qty = int(qty_raw)
                price = float(price_raw)
            except ValueError:
                print(f"  ⚠️ invalid qty/price: {row}")
                continue

            if qty <= 0 or price <= 0:
                print(f"  ⚠️ invalid qty/price: {row}")
                continue

            effective_date = date_raw or trade_date

            if action == "BUY":
                target_group.add_position(
                    ticker=ticker,
                    quantity=qty,
                    entry_price=price,
                    entry_date=effective_date,
                    entry_score=0.0,
                )
                history.record_trade(
                    date=effective_date,
                    group_id=target_group.id,
                    ticker=ticker,
                    action="BUY",
                    quantity=qty,
                    price=price,
                    entry_score=0.0,
                )
                recorded += 1
                print(f"  ✅ BUY recorded: {ticker} {qty} @ {price}")
            elif action == "SELL":
                positions = target_group.get_positions_by_ticker(ticker)
                held_qty = sum(p.quantity for p in positions)
                if held_qty <= 0:
                    print(f"  ⚠️ no holdings for {ticker}, skipped")
                    continue
                if qty > held_qty:
                    print(
                        f"  ⚠️ quantity > held ({held_qty}) for {ticker}, skipped"
                    )
                    continue

                target_group.partial_sell(
                    ticker=ticker,
                    quantity=qty,
                    exit_price=price,
                )
                history.record_trade(
                    date=effective_date,
                    group_id=target_group.id,
                    ticker=ticker,
                    action="SELL",
                    quantity=qty,
                    price=price,
                    exit_reason="Manual input",
                    exit_score=0.0,
                )
                recorded += 1
                print(f"  ✅ SELL recorded: {ticker} {qty} @ {price}")
            else:
                print(f"  ⚠️ invalid action '{action}' (use BUY/SELL): {row}")

        state.save()
        history.save()
        print(f"\n✅ Manual input completed. Recorded trades: {recorded}")
        print(f"  State saved: {prod_cfg.state_file}")
        print(f"  History saved: {prod_cfg.history_file}")
        return

    signal_path = find_latest_signal_file(
        prod_cfg.signal_file_pattern, args.signal_date
    )
    if not signal_path:
        print("[ERROR] Signal file not found. Run 'production --daily' first.")
        return

    signal_date = args.signal_date or get_signal_date_from_path(signal_path)
    trade_date = args.trade_date or datetime.now().strftime("%Y-%m-%d")

    print(f"\n[Input] Loading signal file: {signal_path}")
    print(f"  Signal date: {signal_date} | Trade date: {trade_date}")
    signals = parse_signal_payload(signal_path)
    if not signals:
        print("  No signals found in file.")
        return

    buy_signals = [s for s in signals if s.get("signal_type") == "BUY"]
    sell_signals = [s for s in signals if s.get("signal_type") in ["SELL", "EXIT"]]
    print(f"  Signals loaded: {len(buy_signals)} BUY, {len(sell_signals)} SELL")

    if not args.yes:
        confirm = input("Continue manual trade input? [y/N]: ").strip().lower()
        if confirm != "y":
            print("Cancelled.")
            return

    print("\n[BUY Input]")
    for sig in buy_signals:
        group_id = sig.get("group_id")
        group = groups.get(group_id)
        if not group:
            continue

        ticker = sig.get("ticker")
        ref_price = float(sig.get("current_price", 0) or 0)
        ans = (
            input(
                f"BUY {group_id} {ticker} ({sig.get('ticker_name', ticker)}) executed? [y/N]: "
            )
            .strip()
            .lower()
        )
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
        default_qty = max(
            1, int(held_qty * _parse_sell_action_to_pct(sig.get("action", "SELL_100%")))
        )
        ans = (
            input(
                f"SELL {group_id} {ticker} held={held_qty} action={sig.get('action', 'SELL_100%')} executed? [y/N]: "
            )
            .strip()
            .lower()
        )
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
