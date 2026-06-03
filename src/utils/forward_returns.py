from __future__ import annotations

from typing import Literal

import pandas as pd


ForwardLabelMode = Literal["signal_close", "next_open"]


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price_at(frame: pd.DataFrame, row_pos: int, column: str) -> float | None:
    if row_pos < 0 or row_pos >= len(frame) or column not in frame.columns:
        return None
    return _to_float(frame.iloc[row_pos].get(column))


def compute_forward_returns(
    features: pd.DataFrame,
    signal_pos: int,
    horizons: list[int],
    label_mode: ForwardLabelMode,
) -> dict[str, object]:
    values: dict[str, object] = {"label_mode": label_mode}

    if label_mode == "next_open":
        entry_pos = signal_pos + 1
        entry_column = "Open"
    else:
        entry_pos = signal_pos
        entry_column = "Close"

    entry_price = _price_at(features, entry_pos, entry_column)
    entry_date = None
    if 0 <= entry_pos < len(features):
        entry_date = pd.Timestamp(features.index[entry_pos]).date().isoformat()

    values["label_entry_date"] = entry_date
    values["label_entry_price"] = entry_price

    for horizon in horizons:
        target_pos = signal_pos + int(horizon)
        target_price = _price_at(features, target_pos, "Close")
        target_date = None
        if 0 <= target_pos < len(features):
            target_date = pd.Timestamp(features.index[target_pos]).date().isoformat()

        return_pct = None
        missing = entry_price in (None, 0) or target_price is None
        if not missing:
            return_pct = (float(target_price) / float(entry_price) - 1.0) * 100.0

        values[f"forward_date_{horizon}d"] = target_date
        values[f"forward_price_{horizon}d"] = target_price
        values[f"forward_return_{horizon}d_pct"] = return_pct
        values[f"forward_missing_{horizon}d"] = missing

    return values