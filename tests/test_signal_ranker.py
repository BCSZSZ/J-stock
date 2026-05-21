import pandas as pd

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.backtest.signal_ranker import SignalRanker
from src.utils.strategy_loader import get_available_ranking_strategies


def _market_data(closes: list[float]) -> MarketData:
    idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
    return MarketData(
        ticker="0000",
        current_date=idx[-1],
        df_features=pd.DataFrame({"Close": closes}, index=idx),
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def _buy_signal(stale: bool = False, streak_days: int = 1) -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.8,
        reasons=["BUY"],
        metadata={
            "score": 70.0,
            "stale_buy_signal": stale,
            "buy_signal_streak_days": streak_days,
        },
        strategy_name="test",
    )


def test_fresh_momentum_ranks_fresh_signals_before_stale_repeats():
    signals = {
        "fresh_low": _buy_signal(stale=False, streak_days=1),
        "stale_high": _buy_signal(stale=True, streak_days=3),
        "fresh_high": _buy_signal(stale=False, streak_days=1),
    }
    market_data = {
        "fresh_low": _market_data([100.0, 100.5, 101.0, 101.5, 102.0]),
        "stale_high": _market_data([100.0, 105.0, 110.0, 115.0, 120.0]),
        "fresh_high": _market_data([100.0, 103.0, 106.0, 109.0, 112.0]),
    }

    ranked = SignalRanker(method="fresh_momentum").rank_buy_signals(
        signals,
        market_data,
    )

    assert [ticker for ticker, _signal, _priority in ranked] == [
        "fresh_high",
        "fresh_low",
        "stale_high",
    ]
    assert ranked[2][2] > ranked[1][2]


def test_fresh_momentum_is_available_from_strategy_loader():
    assert "fresh_momentum" in get_available_ranking_strategies()