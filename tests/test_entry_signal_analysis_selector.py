from __future__ import annotations

import pandas as pd

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.entry_signal_analysis.selector import DailyEntryCandidate, select_daily_candidates


def _market_data(closes: list[float]) -> MarketData:
    frame = pd.DataFrame(
        {
            "Close": closes,
            "Open": closes,
        },
        index=pd.date_range("2026-01-01", periods=len(closes), freq="D"),
    )
    return MarketData(
        ticker="0000",
        current_date=frame.index[-1],
        df_features=frame,
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def _candidate(
    ticker: str,
    score: float,
    closes: list[float],
) -> DailyEntryCandidate:
    return DailyEntryCandidate(
        ticker=ticker,
        entry_strategy="FakeEntry",
        signal_date="2026-01-05",
        signal=TradingSignal(
            action=SignalAction.BUY,
            confidence=1.0,
            reasons=["buy"],
            metadata={"score": score},
            strategy_name="FakeEntry",
        ),
        market_data=_market_data(closes),
        payload={"score": score},
    )


def test_select_daily_candidates_uses_tail_guard_base_rank_limit() -> None:
    candidates = [
        _candidate("1111", 90.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 80.0, [10, 10, 10, 10, 10]),
        _candidate("3333", -5.0, [10, 9, 8, 7, 6]),
    ]

    result = select_daily_candidates(
        candidates,
        ranking_strategy_name="score_only",
        tail_guard_config={"enabled": True, "max_rank": 2},
    )

    selected_by_ticker = {row["ticker"]: row["selected"] for row in result}
    assert selected_by_ticker == {
        "1111": True,
        "2222": True,
        "3333": False,
    }
    assert all(row["tail_guard_limit"] == 2 for row in result)


def test_select_daily_candidates_extends_limit_for_positive_rank_scores() -> None:
    candidates = [
        _candidate("1111", 90.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 80.0, [10, 10.5, 11, 11.5, 12]),
        _candidate("3333", 70.0, [10, 10.2, 10.4, 10.6, 10.8]),
    ]

    result = select_daily_candidates(
        candidates,
        ranking_strategy_name="score_only",
        tail_guard_config={"enabled": True, "max_rank": 1},
    )

    assert all(row["positive_rank_score_count"] == 3 for row in result)
    assert all(row["tail_guard_limit"] == 3 for row in result)
    assert all(row["selected"] is True for row in result)


def test_select_daily_candidates_supports_momentum_ranking() -> None:
    candidates = [
        _candidate("1111", 10.0, [10, 10, 10, 10, 10]),
        _candidate("2222", 10.0, [10, 11, 12, 13, 14]),
    ]

    result = select_daily_candidates(
        candidates,
        ranking_strategy_name="momentum",
        tail_guard_config={"enabled": True, "max_rank": 1},
    )

    ranked = {row["ticker"]: row["rank"] for row in result}
    assert ranked["2222"] == 1
    assert ranked["1111"] == 2


def test_select_daily_candidates_supports_min_tail_guard_rank_limit() -> None:
    candidates = [
        _candidate("1111", 90.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 80.0, [10, 10.5, 11, 11.5, 12]),
        _candidate("3333", 70.0, [10, 10.2, 10.4, 10.6, 10.8]),
    ]

    result = select_daily_candidates(
        candidates,
        ranking_strategy_name="score_only",
        tail_guard_config={"enabled": True, "max_rank": 2, "rank_limit_mode": "min"},
    )

    selected_by_ticker = {row["ticker"]: row["selected"] for row in result}
    assert all(row["positive_rank_score_count"] == 3 for row in result)
    assert all(row["tail_guard_limit"] == 2 for row in result)
    assert selected_by_ticker == {
        "1111": True,
        "2222": True,
        "3333": False,
    }