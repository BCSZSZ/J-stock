import pandas as pd
import src.analysis.strategies.entry.macd_precross_momentum_entry as precross_entry_module

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.macd_precross_momentum_entry import (
    MACDPreCross2BarEntry,
    MACDPreCross2BarLiteComboEntry,
    MACDPreCross2BarMinHistDeltaNorm0005Entry,
    MACDPreCross2BarMinHistDeltaNorm0015Entry,
    MACDPreCross2BarMinHistDeltaNorm001Entry,
    MACDPreCross2BarMinHistDeltaNorm002Entry,
    MACDPreCross2BarRet5d008Entry,
    MACDPreCross3BarEntry,
    MACDHist2BarAnySignEntry,
    MACDHist2BarAnySignFollowExitBiasEntry,
    MACDHist2BarAnySignMaxBiasPct15Entry,
    MACDHist2BarAnySignStrictFreshEntry,
    MACDPreCrossMomentumEntry,
    _latest_precross_momentum_flags,
    build_precross_momentum_flags,
)
from src.utils.strategy_loader import (
    ENTRY_STRATEGIES,
    create_strategy_instance,
    load_strategy_pair,
)


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


def test_hist2bar_anysign_marks_repeated_buy_signal_as_stale_but_still_buys():
    df = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "MACD_Hist": [-0.30, -0.20, -0.10],
            "MACD": [-0.50, -0.35, -0.20],
            "MACD_Signal": [-0.40, -0.30, -0.15],
        }
    )
    st = MACDHist2BarAnySignEntry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert sig.metadata.get("raw_entry_signal") is True
    assert sig.metadata.get("buy_signal_streak_days") == 2
    assert sig.metadata.get("stale_buy_signal") is True


def test_hist2bar_anysign_strict_fresh_buys_only_first_raw_buy_day():
    fresh_df = pd.DataFrame(
        {
            "Close": [100.0, 101.0],
            "MACD_Hist": [-0.30, -0.20],
            "MACD": [-0.50, -0.35],
            "MACD_Signal": [-0.40, -0.30],
        }
    )
    stale_df = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "MACD_Hist": [-0.30, -0.20, -0.10],
            "MACD": [-0.50, -0.35, -0.20],
            "MACD_Signal": [-0.40, -0.30, -0.15],
        }
    )
    st = MACDHist2BarAnySignStrictFreshEntry()

    fresh_sig = st.generate_entry_signal(_mk_market_data(fresh_df))
    stale_sig = st.generate_entry_signal(_mk_market_data(stale_df))

    assert fresh_sig.action == SignalAction.BUY
    assert fresh_sig.metadata.get("buy_signal_streak_days") == 1
    assert fresh_sig.metadata.get("is_fresh_buy_signal") is True
    assert stale_sig.action == SignalAction.HOLD
    assert stale_sig.metadata.get("entry_stage") == "STALE_PRE_CROSS_MOMENTUM"
    assert stale_sig.metadata.get("buy_signal_streak_days") == 2
    assert stale_sig.metadata.get("stale_buy_signal") is True
    assert any("BUY signal stale" in reason for reason in stale_sig.reasons)


def test_batch_and_latest_flags_track_strict_fresh_streak_for_hist_only_entry():
    df = pd.DataFrame(
        {
            "Close": [100.0, 99.0, 98.0],
            "MACD_Hist": [-0.30, -0.20, -0.10],
        }
    )

    batch_flags = build_precross_momentum_flags(
        df,
        hist_rise_days=2,
        price_rise_days=2,
        require_price_rising=False,
        require_hist_below_zero=False,
        max_buy_signal_streak_days=1,
    ).iloc[-1]
    latest_flags = _latest_precross_momentum_flags(
        df,
        hist_rise_days=2,
        price_rise_days=2,
        require_price_rising=False,
        require_hist_below_zero=False,
        max_buy_signal_streak_days=1,
    )

    assert bool(batch_flags["raw_entry_signal"]) is True
    assert bool(batch_flags["signal"]) is False
    assert int(batch_flags["buy_signal_streak_days"]) == 2
    assert latest_flags["buy_signal_streak_days"] == 2
    assert bool(latest_flags["raw_entry_signal"]) == bool(batch_flags["raw_entry_signal"])
    assert bool(latest_flags["signal"]) == bool(batch_flags["signal"])


