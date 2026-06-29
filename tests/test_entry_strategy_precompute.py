from __future__ import annotations

import math

import pandas as pd
import pytest

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.analysis.strategies.entry.bollinger_squeeze_strategy import (
    BollingerSqueezeStrategy,
)
from src.analysis.strategies.entry.ichimoku_stoch_strategy import IchimokuStochStrategy
from src.analysis.strategies.entry.rule_based_crossover_entry import (
    CrossTrendMACDVolumeEntry,
    CrossTrendMACDVolumeLooseEntry,
)
from src.analysis.strategies.entry.scorer_strategy import (
    EnhancedScorerStrategy,
    SimpleScorerStrategy,
)


def _market_data(
    *,
    ticker: str,
    features: pd.DataFrame,
    row_pos: int,
    trades: pd.DataFrame | None = None,
    financials: pd.DataFrame | None = None,
    metadata: dict | None = None,
) -> MarketData:
    current_date = pd.Timestamp(features.index[row_pos])
    trades_frame = trades if trades is not None else pd.DataFrame()
    if not trades_frame.empty and "EnDate" in trades_frame.columns:
        trade_dates = pd.to_datetime(trades_frame["EnDate"], errors="coerce")
        trades_frame = trades_frame.loc[trade_dates <= current_date]
    financials_frame = financials if financials is not None else pd.DataFrame()
    if not financials_frame.empty and "DiscDate" in financials_frame.columns:
        disc_dates = pd.to_datetime(financials_frame["DiscDate"], errors="coerce")
        financials_frame = financials_frame.loc[disc_dates <= current_date]
    return MarketData(
        ticker=ticker,
        current_date=current_date,
        df_features=features.iloc[: row_pos + 1],
        df_trades=trades_frame,
        df_financials=financials_frame,
        metadata=metadata or {},
    )


def _assert_precompute_matches_daily(
    strategy,
    features: pd.DataFrame,
    *,
    trades: pd.DataFrame | None = None,
    financials: pd.DataFrame | None = None,
    metadata: dict | None = None,
) -> None:
    precomputed = strategy.precompute_entry_signals(
        ticker="0000",
        features=features,
        trades=trades,
        financials=financials,
        metadata=metadata,
    )
    for row_pos in range(len(features)):
        direct = strategy.generate_entry_signal(
            _market_data(
                ticker="0000",
                features=features,
                row_pos=row_pos,
                trades=trades,
                financials=financials,
                metadata=metadata,
            )
        )
        precomputed_signal = precomputed.get(row_pos)
        if direct.action == SignalAction.BUY:
            assert precomputed_signal is not None, row_pos
            _assert_signal_equivalent(precomputed_signal, direct)
        else:
            assert precomputed_signal is None, row_pos


def _assert_signal_equivalent(actual: TradingSignal, expected: TradingSignal) -> None:
    assert actual.action == expected.action
    assert actual.strategy_name == expected.strategy_name
    assert actual.reasons == expected.reasons
    assert actual.confidence == pytest.approx(expected.confidence)
    _assert_nested_equivalent(actual.metadata, expected.metadata)


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return value
        return float(value)
    return value


def _assert_nested_equivalent(actual, expected) -> None:
    actual = _normalize(actual)
    expected = _normalize(expected)
    if isinstance(expected, dict):
        assert isinstance(actual, dict)
        assert set(actual) == set(expected)
        for key in expected:
            _assert_nested_equivalent(actual[key], expected[key])
        return
    if isinstance(expected, list):
        assert isinstance(actual, list)
        assert len(actual) == len(expected)
        for actual_item, expected_item in zip(actual, expected):
            _assert_nested_equivalent(actual_item, expected_item)
        return
    if isinstance(expected, float):
        if math.isnan(expected):
            assert isinstance(actual, float) and math.isnan(actual)
        else:
            assert actual == pytest.approx(expected)
        return
    assert actual == expected


