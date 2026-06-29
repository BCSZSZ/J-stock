from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from src.artifacts.tabular import read_table_auto
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
        analysis_profile="legacy",
        horizons=[1, 3, 5],
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    manifest_path = Path(summary.artifacts.manifest_json)
    summary_path = Path(summary.artifacts.summary_json)
    report_path = Path(summary.artifacts.report_md)
    performance_path = Path(summary.artifacts.performance_json or "")
    assert summary.candidate_count == 2
    assert summary.selected_count == 1
    assert summary.effective_entry_filter_mode == "off"
    assert summary.effective_entry_filter_names == ["production"]
    assert summary.overall["1d"]["count"] == 1
    assert summary.artifacts.candidates_csv is None
    assert summary.artifacts.selected_csv is None
    assert summary.artifacts.candidates_parquet is not None
    assert summary.artifacts.selected_parquet is not None
    assert Path(summary.artifacts.candidates_parquet).exists()
    assert Path(summary.artifacts.selected_parquet).exists()
    assert manifest_path.exists()
    assert summary_path.exists()
    assert report_path.exists()
    assert performance_path.exists()
    assert summary.performance["row_counts"]["selected"] == 1
    assert summary.performance["artifact_sizes_bytes"]["candidates_parquet"] > 0
    assert any(
        item["name"] == "scan_entry_signal_candidates"
        for item in summary.performance["stages"]
    )
    assert summary.primary_horizon_validation.primary_horizon == 5
    assert summary.primary_horizon_validation.overall.count == 1
    assert [item.primary_horizon for item in summary.primary_horizon_validations] == [5]
    assert [item.primary_horizon for item in summary.top_daily_windows_by_horizon] == [5]
    assert summary.top_daily_windows_by_horizon[0].windows == summary.top_daily_windows
    manifest_text = manifest_path.read_text(encoding="utf-8")
    report_text = report_path.read_text(encoding="utf-8")
    assert "FakeEntry" in manifest_text
    assert "over" + "lap_matrix_csv" not in manifest_text
    assert "incremental" + "_lift_csv" not in manifest_text
    assert "#" + "12" not in report_text


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
        analysis_profile="legacy",
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
    assert [item.primary_horizon for item in summary.primary_horizon_validations] == [5]
    assert [item.primary_horizon for item in summary.top_daily_windows_by_horizon] == [5]
    assert summary.top_daily_windows_by_horizon[0].windows == []
    assert Path(summary.artifacts.summary_json).exists()
    assert Path(summary.artifacts.manifest_json).exists()


def test_run_entry_signal_analysis_priority15_compacts_core_outputs(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": ["FakeEntry", "FakeEntry"],
            "entry_filter_name": ["production", "production"],
            "signal_date": ["2026-01-05", "2026-01-06"],
            "entry_date": ["2026-01-06", "2026-01-07"],
            "entry_price": [100.0, 110.0],
            "ticker": ["7203", "6758"],
            "selected": [True, True],
            "rank": [1, 1],
            "rank_score": [2.0, 1.0],
            "positive_rank_score": [True, True],
            "tail_guard_limit": [12, 12],
            "forward_return_5d_pct": [2.0, -1.0],
            "forward_diff_5d": [2.0, -1.0],
            "very_wide_priority15_only_column": ["x" * 100, "y" * 100],
        }
    )
    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[5],
        primary_horizon=5,
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    assert summary.artifacts.candidates_parquet is not None
    assert summary.artifacts.selected_parquet is not None
    candidates_frame = read_table_auto(summary.artifacts.candidates_parquet)
    selected_frame = read_table_auto(summary.artifacts.selected_parquet)
    assert "very_wide_priority15_only_column" not in candidates_frame.columns
    assert "very_wide_priority15_only_column" not in selected_frame.columns
    assert "forward_return_5d_pct" in candidates_frame.columns
    assert summary.performance["row_counts"]["daily_summary"] == 0
    assert summary.performance["row_counts"]["strategy_summary"] == 1
    assert "5d" in summary.overall
    assert any(
        item["name"] == "build_legacy_summaries" and item["behavior"] == "priority15_minimal"
        for item in summary.performance["stages"]
    )
    assert any(
        item["name"] == "write_core_artifacts" and item["behavior"] == "priority15_compact"
        for item in summary.performance["stages"]
    )


