"""Reusable crossover helpers for entry strategies."""

from __future__ import annotations

import math


def safe_float(value: object) -> float | None:
    """Return a finite float or None for missing/unusable values."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def crossed_up(
    fast_prev: object,
    slow_prev: object,
    fast_now: object,
    slow_now: object,
) -> bool:
    """Return True when the fast line crosses up through the slow line."""
    fast_prev_float = safe_float(fast_prev)
    slow_prev_float = safe_float(slow_prev)
    fast_now_float = safe_float(fast_now)
    slow_now_float = safe_float(slow_now)
    if (
        fast_prev_float is None
        or slow_prev_float is None
        or fast_now_float is None
        or slow_now_float is None
    ):
        return False
    return fast_prev_float <= slow_prev_float and fast_now_float > slow_now_float


def gt_latest(left: object, right: object) -> bool:
    """Return True when both latest values are finite and left > right."""
    left_float = safe_float(left)
    right_float = safe_float(right)
    if left_float is None or right_float is None:
        return False
    return left_float > right_float


def volume_ratio(volume: object, average_volume: object) -> float | None:
    """Return volume / average_volume when both values are usable."""
    volume_float = safe_float(volume)
    average_float = safe_float(average_volume)
    if volume_float is None or average_float is None or average_float <= 0:
        return None
    return volume_float / average_float


def volume_ratio_ok(
    volume: object,
    average_volume: object,
    multiplier: float,
) -> bool:
    """Return True when volume is at least multiplier times average volume."""
    ratio = volume_ratio(volume, average_volume)
    return ratio is not None and ratio >= float(multiplier)


def rsi_not_overheated(rsi: object, max_rsi: float) -> bool:
    """Return True when RSI is finite and below the configured overheat cap."""
    rsi_float = safe_float(rsi)
    return rsi_float is not None and rsi_float < float(max_rsi)


def macd_position_ok(
    macd: object,
    macd_signal: object | None = None,
    *,
    mode: str = "any",
    near_zero_abs: float = 0.02,
) -> bool:
    """Validate MACD's zero-axis position.

    Modes:
    - any: finite MACD is enough.
    - near_zero: MACD and signal must be no lower than -near_zero_abs.
    - above_zero: MACD must be above zero.
    """
    normalized = str(mode).strip().lower()
    if normalized not in {"any", "near_zero", "above_zero"}:
        raise ValueError(f"Unsupported MACD position mode: {mode}")

    macd_float = safe_float(macd)
    if macd_float is None:
        return False

    if normalized == "any":
        return True
    if normalized == "above_zero":
        return macd_float > 0.0

    signal_float = safe_float(macd_signal)
    if signal_float is None:
        return macd_float >= -abs(float(near_zero_abs))
    floor = -abs(float(near_zero_abs))
    return macd_float >= floor and signal_float >= floor
