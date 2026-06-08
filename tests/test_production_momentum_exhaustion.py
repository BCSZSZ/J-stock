from __future__ import annotations

from src.cli.production_daily import _apply_momentum_exhaustion_to_signal
from src.production.signal_generator import Signal
from src.utils.momentum_exhaustion import (
    MomentumExhaustionConfig,
    evaluate_momentum_exhaustion,
)


def _buy_signal() -> Signal:
    return Signal(
        group_id="group_main",
        ticker="7203",
        ticker_name="Toyota",
        signal_type="BUY",
        action="BUY",
        confidence=0.8,
        score=70.0,
        reason="buy",
        current_price=3000.0,
        rank=1,
        rank_score=5.0,
    )


def test_production_momentum_exhaustion_shadow_marks_without_filtering() -> None:
    signal = _buy_signal()
    decision = evaluate_momentum_exhaustion(
        signal.rank_score,
        MomentumExhaustionConfig(mode="shadow", max_score=4.0),
    )

    _apply_momentum_exhaustion_to_signal(signal, decision)

    assert signal.momentum_exhaustion_blocked is True
    assert signal.momentum_exhaustion_filtered is False
    assert signal.signal_metadata["momentum_exhaustion_blocked"] is True
    assert "Shadow blocked" in signal.reason


def test_production_momentum_exhaustion_enforce_marks_filtered() -> None:
    signal = _buy_signal()
    decision = evaluate_momentum_exhaustion(
        signal.rank_score,
        MomentumExhaustionConfig(mode="enforce", max_score=4.0),
    )

    _apply_momentum_exhaustion_to_signal(signal, decision)

    assert signal.momentum_exhaustion_blocked is True
    assert signal.momentum_exhaustion_filtered is True
    assert signal.signal_metadata["momentum_exhaustion_filtered"] is True
    assert "Filtered" in signal.reason
