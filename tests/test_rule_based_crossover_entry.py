import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.analysis.strategies.entry.rule_based_crossover_entry import (
    CrossReboundKDJRSIEntry,
    CrossTrendMACDVolumeEntry,
    CrossTrendMACDVolumeLooseEntry,
)
from src.utils.strategy_loader import (
    ENTRY_STRATEGIES,
    create_strategy_instance,
    entry_strategy_uses_only_feature_data,
)


def _mk_market_data(df: pd.DataFrame) -> MarketData:
    idx = pd.date_range("2026-01-01", periods=len(df), freq="B")
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


def _trend_df(**overrides) -> pd.DataFrame:
    data = {
        "Close": [20.5, 20.8],
        "SMA_20": [19.8, 20.1],
        "SMA_60": [19.2, 18.9],
        "MACD": [0.05, 0.12],
        "MACD_Signal": [0.08, 0.09],
        "Volume": [100.0, 130.0],
        "Volume_SMA_20": [100.0, 100.0],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def test_trend_macd_volume_entry_buys_when_all_rules_pass() -> None:
    signal = CrossTrendMACDVolumeEntry().generate_entry_signal(
        _mk_market_data(_trend_df())
    )

    assert signal.action == SignalAction.BUY
    assert signal.metadata["score"] == 100.0
    assert signal.metadata["failed_rule"] is None
    assert signal.metadata["rules"]["volume_confirmation"]["volume_ratio"] == 1.3


def test_trend_macd_volume_entry_blocks_trend_failure() -> None:
    signal = CrossTrendMACDVolumeEntry().generate_entry_signal(
        _mk_market_data(_trend_df(Close=[18.8, 18.7]))
    )

    assert signal.action == SignalAction.HOLD
    assert signal.metadata["failed_rule"] == "close_above_sma60"
    assert "close_above_sma60 failed" in signal.reasons[0]


def test_trend_macd_volume_entry_blocks_when_macd_does_not_cross() -> None:
    signal = CrossTrendMACDVolumeEntry().generate_entry_signal(
        _mk_market_data(_trend_df(MACD=[0.10, 0.12], MACD_Signal=[0.08, 0.09]))
    )

    assert signal.action == SignalAction.HOLD
    assert signal.metadata["failed_rule"] == "macd_golden_cross"


def test_trend_macd_volume_entry_blocks_volume_failure() -> None:
    signal = CrossTrendMACDVolumeEntry().generate_entry_signal(
        _mk_market_data(_trend_df(Volume=[100.0, 110.0]))
    )

    assert signal.action == SignalAction.HOLD
    assert signal.metadata["failed_rule"] == "volume_confirmation"


def test_trend_macd_volume_entry_blocks_below_zero_but_loose_variant_buys() -> None:
    df = _trend_df(
        MACD=[-0.05, -0.01],
        MACD_Signal=[-0.02, -0.03],
    )

    strict_signal = CrossTrendMACDVolumeEntry().generate_entry_signal(
        _mk_market_data(df)
    )
    loose_signal = CrossTrendMACDVolumeLooseEntry().generate_entry_signal(
        _mk_market_data(df)
    )

    assert strict_signal.action == SignalAction.HOLD
    assert strict_signal.metadata["failed_rule"] == "macd_position"
    assert loose_signal.action == SignalAction.BUY


def _rebound_df(rsi_latest: float = 56.0) -> pd.DataFrame:
    close = [10, 10, 10, 10, 10, 9, 9, 9, 9, 9, 20]
    return pd.DataFrame(
        {
            "Close": close,
            "KDJ_K_9": [30.0] * 9 + [22.0, 36.0],
            "KDJ_D_9": [32.0] * 9 + [28.0, 32.0],
            "RSI_9": [45.0] * 10 + [rsi_latest],
        }
    )


def test_rebound_kdj_rsi_entry_uses_rolling_ma_fallback_and_buys() -> None:
    signal = CrossReboundKDJRSIEntry().generate_entry_signal(
        _mk_market_data(_rebound_df())
    )

    assert signal.action == SignalAction.BUY
    assert signal.metadata["rules"]["sma5_cross_sma10"]["passed"] is True
    assert signal.metadata["rules"]["close_above_sma10"]["sma10"] == 10.5


def test_rebound_kdj_rsi_entry_blocks_rsi_overheat() -> None:
    signal = CrossReboundKDJRSIEntry().generate_entry_signal(
        _mk_market_data(_rebound_df(rsi_latest=80.0))
    )

    assert signal.action == SignalAction.HOLD
    assert signal.metadata["failed_rule"] == "rsi_not_overheated"


def test_rule_based_crossover_entries_are_registered() -> None:
    assert "CrossTrendMACDVolumeEntry" in ENTRY_STRATEGIES
    assert "CrossTrendMACDVolumeLooseEntry" in ENTRY_STRATEGIES
    assert "CrossReboundKDJRSIEntry" in ENTRY_STRATEGIES

    assert create_strategy_instance("CrossTrendMACDVolumeEntry", "entry") is not None
    assert create_strategy_instance("CrossTrendMACDVolumeLooseEntry", "entry") is not None
    assert create_strategy_instance("CrossReboundKDJRSIEntry", "entry") is not None
    assert entry_strategy_uses_only_feature_data("CrossTrendMACDVolumeEntry")
