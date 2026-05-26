import math
from dataclasses import dataclass
from statistics import median
from typing import Sequence

from src.config.capacity import CapacityRegimeConfig, CapacityTierConfig


@dataclass(frozen=True)
class CapacityTierSnapshot:
    regime_version: str
    effective_equity_jpy: float
    tier_index: int
    tier_name: str
    max_positions: int
    max_position_pct: float
    participation_cap_pct: float
    min_turnover_20_jpy: float


@dataclass(frozen=True)
class CapacityOrderDecision:
    tier: CapacityTierSnapshot
    turnover_jpy: float | None
    equity_cap_jpy: float
    turnover_cap_jpy: float | None
    cash_cap_jpy: float
    exposure_cap_jpy: float | None
    order_cap_jpy: float
    participation_pct: float | None
    blocking_reason: str | None
    is_trimmed: bool


def capacity_mode_enabled(mode: str, regime: CapacityRegimeConfig | None) -> bool:
    return regime is not None and str(mode).lower() == "enforce"


def capacity_order_cap_applies_to_sizing(position_sizing_mode: str) -> bool:
    return str(position_sizing_mode or "fixed").strip().lower() != "atr"


def _resolve_tier(
    regime: CapacityRegimeConfig, effective_equity_jpy: float
) -> tuple[int, CapacityTierConfig]:
    for index, tier in enumerate(regime.tiers):
        if tier.max_equity_jpy is None or effective_equity_jpy <= tier.max_equity_jpy:
            return index, tier
    return len(regime.tiers) - 1, regime.tiers[-1]


def resolve_capacity_tier(
    regime: CapacityRegimeConfig,
    equity_history_jpy: Sequence[float],
    observed_equity_jpy: float,
) -> CapacityTierSnapshot:
    window_size = max(1, int(regime.equity_window_days))
    samples = [float(value) for value in equity_history_jpy if float(value) > 0.0]
    samples.append(float(observed_equity_jpy))
    window = samples[-window_size:] if len(samples) > window_size else samples
    effective_equity_jpy = float(median(window)) if window else float(observed_equity_jpy)

    tier_index, tier = _resolve_tier(regime, effective_equity_jpy)
    return CapacityTierSnapshot(
        regime_version=regime.version,
        effective_equity_jpy=effective_equity_jpy,
        tier_index=tier_index,
        tier_name=tier.name,
        max_positions=tier.max_positions,
        max_position_pct=tier.max_position_pct,
        participation_cap_pct=tier.participation_cap_pct,
        min_turnover_20_jpy=tier.min_turnover_20_jpy,
    )


def compute_order_capacity(
    tier: CapacityTierSnapshot,
    turnover_jpy: float | None,
    available_cash_jpy: float,
    available_exposure_jpy: float | None,
    signal_scale: float = 1.0,
) -> CapacityOrderDecision:
    scale = max(float(signal_scale), 0.0)
    equity_cap_jpy = max(tier.effective_equity_jpy * tier.max_position_pct * scale, 0.0)
    cash_cap_jpy = max(float(available_cash_jpy), 0.0)
    exposure_cap_jpy = (
        max(float(available_exposure_jpy), 0.0)
        if available_exposure_jpy is not None
        else None
    )

    turnover_cap_jpy: float | None = None
    blocking_reason: str | None = None

    if turnover_jpy is None or math.isnan(turnover_jpy) or turnover_jpy <= 0.0:
        blocking_reason = "missing_turnover"
    else:
        turnover_value = float(turnover_jpy)
        turnover_cap_jpy = max(turnover_value * tier.participation_cap_pct * scale, 0.0)
        if turnover_value < tier.min_turnover_20_jpy:
            blocking_reason = "liquidity_floor"

    cap_candidates = [equity_cap_jpy, cash_cap_jpy]
    if turnover_cap_jpy is not None:
        cap_candidates.append(turnover_cap_jpy)
    if exposure_cap_jpy is not None:
        cap_candidates.append(exposure_cap_jpy)

    order_cap_jpy = min(cap_candidates) if cap_candidates else 0.0

    if blocking_reason is None and cash_cap_jpy <= 0.0:
        blocking_reason = "cash"
    if blocking_reason is None and exposure_cap_jpy is not None and exposure_cap_jpy <= 0.0:
        blocking_reason = "overlay_exposure"
    if blocking_reason is None and order_cap_jpy <= 0.0:
        blocking_reason = "order_cap_zero"

    participation_pct = (
        order_cap_jpy / float(turnover_jpy)
        if turnover_jpy is not None and turnover_jpy > 0.0 and order_cap_jpy > 0.0
        else None
    )
    trim_candidates = [cash_cap_jpy]
    if turnover_cap_jpy is not None:
        trim_candidates.append(turnover_cap_jpy)
    if exposure_cap_jpy is not None:
        trim_candidates.append(exposure_cap_jpy)
    external_cap = min(trim_candidates) if trim_candidates else equity_cap_jpy
    is_trimmed = order_cap_jpy > 0.0 and external_cap + 1e-9 < equity_cap_jpy

    return CapacityOrderDecision(
        tier=tier,
        turnover_jpy=turnover_jpy,
        equity_cap_jpy=equity_cap_jpy,
        turnover_cap_jpy=turnover_cap_jpy,
        cash_cap_jpy=cash_cap_jpy,
        exposure_cap_jpy=exposure_cap_jpy,
        order_cap_jpy=order_cap_jpy,
        participation_pct=participation_pct,
        blocking_reason=blocking_reason,
        is_trimmed=is_trimmed,
    )