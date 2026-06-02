from __future__ import annotations

from typing import Any

from src.entry_signal_analysis.runtime import build_request_from_args, load_config_manager, resolve_universe_files
from src.entry_signal_analysis.runner import run_entry_signal_analysis


def cmd_entry_signal_analysis(args: Any) -> None:
    request = build_request_from_args(args)
    config_mgr = load_config_manager()
    universe_files = resolve_universe_files(args, config_mgr)

    print("Entry Signal Analysis")
    print(f"  strategies: {', '.join(request.entry_strategies)}")
    print(f"  universe files: {', '.join(universe_files)}")
    print(f"  tickers: {len(request.tickers)}")
    print(f"  range: {request.start_date} -> {request.end_date}")
    print(f"  horizons: {', '.join(map(str, request.normalized_horizons))}")
    print(f"  label_mode: {request.label_mode}")
    print(f"  ranking_strategy: {request.ranking_strategy}")
    print(f"  entry_filter_mode: {request.entry_filter_mode}")
    run_entry_signal_analysis(request)