def test_run_entry_signal_analysis_priority15_writes_layered_and_columnar_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.runner as runner

    event_metrics = pd.DataFrame(
        {
            "event_row": [1],
            "event_id": ["FakeEntry::production::7203::2026-01-05"],
            "entry_strategy": ["FakeEntry"],
            "entry_filter_name": ["production"],
            "ticker": ["7203"],
            "signal_date": ["2026-01-05"],
            "entry_date": ["2026-01-06"],
            "entry_price": [100.0],
            "selected": [True],
            "rank": [1],
            "rank_score": [3.5],
            "confidence": [0.8],
            "score": [7.0],
            "sector": ["Auto"],
            "liquidity_bucket": ["high"],
            "volatility_bucket": ["mid"],
            "market_regime": ["bull"],
            "forward_return_5d_pct": [4.2],
            "MFE_10d_pct": [6.0],
            "MAE_10d_pct": [-2.0],
            "day10_strong": [True],
            "alpha_5d_vs_universe_pct": [1.2],
            "late_entry_1d_date": ["2026-01-07"],
            "decay_1d_5d_pct": [-0.4],
            "net_return_after_10bps_5d_pct": [4.0],
            "signal_close": [99.0],
            "signal_close_to_next_open_gap_pct": [1.0],
            "entry_day_open_to_close_pct": [0.5],
            "adv20_jpy": [1_000_000_000.0],
            "dollar_volume_jpy": [1_000_000_000.0],
            "turnover_median_20_jpy": [900_000_000.0],
            "entry_atr_ratio": [0.02],
            "spread_proxy_pct": [0.2],
        }
    )
    priority15_outputs = runner.Priority15Outputs(
        event_metrics=event_metrics,
        path_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        target_stop_events=pd.DataFrame(
            {
                "event_row": [1],
                "target_pct": [5.0],
                "stop_pct": [3.0],
                "horizon": [10],
                "hit_type": ["target_first"],
                "days_to_target": [3],
                "days_to_stop": [None],
                "rule_return_pct": [5.0],
            }
        ),
        target_stop_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        checkpoint_events=pd.DataFrame({"entry_strategy": ["FakeEntry"], "checkpoint_day": [10]}),
        checkpoint_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        trend_feature_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        cooldown_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        alpha_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        regime_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        stability_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        signal_decay_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        execution_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        exit_rule_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
        walk_forward_summary=pd.DataFrame({"entry_strategy": ["FakeEntry"], "event_count": [1]}),
    )
    scan_result = SimpleNamespace(
        candidates=event_metrics,
        scanner_metrics={"market_data_build_count": 0},
        cache=None,
    )
    monkeypatch.setattr(runner, "scan_entry_signal_events", lambda _request: scan_result)
    monkeypatch.setattr(runner, "build_priority15_outputs", lambda *_args, **_kwargs: priority15_outputs)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[5],
        primary_horizon=5,
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    parquet_artifact_names = [
        "event_metrics_parquet",
        "event_metrics_core_parquet",
        "event_metrics_path_parquet",
        "event_metrics_checkpoint_parquet",
        "event_metrics_alpha_parquet",
        "event_metrics_decay_parquet",
        "event_metrics_cost_parquet",
        "event_metrics_execution_parquet",
        "target_stop_events_parquet",
        "checkpoint_events_parquet",
    ]
    for artifact_name in parquet_artifact_names:
        path = Path(getattr(summary.artifacts, artifact_name) or "")
        assert path.exists(), artifact_name
        assert summary.performance["artifact_sizes_bytes"][artifact_name] > 0

    csv_artifact_names = [
        "event_metrics_csv",
        "event_metrics_core_csv",
        "event_metrics_path_csv",
        "event_metrics_checkpoint_csv",
        "event_metrics_alpha_csv",
        "event_metrics_decay_csv",
        "event_metrics_cost_csv",
        "event_metrics_execution_csv",
        "target_stop_events_csv",
        "checkpoint_events_csv",
    ]
    for artifact_name in csv_artifact_names:
        assert getattr(summary.artifacts, artifact_name) is None
        assert artifact_name not in summary.performance["artifact_sizes_bytes"]

    manifest_text = Path(summary.artifacts.manifest_json).read_text(encoding="utf-8")
    assert "event_metrics_parquet" in manifest_text
    assert "target_stop_events_parquet" in manifest_text
    assert "target_stop_events_csv_gz" not in manifest_text
    report_text = Path(summary.artifacts.report_md).read_text(encoding="utf-8")
    assert str(summary.artifacts.event_metrics_parquet) in report_text
    assert "event_metrics.csv" not in report_text
    assert "MFE_10d_pct" in pd.read_parquet(summary.artifacts.event_metrics_path_parquet).columns
    assert "day10_strong" in pd.read_parquet(summary.artifacts.event_metrics_checkpoint_parquet).columns
    assert "alpha_5d_vs_universe_pct" in pd.read_parquet(summary.artifacts.event_metrics_alpha_parquet).columns
    assert "decay_1d_5d_pct" in pd.read_parquet(summary.artifacts.event_metrics_decay_parquet).columns
    assert "net_return_after_10bps_5d_pct" in pd.read_parquet(summary.artifacts.event_metrics_cost_parquet).columns
    assert "signal_close_to_next_open_gap_pct" in pd.read_parquet(summary.artifacts.event_metrics_execution_parquet).columns


