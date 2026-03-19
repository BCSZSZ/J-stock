import csv
import subprocess
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


def _try_sync_state_to_s3(args, prod_cfg) -> None:
    """Upload production_state.json and trade_history.json to S3 after --input save."""
    aws_profile = getattr(args, "aws_profile", None)
    ops_s3_prefix = getattr(prod_cfg, "ops_s3_prefix", None)
    if not aws_profile or not ops_s3_prefix:
        return

    prefix = ops_s3_prefix.rstrip("/")
    uploads = [
        (prod_cfg.state_file, f"{prefix}/state/production_state.json"),
        (prod_cfg.history_file, f"{prefix}/state/trade_history.json"),
    ]

    def _do_uploads() -> list[str]:
        """Returns list of error messages; empty = all ok."""
        errors = []
        for local_path, s3_uri in uploads:
            cmd = ["aws", "s3", "cp", str(local_path), s3_uri, "--profile", aws_profile]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✅ {Path(local_path).name} → {s3_uri}")
            else:
                errors.append((Path(local_path).name, (result.stderr or result.stdout).strip()))
        return errors

    print(f"\n[S3 Sync] Uploading state to {prefix} (profile={aws_profile})")
    errors = _do_uploads()

    if errors:
        first_err = errors[0][1]
        if "expired" in first_err.lower() or "login" in first_err.lower() or "sso" in first_err.lower():
            print(f"  ⚠️  AWS SSO session expired. Running: aws sso login --profile {aws_profile}")
            login = subprocess.run(["aws", "sso", "login", "--profile", aws_profile])
            if login.returncode == 0:
                print("[S3 Sync] Re-authenticated. Retrying uploads...")
                errors = _do_uploads()
            else:
                print("[S3 Sync] SSO login failed. Upload skipped.")
                return

    if not errors:
        print("[S3 Sync] Done.")
    else:
        for name, err in errors:
            print(f"  ❌ Failed to upload {name}: {err}")
        print("[S3 Sync] Some uploads failed. Run sync_ops_state_s3.py push manually.")


def _trade_cash_delta(trade) -> float:
    if trade.cash_effect and "delta" in trade.cash_effect:
        return float(trade.cash_effect["delta"])
    if trade.action == "BUY":
        return -float(trade.total_jpy)
    return float(trade.total_jpy)


def _build_buy_effect(position) -> dict:
    return {
        "effect_type": "OPEN",
        "lot_id": position.lot_id,
        "ticker": position.ticker,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "entry_date": position.entry_date,
        "entry_score": position.entry_score,
        "peak_price": position.peak_price,
    }