def test_generate_entry_signal_reuses_previous_streak_state_without_batch_recompute(
    monkeypatch,
):
    df = pd.DataFrame(
        {
            "Close": [100.0, 99.0, 98.0],
            "MACD_Hist": [-0.30, -0.20, -0.10],
            "MACD": [-0.50, -0.40, -0.20],
            "MACD_Signal": [-0.45, -0.35, -0.15],
        }
    )

    strategy = MACDHist2BarAnySignStrictFreshEntry()
    first_signal = strategy.generate_entry_signal(_mk_market_data(df.iloc[:2]))
    assert first_signal.metadata.get("buy_signal_streak_days") == 1
    assert first_signal.action == SignalAction.BUY

    def _unexpected_batch_recompute(*args, **kwargs):
        raise AssertionError("cached hot path should not invoke build_precross_momentum_flags")

    monkeypatch.setattr(
        precross_entry_module,
        "build_precross_momentum_flags",
        _unexpected_batch_recompute,
    )

    stale_signal = strategy.generate_entry_signal(_mk_market_data(df))

    assert stale_signal.metadata.get("buy_signal_streak_days") == 2
    assert bool(stale_signal.metadata.get("raw_entry_signal")) is True
    assert stale_signal.action == SignalAction.HOLD

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


def test_bias_overheat_filter_blocks_entry_but_legacy_variant_still_buys():
    df = pd.DataFrame(
        {
            "Close": [100.0, 110.0],
            "SMA_25": [90.0, 94.0],
            "MACD_Hist": [-0.10, -0.02],
            "MACD": [-0.30, -0.12],
            "MACD_Signal": [-0.22, -0.10],
        }
    )
    legacy = MACDHist2BarAnySignEntry()
    blocked = MACDHist2BarAnySignMaxBiasPct15Entry()

    legacy_sig = legacy.generate_entry_signal(_mk_market_data(df))
    blocked_sig = blocked.generate_entry_signal(_mk_market_data(df))

    assert legacy_sig.action == SignalAction.BUY
    assert blocked_sig.action == SignalAction.HOLD
    assert any("Bias overheat" in reason for reason in blocked_sig.reasons)
    assert blocked_sig.metadata.get("bias_reference") == "SMA_25"
    assert blocked_sig.metadata.get("max_bias_pct") == 15.0


def test_bias_overheat_filter_falls_back_to_sma20_when_sma25_missing():
    df = pd.DataFrame(
        {
            "Close": [100.0, 111.0],
            "SMA_20": [95.0, 95.0],
            "MACD_Hist": [-0.10, -0.02],
            "MACD": [-0.30, -0.12],
            "MACD_Signal": [-0.22, -0.10],
        }
    )
    blocked = MACDHist2BarAnySignMaxBiasPct15Entry()

    sig = blocked.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert sig.metadata.get("bias_reference") == "SMA_20"
    assert sig.metadata.get("bias_pct") > 15.0


def test_follow_exit_bias_variant_uses_exit_bias_threshold_when_available():
    entry, exit_strategy = load_strategy_pair(
        "MACDHist2BarAnySignFollowExitBiasEntry",
        "MVXW_N3_R0p54_T1p3_D10_B20p0",
    )

    assert isinstance(entry, MACDHist2BarAnySignFollowExitBiasEntry)
    assert entry.max_bias_pct == exit_strategy.bias_exit_threshold_pct == 20.0
    assert entry.bias_threshold_source == "exit"
    assert entry.bound_exit_strategy_name == "MVXW_N3_R0p54_T1p3_D10_B20p0"


def test_follow_exit_bias_variant_falls_back_to_15_without_exit_bias():
    entry, _ = load_strategy_pair(
        "MACDHist2BarAnySignFollowExitBiasEntry",
        "ATRExitStrategy",
    )

    assert isinstance(entry, MACDHist2BarAnySignFollowExitBiasEntry)
    assert entry.max_bias_pct == 15.0
    assert entry.bias_threshold_source == "fallback"


