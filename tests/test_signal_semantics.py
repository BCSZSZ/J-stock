from src.cli.production_daily import (
    _apply_signal_semantic_metadata,
    _derive_signal_semantic_metadata,
)
from src.production.signal_generator import Signal


def test_signal_semantics_for_executable_buy() -> None:
    signal = Signal(
        group_id="core",
        ticker="8306",
        ticker_name="MUFG",
        signal_type="BUY",
        action="BUY",
        confidence=0.66,
        score=0.0,
        reason="momentum buy",
        current_price=1000.0,
        suggested_qty=100,
        required_capital=100000.0,
        rank=2,
        rank_score=3.14,
        strategy_name="MACDPreCross2BarEntry",
    )

    semantics = _derive_signal_semantic_metadata(signal)

    assert semantics.momentum_rank == 2
    assert semantics.momentum_value == 3.14
    assert semantics.is_executable is True
    assert semantics.is_executable_buy is True
    assert semantics.is_executable_sell is False


def test_signal_semantics_for_partial_sell() -> None:
    signal = Signal(
        group_id="core",
        ticker="7974",
        ticker_name="Nintendo",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.0,
        score=0.0,
        reason="trim",
        current_price=5000.0,
        position_qty=200,
        planned_sell_qty=100,
        planned_sell_value=500000.0,
        strategy_name="LayeredExit",
    )

    enriched = _apply_signal_semantic_metadata([signal])[0]

    assert enriched.momentum_rank is None
    assert enriched.momentum_value is None
    assert enriched.is_executable is True
    assert enriched.is_executable_buy is False
    assert enriched.is_executable_sell is True