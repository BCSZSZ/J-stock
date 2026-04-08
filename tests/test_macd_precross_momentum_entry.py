import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.macd_precross_momentum_entry import (
    MACDPreCross2BarEntry,
    MACDPreCross2BarLiteComboEntry,
    MACDPreCross2BarRet5d008Entry,
    MACDPreCrossMomentumEntry,
    build_precross_momentum_flags,
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


def test_precross_momentum_entry_triggers_on_core_pattern():
    df = pd.DataFrame(
        {
            "Close": [98.0, 99.0, 101.0],
            "MACD_Hist": [-0.30, -0.18, -0.06],
            "MACD": [-0.6, -0.4, -0.2],
            "MACD_Signal": [-0.4, -0.3, -0.14],
        }
    )
    st = MACDPreCrossMomentumEntry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("entry_stage") == "PRE_CROSS_MOMENTUM"


def test_precross_momentum_entry_requires_price_rise():
    df = pd.DataFrame(
        {
            "Close": [98.0, 99.0, 98.5],
            "MACD_Hist": [-0.30, -0.18, -0.06],
            "MACD": [-0.6, -0.4, -0.2],
            "MACD_Signal": [-0.4, -0.3, -0.14],
        }
    )
    st = MACDPreCrossMomentumEntry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert "Price not rising consecutively" in sig.reasons


def test_precross_momentum_entry_requires_negative_histogram():
    df = pd.DataFrame(
        {
            "Close": [98.0, 99.0, 101.0],
            "MACD_Hist": [-0.30, -0.18, 0.02],
            "MACD": [-0.6, -0.4, -0.1],
            "MACD_Signal": [-0.4, -0.3, -0.12],
        }
    )
    st = MACDPreCrossMomentumEntry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert "Histogram is not below zero" in sig.reasons


def test_precross_momentum_entry_optional_filters_work():
    df = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "MACD_Hist": [-2.0, -1.4, -0.9],
            "EMA_200": [110.0, 110.0, 110.0],
            "MACD": [-2.1, -1.7, -1.2],
            "MACD_Signal": [-1.8, -1.5, -1.0],
        }
    )

    deep_hist = MACDPreCrossMomentumEntry(max_hist_abs_norm=0.005)
    trend_filtered = MACDPreCrossMomentumEntry(require_above_ema200=True)

    deep_sig = deep_hist.generate_entry_signal(_mk_market_data(df))
    trend_sig = trend_filtered.generate_entry_signal(_mk_market_data(df))

    assert deep_sig.action == SignalAction.HOLD
    assert "Histogram is too far below zero axis" in deep_sig.reasons
    assert trend_sig.action == SignalAction.HOLD
    assert "Price is below EMA200" in trend_sig.reasons


def test_build_flags_and_registration():
    df = pd.DataFrame(
        {
            "Close": [98.0, 99.0, 101.0, 102.0],
            "MACD_Hist": [-0.30, -0.18, -0.06, -0.02],
            "EMA_200": [90.0, 90.0, 90.0, 90.0],
            "Volume": [1000.0, 1200.0, 1100.0, 1500.0],
            "Volume_SMA_20": [1000.0, 1000.0, 1000.0, 1000.0],
        }
    )
    flags = build_precross_momentum_flags(
        df,
        max_hist_abs_norm=0.01,
        require_above_ema200=True,
    )

    assert bool(flags.iloc[-1]["signal"]) is True
    assert "MACDPreCrossMomentumEntry" in ENTRY_STRATEGIES

    instance = create_strategy_instance("MACDPreCrossMomentumEntry", "entry")
    assert instance is not None


def test_precross_two_bar_variant_triggers_with_two_bar_rise():
    df = pd.DataFrame(
        {
            "Close": [97.0, 98.5],
            "MACD_Hist": [-0.12, -0.04],
            "MACD": [-0.30, -0.12],
            "MACD_Signal": [-0.22, -0.10],
        }
    )
    st = MACDPreCrossMomentumEntry(hist_rise_days=2, price_rise_days=2)

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("hist_rise_days") == 2
    assert sig.metadata.get("price_rise_days") == 2


