import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.macd_crossover_precross_entry import (
    GRID_ENTRY_STRATEGY_MAP,
    MACDCrossoverWithPreCrossEntry,
)
from src.utils.strategy_loader import ENTRY_STRATEGIES, create_strategy_instance


def _mk_market_data(df: pd.DataFrame) -> MarketData:
    idx = pd.date_range("2025-01-01", periods=len(df), freq="B")
    df_local = df.copy()
    df_local.index = idx
    return MarketData(
        ticker="0000",
        current_date=idx[-1],
        df_features=df_local,
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def test_macd_cross_path_has_priority_over_precross():
    df = pd.DataFrame(
        {
            "Close": [100.0, 101.0],
            "MACD_Hist": [-0.2, 0.3],
            "Volume": [1200, 1500],
            "Volume_SMA_20": [1000, 1000],
            "EMA_200": [95.0, 95.5],
            "MACD": [0.1, 0.2],
            "MACD_Signal": [0.05, 0.1],
        }
    )
    st = MACDCrossoverWithPreCrossEntry()
    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("entry_stage") == "MACD_CROSS"


def test_precross_path_triggers_buy_with_size_multiplier():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0, 101.0],
            "MACD_Hist": [-0.06, -0.03, -0.01, -0.001],
            "EMA_200": [95.0, 95.0, 95.0, 95.0],
        }
    )
    st = MACDCrossoverWithPreCrossEntry(
        confirm_with_volume=False,
        confirm_with_trend=False,
        eps=0.0010,
        pre_rise_days=3,
        pre_slope_min=0.0002,
        pre_buy_size_multiplier=0.8,
    )
    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("entry_stage") == "PRE_CROSS"
    assert sig.metadata.get("buy_size_multiplier") == 0.8


def test_bulk_registration_count_is_81():
    assert len(GRID_ENTRY_STRATEGY_MAP) == 81

    names = [name for name in ENTRY_STRATEGIES if name.startswith("MACDCP_")]
    assert len(names) == 81

    instance = create_strategy_instance(names[0], "entry")
    assert instance is not None
