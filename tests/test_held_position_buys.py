from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.portfolio import Portfolio, Position
from src.backtest.portfolio_engine import PortfolioBacktestEngine


def _make_data(current_date: pd.Timestamp, price: float) -> dict:
    features = pd.DataFrame(
        {"Open": [price], "Close": [price]},
        index=pd.to_datetime([current_date]),
    )
    return {
        "features": features,
        "date_pos_map": {current_date: 0},
        "open_col_pos": 0,
        "close_col_pos": 1,
        "trades": pd.DataFrame(),
        "trade_dates": None,
        "financials": pd.DataFrame(),
        "financial_dates": None,
        "metadata": {},
    }


def _seeded_position(ticker: str = "7203") -> Position:
    return Position(
        ticker=ticker,
        quantity=100,
        entry_price=100.0,
        signal_entry_price=100.0,
        entry_date=pd.Timestamp("2026-05-15"),
        entry_signal=TradingSignal(
            action=SignalAction.BUY,
            confidence=0.8,
            reasons=["seed"],
            metadata={"score": 80.0},
            strategy_name="SeedEntry",
        ),
        peak_price_since_entry=100.0,
    )


def _buy_signal(score: float = 80.0) -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.9,
        reasons=["buy"],
        metadata={"score": score},
        strategy_name="Entry",
    )


def _sell_signal() -> TradingSignal:
    return TradingSignal(
        action=SignalAction.SELL,
        confidence=1.0,
        reasons=["sell"],
        metadata={"trigger": "test_exit"},
        strategy_name="Exit",
    )


def _patch_engine_data(
    monkeypatch: pytest.MonkeyPatch,
    all_data: dict[str, dict],
    generated_signal: TradingSignal | None = None,
) -> None:
    monkeypatch.setattr(
        PortfolioBacktestEngine,
        "_resolve_data_requirements",
        lambda self, entry_strategy, exit_strategy: (False, False, False),
    )
    monkeypatch.setattr(
        PortfolioBacktestEngine,
        "_load_stock_data",
        lambda self, ticker, **kwargs: all_data[ticker],
    )
    monkeypatch.setattr(
        "src.backtest.portfolio_engine.generate_signal_v2",
        lambda *args, **kwargs: generated_signal
        if "position" not in kwargs and generated_signal is not None
        else TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["hold"],
            metadata={},
            strategy_name="Hold",
        ),
    )


def _run_engine(engine: PortfolioBacktestEngine, tickers: list[str]) -> None:
    engine.backtest_portfolio_strategy(
        tickers=tickers,
        entry_strategy=SimpleNamespace(strategy_name="Entry"),
        exit_strategy=SimpleNamespace(strategy_name="Exit"),
        start_date="2026-05-18",
        end_date="2026-05-18",
        show_signal_ranking=False,
        show_signal_details=False,
        compute_benchmark=False,
    )


def test_held_position_buy_signals_are_generated_only_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = pd.Timestamp("2026-05-18")
    all_data = {"7203": _make_data(current_date, 100.0)}
    _patch_engine_data(monkeypatch, all_data, generated_signal=_buy_signal())

    disabled = PortfolioBacktestEngine(
        starting_capital=110_000.0,
        initial_cash=100_000.0,
        seeded_positions=[_seeded_position()],
        allow_held_position_buys=False,
    )
    _run_engine(disabled, ["7203"])

    enabled = PortfolioBacktestEngine(
        starting_capital=110_000.0,
        initial_cash=100_000.0,
        seeded_positions=[_seeded_position()],
        allow_held_position_buys=True,
    )
    _run_engine(enabled, ["7203"])

    assert disabled.last_pending_buy_signals == {}
    assert "7203" in enabled.last_pending_buy_signals
    assert enabled.last_pending_buy_signals["7203"].metadata["is_add_on_buy"] is True


