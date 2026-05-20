from pathlib import Path

import json
import pytest

from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.portfolio import Portfolio, Position as BacktestPosition
from src.evaluation.replay_seed import ReplaySeed, ReplaySeedPosition
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