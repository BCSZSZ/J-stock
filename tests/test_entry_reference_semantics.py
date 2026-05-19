import json

import pandas as pd
import pytest

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.analysis.strategies.exit.multiview_grid_exit import MultiViewCompositeExit
from src.backtest.portfolio import Position as BacktestPosition
from src.production.signal_generator import SignalGenerator
from src.production.state_manager import Position as ProductionPosition
from src.production.state_manager import ProductionState


def _build_entry_signal() -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["entry"],
        metadata={"score": 80.0},
        strategy_name="MACDPreCross2BarEntry",
    )


def _build_market_data() -> MarketData:
    dates = pd.date_range("2025-01-01", periods=4, freq="D")
    df_features = pd.DataFrame(
        {
            "Close": [1000.0, 1005.0, 1008.0, 1100.0],
            "High": [1002.0, 1007.0, 1010.0, 1102.0],
            "Low": [998.0, 1000.0, 1003.0, 1090.0],
            "ATR": [100.0, 100.0, 100.0, 100.0],
            "MACD_Hist": [0.1, 0.2, 0.1, 0.2],
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


def _build_exit_strategy() -> MultiViewCompositeExit:
    return MultiViewCompositeExit(
        hist_shrink_n=3,
        r_mult=1.0,
        trail_mult=1.3,
        time_stop_days=10,
        bias_exit_threshold_pct=20.0,
        tp1_r=1.0,
        tp2_r=2.0,
    )


def test_backtest_exit_uses_signal_entry_price_for_tp1() -> None:
    market_data = _build_market_data()
    strategy = _build_exit_strategy()
    entry_signal = _build_entry_signal()

    buffered_position = BacktestPosition(
        ticker="7203",
        quantity=100,
        entry_price=1010.0,
        signal_entry_price=1000.0,
        entry_date=market_data.df_features.index[0],
        entry_signal=entry_signal,
        peak_price_since_entry=1000.0,
    )
    legacy_position = BacktestPosition(
        ticker="7203",
        quantity=100,
        entry_price=1010.0,
        entry_date=market_data.df_features.index[0],
        entry_signal=entry_signal,
        peak_price_since_entry=1010.0,
    )

    buffered_signal = strategy.generate_exit_signal(buffered_position, market_data)
    legacy_signal = strategy.generate_exit_signal(legacy_position, market_data)

    assert buffered_signal.action == SignalAction.SELL
    assert buffered_signal.metadata["trigger"] == "P_TP1"
    assert buffered_signal.metadata["sell_percentage"] == 0.5
    assert legacy_signal.action == SignalAction.HOLD


def test_production_exit_uses_signal_entry_price_but_reports_actual_pnl(
    tmp_path,
) -> None:
    monitor_file = tmp_path / "monitor.json"
    monitor_file.write_text(json.dumps({"tickers": []}), encoding="utf-8")

    state = ProductionState(state_file=str(tmp_path / "state.json"))
    generator = SignalGenerator(
        config={"monitor_list_file": str(monitor_file)},
        data_manager=None,
        state=state,
    )
    market_data = _build_market_data()
    generator._load_market_data = lambda ticker, current_date: market_data
    strategy = _build_exit_strategy()

    buffered_position = ProductionPosition(
        ticker="7203",
        quantity=100,
        entry_price=1040.0,
        signal_entry_price=1000.0,
        entry_date="2025-01-01",
        entry_score=80.0,
        peak_price=1000.0,
    )
    legacy_position = ProductionPosition(
        ticker="7203",
        quantity=100,
        entry_price=1040.0,
        entry_date="2025-01-01",
        entry_score=80.0,
        peak_price=1040.0,
    )

    buffered_signal = generator._evaluate_exit(
        group_id="group_main",
        position=buffered_position,
        exit_strategy=strategy,
        current_date="2025-01-04",
    )
    legacy_signal = generator._evaluate_exit(
        group_id="group_main",
        position=legacy_position,
        exit_strategy=strategy,
        current_date="2025-01-04",
    )

    assert buffered_signal is not None
    assert buffered_signal.signal_type == "SELL"
    assert buffered_signal.action == "SELL_50%"
    assert buffered_signal.unrealized_pl_pct == pytest.approx(
        ((1100.0 / 1040.0) - 1.0) * 100.0
    )
    assert legacy_signal is not None
    assert legacy_signal.signal_type == "HOLD"