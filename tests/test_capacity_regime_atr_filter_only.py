import pytest

from src.capacity import capacity_order_cap_applies_to_sizing, compute_order_capacity
from src.capacity.regime import CapacityTierSnapshot


def test_capacity_order_cap_applies_to_fixed_sizing() -> None:
    assert capacity_order_cap_applies_to_sizing("fixed") is True


def test_capacity_order_cap_does_not_apply_to_atr_sizing() -> None:
    assert capacity_order_cap_applies_to_sizing("atr") is False


def test_capacity_regime_still_blocks_low_turnover_candidates() -> None:
    tier = CapacityTierSnapshot(
        regime_version="test",
        effective_equity_jpy=100_000_000.0,
        tier_index=0,
        tier_name="base",
        max_positions=7,
        max_position_pct=0.18,
        participation_cap_pct=0.02,
        min_turnover_20_jpy=500_000_000.0,
    )

    decision = compute_order_capacity(
        tier=tier,
        turnover_jpy=100_000_000.0,
        available_cash_jpy=100_000_000.0,
        available_exposure_jpy=None,
    )

    assert decision.blocking_reason == "liquidity_floor"
    assert decision.order_cap_jpy == pytest.approx(2_000_000.0)
