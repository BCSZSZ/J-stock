from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LockedAtrStopResult:
    entry_atr: float
    current_atr: float
    initial_stop_price: float
    dynamic_trail_price: float
    previous_stop_price: float | None
    effective_stop_price: float


def calculate_locked_atr_stop(
    *,
    entry_price: float,
    peak_price: float,
    entry_atr: float,
    current_atr: float,
    initial_stop_multiple: float,
    trail_multiple: float,
    previous_stop_price: float | None = None,
) -> LockedAtrStopResult:
    entry_price = float(entry_price)
    peak_price = float(peak_price)
    entry_atr = float(entry_atr)
    current_atr = float(current_atr)
    initial_stop_multiple = float(initial_stop_multiple)
    trail_multiple = float(trail_multiple)

    if entry_price <= 0 or not math.isfinite(entry_price):
        raise ValueError("entry_price must be a positive finite number")
    if peak_price <= 0 or not math.isfinite(peak_price):
        raise ValueError("peak_price must be a positive finite number")
    if entry_atr <= 0 or not math.isfinite(entry_atr):
        raise ValueError("entry_atr must be a positive finite number")
    if current_atr <= 0 or not math.isfinite(current_atr):
        raise ValueError("current_atr must be a positive finite number")
    if initial_stop_multiple <= 0 or trail_multiple <= 0:
        raise ValueError("ATR stop multiples must be positive")

    initial_stop_price = entry_price - (entry_atr * initial_stop_multiple)
    dynamic_trail_price = peak_price - (current_atr * trail_multiple)
    candidates = [initial_stop_price, dynamic_trail_price]

    normalized_previous_stop: float | None = None
    if previous_stop_price is not None:
        previous = float(previous_stop_price)
        if math.isfinite(previous) and previous > 0:
            normalized_previous_stop = previous
            candidates.append(previous)

    return LockedAtrStopResult(
        entry_atr=entry_atr,
        current_atr=current_atr,
        initial_stop_price=initial_stop_price,
        dynamic_trail_price=dynamic_trail_price,
        previous_stop_price=normalized_previous_stop,
        effective_stop_price=max(candidates),
    )