def test_portfolio_increase_position_updates_weighted_entry_prices() -> None:
    portfolio = Portfolio(starting_cash=50_000.0)
    assert portfolio.add_position(_seeded_position("7203")) is True

    added = Position(
        ticker="7203",
        quantity=100,
        entry_price=120.0,
        signal_entry_price=110.0,
        entry_date=pd.Timestamp("2026-05-18"),
        entry_signal=_buy_signal(score=90.0),
        peak_price_since_entry=110.0,
    )

    assert portfolio.increase_position(added) is True
    position = portfolio.positions["7203"]
    assert position.quantity == 200
    assert position.entry_price == pytest.approx(110.0)
    assert position.signal_entry_price == pytest.approx(105.0)
    assert position.peak_price_since_entry == pytest.approx(110.0)
    assert portfolio.cash == pytest.approx(28_000.0)


def test_add_on_buy_can_execute_when_new_positions_are_full(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = pd.Timestamp("2026-05-18")
    all_data = {
        "7203": _make_data(current_date, 100.0),
        "8306": _make_data(current_date, 100.0),
    }
    _patch_engine_data(monkeypatch, all_data)

    engine = PortfolioBacktestEngine(
        starting_capital=110_000.0,
        initial_cash=100_000.0,
        seeded_positions=[_seeded_position("7203")],
        initial_pending_buy_signals={
            "8306": _buy_signal(score=100.0),
            "7203": _buy_signal(score=80.0),
        },
        max_positions=1,
        max_position_pct=0.30,
        allow_held_position_buys=True,
    )

    _run_engine(engine, ["7203", "8306"])

    assert len(engine.last_final_open_positions) == 1
    assert engine.last_final_open_positions[0].ticker == "7203"
    assert engine.last_final_open_positions[0].quantity == 300
    assert [event["ticker"] for event in engine.last_execution_events] == ["7203"]


def test_same_ticker_sell_is_cancelled_only_after_add_on_buy_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = pd.Timestamp("2026-05-18")
    all_data = {"7203": _make_data(current_date, 100.0)}
    _patch_engine_data(monkeypatch, all_data)

    engine = PortfolioBacktestEngine(
        starting_capital=110_000.0,
        initial_cash=100_000.0,
        seeded_positions=[_seeded_position("7203")],
        initial_pending_buy_signals={"7203": _buy_signal()},
        initial_pending_sell_signals={"7203": _sell_signal()},
        max_positions=1,
        max_position_pct=0.30,
        allow_held_position_buys=True,
    )

    result = engine.backtest_portfolio_strategy(
        tickers=["7203"],
        entry_strategy=SimpleNamespace(strategy_name="Entry"),
        exit_strategy=SimpleNamespace(strategy_name="Exit"),
        start_date="2026-05-18",
        end_date="2026-05-18",
        show_signal_ranking=False,
        show_signal_details=False,
        compute_benchmark=False,
    )

    assert result.trades == []
    assert [event["executed_action"] for event in engine.last_execution_events] == [
        "BUY"
    ]
    assert engine.last_final_open_positions[0].quantity == 300


def test_same_ticker_sell_still_executes_when_add_on_buy_has_no_cash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = pd.Timestamp("2026-05-18")
    all_data = {"7203": _make_data(current_date, 100.0)}
    _patch_engine_data(monkeypatch, all_data)

    engine = PortfolioBacktestEngine(
        starting_capital=10_000.0,
        initial_cash=0.0,
        seeded_positions=[_seeded_position("7203")],
        initial_pending_buy_signals={"7203": _buy_signal()},
        initial_pending_sell_signals={"7203": _sell_signal()},
        max_positions=1,
        max_position_pct=2.0,
        allow_held_position_buys=True,
    )

    result = engine.backtest_portfolio_strategy(
        tickers=["7203"],
        entry_strategy=SimpleNamespace(strategy_name="Entry"),
        exit_strategy=SimpleNamespace(strategy_name="Exit"),
        start_date="2026-05-18",
        end_date="2026-05-18",
        show_signal_ranking=False,
        show_signal_details=False,
        compute_benchmark=False,
    )

    assert len(result.trades) == 1
    assert result.trades[0].ticker == "7203"
    assert [event["executed_action"] for event in engine.last_execution_events] == [
        "SELL"
    ]
    assert engine.last_final_open_positions == []
