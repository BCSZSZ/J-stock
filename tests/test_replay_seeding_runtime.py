from pathlib import Path
from types import SimpleNamespace

import json
import pandas as pd
import pytest

from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.backtest.portfolio import Portfolio, Position as BacktestPosition
from src.data.stock_data_manager import StockDataManager
from src.evaluation.replay_seed import (
    ReplayPendingOrder,
    ReplaySeed,
    ReplaySeedPosition,
    build_replay_pending_signal,
)
from src.evaluation.strategy_evaluator import StrategyEvaluator


def _seed_position() -> ReplaySeedPosition:
    return ReplaySeedPosition(
        ticker="3778",
        quantity=500,
        entry_price=3_095.0,
        entry_date="2026-05-15",
        entry_score=88.0,
        peak_price=3_150.0,
        signal_entry_price=3_060.0,
        report_close_price=3_060.0,
    )


def _seed() -> ReplaySeed:
    return ReplaySeed(
        report_file="report.md",
        report_date="2026-05-15",
        replay_start_date="2026-05-18",
        group_id="group_main",
        group_name="Main",
        starting_cash_jpy=1_759_670.0,
        baseline_total_equity_jpy=9_103_270.0,
        positions=(_seed_position(),),
        prior_signal_file="signals_2026-05-15.json",
        pending_orders=(
            ReplayPendingOrder(
                group_id="group_main",
                signal_date="2026-05-15",
                signal_type="BUY",
                action="BUY",
                ticker="2768",
                planned_quantity=100,
                position_quantity=None,
                sell_percentage=None,
                current_price=1_000.0,
                planned_price=1_020.0,
                required_capital=100_000.0,
                confidence=0.66,
                score=10.0,
                reason="seeded",
                strategy_name="ReplayEntry",
                signal_payload={"is_executable": True},
            ),
        ),
    )


def test_portfolio_restore_position_preserves_cash() -> None:
    portfolio = Portfolio(starting_cash=1_759_670.0, max_positions=7, max_position_pct=0.18)
    restored = portfolio.restore_position(
        BacktestPosition(
            ticker="3778",
            quantity=500,
            entry_price=3_095.0,
            signal_entry_price=3_060.0,
            entry_date=Path("2026-05-15"),
            entry_signal=TradingSignal(
                action=SignalAction.BUY,
                confidence=0.0,
                reasons=["seed"],
                metadata={"score": 88.0},
                strategy_name="Replay",
            ),
            peak_price_since_entry=3_150.0,
        )
    )

    assert restored is True
    assert portfolio.cash == pytest.approx(1_759_670.0)
    assert portfolio.positions["3778"].quantity == 500


def test_strategy_evaluator_merges_seeded_tickers_into_monitor_list(
    tmp_path: Path,
) -> None:
    monitor_file = tmp_path / "monitor.json"
    monitor_file.write_text(
        json.dumps({"tickers": ["2768", "3778"]}),
        encoding="utf-8",
    )

    evaluator = StrategyEvaluator(
        monitor_list_file=str(monitor_file),
        replay_seed=_seed(),
    )

    assert evaluator._load_monitor_list() == ["2768", "3778"]


def test_portfolio_engine_executes_replay_pending_orders_on_day_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_date = pd.Timestamp("2026-05-18")

    def _make_data(open_price: float, close_price: float) -> dict:
        features = pd.DataFrame(
            {"Open": [open_price], "Close": [close_price]},
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

    all_data = {
        "3778": _make_data(open_price=90.0, close_price=90.0),
        "2768": _make_data(open_price=100.0, close_price=100.0),
    }

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
        lambda *args, **kwargs: TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["hold"],
            metadata={},
            strategy_name="Hold",
        ),
    )

    seeded_position = BacktestPosition(
        ticker="3778",
        quantity=500,
        entry_price=100.0,
        signal_entry_price=100.0,
        entry_date=pd.Timestamp("2026-05-15"),
        entry_signal=TradingSignal(
            action=SignalAction.BUY,
            confidence=0.0,
            reasons=["seed"],
            metadata={"score": 88.0},
            strategy_name="Replay",
        ),
        peak_price_since_entry=100.0,
    )
    pending_buy = build_replay_pending_signal(
        ReplayPendingOrder(
            group_id="group_main",
            signal_date="2026-05-15",
            signal_type="BUY",
            action="BUY",
            ticker="2768",
            planned_quantity=200,
            position_quantity=None,
            sell_percentage=None,
            current_price=95.0,
            planned_price=96.9,
            required_capital=19_000.0,
            confidence=0.66,
            score=12.0,
            reason="buy pending",
            strategy_name="ReplayEntry",
            signal_payload={"is_executable": True},
        ),
        priority=0,
    )
    pending_sell = build_replay_pending_signal(
        ReplayPendingOrder(
            group_id="group_main",
            signal_date="2026-05-15",
            signal_type="SELL",
            action="SELL_100%",
            ticker="3778",
            planned_quantity=500,
            position_quantity=500,
            sell_percentage=1.0,
            current_price=90.0,
            planned_price=None,
            required_capital=None,
            confidence=1.0,
            score=0.0,
            reason="sell pending",
            strategy_name="ReplayExit",
            signal_payload={"is_executable": True},
        ),
        priority=1,
    )

    engine = PortfolioBacktestEngine(
        starting_capital=51_000.0,
        initial_cash=1_000.0,
        seeded_positions=[seeded_position],
        initial_pending_buy_signals={"2768": pending_buy},
        initial_pending_sell_signals={"3778": pending_sell},
    )

    result = engine.backtest_portfolio_strategy(
        tickers=["3778", "2768"],
        entry_strategy=SimpleNamespace(strategy_name="Entry"),
        exit_strategy=SimpleNamespace(strategy_name="Exit"),
        start_date="2026-05-18",
        end_date="2026-05-18",
        show_signal_ranking=False,
        show_signal_details=False,
        compute_benchmark=False,
    )

    assert len(result.trades) == 1
    assert result.trades[0].ticker == "3778"
    assert result.trades[0].shares == 500
    assert len(engine.last_execution_events) == 2
    assert [event["executed_action"] for event in engine.last_execution_events] == [
        "SELL",
        "BUY",
    ]
    assert engine.last_final_cash_jpy == pytest.approx(26_000.0)
    assert len(engine.last_final_open_positions) == 1
    assert engine.last_final_open_positions[0].ticker == "2768"
    assert engine.last_final_open_positions[0].quantity == 200


