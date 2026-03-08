import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.macd_hysteresis_entry import (
    MACDHistHysteresisEntry,
    MACDHistHysteresisPreCrossEntry,
)
from src.utils.strategy_loader import ENTRY_STRATEGIES, create_strategy_instance


def _mk_market_data(hist_values, close=1000.0):
    idx = pd.date_range("2025-01-01", periods=len(hist_values), freq="B")
    df = pd.DataFrame(
        {
            "MACD_Hist": hist_values,
            "Close": [close] * len(hist_values),
        },
        index=idx,
    )
    return MarketData(
        ticker="0000",
        current_date=idx[-1],
        df_features=df,
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def test_hysteresis_cross_triggers_buy():
    md = _mk_market_data([-3.0, -1.0, -0.2, 0.6, 1.5])
    st = MACDHistHysteresisEntry(eps=0.001, arm_lookback=3)
    sig = st.generate_entry_signal(md)
    assert sig.action == SignalAction.BUY


def test_precross_sets_buy_size_multiplier():
    md = _mk_market_data([-2.0, -1.2, -0.6, -0.2, -0.05])
    st = MACDHistHysteresisPreCrossEntry(
        eps=0.001,
        arm_lookback=4,
        pre_rise_days=3,
        pre_slope_min=0.0001,
        pre_buy_size_multiplier=0.8,
    )
    sig = st.generate_entry_signal(md)
    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("entry_stage") == "PRE_CROSS"
    assert sig.metadata.get("buy_size_multiplier") == 0.8


def test_loader_has_bulk_registered_variants():
    names = [name for name in ENTRY_STRATEGIES if name.startswith("MGC_HYS_")]
    assert names
    instance = create_strategy_instance(names[0], "entry")
    assert instance is not None
