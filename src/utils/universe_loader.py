from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

import pandas as pd


def _normalize_ticker(value: object) -> str:
    ticker = str(value or "").strip()
    if ticker.endswith(".0") and ticker[:-2].isdigit():
        ticker = ticker[:-2]
    return ticker


def _dedupe(values: Iterable[object]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        ticker = _normalize_ticker(value)
        if ticker and ticker not in seen:
            seen.add(ticker)
            result.append(ticker)
    return result


def load_tickers_from_file(path: str | Path) -> list[str]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Universe file not found: {source}")

    if source.suffix.lower() == ".json":
        payload = json.loads(source.read_text(encoding="utf-8"))
        raw_items: object
        if isinstance(payload, dict):
            raw_items = payload.get("tickers") or payload.get("symbols") or payload.get("stocks") or []
        else:
            raw_items = payload
        tickers: list[str] = []
        if isinstance(raw_items, list):
            for item in raw_items:
                if isinstance(item, dict):
                    value = item.get("code") or item.get("ticker") or item.get("symbol")
                else:
                    value = item
                normalized = _normalize_ticker(value)
                if normalized:
                    tickers.append(normalized)
        return _dedupe(tickers)

    if source.suffix.lower() == ".csv":
        frame = pd.read_csv(source)
        for column in ["code", "Code", "ticker", "Ticker", "symbol", "Symbol"]:
            if column in frame.columns:
                return _dedupe(_normalize_ticker(value) for value in frame[column].tolist())
        raise ValueError(f"CSV universe file lacks a ticker column: {source}")

    tickers = []
    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            tickers.append(stripped)
    return _dedupe(tickers)