def test_cross_trend_macd_volume_precompute_matches_daily_signal() -> None:
    dates = pd.bdate_range("2026-01-01", periods=5)
    features = pd.DataFrame(
        {
            "Close": [20.1, 20.8, 20.5, 21.2, 21.5],
            "SMA_20": [19.8, 20.1, 20.2, 20.3, 20.4],
            "SMA_60": [19.1, 19.2, 19.3, 19.4, 19.5],
            "MACD": [0.05, 0.12, 0.06, 0.14, -0.01],
            "MACD_Signal": [0.08, 0.09, 0.08, 0.10, -0.03],
            "Volume": [100.0, 140.0, 110.0, 130.0, 125.0],
            "Volume_SMA_20": [100.0, 100.0, 100.0, 100.0, 100.0],
        },
        index=dates,
    )

    _assert_precompute_matches_daily(CrossTrendMACDVolumeEntry(), features)
    _assert_precompute_matches_daily(CrossTrendMACDVolumeLooseEntry(), features)


def test_bollinger_squeeze_precompute_matches_daily_signal() -> None:
    dates = pd.bdate_range("2026-01-01", periods=55)
    features = pd.DataFrame(
        {
            "Close": [100.0] * 55,
            "BB_Width": [0.10] * 54 + [0.01],
            "BB_PctB": [0.70] * 54 + [1.20],
            "ADX_14": [25.0] * 55,
            "Volume": [100.0] * 54 + [220.0],
            "Volume_SMA_20": [100.0] * 55,
        },
        index=dates,
    )

    _assert_precompute_matches_daily(BollingerSqueezeStrategy(), features)


def test_ichimoku_stoch_precompute_matches_daily_signal() -> None:
    dates = pd.bdate_range("2026-01-01", periods=35)
    stoch_k = [50.0] * 33 + [20.0, 25.0]
    stoch_d = [55.0] * 33 + [25.0, 20.0]
    features = pd.DataFrame(
        {
            "Close": [110.0] * 35,
            "Ichi_SpanA": [100.0] * 35,
            "Ichi_SpanB": [90.0] * 35,
            "Stoch_K": stoch_k,
            "Stoch_D": stoch_d,
            "OBV": [1_000.0 + index * 10 for index in range(35)],
            "OBV_Slope_20": [5.0] * 35,
        },
        index=dates,
    )

    _assert_precompute_matches_daily(
        IchimokuStochStrategy(min_confidence=0.8),
        features,
    )


def test_scorer_precompute_matches_daily_signal() -> None:
    dates = pd.bdate_range("2026-01-01", periods=25)
    close = [120.0 + index for index in range(25)]
    features = pd.DataFrame(
        {
            "Close": close,
            "EMA_20": [100.0] * 25,
            "EMA_50": [90.0] * 25,
            "EMA_200": [80.0] * 25,
            "RSI": [50.0] * 25,
            "MACD_Hist": [0.5] * 25,
            "MACD": [0.4] * 25,
            "ATR_Z_60": [-1.0] * 25,
            "ATR": [2.0] * 25,
        },
        index=dates,
    )
    trades = pd.DataFrame(
        {
            "EnDate": ["2025-12-20", "2025-12-30"],
            "FrgnBal": [10_000_000.0, 30_000_000.0],
        }
    )
    financials = pd.DataFrame(
        {
            "DiscDate": ["2025-10-01", "2025-12-15"],
            "Sales": [100.0, 120.0],
            "OperatingProfit": [10.0, 13.0],
            "FSales": [100.0, 110.0],
        }
    )

    _assert_precompute_matches_daily(
        SimpleScorerStrategy(),
        features,
        trades=trades,
        financials=financials,
        metadata={},
    )
    _assert_precompute_matches_daily(
        EnhancedScorerStrategy(),
        features,
        trades=trades,
        financials=financials,
        metadata={},
    )
