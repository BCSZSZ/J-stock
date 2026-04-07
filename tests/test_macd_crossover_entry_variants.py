import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.macd_crossover_entry_variants import (
    MACDCrossoverFragileBelowZeroDownweightV6,
    MACDCrossoverFragileBelowZeroFilterV4,
    MACDCrossoverFragileBelowZeroLowADXFilterV5,
    MACDCrossoverFollowThroughFilterV3,
    MACDCrossoverShockFilterV1,
    MACDCrossoverShockOverheatFilterV2,
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


def test_v1_filters_shock_cross():
    df = pd.DataFrame(
        {
            "Close": [780.0, 800.0],
            "MACD_Hist": [-1.0, 5.0],
            "MACD": [0.1, 0.5],
            "MACD_Signal": [0.2, 0.3],
        }
    )
    st = MACDCrossoverShockFilterV1(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_hist_jump_norm=0.0050,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("shock_filtered") is True


def test_v1_keeps_normal_cross():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0],
            "MACD_Hist": [-0.2, 0.2],
            "MACD": [0.1, 0.2],
            "MACD_Signal": [0.05, 0.1],
        }
    )
    st = MACDCrossoverShockFilterV1(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_hist_jump_norm=0.0050,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("shock_filtered") is False


def test_v2_filters_overheated_cross_even_without_shock():
    df = pd.DataFrame(
        {
            "Close": [99.0, 100.0],
            "EMA_20": [94.0, 94.0],
            "BB_PctB": [0.91, 0.96],
            "Return_20d": [0.04, 0.06],
            "MACD_Hist": [-0.05, 0.15],
            "MACD": [0.1, 0.2],
            "MACD_Signal": [0.05, 0.1],
        }
    )
    st = MACDCrossoverShockOverheatFilterV2(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_hist_jump_norm=0.0050,
        max_bb_pctb=0.94,
        max_gap_above_ema20_pct=5.0,
        max_return_20d=0.05,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("overheat_filtered") is True
    assert sig.metadata.get("shock_filtered") is False


def test_variant_registration_and_loading():
    assert "MACDCrossoverShockFilterV1" in ENTRY_STRATEGIES
    assert "MACDCrossoverShockOverheatFilterV2" in ENTRY_STRATEGIES
    assert "MACDCrossoverFollowThroughFilterV3" in ENTRY_STRATEGIES
    assert "MACDCrossoverFragileBelowZeroFilterV4" in ENTRY_STRATEGIES
    assert "MACDCrossoverFragileBelowZeroLowADXFilterV5" in ENTRY_STRATEGIES
    assert "MACDCrossoverFragileBelowZeroDownweightV6" in ENTRY_STRATEGIES

    v1 = create_strategy_instance("MACDCrossoverShockFilterV1", "entry")
    v2 = create_strategy_instance("MACDCrossoverShockOverheatFilterV2", "entry")
    v3 = create_strategy_instance("MACDCrossoverFollowThroughFilterV3", "entry")
    v4 = create_strategy_instance("MACDCrossoverFragileBelowZeroFilterV4", "entry")
    v5 = create_strategy_instance("MACDCrossoverFragileBelowZeroLowADXFilterV5", "entry")
    v6 = create_strategy_instance("MACDCrossoverFragileBelowZeroDownweightV6", "entry")

    assert v1 is not None
    assert v2 is not None
    assert v3 is not None
    assert v4 is not None
    assert v5 is not None
    assert v6 is not None


def test_v3_filters_fragile_below_zero_cross():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.80, 99.95],
            "MACD_Hist": [-0.20, -0.11, 0.07],
            "MACD": [-0.60, -0.45, -0.20],
            "MACD_Signal": [-0.40, -0.34, -0.27],
        }
    )
    st = MACDCrossoverFollowThroughFilterV3(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_ema20_slope_pct=0.25,
        min_prev_hist_norm=0.0010,
        max_hist_now_norm=0.0008,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("followthrough_filtered") is True


def test_v3_keeps_healthier_cross():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.60, 99.95, 100.40],
            "MACD_Hist": [-0.12, -0.05, 0.18],
            "MACD": [-0.25, -0.10, 0.06],
            "MACD_Signal": [-0.22, -0.12, -0.02],
        }
    )
    st = MACDCrossoverFollowThroughFilterV3(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_ema20_slope_pct=0.25,
        min_prev_hist_norm=0.0010,
        max_hist_now_norm=0.0008,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("followthrough_filtered") is False


def test_v4_filters_with_optimized_defaults():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
        }
    )
    st = MACDCrossoverFragileBelowZeroFilterV4(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("followthrough_filtered") is True


def test_v4_parameters_remain_adjustable():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
        }
    )
    st = MACDCrossoverFragileBelowZeroFilterV4(
        confirm_with_volume=False,
        confirm_with_trend=False,
        max_hist_now_norm=0.0003,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("followthrough_filtered") is False


def test_v5_filters_only_when_fragile_and_low_adx():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
            "ADX_14": [18.0, 17.0, 15.0],
        }
    )
    st = MACDCrossoverFragileBelowZeroLowADXFilterV5(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("followthrough_filtered") is True
    assert sig.metadata.get("low_adx_filtered") is True


def test_v5_keeps_fragile_cross_when_adx_is_high():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
            "ADX_14": [24.0, 26.0, 28.0],
        }
    )
    st = MACDCrossoverFragileBelowZeroLowADXFilterV5(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("followthrough_filtered") is False
    assert sig.metadata.get("low_adx_filtered") is False


def test_v6_downweights_fragile_buy_without_filtering():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
        }
    )
    st = MACDCrossoverFragileBelowZeroDownweightV6(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("score") == 35.0
    assert sig.metadata.get("downweight_tier") == "fragile"
    assert sig.metadata.get("score_downweighted") is True


def test_v6_uses_low_adx_score_for_fragile_low_adx_buy():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
            "ADX_14": [18.0, 17.0, 15.0],
        }
    )
    st = MACDCrossoverFragileBelowZeroDownweightV6(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("score") == 25.0
    assert sig.metadata.get("downweight_tier") == "fragile_low_adx"
    assert sig.metadata.get("low_adx_candidate") is True


def test_v6_uses_weakest_score_when_low_adx_and_weak_volume():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.70, 99.78, 100.00450],
            "MACD_Hist": [-0.30, -0.14, 0.035],
            "MACD": [-0.60, -0.44, -0.18],
            "MACD_Signal": [-0.45, -0.35, -0.22],
            "ADX_14": [18.0, 17.0, 15.0],
            "Volume": [100.0, 100.0, 100.0],
            "Volume_SMA_20": [100.0, 100.0, 100.0],
        }
    )
    st = MACDCrossoverFragileBelowZeroDownweightV6(
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("score") == 15.0
    assert sig.metadata.get("downweight_tier") == "fragile_low_adx_weak_volume"
    assert sig.metadata.get("weak_volume_candidate") is True


def test_v6_keeps_base_score_for_healthier_cross():
    df = pd.DataFrame(
        {
            "Close": [100.0, 100.0, 100.0],
            "EMA_20": [99.60, 99.95, 100.40],
            "MACD_Hist": [-0.12, -0.05, 0.18],
            "MACD": [-0.25, -0.10, 0.06],
            "MACD_Signal": [-0.22, -0.12, -0.02],
        }
    )
    st = MACDCrossoverFragileBelowZeroDownweightV6(
        confirm_with_volume=False,
        confirm_with_trend=False,
    )

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("score") == 50.0
    assert sig.metadata.get("downweight_tier") == "base"
    assert sig.metadata.get("score_downweighted") is False