from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

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
    assert summary.primary_horizon_validation.primary_horizon == 5
    assert summary.primary_horizon_validation.overall.count == 1
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
    assert summary.primary_horizon_validation.primary_horizon == 5
    assert summary.primary_horizon_validation.overall.count == 0
    assert Path(summary.artifacts.summary_json).exists()
    assert Path(summary.artifacts.manifest_json).exists()


def test_run_entry_signal_analysis_includes_primary_horizon_validation(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": ["FakeEntry"] * 4,
            "entry_filter_name": ["atr_low", "atr_low", "atr_high", "atr_high"],
            "signal_date": ["2025-01-10", "2025-02-10", "2026-01-15", "2026-01-16"],
            "ticker": ["7203", "6758", "6501", "8306"],
            "selected": [True, True, True, True],
            "positive_rank_score": [True, True, True, True],
            "tail_guard_limit": [1, 1, 1, 1],
            "rank_score": [0.1, 0.2, 0.8, 0.9],
            "confidence": [0.55, 0.60, 0.75, 0.80],
            "forward_return_1d_pct": [10.0, -10.0, 1.0, 1.0],
            "forward_return_3d_pct": [2.0, 4.0, -1.0, 8.0],
            "forward_diff_1d": [10.0, -10.0, 1.0, 1.0],
            "forward_diff_3d": [2.0, 4.0, -1.0, 8.0],
        }
    )
    benchmark_dates = pd.bdate_range("2024-12-02", "2026-01-31")
    close_values: list[float] = []
    for value in benchmark_dates:
        if value <= pd.Timestamp("2025-01-10"):
            close_values.append(100.0 + len(close_values) * 0.4)
        elif value <= pd.Timestamp("2025-12-10"):
            close_values.append(110.0)
        else:
            prior = close_values[-1] if close_values else 110.0
            close_values.append(prior - 0.6)
    benchmark_frame = pd.DataFrame({"Date": benchmark_dates, "Close": close_values})

    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("grid", ["atr_low", "atr_high"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: benchmark_frame)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203", "6758", "6501", "8306"],
        start_date=date(2025, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[1, 3],
        primary_horizon=3,
        data_root=str(tmp_path / "data"),
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    validation = summary.primary_horizon_validation
    report_text = Path(summary.artifacts.report_md).read_text(encoding="utf-8")
    summary_text = Path(summary.artifacts.summary_json).read_text(encoding="utf-8")

    assert validation.primary_horizon == 3
    assert validation.primary_return_column == "forward_return_3d_pct"
    assert validation.overall.count == 4
    assert validation.overall.avg_return_pct == pytest.approx(3.25)
    assert validation.overall.median_return_pct == pytest.approx(3.0)
    assert validation.overall.mean_gt_median is True
    assert validation.overall.avg_loss_pct == pytest.approx(-1.0)
    assert validation.overall.p50_return_pct == pytest.approx(3.0)
    assert [item.group_key for item in validation.by_year] == ["2025", "2026"]
    assert [item.group_key for item in validation.by_month] == ["2025-01", "2025-02", "2026-01"]
    assert [item.group_key for item in validation.by_entry_filter] == ["atr_high", "atr_low"]
    assert validation.signal_strength_metric == "rank_score"
    assert validation.signal_strength_bucket_method == "quantile_4"
    assert [item.group_key for item in validation.by_signal_strength_bucket] == ["Q1", "Q2", "Q3", "Q4"]
    assert [item.group_key for item in validation.by_market_regime] == ["bull", "sideways", "bear"]
    assert validation.by_market_regime[0].stats.count == 1
    assert validation.by_market_regime[1].stats.count == 1
    assert validation.by_market_regime[2].stats.count == 2
    assert "Primary Horizon Validation" in report_text
    assert "primary_horizon_validation" in summary_text