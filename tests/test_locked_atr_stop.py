import pandas as pd
import pytest

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.analysis.strategies.exit.locked_atr_stop import calculate_locked_atr_stop
from src.analysis.strategies.exit.multiview_grid_exit import (
    MultiViewWindowDecayLockedStopExit,
)
from src.backtest.portfolio import Position as BacktestPosition
from src.utils.strategy_loader import load_exit_strategy


def _entry_signal() -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["entry"],
        strategy_name="Entry",
    )


def _market_data(close_prices: list[float], atr_values: list[float]) -> MarketData:
    dates = pd.date_range("2026-01-01", periods=len(close_prices), freq="D")
    return MarketData(
        ticker="7203",
        current_date=dates[-1],
        df_features=pd.DataFrame(
            {
                "Close": close_prices,
                "ATR": atr_values,
                "MACD_Hist": [0.1 + 0.1 * idx for idx in range(len(close_prices))],
                "SMA_25": [100.0 for _ in close_prices],
            },
            index=dates,
        ),
        df_trades=pd.DataFrame(),
        df_financials=pd.DataFrame(),
        metadata={},
    )


def test_calculate_locked_atr_stop_never_widens_from_previous_stop() -> None:
    stop = calculate_locked_atr_stop(
        entry_price=100.0,
        peak_price=105.0,
        entry_atr=5.0,
        current_atr=6.0,
        initial_stop_multiple=2.0,
        trail_multiple=2.0,
        previous_stop_price=99.0,
    )

    assert stop.initial_stop_price == pytest.approx(90.0)
    assert stop.dynamic_trail_price == pytest.approx(93.0)
    assert stop.effective_stop_price == pytest.approx(99.0)


def test_locked_mvxw_initial_stop_can_trigger_before_profit() -> None:
    market_data = _market_data([100.0, 89.0], [5.0, 10.0])
    position = Position(
        ticker="7203",
        entry_price=100.0,
        entry_date=market_data.df_features.index[0],
        quantity=100,
        entry_signal=_entry_signal(),
        peak_price_since_entry=100.0,
    )
    strategy = MultiViewWindowDecayLockedStopExit(
        hist_shrink_n=1,
        r_mult=1.0,
        trail_mult=2.0,
        time_stop_days=18,
        bias_exit_threshold_pct=20.0,
        initial_stop_mult=2.0,
    )

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.SELL
    assert signal.metadata["trigger"] == "R1_LockedATRTrailing"
    assert signal.metadata["initial_stop_price"] == pytest.approx(90.0)
    assert signal.metadata["dynamic_trail_price"] == pytest.approx(80.0)
    assert signal.metadata["locked_stop_price"] == pytest.approx(90.0)
    assert position.locked_stop_price == pytest.approx(90.0)


def test_locked_mvxw_uses_previous_locked_stop_when_atr_expands() -> None:
    market_data = _market_data([100.0, 85.0], [5.0, 20.0])
    position = Position(
        ticker="7203",
        entry_price=100.0,
        entry_date=market_data.df_features.index[0],
        quantity=100,
        entry_signal=_entry_signal(),
        peak_price_since_entry=100.0,
        locked_stop_price=92.0,
    )
    strategy = MultiViewWindowDecayLockedStopExit(
        hist_shrink_n=1,
        r_mult=1.0,
        trail_mult=2.0,
        time_stop_days=18,
        bias_exit_threshold_pct=20.0,
        initial_stop_mult=2.0,
    )

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.SELL
    assert signal.metadata["locked_stop_price"] == pytest.approx(92.0)
    assert position.locked_stop_price == pytest.approx(92.0)


def test_locked_mvxw_accepts_backtest_position_instances() -> None:
    market_data = _market_data([100.0, 89.0], [5.0, 10.0])
    position = BacktestPosition(
        ticker="7203",
        entry_price=100.0,
        entry_date=market_data.df_features.index[0],
        quantity=100,
        entry_signal=_entry_signal(),
        peak_price_since_entry=100.0,
    )
    strategy = MultiViewWindowDecayLockedStopExit(
        hist_shrink_n=1,
        r_mult=1.0,
        trail_mult=2.0,
        time_stop_days=18,
        bias_exit_threshold_pct=20.0,
        initial_stop_mult=2.0,
    )

    signal = strategy.generate_exit_signal(position, market_data)

    assert signal.action == SignalAction.SELL
    assert position.entry_atr == pytest.approx(5.0)
    assert position.initial_stop_price == pytest.approx(90.0)
    assert position.locked_stop_price == pytest.approx(90.0)


def test_locked_mvxw_variants_are_loader_registered() -> None:
    strategy = load_exit_strategy("MVXWL_N5_R3p35_T1p45_D10_B20p0_I2p0")

    assert strategy.strategy_name == "MVXWL_N5_R3p35_T1p45_D10_B20p0_I2p0"
    assert isinstance(strategy, MultiViewWindowDecayLockedStopExit)
