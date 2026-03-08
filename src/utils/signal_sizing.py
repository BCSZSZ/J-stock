"""Utilities for optional signal-level position sizing."""

from __future__ import annotations

from typing import Any, Dict, Optional


_BUY_SIZE_KEYS = (
    "buy_size_multiplier",
    "position_size_multiplier",
    "entry_size_multiplier",
)


def extract_buy_size_multiplier(metadata: Optional[Dict[str, Any]]) -> float:
    """Return signal-level buy size multiplier, defaulting to 1.0.

    Existing strategies are unaffected because missing/invalid values return 1.0.
    Values are clamped to [0.0, 1.0] for risk safety.
    """
    if not metadata:
        return 1.0

    for key in _BUY_SIZE_KEYS:
        if key not in metadata:
            continue
        try:
            value = float(metadata[key])
        except (TypeError, ValueError):
            return 1.0
        return min(1.0, max(0.0, value))

    return 1.0