def _reverse_trade_event(target_group, history, old_trade) -> tuple[bool, str]:
    effects = old_trade.position_effects or []
    cash_delta = _trade_cash_delta(old_trade)

    if old_trade.action == "BUY" and effects:
        open_effects = [e for e in effects if e.get("effect_type") == "OPEN"]
        for effect in open_effects:
            position = target_group.get_position_by_lot_id(effect.get("lot_id", ""))
            expected_qty = int(effect.get("quantity", old_trade.quantity))
            if position is None:
                return False, "created lot no longer exists; likely consumed by later SELL"
            if position.quantity != expected_qty:
                return False, "created lot quantity changed after original BUY"

        for effect in reversed(open_effects):
            position = target_group.get_position_by_lot_id(effect.get("lot_id", ""))
            if position is not None:
                target_group.positions.remove(position)
        target_group.cash -= cash_delta
        return True, ""

    if old_trade.action == "SELL" and effects:
        close_effects = [e for e in effects if e.get("effect_type") == "CLOSE"]
        for effect in close_effects:
            lot_id = effect.get("lot_id", "")
            remaining_after = int(effect.get("remaining_quantity_after", 0))
            position = target_group.get_position_by_lot_id(lot_id)
            if remaining_after == 0:
                if position is not None:
                    return False, f"lot {lot_id} was changed after original SELL"
            else:
                if position is None:
                    return False, f"lot {lot_id} missing after original SELL"
                if position.quantity != remaining_after:
                    return False, f"lot {lot_id} quantity changed after original SELL"

        for effect in reversed(close_effects):
            target_group.restore_position_lot(
                lot_id=effect.get("lot_id", ""),
                ticker=effect.get("ticker", old_trade.ticker),
                quantity=int(effect.get("consumed_quantity", 0)),
                entry_price=float(effect.get("entry_price", 0.0)),
                entry_date=effect.get("entry_date", old_trade.date),
                entry_score=float(effect.get("entry_score", 0.0)),
                peak_price=float(effect.get("peak_price", effect.get("entry_price", 0.0))),
            )
        target_group.cash -= cash_delta
        return True, ""

    if old_trade.action == "BUY":
        ticker, buy_date = old_trade.ticker, old_trade.date
        to_remove = [
            p for p in target_group.positions
            if p.ticker == ticker and p.entry_date == buy_date
        ]
        for p in to_remove:
            target_group.positions.remove(p)
        target_group.cash -= cash_delta
        return True, "legacy BUY fallback applied"

    if old_trade.action == "SELL":
        existing = target_group.get_positions_by_ticker(old_trade.ticker)
        if existing:
            existing[0].quantity += old_trade.quantity
        else:
            buy_trades = [
                t for t in history.get_trades_by_ticker(old_trade.ticker, active_only=False)
                if t.action == "BUY"
            ]
            if not buy_trades:
                return False, "legacy SELL fallback has no BUY history to restore"
            last_buy = buy_trades[-1]
            target_group.restore_position_lot(
                lot_id=f"legacy_restore_{old_trade.event_id}",
                ticker=old_trade.ticker,
                quantity=old_trade.quantity,
                entry_price=last_buy.price,
                entry_date=last_buy.date,
                entry_score=float(last_buy.entry_score or 0.0),
                peak_price=last_buy.price,
            )
        target_group.cash -= cash_delta
        return True, "legacy SELL fallback applied"

    return False, "unsupported trade action for reverse"


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

            # Overwrite check: if same (date, ticker, action) already exists, undo it first
            existing_trade = history.find_active_trade(
                date=effective_date,
                group_id=target_group.id,
                ticker=ticker,
                action=action,
            )
            if existing_trade is not None:
                if action == "SELL":
                    current_held_qty = sum(p.quantity for p in target_group.get_positions_by_ticker(ticker))
                    if qty > current_held_qty + existing_trade.quantity:
                        print(
                            f"  ⚠️  Cannot overwrite SELL {ticker}: new qty {qty} exceeds restored holding {current_held_qty + existing_trade.quantity}."
                        )
                        continue
                if action == "BUY":
                    old_info = f"{existing_trade.quantity}@{existing_trade.price}"
                    ok, reason = _reverse_trade_event(target_group, history, existing_trade)
                    if not ok:
                        print(f"  ⚠️  Cannot overwrite BUY {ticker}: {reason}. Skipped.")
                        continue
                    print(f"  ⚠️  OVERWRITE! BUY {ticker}: previous={old_info} → new={qty}@{price}")
                elif action == "SELL":
                    old_info = f"{existing_trade.quantity}@{existing_trade.price}"
                    ok, reason = _reverse_trade_event(target_group, history, existing_trade)
                    if not ok:
                        print(f"  ⚠️  Cannot overwrite SELL {ticker}: {reason}. Skipped.")
                        continue
                    print(f"  ⚠️  OVERWRITE! SELL {ticker}: previous={old_info} → new={qty}@{price}")

            if action == "BUY":
                cash_before = target_group.cash
                new_position = target_group.add_position(
                    ticker=ticker,
                    quantity=qty,
                    entry_price=price,
                    entry_date=effective_date,
                    entry_score=0.0,
                )
                new_trade = history.record_trade(
                    date=effective_date,
                    group_id=target_group.id,
                    ticker=ticker,
                    action="BUY",
                    quantity=qty,
                    price=price,
                    entry_score=0.0,
                    position_effects=[_build_buy_effect(new_position)],
                    cash_effect={
                        "delta": target_group.cash - cash_before,
                        "before": cash_before,
                        "after": target_group.cash,
                    },
                    source={
                        "channel": "manual_csv",
                        "file": args.manual_file,
                    },
                    replaces_event_id=existing_trade.event_id if existing_trade is not None else None,
                )
                if existing_trade is not None:
                    history.mark_superseded(existing_trade, new_trade)
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

                cash_before = target_group.cash
                sell_details = target_group.partial_sell(
                    ticker=ticker,
                    quantity=qty,
                    exit_price=price,
                    return_details=True,
                )
                new_trade = history.record_trade(
                    date=effective_date,
                    group_id=target_group.id,
                    ticker=ticker,
                    action="SELL",
                    quantity=sell_details["sold_quantity"],
                    price=price,
                    exit_reason="Manual input",
                    exit_score=0.0,
                    position_effects=sell_details["consumed_lots"],
                    cash_effect={
                        "delta": target_group.cash - cash_before,
                        "before": cash_before,
                        "after": target_group.cash,
                    },
                    source={
                        "channel": "manual_csv",
                        "file": args.manual_file,
                    },
                    replaces_event_id=existing_trade.event_id if existing_trade is not None else None,
                )
                if existing_trade is not None:
                    history.mark_superseded(existing_trade, new_trade)
                recorded += 1
                print(f"  ✅ SELL recorded: {ticker} {qty} @ {price}")
            else:
                print(f"  ⚠️ invalid action '{action}' (use BUY/SELL): {row}")

        state.save()
        history.save()
        print(f"\n✅ Manual input completed. Recorded trades: {recorded}")
        print(f"  State saved: {prod_cfg.state_file}")
        print(f"  History saved: {prod_cfg.history_file}")

        _try_sync_state_to_s3(args, prod_cfg)
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

        cash_before = group.cash
        new_position = group.add_position(
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
            position_effects=[_build_buy_effect(new_position)],
            cash_effect={
                "delta": group.cash - cash_before,
                "before": cash_before,
                "after": group.cash,
            },
            source={
                "channel": "signal_confirmed",
                "signal_date": signal_date,
            },
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

        cash_before = group.cash
        sell_details = group.partial_sell(
            ticker=ticker,
            quantity=qty,
            exit_price=price,
            return_details=True,
        )
        history.record_trade(
            date=trade_date,
            group_id=group_id,
            ticker=ticker,
            action="SELL",
            quantity=sell_details["sold_quantity"],
            price=price,
            exit_reason=sig.get("reason"),
            exit_score=float(sig.get("confidence", 0) or 0) * 100,
            position_effects=sell_details["consumed_lots"],
            cash_effect={
                "delta": group.cash - cash_before,
                "before": cash_before,
                "after": group.cash,
            },
            source={
                "channel": "signal_confirmed",
                "signal_date": signal_date,
            },
        )
        recorded += 1
        print(f"  ✅ SELL recorded: {qty} @ {price}")

    state.save()
    history.save()
    print(f"\n✅ Manual input completed. Recorded trades: {recorded}")
    print(f"  State saved: {prod_cfg.state_file}")
    print(f"  History saved: {prod_cfg.history_file}")
