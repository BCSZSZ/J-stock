import pandas as pd
import pytest

from src.backtest.entry_reference import (
    normalize_entry_reference_mode,
    resolve_signal_entry_price,
)
from src.backtest.engine import BacktestEngine
from src.backtest.fill_buffer import (
    apply_buy_fill_buffer,
    apply_sell_fill_buffer,
    normalize_fill_buffer_pct,
)
from src.backtest.portfolio_engine import PortfolioBacktestEngine


def test_fill_buffer_helpers_adjust_buy_and_sell_prices() -> None:
    assert apply_buy_fill_buffer(100.0, enabled=True, fill_buffer_pct=0.02) == 102.0
    assert apply_sell_fill_buffer(100.0, enabled=True, fill_buffer_pct=0.02) == 98.0


def test_fill_buffer_helpers_skip_adjustment_when_disabled() -> None:
    assert apply_buy_fill_buffer(100.0, enabled=False, fill_buffer_pct=0.02) == 100.0
    assert apply_sell_fill_buffer(100.0, enabled=False, fill_buffer_pct=0.02) == 100.0


@pytest.mark.parametrize("invalid_pct", [-0.01, 1.0, 1.2, "oops"])
def test_normalize_fill_buffer_pct_rejects_invalid_values(invalid_pct) -> None:
    with pytest.raises(ValueError):
        normalize_fill_buffer_pct(invalid_pct)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_mode", ["open", "buffer", "oops"])
def test_normalize_entry_reference_mode_rejects_invalid_values(invalid_mode) -> None:
    with pytest.raises(ValueError):
        normalize_entry_reference_mode(invalid_mode)


def test_entry_reference_helper_switches_between_raw_and_buffered_fill() -> None:
    assert resolve_signal_entry_price(100.0, 102.0, "raw_fill") == 100.0
    assert resolve_signal_entry_price(100.0, 102.0, "buffered_fill") == 102.0


def test_single_stock_engine_applies_fill_buffer_to_open_prices() -> None:
    engine = BacktestEngine(fill_buffer_enabled=True, fill_buffer_pct=0.02)

    assert engine._apply_buy_fill_buffer(100.0) == 102.0
    assert engine._apply_sell_fill_buffer(100.0) == 98.0


def test_single_stock_engine_can_use_buffered_entry_reference_price() -> None:
    engine = BacktestEngine(
        fill_buffer_enabled=True,
        fill_buffer_pct=0.02,
        entry_reference_mode="buffered_fill",
    )

    assert engine._resolve_signal_entry_price(100.0, 102.0) == 102.0


def test_portfolio_engine_applies_fill_buffer_to_buy_and_sell_fills() -> None:
    engine = PortfolioBacktestEngine(
        starting_capital=1_000_000,
        buy_fill_mode="next_open",
        fill_buffer_enabled=True,
        fill_buffer_pct=0.02,
    )
    current_date = pd.Timestamp("2024-01-05")
    features = pd.DataFrame(
        {"Open": [100.0], "Close": [101.0]},
        index=[current_date],
    )
    data = {
        "features": features,
        "date_pos_map": {current_date: 0},
        "open_col_pos": features.columns.get_loc("Open"),
        "close_col_pos": features.columns.get_loc("Close"),
    }

    assert engine._get_buy_fill_price(data, current_date) == 102.0
    assert engine._get_sell_fill_price(data, current_date) == 98.0


def test_portfolio_engine_respects_next_close_before_buffer() -> None:
    engine = PortfolioBacktestEngine(
        starting_capital=1_000_000,
        buy_fill_mode="next_close",
        fill_buffer_enabled=True,
        fill_buffer_pct=0.02,
    )
    current_date = pd.Timestamp("2024-01-05")
    features = pd.DataFrame(
        {"Open": [100.0], "Close": [110.0]},
        index=[current_date],
    )
    data = {
        "features": features,
        "date_pos_map": {current_date: 0},
        "open_col_pos": features.columns.get_loc("Open"),
        "close_col_pos": features.columns.get_loc("Close"),
    }

    assert engine._get_buy_fill_price(data, current_date) == 112.2


def test_portfolio_engine_can_use_buffered_entry_reference_price() -> None:
    engine = PortfolioBacktestEngine(
        starting_capital=1_000_000,
        buy_fill_mode="next_open",
        fill_buffer_enabled=True,
        fill_buffer_pct=0.02,
        entry_reference_mode="buffered_fill",
    )

    assert engine._resolve_signal_entry_price(100.0, 102.0) == 102.0