from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.analysis.signals import SignalAction, TradingSignal
from src.entry_exit_validation.models import EntryExitValidationRequest
from src.entry_exit_validation.scanner import EntryExitCandidateContext
from src.entry_exit_validation.simulator import simulate_candidate_exit


class FakeCache:
    def __init__(self, features: pd.DataFrame) -> None:
        self.features = features

    def get_features(self, _ticker: str) -> pd.DataFrame:
        return self.features

    def get_trades(self, _ticker: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_financials(self, _ticker: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_metadata(self, _ticker: str) -> dict[str, object]:
        return {}


class SellOnDateExit:
    def __init__(self, sell_date: str | None = None) -> None:
        self.sell_date = sell_date

    def generate_exit_signal(self, _position, market_data):
        if self.sell_date and market_data.current_date.date().isoformat() == self.sell_date:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=["take profit"],
                metadata={"trigger": "TAKE_PROFIT", "sell_percentage": 0.5},
                strategy_name="FakeExit",
            )
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=1.0,
            reasons=["hold"],
            metadata={},
            strategy_name="FakeExit",
        )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0, 103.0, 105.0],
            "Close": [100.5, 101.5, 102.5, 104.0, 106.0],
            "High": [101.0, 102.0, 103.0, 105.0, 107.0],
            "Low": [99.0, 100.0, 101.0, 102.0, 104.0],
            "Volume": [1000, 1000, 1000, 1000, 1000],
            "ATR": [2.0, 2.0, 2.0, 2.0, 2.0],
        },
        index=pd.date_range("2026-01-01", periods=5, freq="D"),
    )


def _request(max_holding: int = 60) -> EntryExitValidationRequest:
    return EntryExitValidationRequest(
        entry_strategies=["FakeEntry"],
        exit_strategies=["FakeExit"],
        tickers=["1111"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        max_holding_trading_days=max_holding,
    )


def _context() -> EntryExitCandidateContext:
    signal = TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["buy"],
        metadata={"score": 88.0},
        strategy_name="FakeEntry",
    )
    return EntryExitCandidateContext(
        ticker="1111",
        entry_strategy="FakeEntry",
        exit_strategy="FakeExit",
        entry_filter_name="production",
        signal_date="2026-01-01",
        signal_pos=0,
        entry_pos=1,
        signal=signal,
        payload={
            "ticker": "1111",
            "signal_date": "2026-01-01",
            "label_entry_price": 101.0,
            "rank": 1,
            "rank_score": 10.0,
            "selected": True,
        },
    )


def test_next_open_exit_uses_following_open(monkeypatch) -> None:
    import src.entry_exit_validation.simulator as simulator

    monkeypatch.setattr(
        simulator,
        "create_strategy_instance",
        lambda _name, _kind: SellOnDateExit("2026-01-04"),
    )

    record = simulate_candidate_exit(_context(), _request(), FakeCache(_features()))

    assert record["entry_date"] == "2026-01-02"
    assert record["entry_price"] == pytest.approx(101.0)
    assert record["exit_signal_date"] == "2026-01-04"
    assert record["exit_date"] == "2026-01-05"
    assert record["exit_price"] == pytest.approx(105.0)
    assert record["return_pct"] == pytest.approx((105.0 / 101.0 - 1.0) * 100.0)
    assert record["exit_sell_percentage"] == pytest.approx(0.5)
    assert record["no_exit"] is False


def test_no_exit_marks_at_holding_cap_close(monkeypatch) -> None:
    import src.entry_exit_validation.simulator as simulator

    monkeypatch.setattr(
        simulator,
        "create_strategy_instance",
        lambda _name, _kind: SellOnDateExit(None),
    )

    record = simulate_candidate_exit(_context(), _request(max_holding=2), FakeCache(_features()))

    assert record["exit_reason"] == "no_exit"
    assert record["exit_date"] == "2026-01-04"
    assert record["exit_price"] == pytest.approx(104.0)
    assert record["holding_trading_days"] == 2
    assert record["no_exit"] is True