def test_large_artifact_writer_supports_csv_and_both_modes(tmp_path) -> None:
    import src.entry_signal_analysis.runner as runner

    frame = pd.DataFrame(
        {
            "event_row": [1, None],
            "entry_strategy": ["EntryA", "EntryA"],
            "horizon": [10, 20],
            "return_pct": [1.5, -0.5],
        }
    )

    csv_artifacts: dict[str, Path | None] = {}
    runner._write_large_artifact(
        artifacts=csv_artifacts,
        frame=frame,
        key_prefix="event_metrics",
        csv_path=tmp_path / "event_metrics.csv",
        parquet_path=tmp_path / "event_metrics.parquet",
        large_artifact_format="csv",
    )
    assert csv_artifacts["event_metrics_csv"] == tmp_path / "event_metrics.csv"
    assert csv_artifacts["event_metrics_parquet"] is None
    assert (tmp_path / "event_metrics.csv").exists()
    assert not (tmp_path / "event_metrics.parquet").exists()

    both_artifacts: dict[str, Path | None] = {}
    runner._write_large_artifact(
        artifacts=both_artifacts,
        frame=frame,
        key_prefix="target_stop_events",
        csv_path=tmp_path / "target_stop_events.csv",
        parquet_path=tmp_path / "target_stop_events.parquet",
        large_artifact_format="both",
    )
    assert both_artifacts["target_stop_events_csv"] == tmp_path / "target_stop_events.csv"
    assert both_artifacts["target_stop_events_parquet"] == tmp_path / "target_stop_events.parquet"
    assert (tmp_path / "target_stop_events.csv").exists()
    assert (tmp_path / "target_stop_events.parquet").exists()


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
    assert validation.overall.trimmed_mean_5pct_return_pct == pytest.approx(3.0)
    assert validation.overall.winsorized_mean_5pct_return_pct == pytest.approx(3.0)
    assert [item.group_key for item in validation.by_year] == ["2025", "2026"]
    assert [item.group_key for item in validation.by_month] == ["2025-01", "2025-02", "2026-01"]
    assert [item.group_key for item in validation.by_strategy] == ["FakeEntry"]
    assert [item.group_key for item in validation.by_entry_filter] == ["atr_high", "atr_low"]
    assert validation.signal_strength_metric == "rank_score"
    assert validation.signal_strength_bucket_method == "quantile_4"
    assert [item.group_key for item in validation.by_signal_strength_bucket] == ["Q1", "Q2", "Q3", "Q4"]
    assert [item.group_key for item in validation.by_strategy_bucket] == [
        "FakeEntry::Q1",
        "FakeEntry::Q2",
        "FakeEntry::Q3",
        "FakeEntry::Q4",
    ]
    assert [item.group_key for item in validation.by_market_regime] == ["bull", "sideways", "bear"]
    assert validation.by_market_regime[0].stats.count == 1
    assert validation.by_market_regime[1].stats.count == 1
    assert validation.by_market_regime[2].stats.count == 2
    assert "Detailed Horizon Validations" in report_text
    assert "## Top Daily Windows" in report_text
    assert "selected_3d_avg_return_pct" in report_text
    assert "By Strategy" in report_text
    assert "By Strategy Bucket" in report_text
    assert "3d Tail Metrics Detail" in report_text
    assert "| p01_return_pct |" in report_text
    assert "| bottom_5pct_contribution_ratio |" in report_text
    assert "primary_horizon_validation" in summary_text
    assert "primary_horizon_validations" in summary_text
    assert "top_daily_windows_by_horizon" in summary_text
    assert "by_strategy_tail_robustness" in summary_text