def test_follow_exit_bias_variant_changes_buy_gate_with_paired_exit_threshold():
    df = pd.DataFrame(
        {
            "Close": [100.0, 112.0],
            "SMA_25": [95.0, 95.0],
            "MACD_Hist": [-0.10, -0.02],
            "MACD": [-0.30, -0.12],
            "MACD_Signal": [-0.22, -0.10],
        }
    )
    permissive_entry, _ = load_strategy_pair(
        "MACDHist2BarAnySignFollowExitBiasEntry",
        "MVXW_N3_R0p54_T1p3_D10_B20p0",
    )
    fallback_entry, _ = load_strategy_pair(
        "MACDHist2BarAnySignFollowExitBiasEntry",
        "ATRExitStrategy",
    )

    permissive_sig = permissive_entry.generate_entry_signal(_mk_market_data(df))
    fallback_sig = fallback_entry.generate_entry_signal(_mk_market_data(df))

    assert permissive_sig.action == SignalAction.BUY
    assert fallback_sig.action == SignalAction.HOLD
    assert fallback_sig.metadata.get("bias_threshold_source") == "fallback"


def test_cli_friendly_precross_variants_are_registered_with_fixed_params():
    plain = MACDPreCross2BarEntry()
    three_bar = MACDPreCross3BarEntry()
    ret5d = MACDPreCross2BarRet5d008Entry()
    min_delta = MACDPreCross2BarMinHistDeltaNorm0005Entry()
    min_delta_001 = MACDPreCross2BarMinHistDeltaNorm001Entry()
    min_delta_0015 = MACDPreCross2BarMinHistDeltaNorm0015Entry()
    min_delta_002 = MACDPreCross2BarMinHistDeltaNorm002Entry()
    lite = MACDPreCross2BarLiteComboEntry()
    max_bias = MACDHist2BarAnySignMaxBiasPct15Entry()
    strict_fresh = MACDHist2BarAnySignStrictFreshEntry()
    follow_exit_bias = MACDHist2BarAnySignFollowExitBiasEntry()

    assert plain.strategy_name == "MACDPreCross2BarEntry"
    assert plain.hist_rise_days == 2
    assert plain.price_rise_days == 2

    assert three_bar.strategy_name == "MACDPreCross3BarEntry"
    assert three_bar.hist_rise_days == 3
    assert three_bar.price_rise_days == 3

    assert ret5d.strategy_name == "MACDPreCross2BarRet5d008Entry"
    assert ret5d.max_return_5d == 0.08

    assert min_delta.strategy_name == "MACDPreCross2BarMinHistDeltaNorm0005Entry"
    assert min_delta.min_hist_delta_norm == 0.0005

    assert min_delta_001.strategy_name == "MACDPreCross2BarMinHistDeltaNorm001Entry"
    assert min_delta_001.min_hist_delta_norm == 0.001

    assert min_delta_0015.strategy_name == "MACDPreCross2BarMinHistDeltaNorm0015Entry"
    assert min_delta_0015.min_hist_delta_norm == 0.0015

    assert min_delta_002.strategy_name == "MACDPreCross2BarMinHistDeltaNorm002Entry"
    assert min_delta_002.min_hist_delta_norm == 0.002

    assert lite.strategy_name == "MACDPreCross2BarLiteComboEntry"
    assert lite.max_hist_abs_norm == 0.01
    assert lite.min_adx_14 == 10.0
    assert lite.max_return_5d == 0.08

    assert max_bias.strategy_name == "MACDHist2BarAnySignMaxBiasPct15Entry"
    assert max_bias.max_bias_pct == 15.0
    assert max_bias.require_hist_below_zero is False

    assert strict_fresh.strategy_name == "MACDHist2BarAnySignStrictFreshEntry"
    assert strict_fresh.max_buy_signal_streak_days == 1
    assert strict_fresh.require_price_rising is False
    assert strict_fresh.require_hist_below_zero is False

    assert follow_exit_bias.strategy_name == "MACDHist2BarAnySignFollowExitBiasEntry"
    assert follow_exit_bias.max_bias_pct == 15.0
    assert follow_exit_bias.follow_exit_bias_pct is True

    assert "MACDPreCross2BarMinHistDeltaNorm0005Entry" in ENTRY_STRATEGIES
    assert "MACDPreCross2BarMinHistDeltaNorm001Entry" in ENTRY_STRATEGIES
    assert "MACDPreCross2BarMinHistDeltaNorm0015Entry" in ENTRY_STRATEGIES
    assert "MACDPreCross2BarMinHistDeltaNorm002Entry" in ENTRY_STRATEGIES
    assert "MACDHist2BarAnySignMaxBiasPct15Entry" in ENTRY_STRATEGIES
    assert "MACDHist2BarAnySignStrictFreshEntry" in ENTRY_STRATEGIES
    assert "MACDHist2BarAnySignFollowExitBiasEntry" in ENTRY_STRATEGIES
    assert create_strategy_instance(
        "MACDPreCross2BarMinHistDeltaNorm0005Entry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDPreCross2BarMinHistDeltaNorm001Entry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDPreCross2BarMinHistDeltaNorm0015Entry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDPreCross2BarMinHistDeltaNorm002Entry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDHist2BarAnySignMaxBiasPct15Entry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDHist2BarAnySignStrictFreshEntry", "entry"
    ) is not None
    assert create_strategy_instance(
        "MACDHist2BarAnySignFollowExitBiasEntry", "entry"
    ) is not None


