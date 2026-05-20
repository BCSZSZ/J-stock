from __future__ import annotations

from datetime import datetime

from src.production import TradeHistoryManager
from src.production.signal_price_repair import (
    SignalPriceRepairSummary,
    format_signal_price_repair_summary,
    repair_signal_entry_prices,
)


def run_signal_price_check(
    prod_cfg,
    state,
    *,
    scope: str,
    target_date: str | None = None,
    data_root: str | None = None,
    save_if_changed: bool = True,
) -> SignalPriceRepairSummary:
    history = TradeHistoryManager(history_file=prod_cfg.history_file)
    summary = repair_signal_entry_prices(
        state,
        history,
        scope=scope,
        target_date=target_date,
        data_root=data_root,
    )

    for line in format_signal_price_repair_summary(summary):
        print(line)

    if summary.has_changes and save_if_changed:
        state.save()
        history.save()
        print(f"  State saved: {prod_cfg.state_file}")
        print(f"  History saved: {prod_cfg.history_file}")
    else:
        print("  No persisted changes.")

    return summary


def run_signal_price_check_command(args, prod_cfg, state) -> None:
    scope = str(args.check_price or "").strip().lower()
    if scope not in {"all", "today"}:
        print(f"[ERROR] Unsupported check-price scope: {scope}")
        return

    target_date = None
    if scope == "today":
        target_date = datetime.now().strftime("%Y-%m-%d")

    run_signal_price_check(
        prod_cfg,
        state,
        scope=scope,
        target_date=target_date,
        data_root=getattr(prod_cfg, "data_dir", None),
        save_if_changed=True,
    )