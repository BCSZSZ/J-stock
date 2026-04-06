import pandas as pd
import pytest

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.analysis.strategies.exit.multiview_grid_exit import (
    MultiViewUnifiedTakeProfitExit,
)
from src.utils.strategy_loader import load_exit_strategy


def _build_entry_signal() -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["entry"],
        metadata={"score": 70.0},
        strategy_name="MACDCrossoverStrategy",
    )


@pytest.mark.parametrize(
    ("take_profit_r", "close_price", "expected_trigger", "expected_reason"),
    [
        (1.2, 101.3, "P_TP1p2", "TP1.2 hit: +1.2R"),
        (1.4, 101.5, "P_TP1p4", "TP1.4 hit: +1.4R"),
        (1.5, 101.6, "P_TP1p5", "TP1.5 hit: +1.5R"),
    ],
)
def test_unified_take_profit_triggers_full_exit_at_configured_r(
    take_profit_r: float,
    close_price: float,
    expected_trigger: str,
    expected_reason: str,
):
    dates = pd.date_range("2025-01-01", periods=3, freq="D")
    df_features = pd.DataFrame(
        {
            "Close": [100.0, 101.0, close_price],
            "High": [100.5, 101.5, 102.0],
            "Low": [99.5, 100.5, 101.0],
            "ATR": [1.0, 1.0, 1.0],
            "MACD_Hist": [0.1, 0.2, 0.3],
            "SMA_25": [100.0, 100.0, 100.0],
        },
        index=dates,
    )

    market_data = MarketData(
        ticker="7203",
        current_date=dates[-1],
        df_features=df_features,
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )
    position = Position(
        ticker="7203",
        entry_price=100.0,
        entry_date=dates[0],
        quantity=100,
        entry_signal=_build_entry_signal(),
        peak_price_since_entry=102.0,
    )

    strategy = MultiViewUnifiedTakeProfitExit(
        hist_shrink_n=2,
        r_mult=1.0,
        trail_mult=1.6,
        time_stop_days=18,
        bias_exit_threshold_pct=20.0,
        take_profit_r=take_profit_r,
    )

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.SELL
    assert signal.metadata["trigger"] == expected_trigger
    assert signal.metadata["sell_percentage"] == 1.0
    assert signal.reasons == [expected_reason]


@pytest.mark.parametrize(
    "strategy_name",
    [
        "MVU12_N1_R3p4_T1p6_D18_B20p0",
        "MVU14_N2_R3p4_T1p6_D18_B20p0",
        "MVU_N3_R3p4_T1p6_D18_B20p0",
        "MVX_N1_R3p4_T1p6_D18_B20p0",
        "MVX_N3_R3p4_T1p2_D18_B20p0",
        "MVX_N3_R3p4_T1p3_D18_B20p0",
        "MVX_N3_R3p4_T1p4_D18_B20p0",
        "MVX_N3_R3p4_T1p5_D18_B20p0",
        "MVX_N3_R3p2_T1p5_D18_B20p0",
        "MVX_N3_R3p2_T1p6_D15_B20p0",
        "MVX_N3_R3p2_T1p65_D18_B20p0",
        "MVX_N3_R3p25_T1p55_D18_B20p0",
        "MVX_N3_R3p3_T1p7_D18_B20p0",
        "MVX_N3_R3p35_T1p65_D18_B20p0",
        "MVX_N3_R3p2_T1p6_D21_B20p0",
        "MVX_N3_R3p2_T1p6_D22_B20p0",
        "MVX_N3_R3p2_T1p65_D22_B20p0",
        "MVX_N3_R3p25_T1p6_D21_B20p0",
        "MVX_N3_R3p25_T1p65_D22_B20p0",
        "MVX_N3_R3p2_T1p6_D27_B20p0",
        "MVX_N3_R3p5_T1p6_D18_B20p0",
        "MVX_N3_R3p6_T1p7_D18_B20p0",
        "MVX_N3_R3p4_T1p7_D18_B20p0",
        "MVX_N3_R3p4_T1p8_D18_B20p0",
    ],
)
def test_unified_take_profit_variants_are_loader_registered(strategy_name: str):
    strategy = load_exit_strategy(strategy_name)

    assert strategy.strategy_name == strategy_name
    if strategy_name.startswith("MVU"):
        assert isinstance(strategy, MultiViewUnifiedTakeProfitExit)