def test_peak_constraint_requires_window_to_start_at_negative_peak():
    df = pd.DataFrame(
        {
            "Close": [100.0, 99.0, 100.0, 101.0],
            "MACD_Hist": [-0.60, -0.40, -0.20, -0.05],
            "MACD": [-0.8, -0.6, -0.3, -0.1],
            "MACD_Signal": [-0.7, -0.5, -0.25, -0.08],
        }
    )
    flags = build_precross_momentum_flags(
        df,
        hist_rise_days=3,
        price_rise_days=3,
        require_peak_at_window_start=True,
    )
    st = MACDPreCrossMomentumEntry(
        hist_rise_days=3,
        price_rise_days=3,
        require_peak_at_window_start=True,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert bool(flags.iloc[-1]["peak_at_window_start"]) is False
    assert sig.action == SignalAction.HOLD
    assert "Rising window does not start at the negative histogram peak" in sig.reasons


def test_peak_constraint_triggers_when_peak_is_window_start():
    df = pd.DataFrame(
        {
            "Close": [99.0, 100.0, 101.0],
            "MACD_Hist": [-0.50, -0.22, -0.08],
            "MACD": [-0.7, -0.4, -0.2],
            "MACD_Signal": [-0.5, -0.3, -0.15],
        }
    )
    st = MACDPreCrossMomentumEntry(
        hist_rise_days=3,
        price_rise_days=3,
        require_peak_at_window_start=True,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("peak_at_window_start") is True


def test_lightweight_helper_filters_block_or_allow_as_expected():
    df = pd.DataFrame(
        {
            "Close": [99.0, 101.0],
            "EMA_20": [98.0, 95.0],
            "Return_5d": [0.03, 0.09],
            "ADX_14": [9.0, 9.0],
            "MACD_Hist": [-0.10, -0.02],
            "MACD": [-0.30, -0.12],
            "MACD_Signal": [-0.22, -0.10],
        }
    )
    blocked = MACDPreCrossMomentumEntry(
        hist_rise_days=2,
        price_rise_days=2,
        max_gap_above_ema20_pct=5.0,
        max_return_5d=0.08,
        min_adx_14=10.0,
    )
    relaxed = MACDPreCrossMomentumEntry(
        hist_rise_days=2,
        price_rise_days=2,
        max_gap_above_ema20_pct=7.0,
        max_return_5d=0.10,
        min_adx_14=8.0,
    )

    blocked_sig = blocked.generate_entry_signal(_mk_market_data(df))
    relaxed_sig = relaxed.generate_entry_signal(_mk_market_data(df))

    assert blocked_sig.action == SignalAction.HOLD
    assert "Price is too far above EMA20" in blocked_sig.reasons
    assert "Return_5d is too high" in blocked_sig.reasons
    assert "ADX_14 is too low" in blocked_sig.reasons
    assert relaxed_sig.action == SignalAction.BUY


def test_cli_friendly_precross_variants_are_registered_with_fixed_params():
    plain = MACDPreCross2BarEntry()
    ret5d = MACDPreCross2BarRet5d008Entry()
    lite = MACDPreCross2BarLiteComboEntry()

    assert plain.strategy_name == "MACDPreCross2BarEntry"
    assert plain.hist_rise_days == 2
    assert plain.price_rise_days == 2

    assert ret5d.strategy_name == "MACDPreCross2BarRet5d008Entry"
    assert ret5d.max_return_5d == 0.08

    assert lite.strategy_name == "MACDPreCross2BarLiteComboEntry"
    assert lite.max_hist_abs_norm == 0.01
    assert lite.min_adx_14 == 10.0
    assert lite.max_return_5d == 0.08