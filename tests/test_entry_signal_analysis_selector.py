from __future__ import annotations

import pandas as pd

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.entry_signal_analysis.selector import DailyEntryCandidate, select_daily_candidates
from src.utils.strategy_loader import load_ranking_strategy


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
        ranker=load_ranking_strategy("score_only"),
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
        ranker=load_ranking_strategy("score_only"),
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
        ranker=load_ranking_strategy("momentum"),
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
        ranker=load_ranking_strategy("score_only"),
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


def test_select_daily_candidates_enforces_momentum_exhaustion_filter() -> None:
    candidates = [
        _candidate("1111", 5.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 4.0, [10, 10.5, 11, 11.5, 12]),
    ]

    result = select_daily_candidates(
        candidates,
        ranker=load_ranking_strategy("score_only"),
        tail_guard_config={"enabled": False},
        momentum_exhaustion_config={"mode": "enforce", "max_score": 4.0},
    )

    rows = {row["ticker"]: row for row in result}
    assert rows["1111"]["selected"] is False
    assert rows["1111"]["momentum_exhaustion_blocked"] is True
    assert rows["1111"]["momentum_exhaustion_filtered"] is True
    assert rows["2222"]["selected"] is True
    assert rows["2222"]["momentum_exhaustion_blocked"] is False


def test_select_daily_candidates_shadows_momentum_exhaustion_filter() -> None:
    candidates = [
        _candidate("1111", 5.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 4.0, [10, 10.5, 11, 11.5, 12]),
    ]

    result = select_daily_candidates(
        candidates,
        ranker=load_ranking_strategy("score_only"),
        tail_guard_config={"enabled": False},
        momentum_exhaustion_config={"mode": "shadow", "max_score": 4.0},
    )

    rows = {row["ticker"]: row for row in result}
    assert rows["1111"]["selected"] is True
    assert rows["1111"]["momentum_exhaustion_blocked"] is True
    assert rows["1111"]["momentum_exhaustion_filtered"] is False


def test_select_daily_candidates_enforces_industry_filter(tmp_path) -> None:
    reference_file = tmp_path / "jpx_final_list.csv"
    reference_file.write_text(
        "\n".join(
            [
                "Yahoo_Ticker,Code,銘柄名,Type,市場・商品区分,33業種区分,規模区分",
                "1111.T,1111,A,Stock,Prime,銀行業,TOPIX",
                "2222.T,2222,B,Stock,Prime,銀行業,TOPIX",
                "3333.T,3333,C,Stock,Prime,輸送用機器,TOPIX",
            ]
        ),
        encoding="utf-8-sig",
    )
    candidates = [
        _candidate("1111", 90.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 80.0, [10, 10.5, 11, 11.5, 12]),
        _candidate("3333", 70.0, [10, 10.2, 10.4, 10.6, 10.8]),
    ]

    result = select_daily_candidates(
        candidates,
        ranker=load_ranking_strategy("score_only"),
        tail_guard_config={"enabled": False},
        industry_filter_config={
            "mode": "enforce",
            "max_buy_per_industry_per_day": 1,
            "max_total_positions_per_industry": 3,
            "reference_file": str(reference_file),
        },
    )

    rows = {row["ticker"]: row for row in result}
    assert rows["1111"]["selected"] is True
    assert rows["2222"]["selected"] is False
    assert rows["2222"]["industry_filter_filtered"] is True
    assert rows["2222"]["industry_filter_daily_cap_blocked"] is True
    assert rows["3333"]["selected"] is True


def test_select_daily_candidates_shadows_industry_filter(tmp_path) -> None:
    reference_file = tmp_path / "jpx_final_list.csv"
    reference_file.write_text(
        "\n".join(
            [
                "Yahoo_Ticker,Code,銘柄名,Type,市場・商品区分,33業種区分,規模区分",
                "1111.T,1111,A,Stock,Prime,銀行業,TOPIX",
                "2222.T,2222,B,Stock,Prime,銀行業,TOPIX",
            ]
        ),
        encoding="utf-8-sig",
    )
    candidates = [
        _candidate("1111", 90.0, [10, 11, 12, 13, 14]),
        _candidate("2222", 80.0, [10, 10.5, 11, 11.5, 12]),
    ]

    result = select_daily_candidates(
        candidates,
        ranker=load_ranking_strategy("score_only"),
        tail_guard_config={"enabled": False},
        industry_filter_config={
            "mode": "shadow",
            "max_buy_per_industry_per_day": 1,
            "max_total_positions_per_industry": 3,
            "reference_file": str(reference_file),
        },
    )

    rows = {row["ticker"]: row for row in result}
    assert rows["2222"]["selected"] is True
    assert rows["2222"]["industry_filter_blocked"] is True
    assert rows["2222"]["industry_filter_filtered"] is False
