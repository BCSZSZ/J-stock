from __future__ import annotations

from typing import Any

from src.entry_exit_validation.runtime import build_request_from_args, load_config_manager, resolve_universe_files
from src.entry_exit_validation.runner import run_entry_exit_validation


def cmd_entry_exit_validation(args: Any) -> None:
    request = build_request_from_args(args)
    config_mgr = load_config_manager()
    universe_files = resolve_universe_files(args, config_mgr)

    print("Entry x Exit Validation")
    print(f"  entry strategies: {', '.join(request.entry_strategies)}")
    print(f"  exit strategies: {', '.join(request.exit_strategies)}")
    print(f"  universe files: {', '.join(universe_files)}")
    print(f"  tickers: {len(request.tickers)}")
    print(f"  range: {request.start_date} -> {request.end_date}")
    print(f"  horizons: {', '.join(map(str, request.normalized_horizons))}")
    print(f"  execution_mode: {request.execution_mode}")
    print(f"  signal_scope: {request.signal_scope}")
    print(f"  max_holding_trading_days: {request.max_holding_trading_days}")
    print(f"  ranking_strategy: {request.ranking_strategy}")
    print(f"  entry_filter_mode: {request.entry_filter_mode}")
    run_entry_exit_validation(request)
