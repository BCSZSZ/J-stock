from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from src.data.stock_data_manager import StockDataManager


def _default_data_root() -> str:
    return str(Path(__file__).resolve().parents[2] / "data")


@lru_cache(maxsize=1)
def _get_data_manager(data_root: str) -> StockDataManager:
    return StockDataManager(data_root=data_root)


def resolve_signal_entry_price(
    ticker: str,
    trade_date: str,
    data_root: str | None = None,
) -> float | None:
    manager = _get_data_manager(data_root or _default_data_root())
    df = manager.load_stock_features(ticker)
    if df.empty or "Open" not in df.columns:
        return None

    if "Date" not in df.columns:
        df = df.reset_index()
    if "Date" not in df.columns:
        return None

    dates = pd.to_datetime(df["Date"], errors="coerce")
    matches = df.loc[dates.dt.strftime("%Y-%m-%d") == trade_date, "Open"]
    if matches.empty:
        return None

    value = matches.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)