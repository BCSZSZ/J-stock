from __future__ import annotations

import pandas as pd
import pytest

from src.entry_exit_validation.stats import (
    attach_market_regime,
    attach_signal_buckets,
    build_combo_summary,
    build_exit_reason_summary,
    build_rankings,
    build_tail_metrics,
    build_vs_fixed_horizon,
)


def _trades() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entry_strategy": ["EntryA", "EntryA", "EntryA", "EntryA", "EntryA"],
            "exit_strategy": ["ExitA", "ExitA", "ExitA", "ExitA", "ExitA"],
            "ticker": ["1111", "2222", "3333", "4444", "5555"],
            "signal_date": [
                "2026-01-10",
                "2026-01-11",
                "2026-01-12",
                "2026-01-13",
                "2026-01-14",
            ],
            "return_pct": [10.0, -5.0, 2.0, -1.0, 4.0],
            "holding_days": [3, 2, 5, 4, 2],
            "exit_reason": ["take profit", "hardstop", "trail stop", "no_exit", "score decay"],
            "exit_urgency": ["TAKE_PROFIT", "HARDSTOP", "TRAIL", "NO_EXIT", "SCORE"],
            "no_exit": [False, False, False, True, False],
            "forward_return_3d_pct": [8.0, -2.0, 1.0, 0.0, 3.0],
            "forward_return_5d_pct": [9.0, -3.0, 2.5, -0.5, 3.5],
            "rank_score": [0.9, 0.1, 0.6, 0.2, 0.8],
        }
    )


def test_combo_summary_includes_tail_and_exit_metrics() -> None:
    summary = build_combo_summary(_trades())

    assert len(summary) == 1
    row = summary.iloc[0]
    assert row["count"] == 5
    assert row["win_rate"] == pytest.approx(0.6)
    assert row["avg_return"] == pytest.approx(2.0)
    assert row["median_return"] == pytest.approx(2.0)
    assert row["stop_loss_ratio"] == pytest.approx(0.2)
    assert row["take_profit_ratio"] == pytest.approx(0.2)
    assert row["trailing_stop_ratio"] == pytest.approx(0.2)
    assert row["no_exit_ratio"] == pytest.approx(0.2)
    assert row["top_5pct_sum_return_pct"] == pytest.approx(10.0)
    assert row["mean_without_top_5pct_return_pct"] == pytest.approx(0.0)


def test_vs_fixed_horizon_and_rankings_are_generated() -> None:
    trades = _trades()
    summary = build_combo_summary(trades)
    vs_fixed = build_vs_fixed_horizon(trades, [3, 5])
    tail_metrics = build_tail_metrics(trades)
    exit_reasons = build_exit_reason_summary(trades)
    robustness, risk = build_rankings(summary)

    assert vs_fixed.iloc[0]["avg_return_vs_fixed_3d"] == pytest.approx(0.0)
    assert "top_5pct_contribution_ratio" in tail_metrics.columns
    assert set(exit_reasons["exit_reason"]) == {
        "take_profit",
        "stop_loss",
        "trailing_stop",
        "no_exit",
        "signal_exit",
    }
    assert robustness.iloc[0]["robustness_rank"] == 1
    assert risk.iloc[0]["risk_rank"] == 1


def test_market_regime_and_signal_buckets_are_attached() -> None:
    benchmark_dates = pd.bdate_range("2025-12-01", "2026-01-31")
    benchmark = pd.DataFrame(
        {
            "Date": benchmark_dates,
            "Close": [100.0 + index for index in range(len(benchmark_dates))],
        }
    )

    with_regime, status, definition = attach_market_regime(_trades(), benchmark)
    with_buckets = attach_signal_buckets(with_regime)

    assert status == "available"
    assert "TOPIX" in definition
    assert set(with_regime["market_regime"]) == {"bull"}
    assert set(with_buckets["rank_score_bucket"]) - {"unknown"}