def test_run_entry_signal_analysis_includes_multiple_primary_horizon_validations(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": ["FakeEntry"] * 4,
            "entry_filter_name": ["production"] * 4,
            "signal_date": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
            "ticker": ["7203", "6758", "6501", "8306"],
            "selected": [True, True, True, True],
            "positive_rank_score": [True, True, True, True],
            "tail_guard_limit": [12, 12, 12, 12],
            "forward_return_3d_pct": [1.0, 2.0, -1.0, 4.0],
            "forward_return_5d_pct": [2.0, 3.0, -2.0, 5.0],
            "forward_return_7d_pct": [3.0, 4.0, -3.0, 6.0],
            "forward_diff_3d": [1.0, 2.0, -1.0, 4.0],
            "forward_diff_5d": [2.0, 3.0, -2.0, 5.0],
            "forward_diff_7d": [3.0, 4.0, -3.0, 6.0],
        }
    )

    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203", "6758", "6501", "8306"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[3, 5, 7],
        primary_horizons=[3, 5, 7],
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)
    report_text = Path(summary.artifacts.report_md).read_text(encoding="utf-8")
    summary_text = Path(summary.artifacts.summary_json).read_text(encoding="utf-8")
    manifest_text = Path(summary.artifacts.manifest_json).read_text(encoding="utf-8")

    assert [item.primary_horizon for item in summary.primary_horizon_validations] == [3, 5, 7]
    assert summary.primary_horizon_validation.primary_horizon == 3
    assert [item.primary_horizon for item in summary.top_daily_windows_by_horizon] == [3, 5, 7]
    assert summary.top_daily_windows_by_horizon[0].windows == summary.top_daily_windows
    assert "### 3d" in report_text
    assert "### 5d" in report_text
    assert "### 7d" in report_text
    assert "#### 3d Tail Metrics Detail" in report_text
    assert "#### 5d Tail Metrics Detail" in report_text
    assert "#### 7d Tail Metrics Detail" in report_text
    assert "selected_3d_avg_return_pct" in report_text
    assert "selected_5d_avg_return_pct" in report_text
    assert "selected_7d_avg_return_pct" in report_text
    assert "top_daily_windows_by_horizon" in summary_text
    assert '"primary_horizons": [' in manifest_text