def test_strategy_evaluator_emits_last_day_production_style_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_date = "2026-05-18"

    def _features(close_price: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Date": pd.to_datetime([report_date]),
                "Open": [close_price],
                "Close": [close_price],
            }
        )

    feature_map = {
        "3778": _features(90.0),
        "2768": _features(100.0),
    }
    metadata_map = {
        "3778": {"company_name": "Seed Sell"},
        "2768": {"company_name": "Seed Buy"},
    }

    monkeypatch.setattr(
        StrategyEvaluator,
        "_get_portfolio_limits",
        lambda self: (5, 0.30),
    )
    monkeypatch.setattr(
        StrategyEvaluator,
        "_load_replay_report_runtime_config",
        staticmethod(
            lambda: {
                "production": {
                    "report_buy_price_buffer_pct": 0.02,
                    "report_sell_price_buffer_pct": 0.02,
                }
            }
        ),
    )
    monkeypatch.setattr(
        StockDataManager,
        "load_stock_features",
        lambda self, ticker: feature_map[ticker],
    )
    monkeypatch.setattr(
        StockDataManager,
        "load_metadata",
        lambda self, ticker: metadata_map.get(ticker, {}),
    )

    evaluator = StrategyEvaluator(
        output_dir=str(tmp_path),
        replay_seed=_seed(),
        portfolio_overrides={"position_sizing_mode": "fixed"},
    )
    evaluator.replay_run_snapshots = [
        {
            "period": "replay",
            "start_date": report_date,
            "end_date": report_date,
            "entry_strategy": "EntryStrategy",
            "exit_strategy": "ExitStrategy",
            "entry_filter": "off",
            "ranking_strategy": "default",
            "starting_cash_jpy": 1_759_670.0,
            "baseline_total_equity_jpy": 50_000.0,
            "initial_pending_orders": [],
            "executed_orders": [],
            "next_pending_buy_signals": [
                {
                    "ticker": "2768",
                    "action": "BUY",
                    "confidence": 0.75,
                    "reasons": ["breakout"],
                    "strategy_name": "EntryStrategy",
                    "metadata": {"score": 88.0},
                }
            ],
            "next_pending_sell_signals": [
                {
                    "ticker": "3778",
                    "action": "SELL",
                    "confidence": 1.0,
                    "reasons": ["stop"],
                    "strategy_name": "ExitStrategy",
                    "metadata": {"trigger": "STOP", "sell_percentage": 1.0},
                }
            ],
            "final_cash_jpy": 5_000.0,
            "final_open_positions": [
                {
                    "ticker": "3778",
                    "quantity": 500,
                    "entry_price": 100.0,
                    "signal_entry_price": 100.0,
                    "peak_price": 100.0,
                    "entry_date": "2026-05-15",
                    "current_price": 90.0,
                    "market_value": 45_000.0,
                }
            ],
        }
    ]

    artifact = evaluator._build_replay_last_day_production_style_artifact(
        prefix="replay_eval",
        timestamp="20260520_000000",
    )

    assert artifact is not None
    assert Path(artifact["report_file"]).exists()
    assert str(Path(artifact["report_file"]).parent) == str(tmp_path)

    signals = artifact["signals"]
    buy_signal = next(signal for signal in signals if signal["ticker"] == "2768")
    sell_signal = next(signal for signal in signals if signal["ticker"] == "3778")
    assert buy_signal["suggested_qty"] == 100
    assert buy_signal["required_capital"] == pytest.approx(10_200.0)
    assert sell_signal["planned_sell_qty"] == 500

    report_text = Path(artifact["report_file"]).read_text(encoding="utf-8")
    assert "Daily Trading Report" in report_text
    assert "2768" in report_text
    assert "3778" in report_text