def test_max_bias_pct20_variants_are_registered_with_expected_flags():
    expected = {
        "MACDPreCross2BarMaxBiasPct20Entry": (2, 2, True, True),
        "MACDPreCrossHist2BarMaxBiasPct20Entry": (2, 2, False, True),
        "MACDHist2BarAnySignMaxBiasPct20Entry": (2, 2, False, False),
        "MACD2BarAnySignMaxBiasPct20Entry": (2, 2, True, False),
        "MACDPreCross3BarMaxBiasPct20Entry": (3, 3, True, True),
        "MACDPreCrossHist3BarMaxBiasPct20Entry": (3, 3, False, True),
        "MACDHist3BarAnySignMaxBiasPct20Entry": (3, 3, False, False),
        "MACD3BarAnySignMaxBiasPct20Entry": (3, 3, True, False),
    }

    for strategy_name, (
        hist_rise_days,
        price_rise_days,
        require_price_rising,
        require_hist_below_zero,
    ) in expected.items():
        assert strategy_name in ENTRY_STRATEGIES
        strategy = create_strategy_instance(strategy_name, "entry")
        assert strategy.strategy_name == strategy_name
        assert strategy.hist_rise_days == hist_rise_days
        assert strategy.price_rise_days == price_rise_days
        assert strategy.require_price_rising is require_price_rising
        assert strategy.require_hist_below_zero is require_hist_below_zero
        assert strategy.max_bias_pct == 20.0


def test_hist2bar_anysign_max_bias_family_is_registered_with_expected_thresholds():
    expected = {
        "MACDHist2BarAnySignMaxBiasPct10Entry": 10.0,
        "MACDHist2BarAnySignMaxBiasPct15Entry": 15.0,
        "MACDHist2BarAnySignMaxBiasPct20Entry": 20.0,
        "MACDHist2BarAnySignMaxBiasPct25Entry": 25.0,
        "MACDHist2BarAnySignMaxBiasPct30Entry": 30.0,
    }

    for strategy_name, max_bias_pct in expected.items():
        assert strategy_name in ENTRY_STRATEGIES
        strategy = create_strategy_instance(strategy_name, "entry")
        assert strategy.strategy_name == strategy_name
        assert strategy.hist_rise_days == 2
        assert strategy.price_rise_days == 2
        assert strategy.require_price_rising is False
        assert strategy.require_hist_below_zero is False
        assert strategy.max_bias_pct == max_bias_pct


