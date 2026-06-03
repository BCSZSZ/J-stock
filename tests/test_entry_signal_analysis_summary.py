from __future__ import annotations

import pandas as pd
import pytest

from src.entry_signal_analysis.summary import (
    _build_horizon_stats,
    _build_primary_stats_from_series,
    build_primary_horizon_validation,
    build_primary_strategy_tail_robustness_ranking,
)


def test_build_primary_stats_from_series_adds_tail_robust_metrics() -> None:
    stats = _build_primary_stats_from_series(
        pd.Series([-5.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0, 100.0])
    )

    assert stats.count == 10
    assert stats.avg_return_pct == pytest.approx(9.5)
    assert stats.median_return_pct == pytest.approx(0.0)
    assert stats.trimmed_mean_1pct_return_pct == pytest.approx(0.0)
    assert stats.trimmed_mean_5pct_return_pct == pytest.approx(0.0)
    assert stats.winsorized_mean_1pct_return_pct == pytest.approx(0.0)
    assert stats.winsorized_mean_5pct_return_pct == pytest.approx(0.0)
    assert stats.max_return_pct == pytest.approx(100.0)
    assert stats.min_return_pct == pytest.approx(-5.0)
    assert stats.total_sum_return_pct == pytest.approx(95.0)
    assert stats.top_1pct_sum_return_pct == pytest.approx(100.0)
    assert stats.top_5pct_sum_return_pct == pytest.approx(100.0)
    assert stats.bottom_1pct_sum_return_pct == pytest.approx(-5.0)
    assert stats.bottom_5pct_sum_return_pct == pytest.approx(-5.0)
    assert stats.top_1pct_contribution_ratio == pytest.approx(100.0 / 95.0)
    assert stats.top_5pct_contribution_ratio == pytest.approx(100.0 / 95.0)
    assert stats.net_without_top_1pct_return_pct == pytest.approx(-5.0)
    assert stats.net_without_top_5pct_return_pct == pytest.approx(-5.0)


def test_build_horizon_stats_propagates_tail_robust_metrics() -> None:
    stats = _build_horizon_stats(
        pd.DataFrame(
            {
            "forward_return_5d_pct": [-5.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0, 100.0],
            "forward_diff_5d": [-5.0, -4.0, -3.0, -2.0, -1.0, 1.0, 2.0, 3.0, 4.0, 100.0],
            }
        ),
        [5],
    )

    horizon = stats["5d"]
    assert horizon["avg_return_pct"] == pytest.approx(9.5)
    assert horizon["trimmed_mean_5pct_return_pct"] == pytest.approx(0.0)
    assert horizon["winsorized_mean_5pct_return_pct"] == pytest.approx(0.0)
    assert horizon["top_5pct_contribution_ratio"] == pytest.approx(100.0 / 95.0)
    assert horizon["avg_price_diff"] == pytest.approx(9.5)


def test_build_primary_strategy_tail_robustness_ranking_prefers_stable_strategy() -> None:
    frame = pd.DataFrame(
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
            "selected": [True] * 8,
            "forward_return_5d_pct": [1.8, 1.5, 1.2, 0.8, -3.0, -2.0, 1.0, 30.0],
        }
    )

    rankings = build_primary_strategy_tail_robustness_ranking(frame, primary_horizon=5)

    assert [item.entry_strategy for item in rankings] == ["StableEntry", "ExplosiveEntry"]
    assert rankings[0].stats.trimmed_mean_5pct_return_pct > rankings[1].stats.trimmed_mean_5pct_return_pct
    assert rankings[0].stats.top_5pct_contribution_ratio < rankings[1].stats.top_5pct_contribution_ratio


def test_build_primary_horizon_validation_includes_strategy_and_strategy_bucket_slices() -> None:
    frame = pd.DataFrame(
        {
            "entry_strategy": ["EntryA", "EntryA", "EntryB", "EntryB"],
            "entry_filter_name": ["production"] * 4,
            "signal_date": ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"],
            "selected": [True] * 4,
            "rank_score": [0.1, 0.2, 0.8, 0.9],
            "forward_return_5d_pct": [1.0, 2.0, -1.0, 4.0],
        }
    )

    validation = build_primary_horizon_validation(frame, primary_horizon=5)

    assert [item.group_key for item in validation.by_strategy] == ["EntryA", "EntryB"]
    assert [item.group_key for item in validation.by_strategy_bucket] == [
        "EntryA::Q1",
        "EntryA::Q2",
        "EntryB::Q3",
        "EntryB::Q4",
    ]
    assert validation.by_strategy_tail_robustness