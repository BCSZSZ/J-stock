from __future__ import annotations

import pandas as pd
import pytest

from src.evaluation.scoring import (
    apply_prs_train_score,
    rank_final_prs,
    summarize_prs_train_metrics,
)


def _mdd_win_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for period in ["2025", "2026"]:
        rows.append(
            {
                "period": period,
                "test_year": int(period),
                "entry_strategy": "HighReturnFragile",
                "exit_strategy": "ExitA",
                "entry_filter": "off",
                "return_pct": 300.0,
                "alpha": 290.0,
                "max_drawdown_pct": 50.0 if period == "2026" else 40.0,
                "win_rate_pct": 50.0,
                "sharpe_ratio": 4.0,
                "mean_train_alpha": 290.0,
            }
        )
        rows.append(
            {
                "period": period,
                "test_year": int(period),
                "entry_strategy": "Balanced",
                "exit_strategy": "ExitB",
                "entry_filter": "off",
                "return_pct": 200.0,
                "alpha": 190.0,
                "max_drawdown_pct": 6.0 if period == "2026" else 5.0,
                "win_rate_pct": 80.0,
                "sharpe_ratio": 3.0,
                "mean_train_alpha": 190.0,
            }
        )
    return rows


def test_prs_train_mdd_win_v1_prioritizes_mdd_and_win_rate() -> None:
    summary = summarize_prs_train_metrics(pd.DataFrame(_mdd_win_rows()))

    ranked = apply_prs_train_score(summary, complexity_penalty_resolver=lambda *_: 0.0)

    assert ranked.iloc[0]["entry_strategy"] == "Balanced"
    assert ranked.iloc[0]["prs_train_score"] == pytest.approx(55.0)
    assert ranked.iloc[1]["entry_strategy"] == "HighReturnFragile"
    assert ranked.iloc[1]["prs_train_score"] == pytest.approx(45.0)
    assert "mean_train_win_rate_norm" in ranked.columns
    assert "worst_train_mdd_norm" in ranked.columns


def test_prs_train_accepts_legacy_summary_without_win_or_sharpe() -> None:
    summary = summarize_prs_train_metrics(
        pd.DataFrame(_mdd_win_rows()).drop(columns=["win_rate_pct", "sharpe_ratio"])
    )

    ranked = apply_prs_train_score(summary, complexity_penalty_resolver=lambda *_: 0.0)

    assert len(ranked) == 2
    assert set(ranked["mean_train_win_rate_norm"]) == {0.5}
    assert set(ranked["mean_train_sharpe_norm"]) == {0.5}


def test_final_prs_uses_mdd_win_v1_components() -> None:
    ranked = rank_final_prs(
        pd.DataFrame(_mdd_win_rows()),
        complexity_penalty_resolver=lambda *_: 0.0,
    )

    assert ranked.iloc[0]["entry_strategy"] == "Balanced"
    assert ranked.iloc[0]["final_prs_score"] == pytest.approx(55.0)
    assert ranked.iloc[0]["mean_oos_win_rate"] == pytest.approx(80.0)
    assert ranked.iloc[0]["worst_oos_mdd"] == pytest.approx(6.0)