def test_run_entry_signal_analysis_includes_primary_strategy_risk_ranking(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": [
                "BalancedEntry",
                "BalancedEntry",
                "BalancedEntry",
                "BalancedEntry",
                "AggressiveEntry",
                "AggressiveEntry",
                "AggressiveEntry",
                "AggressiveEntry",
                "MiddleEntry",
                "MiddleEntry",
                "MiddleEntry",
                "MiddleEntry",
            ],
            "entry_filter_name": ["production"] * 12,
            "signal_date": [
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
            ],
            "ticker": [
                "7203",
                "6758",
                "6501",
                "8306",
                "7203",
                "6758",
                "6501",
                "8306",
                "7203",
                "6758",
                "6501",
                "8306",
            ],
            "selected": [True] * 12,
            "positive_rank_score": [True] * 12,
            "tail_guard_limit": [12] * 12,
            "forward_return_5d_pct": [1.2, 0.8, -1.0, -0.6, 4.0, 3.0, -4.0, -3.5, 1.6, 1.2, -2.0, -1.6],
            "forward_diff_5d": [1.2, 0.8, -1.0, -0.6, 4.0, 3.0, -4.0, -3.5, 1.6, 1.2, -2.0, -1.6],
        }
    )

    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["BalancedEntry", "AggressiveEntry", "MiddleEntry"],
        tickers=["7203", "6758", "6501", "8306"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[5],
        primary_horizon=5,
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)

    rankings = summary.primary_horizon_validation.by_strategy_risk
    report_text = Path(summary.artifacts.report_md).read_text(encoding="utf-8")
    summary_text = Path(summary.artifacts.summary_json).read_text(encoding="utf-8")

    assert [item.entry_strategy for item in rankings] == [
        "BalancedEntry",
        "MiddleEntry",
        "AggressiveEntry",
    ]
    assert rankings[0].primary_score < rankings[-1].primary_score
    assert rankings[0].stats.avg_loss_pct == pytest.approx(-0.8)
    assert "Strategy Risk Ranking" in report_text
    assert "by_strategy_risk" in summary_text


def test_run_entry_signal_analysis_includes_tail_robustness_ranking(tmp_path, monkeypatch) -> None:
    import src.entry_signal_analysis.runner as runner

    candidates = pd.DataFrame(
        {
            "entry_strategy": [
                "StableEntry",
                "StableEntry",
                "StableEntry",
                "StableEntry",
                "ExplosiveEntry",
                "ExplosiveEntry",
                "ExplosiveEntry",
                "ExplosiveEntry",
            ],
            "entry_filter_name": ["production"] * 8,
            "signal_date": [
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
                "2026-01-05",
                "2026-01-06",
                "2026-01-07",
                "2026-01-08",
            ],
            "ticker": [
                "7203",
                "6758",
                "6501",
                "8306",
                "7203",
                "6758",
                "6501",
                "8306",
            ],
            "selected": [True] * 8,
            "positive_rank_score": [True] * 8,
            "tail_guard_limit": [12] * 8,
            "forward_return_5d_pct": [1.8, 1.5, 1.2, 0.8, -3.0, -2.0, 1.0, 30.0],
            "forward_diff_5d": [1.8, 1.5, 1.2, 0.8, -3.0, -2.0, 1.0, 30.0],
        }
    )

    monkeypatch.setattr(runner, "scan_entry_signal_candidates", lambda _request: candidates)
    monkeypatch.setattr(
        runner,
        "resolve_effective_entry_filter_for_request",
        lambda _request: ("off", ["production"]),
    )
    monkeypatch.setattr(runner, "_load_topix_benchmark_frame", lambda _data_root: None)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["StableEntry", "ExplosiveEntry"],
        tickers=["7203", "6758", "6501", "8306"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        horizons=[5],
        primary_horizon=5,
        output_dir=str(tmp_path),
    )

    summary = run_entry_signal_analysis(request)
    report_text = Path(summary.artifacts.report_md).read_text(encoding="utf-8")
    summary_text = Path(summary.artifacts.summary_json).read_text(encoding="utf-8")
    rankings = summary.primary_horizon_validation.by_strategy_tail_robustness

    assert [item.entry_strategy for item in rankings] == ["StableEntry", "ExplosiveEntry"]
    assert rankings[0].stats.trimmed_mean_5pct_return_pct > rankings[1].stats.trimmed_mean_5pct_return_pct
    assert rankings[0].stats.top_5pct_contribution_ratio < rankings[1].stats.top_5pct_contribution_ratio
    assert "Tail Robustness Ranking" in report_text
    assert "by_strategy_tail_robustness" in summary_text