def test_requested_strict_fresh_variants_are_registered_with_inherited_flags():
    base_names = (
        "MACDHist2BarAnySignEntry",
        "MACDHist2BarAnySignMaxBiasPct10Entry",
        "MACDHist2BarAnySignMaxBiasPct15Entry",
        "MACDHist2BarAnySignMaxBiasPct20Entry",
        "MACDHist2BarAnySignMaxBiasPct25Entry",
        "MACDHist2BarAnySignMaxBiasPct30Entry",
        "MACDHist2BarAnySignFollowExitBiasEntry",
        "MACD2BarAnySignEntry",
        "MACD2BarAnySignMaxBiasPct20Entry",
        "MACDPreCrossHist3BarEntry",
        "MACDPreCrossHist3BarMaxBiasPct20Entry",
        "MACDHist3BarAnySignEntry",
        "MACDHist3BarAnySignMaxBiasPct20Entry",
        "MACDPreCross3BarEntry",
        "MACDPreCross3BarMaxBiasPct20Entry",
        "MACD3BarAnySignEntry",
        "MACD3BarAnySignMaxBiasPct20Entry",
    )

    for base_name in base_names:
        strict_name = f"{base_name.removesuffix('Entry')}StrictFreshEntry"
        assert strict_name in ENTRY_STRATEGIES

        base_strategy = create_strategy_instance(base_name, "entry")
        strict_strategy = create_strategy_instance(strict_name, "entry")

        assert strict_strategy.strategy_name == strict_name
        assert strict_strategy.max_buy_signal_streak_days == 1
        assert strict_strategy.hist_rise_days == base_strategy.hist_rise_days
        assert strict_strategy.price_rise_days == base_strategy.price_rise_days
        assert (
            strict_strategy.require_price_rising
            is base_strategy.require_price_rising
        )
        assert (
            strict_strategy.require_hist_below_zero
            is base_strategy.require_hist_below_zero
        )
        assert strict_strategy.max_hist_abs_norm == base_strategy.max_hist_abs_norm
        assert (
            strict_strategy.min_hist_delta_norm
            == base_strategy.min_hist_delta_norm
        )
        assert strict_strategy.max_gap_above_ema20_pct == base_strategy.max_gap_above_ema20_pct
        assert strict_strategy.max_return_5d == base_strategy.max_return_5d
        assert strict_strategy.min_adx_14 == base_strategy.min_adx_14
        assert strict_strategy.max_bias_pct == base_strategy.max_bias_pct
        assert (
            strict_strategy.follow_exit_bias_pct
            is base_strategy.follow_exit_bias_pct
        )
        assert strict_strategy.fallback_bias_pct == base_strategy.fallback_bias_pct
        assert (
            strict_strategy.complexity.numeric_param_count
            == base_strategy.complexity.numeric_param_count + 1
        )
        assert (
            strict_strategy.complexity.extra_filter_count
            == base_strategy.complexity.extra_filter_count + 1
        )
        assert (
            strict_strategy.complexity.conditional_rule_count
            == base_strategy.complexity.conditional_rule_count + 1
        )


def test_min_hist_delta_norm_blocks_tiny_histogram_rise():
    df = pd.DataFrame(
        {
            "Close": [4101.0, 4130.0],
            "MACD_Hist": [-26.7168, -26.5211],
            "MACD": [-2.7679, -9.2025],
            "MACD_Signal": [23.9489, 17.3186],
        }
    )
    st = MACDPreCross2BarMinHistDeltaNorm0005Entry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.HOLD
    assert "Histogram rise is too small" in sig.reasons


def test_min_hist_delta_norm_allows_meaningful_histogram_rise():
    df = pd.DataFrame(
        {
            "Close": [1215.0, 1251.0],
            "MACD_Hist": [-6.0958, -0.6892],
            "MACD": [-41.3630, -36.1287],
            "MACD_Signal": [-35.2672, -35.4395],
        }
    )
    st = MACDPreCross2BarMinHistDeltaNorm0005Entry()

    sig = st.generate_entry_signal(_mk_market_data(df))

    assert sig.action == SignalAction.BUY
    assert "Histogram rise >= 0.0005" in sig.reasons


