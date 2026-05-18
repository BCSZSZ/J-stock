"""Helpers for applying configurable execution buffers to backtest fills."""

from __future__ import annotations


def normalize_fill_buffer_pct(fill_buffer_pct: float | None) -> float:
    """Validate and normalize the configured fill buffer percentage."""
    if fill_buffer_pct is None:
        return 0.0

    try:
        normalized = float(fill_buffer_pct)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Invalid fill_buffer_pct: {fill_buffer_pct}. Expected a numeric value."
        ) from exc

    if normalized < 0.0 or normalized >= 1.0:
        raise ValueError(
            f"Invalid fill_buffer_pct: {fill_buffer_pct}. Expected 0 <= pct < 1."
        )

    return normalized


def apply_buy_fill_buffer(price: float, enabled: bool, fill_buffer_pct: float) -> float:
    """Apply a worse buy fill by increasing the raw execution price."""
    if not enabled or fill_buffer_pct <= 0.0:
        return float(price)
    return float(price) * (1.0 + fill_buffer_pct)


def apply_sell_fill_buffer(price: float, enabled: bool, fill_buffer_pct: float) -> float:
    """Apply a worse sell fill by decreasing the raw execution price."""
    if not enabled or fill_buffer_pct <= 0.0:
        return float(price)
    return float(price) * (1.0 - fill_buffer_pct)