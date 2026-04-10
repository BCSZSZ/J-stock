from __future__ import annotations

from typing import Final

import pandas as pd
import pytest

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.utils.strategy_loader import load_exit_strategy


def _float_token(value: float) -> str:
    normalized = f"{float(value):.2f}"
    if normalized.endswith("00"):
        normalized = normalized[:-1]
    elif normalized.endswith("0"):
        normalized = normalized[:-1]
    return normalized.replace(".", "p")


SEED_SWEEP_VARIANT_NAMES: Final[list[str]] = [
    "MVXW_N2_R3p85_T2p0_D21_B20p0",
    "MVXW_N3_R3p85_T2p0_D21_B20p0",
    "MVXW_N4_R3p85_T2p0_D21_B20p0",
    "MVXW_N5_R3p85_T2p0_D21_B20p0",
    "MVXW_N6_R3p85_T2p0_D21_B20p0",
    "MVXW_N7_R3p85_T2p0_D21_B20p0",
    "MVXW_N8_R3p85_T2p0_D21_B20p0",
    "MVXW_N2_R3p35_T1p6_D21_B20p0",
    "MVXW_N3_R3p35_T1p6_D21_B20p0",
    "MVXW_N4_R3p35_T1p6_D21_B20p0",
    "MVXW_N5_R3p35_T1p6_D21_B20p0",
    "MVXW_N6_R3p35_T1p6_D21_B20p0",
    "MVXW_N7_R3p35_T1p6_D21_B20p0",
    "MVXW_N8_R3p35_T1p6_D21_B20p0",
    "MVXW_N2_R3p25_T1p8_D21_B20p0",
    "MVXW_N3_R3p25_T1p8_D21_B20p0",
    "MVXW_N4_R3p25_T1p8_D21_B20p0",
    "MVXW_N5_R3p25_T1p8_D21_B20p0",
    "MVXW_N6_R3p25_T1p8_D21_B20p0",
    "MVXW_N7_R3p25_T1p8_D21_B20p0",
    "MVXW_N8_R3p25_T1p8_D21_B20p0",
]

RT_TUNING_R_VALUES: Final[list[float]] = [3.2, 3.25, 3.3, 3.35, 3.4, 3.45, 3.5]
RT_TUNING_T_VALUES: Final[list[float]] = [1.45, 1.5, 1.55, 1.6, 1.65, 1.7, 1.75]

MVXW_VARIANT_NAMES: Final[list[str]] = list(
    dict.fromkeys(
        SEED_SWEEP_VARIANT_NAMES
        + [
            f"MVXW_N5_R{_float_token(r_value)}_T{_float_token(t_value)}_D21_B20p0"
            for r_value in RT_TUNING_R_VALUES
            for t_value in RT_TUNING_T_VALUES
        ]
    )
)


def _build_entry_signal() -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["entry"],
        metadata={"score": 70.0},
        strategy_name="MACDCrossoverStrategy",
    )


def _build_market_data(macd_hist_values: list[float]) -> MarketData:
    dates = pd.date_range("2025-01-01", periods=len(macd_hist_values), freq="D")
    df_features = pd.DataFrame(
        {
            "Close": [100.0] * len(macd_hist_values),
            "High": [100.5] * len(macd_hist_values),
            "Low": [99.5] * len(macd_hist_values),
            "ATR": [1.0] * len(macd_hist_values),
            "MACD_Hist": macd_hist_values,
            "SMA_25": [100.0] * len(macd_hist_values),
        },
        index=dates,
    )
    return MarketData(
        ticker="7203",
        current_date=dates[-1],
        df_features=df_features,
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def _build_position(entry_date: pd.Timestamp) -> Position:
    return Position(
        ticker="7203",
        entry_price=100.0,
        entry_date=entry_date,
        quantity=100,
        entry_signal=_build_entry_signal(),
        peak_price_since_entry=100.0,
    )


def test_mvxw_triggers_on_window_decay_with_one_rebound_allowed() -> None:
    market_data = _build_market_data([0.9, 0.6, 0.7, 0.4])
    position = _build_position(market_data.df_features.index[0])
    strategy = load_exit_strategy("MVXW_N3_R3p85_T2p0_D21_B20p0")

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.SELL
    assert signal.metadata["trigger"] == "L2_HistWindowDecay"
    assert signal.reasons == ["L2 histogram window decay x3"]


def test_mvxw_requires_current_bar_to_keep_declining() -> None:
    market_data = _build_market_data([0.9, 0.6, 0.5, 0.55])
    position = _build_position(market_data.df_features.index[0])
    strategy = load_exit_strategy("MVXW_N3_R3p85_T2p0_D21_B20p0")

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.HOLD


def test_mvxw_requires_negative_window_slope() -> None:
    market_data = _build_market_data([0.2, 1.0, 0.9, 0.8])
    position = _build_position(market_data.df_features.index[0])
    strategy = load_exit_strategy("MVXW_N3_R3p85_T2p0_D21_B20p0")

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.HOLD


@pytest.mark.parametrize("strategy_name", MVXW_VARIANT_NAMES)
def test_mvxw_variants_are_loader_registered(strategy_name: str) -> None:
    strategy = load_exit_strategy(strategy_name)

    assert strategy.strategy_name == strategy_name