from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.runner import run_entry_signal_analysis


def test_run_entry_signal_analysis_writes_artifacts(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": ["FakeEntry", "FakeEntry"],
            "entry_filter_name": ["production", "production"],
            "signal_date": ["2026-01-05", "2026-01-05"],
            "ticker": ["7203", "6758"],
            "selected": [True, False],
            "positive_rank_score": [True, False],
            "tail_guard_limit": [1, 1],
            "forward_return_1d_pct": [1.2, -0.3],
            "forward_return_3d_pct": [2.5, -0.8],
            "forward_return_5d_pct": [4.0, -1.1],
            "forward_diff_1d": [1.2, -0.3],
            "forward_diff_3d": [2.5, -0.8],
            "forward_diff_5d": [4.0, -1.1],
        }
    )
    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[1, 3, 5],
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    manifest_path = Path(summary.artifacts.manifest_json)
    summary_path = Path(summary.artifacts.summary_json)
    report_path = Path(summary.artifacts.report_md)
    assert summary.candidate_count == 2
    assert summary.selected_count == 1
    assert summary.effective_entry_filter_mode == "off"
    assert summary.effective_entry_filter_names == ["production"]
    assert summary.overall["1d"]["count"] == 1
    assert Path(summary.artifacts.candidates_csv).exists()
    assert Path(summary.artifacts.selected_csv).exists()
    assert manifest_path.exists()
    assert summary_path.exists()
    assert report_path.exists()
    assert "FakeEntry" in manifest_path.read_text(encoding="utf-8")


def test_run_entry_signal_analysis_handles_empty_candidate_results(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: pd.DataFrame())
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[1, 3, 5],
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    assert summary.candidate_count == 0
    assert summary.selected_count == 0
    assert summary.effective_entry_filter_mode == "off"
    assert summary.overall["1d"]["count"] == 0
    assert Path(summary.artifacts.summary_json).exists()
    assert Path(summary.artifacts.manifest_json).exists()