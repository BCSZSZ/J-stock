from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from src.analysis.signals import MarketData, SignalAction
from src.backtest.data_cache import BacktestDataCache
from src.entry_analysis.features import extract_signal_features, safe_json_dumps
from src.entry_analysis.forward_returns import compute_forward_returns
from src.entry_analysis.models import EntryAnalysisRequest
from src.signal_generator import generate_signal_v2
from src.utils.strategy_loader import load_entry_strategy


def load_tickers_from_file(path: str | Path) -> list[str]:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"Universe file not found: {source}")

    if source.suffix.lower() == ".json":
        import json

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


def _normalize_feature_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.copy()
    if "Date" in normalized.columns:
        index = pd.to_datetime(normalized["Date"], errors="coerce")
    else:
        index = pd.to_datetime(normalized.index, errors="coerce")
    normalized.index = pd.DatetimeIndex(index).normalize()
    normalized.index.name = "Date"
    normalized = normalized[normalized.index.notna()]
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized.sort_index()


def _slice_trades(frame: pd.DataFrame, current_date: pd.Timestamp) -> pd.DataFrame:
    if frame.empty or "EnDate" not in frame.columns:
        return frame
    dates = pd.to_datetime(frame["EnDate"], errors="coerce")
    return frame.loc[dates <= current_date]


def _slice_financials(frame: pd.DataFrame, current_date: pd.Timestamp) -> pd.DataFrame:
    if frame.empty or "DiscDate" not in frame.columns:
        return frame
    dates = pd.to_datetime(frame["DiscDate"], errors="coerce")
    return frame.loc[dates <= current_date]


def _build_market_data(
    *,
    ticker: str,
    current_date: pd.Timestamp,
    features: pd.DataFrame,
    row_pos: int,
    trades: pd.DataFrame,
    financials: pd.DataFrame,
    metadata: dict,
) -> MarketData:
    return MarketData(
        ticker=ticker,
        current_date=current_date,
        df_features=features.iloc[: row_pos + 1],
        df_trades=_slice_trades(trades, current_date),
        df_financials=_slice_financials(financials, current_date),
        metadata=metadata,
    )


def _preload_end_date(end_date: pd.Timestamp, horizons: list[int]) -> str:
    extra_days = max(horizons or [1]) * 4 + 10
    return (end_date + timedelta(days=extra_days)).date().isoformat()


def scan_entry_signals(
    request: EntryAnalysisRequest,
    indicator_columns: tuple[str, ...],
) -> pd.DataFrame:
    cache = BacktestDataCache(data_root=request.data_root)
    start = pd.Timestamp(request.start_date).normalize()
    end = pd.Timestamp(request.end_date).normalize()
    cache.preload_tickers(
        request.tickers,
        start_date=start.date().isoformat(),
        end_date=_preload_end_date(end, request.normalized_horizons),
        include_trades=True,
        include_financials=True,
        include_metadata=True,
    )

    records: list[dict[str, object]] = []
    for strategy_name in request.entry_strategies:
        strategy = load_entry_strategy(strategy_name)
        print(f"[entry-analysis] scanning strategy={strategy_name}")

        for ticker_index, ticker in enumerate(request.tickers, start=1):
            features = cache.get_features(ticker)
            if features is None or features.empty:
                continue

            features = _normalize_feature_frame(features)
            trades = cache.get_trades(ticker)
            financials = cache.get_financials(ticker)
            metadata = cache.get_metadata(ticker)
            date_positions = [
                (row_pos, date_value)
                for row_pos, date_value in enumerate(features.index)
                if start <= date_value <= end
            ]

            if ticker_index % 25 == 0:
                print(
                    f"[entry-analysis] {strategy_name}: processed {ticker_index}/{len(request.tickers)} tickers, candidates={len(records)}"
                )

            for row_pos, current_date in date_positions:
                market_data = _build_market_data(
                    ticker=ticker,
                    current_date=current_date,
                    features=features,
                    row_pos=row_pos,
                    trades=trades,
                    financials=financials,
                    metadata=metadata,
                )
                try:
                    signal = generate_signal_v2(market_data=market_data, entry_strategy=strategy)
                except Exception as exc:
                    print(
                        f"[entry-analysis] warning: {strategy_name} {ticker} {current_date.date()} failed: {exc}"
                    )
                    continue

                if signal.action != SignalAction.BUY:
                    continue

                signal_metadata = dict(signal.metadata or {})
                signal_date = current_date.date().isoformat()
                signal_metadata.setdefault("signal_date", signal_date)
                signal_metadata.setdefault("entry_signal_date", signal_date)
                feature_row = features.iloc[row_pos]
                previous_row = features.iloc[row_pos - 1] if row_pos > 0 else None
                feature_values = extract_signal_features(
                    feature_row=feature_row,
                    previous_feature_row=previous_row,
                    metadata=signal_metadata,
                    indicator_columns=indicator_columns,
                )
                forward_values = compute_forward_returns(
                    features=features,
                    signal_pos=row_pos,
                    horizons=request.normalized_horizons,
                    label_mode=request.label_mode,
                )

                records.append({
                    "entry_strategy": strategy_name,
                    "ticker": ticker,
                    "signal_date": signal_date,
                    "action": signal.action.value,
                    "confidence": float(signal.confidence),
                    "score": signal_metadata.get("score"),
                    "reasons_json": safe_json_dumps(signal.reasons),
                    "metadata_json": safe_json_dumps(signal_metadata),
                    **feature_values,
                    **forward_values,
                })

    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records)
