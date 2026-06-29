from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.entry_exit_validation.models import EntryExitValidationRequest
from src.entry_exit_validation.scanner import EntryExitScanResult
from src.entry_exit_validation.runner import run_entry_exit_validation


def test_run_entry_exit_validation_writes_artifacts(tmp_path, monkeypatch) -> None:
    import src.entry_exit_validation.runner as runner

    trades = pd.DataFrame(
        {
            "entry_strategy": ["EntryA", "EntryA"],
            "exit_strategy": ["ExitA", "ExitA"],
            "entry_filter_name": ["production", "production"],
            "ticker": ["1111", "2222"],
            "signal_date": ["2026-01-05", "2026-01-06"],
            "entry_date": ["2026-01-06", "2026-01-07"],
            "exit_date": ["2026-01-10", "2026-01-08"],
            "return_pct": [5.0, -2.0],
            "holding_days": [4, 1],
            "exit_reason": ["take profit", "hardstop"],
            "exit_urgency": ["TAKE_PROFIT", "HARDSTOP"],
            "no_exit": [False, False],
            "rank_score": [0.8, 0.2],
            "forward_return_3d_pct": [4.0, -1.0],
            "forward_return_5d_pct": [3.0, -1.5],
        }
    )
    contexts = [SimpleNamespace(), SimpleNamespace()]
    monkeypatch.setattr(
        runner,
        "scan_entry_exit_candidates",
        lambda _request: EntryExitScanResult(candidates=contexts, cache=object()),
    )
    monkeypatch.setattr(runner, "simulate_candidate_exits", lambda _contexts, _request, _cache: trades)
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )

    request = EntryExitValidationRequest(
        entry_strategies=["EntryA"],
        exit_strategies=["ExitA"],
        tickers=["1111", "2222"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[3, 5],
        output_dir=str(tmp_path),
    )

    summary = run_entry_exit_validation(request)

    assert summary.candidate_count == 2
    assert summary.simulated_trade_count == 2
    assert summary.effective_entry_filter_mode == "off"
    assert summary.effective_entry_filter_names == ["production"]
    assert summary.artifacts.selected_trades_csv is None
    assert summary.artifacts.selected_trades_parquet is not None
    assert Path(summary.artifacts.selected_trades_parquet).exists()
    assert Path(summary.artifacts.combo_summary_csv).exists()
    assert Path(summary.artifacts.combo_robustness_ranking_csv).exists()
    assert Path(summary.artifacts.summary_json).exists()
    assert Path(summary.artifacts.manifest_json).exists()
    assert "EntryA" in Path(summary.artifacts.manifest_json).read_text(encoding="utf-8")


def test_run_entry_exit_validation_handles_empty_trades(tmp_path, monkeypatch) -> None:
    import src.entry_exit_validation.runner as runner

    monkeypatch.setattr(
        runner,
        "scan_entry_exit_candidates",
        lambda _request: EntryExitScanResult(candidates=[], cache=object()),
    )
    monkeypatch.setattr(
        runner,
        "simulate_candidate_exits",
        lambda _contexts, _request, _cache: pd.DataFrame(),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )

    request = EntryExitValidationRequest(
        entry_strategies=["EntryA"],
        exit_strategies=["ExitA"],
        tickers=["1111"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        output_dir=str(tmp_path),
    )

    summary = run_entry_exit_validation(request)

    assert summary.candidate_count == 0
    assert summary.simulated_trade_count == 0
    assert "No simulated trades" in summary.warnings[0]
    assert Path(summary.artifacts.summary_json).exists()