def test_precomputed_signals_match_incremental_generate_buy_rows():
    df = pd.DataFrame(
        {
            "Close": [100.0, 102.0, 104.0, 103.0, 105.0],
            "MACD_Hist": [-0.50, -0.20, -0.08, -0.12, -0.04],
            "MACD": [-0.60, -0.35, -0.18, -0.20, -0.10],
            "MACD_Signal": [-0.55, -0.32, -0.16, -0.18, -0.08],
        },
        index=pd.bdate_range("2026-01-05", periods=5),
    )
    incremental = MACDPreCross2BarMinHistDeltaNorm0005Entry()
    generated: dict[int, object] = {}
    for row_pos in range(len(df)):
        signal = incremental.generate_entry_signal(_mk_market_data(df.iloc[: row_pos + 1]))
        if signal.action == SignalAction.BUY:
            generated[row_pos] = signal

    batch = MACDPreCross2BarMinHistDeltaNorm0005Entry()
    precomputed = batch.precompute_entry_signals(ticker="0000", features=df)

    assert set(precomputed) == set(generated)
    for row_pos, signal in generated.items():
        batch_signal = precomputed[row_pos]
        assert batch_signal.confidence == signal.confidence
        assert batch_signal.reasons == signal.reasons
        assert batch_signal.metadata["entry_stage"] == signal.metadata["entry_stage"]
        assert batch_signal.metadata["buy_signal_streak_days"] == signal.metadata["buy_signal_streak_days"]
        assert batch_signal.metadata["hist_delta_norm"] == signal.metadata["hist_delta_norm"]


def test_latest_precross_flags_match_batch_flags_for_latest_row():
    df = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0, 103.0],
            "MACD_Hist": [-0.40, -0.22, -0.10, -0.04],
            "EMA_20": [98.0, 99.0, 100.0, 101.0],
            "EMA_200": [95.0, 95.0, 95.0, 95.0],
            "Return_5d": [0.01, 0.02, 0.03, 0.04],
            "ADX_14": [9.0, 10.0, 11.0, 12.0],
            "Volume": [1000.0, 1100.0, 1200.0, 1300.0],
            "Volume_SMA_20": [1000.0, 1000.0, 1000.0, 1000.0],
        }
    )

    batch_flags = build_precross_momentum_flags(
        df,
        hist_rise_days=3,
        price_rise_days=3,
        require_hist_below_zero=True,
        max_hist_abs_norm=0.01,
        require_above_ema200=True,
        require_peak_at_window_start=True,
        max_gap_above_ema20_pct=5.0,
        max_return_5d=0.08,
        min_adx_14=10.0,
        max_bias_pct=15.0,
    ).iloc[-1]

    latest_flags = _latest_precross_momentum_flags(
        df,
        hist_rise_days=3,
        price_rise_days=3,
        require_hist_below_zero=True,
        max_hist_abs_norm=0.01,
        require_above_ema200=True,
        require_peak_at_window_start=True,
        max_gap_above_ema20_pct=5.0,
        max_return_5d=0.08,
        min_adx_14=10.0,
        max_bias_pct=15.0,
    )

    for key in [
        "hist_rising",
        "price_rising",
        "peak_at_window_start",
        "hist_below_zero",
        "near_zero_ok",
        "hist_delta_ok",
        "above_ema200",
        "gap_above_ema20_ok",
        "return_5d_ok",
        "adx_ok",
        "bias_ok",
        "peak_ok",
        "signal",
    ]:
        assert bool(latest_flags[key]) == bool(batch_flags[key])


def test_latest_precross_flags_respect_peak_check_across_longer_negative_segment():
    df = pd.DataFrame(
        {
            "Close": [99.0, 100.0, 101.0, 102.0],
            "MACD_Hist": [-0.70, -0.50, -0.30, -0.10],
            "MACD": [-0.9, -0.7, -0.5, -0.3],
            "MACD_Signal": [-0.8, -0.6, -0.4, -0.25],
        }
    )

    batch_flags = build_precross_momentum_flags(
        df,
        hist_rise_days=3,
        price_rise_days=3,
        require_peak_at_window_start=True,
    ).iloc[-1]
    latest_flags = _latest_precross_momentum_flags(
        df,
        hist_rise_days=3,
        price_rise_days=3,
        require_peak_at_window_start=True,
    )

    assert bool(latest_flags["peak_at_window_start"]) is False
    assert bool(latest_flags["peak_at_window_start"]) == bool(batch_flags["peak_at_window_start"])
    assert bool(latest_flags["signal"]) == bool(batch_flags["signal"])
