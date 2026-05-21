import pandas as pd
import pytest

from src.analysis.signals import SignalAction, TradingSignal
from src.entry_analysis.models import EntryAnalysisRequest
from src.entry_analysis.signal_scanner import scan_entry_signals


class _FakeCache:
    def __init__(self, data_root: str) -> None:
        dates = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"])
        self.features = pd.DataFrame(
            {
                "Open": [99.0, 101.0, 103.0, 104.0],
                "Close": [100.0, 102.0, 104.0, 108.0],
                "RSI": [55.0, 62.0, 64.0, 66.0],
                "RSI_9": [56.0, 63.0, 65.0, 67.0],
                "RSI_14": [55.0, 62.0, 64.0, 66.0],
                "RSI_22": [54.0, 60.0, 62.0, 64.0],
                "EMA_20": [98.0, 99.0, 100.0, 101.0],
                "EMA_50": [97.0, 98.0, 99.0, 100.0],
                "EMA_200": [90.0, 91.0, 92.0, 93.0],
                "ATR": [2.0, 2.1, 2.2, 2.3],
                "ADX_14": [18.0, 19.0, 20.0, 21.0],
                "MACD": [1.0, 1.1, 1.2, 1.3],
                "MACD_Signal": [0.8, 0.9, 1.0, 1.1],
                "MACD_Hist": [0.2, 0.2, 0.2, 0.2],
            },
            index=dates,
        )

    def preload_tickers(self, *_args, **_kwargs):
        return {"7203": True}

    def get_features(self, ticker: str):
        return self.features

    def get_trades(self, ticker: str):
        return pd.DataFrame()

    def get_financials(self, ticker: str):
        return pd.DataFrame()

    def get_metadata(self, ticker: str):
        return {}


class _FakeStrategy:
    def generate_entry_signal(self, market_data):
        if market_data.current_date.strftime("%Y-%m-%d") in {"2026-01-05", "2026-01-06"}:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=0.8,
                reasons=["fake buy"],
                metadata={"score": 77.0, "buy_signal_streak_days": 1},
                strategy_name="FakeEntry",
            )
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.1,
            reasons=["hold"],
            metadata={},
            strategy_name="FakeEntry",
        )


def test_scan_entry_signals_records_every_buy_without_position_suppression(monkeypatch) -> None:
    import src.entry_analysis.signal_scanner as scanner

    monkeypatch.setattr(scanner, "BacktestDataCache", _FakeCache)
    monkeypatch.setattr(scanner, "load_entry_strategy", lambda _name: _FakeStrategy())
    request = EntryAnalysisRequest(
        entry_strategies=["FakeEntry"],
        tickers=["7203"],
        start_date=pd.Timestamp("2026-01-05").date(),
        end_date=pd.Timestamp("2026-01-06").date(),
        horizons=[1, 2],
        min_samples=1,
    )

    result = scan_entry_signals(request, ("RSI", "ADX_14"))

    assert list(result["signal_date"]) == ["2026-01-05", "2026-01-06"]
    assert list(result["ticker"]) == ["7203", "7203"]
    assert result.iloc[0]["forward_return_1d_pct"] == pytest.approx(2.0)
    assert result.iloc[1]["forward_return_2d_pct"] == pytest.approx(5.882352941176472)
    assert result.iloc[0]["RSI"] == 55.0
