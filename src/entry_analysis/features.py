from __future__ import annotations

import json
from typing import Iterable

import pandas as pd

from src.evaluation.trade_indicator_enrichment import DEFAULT_INDICATOR_COLUMNS


METADATA_FEATURE_KEYS: tuple[str, ...] = (
    "bias_pct",
    "gap_above_ema20_pct",
    "return_5d",
    "volume_ratio",
    "buy_signal_streak_days",
    "stale_buy_signal",
    "is_fresh_buy_signal",
    "hist_abs_norm",
    "hist_delta_norm",
    "raw_entry_signal",
)


def normalize_indicator_columns(raw_columns: Iterable[str] | None) -> tuple[str, ...]:
    if not raw_columns:
        return DEFAULT_INDICATOR_COLUMNS

    columns: list[str] = []
    for raw_column in raw_columns:
        for column in str(raw_column).split(","):
            cleaned = column.strip()
            if cleaned and cleaned not in columns:
                columns.append(cleaned)
    return tuple(columns)


def safe_json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


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


def _pct_delta(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator - 1.0) * 100.0


def _bool_or_none(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def extract_signal_features(
    feature_row: pd.Series,
    previous_feature_row: pd.Series | None,
    metadata: dict[str, object],
    indicator_columns: tuple[str, ...],
) -> dict[str, object]:
    values: dict[str, object] = {}
    valid_count = 0

    for column in indicator_columns:
        value = feature_row.get(column, pd.NA)
        if not pd.isna(value):
            valid_count += 1
        values[column] = value

    values["feature_valid_count"] = valid_count
    values["feature_missing_count"] = len(indicator_columns) - valid_count
    values["feature_quality"] = valid_count / len(indicator_columns) if indicator_columns else 1.0

    close = _to_float(feature_row.get("Close"))
    open_price = _to_float(feature_row.get("Open"))
    values["signal_close"] = close
    values["signal_open"] = open_price

    ema20 = _to_float(feature_row.get("EMA_20"))
    ema50 = _to_float(feature_row.get("EMA_50"))
    ema200 = _to_float(feature_row.get("EMA_200"))
    for label, ema_value in (("20", ema20), ("50", ema50), ("200", ema200)):
        values[f"close_vs_EMA_{label}_pct"] = _pct_delta(close, ema_value)
        values[f"close_above_EMA_{label}"] = None if close is None or ema_value is None else close > ema_value

    values["EMA_20_above_EMA_50"] = None if ema20 is None or ema50 is None else ema20 > ema50
    values["EMA_50_above_EMA_200"] = None if ema50 is None or ema200 is None else ema50 > ema200
    values["EMA_bull_stack"] = (
        None if None in (ema20, ema50, ema200) else bool(ema20 > ema50 > ema200)
    )

    macd_hist = _to_float(feature_row.get("MACD_Hist"))
    previous_macd_hist = (
        _to_float(previous_feature_row.get("MACD_Hist"))
        if previous_feature_row is not None
        else None
    )
    values["MACD_Hist_norm"] = None if close in (None, 0) or macd_hist is None else macd_hist / close
    values["MACD_Hist_delta"] = (
        None if macd_hist is None or previous_macd_hist is None else macd_hist - previous_macd_hist
    )
    values["MACD_Hist_delta_norm"] = (
        None
        if close in (None, 0) or values["MACD_Hist_delta"] is None
        else float(values["MACD_Hist_delta"]) / close
    )

    rsi9 = _to_float(feature_row.get("RSI_9"))
    rsi22 = _to_float(feature_row.get("RSI_22"))
    values["RSI_9_minus_RSI_22"] = None if rsi9 is None or rsi22 is None else rsi9 - rsi22

    for key in METADATA_FEATURE_KEYS:
        raw_value = metadata.get(key)
        if key in {"stale_buy_signal", "is_fresh_buy_signal", "raw_entry_signal"}:
            values[key] = _bool_or_none(raw_value)
        elif key == "return_5d":
            numeric = _to_float(raw_value)
            values["metadata_return_5d_pct"] = None if numeric is None else numeric * 100.0
        else:
            values[key] = _to_float(raw_value)

    return values


def discover_numeric_feature_columns(feature_frames: Iterable[pd.DataFrame]) -> list[str]:
    columns: set[str] = set()
    for frame in feature_frames:
        if frame.empty:
            continue
        numeric = frame.select_dtypes(include=["number", "bool"]).columns
        columns.update(str(column) for column in numeric)
    return sorted(columns)
