from __future__ import annotations

from datetime import timedelta
from typing import Any

import pandas as pd

from src.analysis.filters import EntrySecondaryFilter
from src.analysis.signals import MarketData, SignalAction
from src.backtest.data_cache import BacktestDataCache
from src.entry_analysis.forward_returns import compute_forward_returns
from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.runtime import (
    resolve_filter_variants_for_request,
    resolve_tail_guard_for_request,
)
from src.entry_signal_analysis.selector import DailyEntryCandidate, select_daily_candidates
from src.signal_generator import generate_signal_v2
from src.utils.strategy_loader import load_entry_strategy


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
    metadata: dict[str, Any],
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


def _collect_trading_dates(
    cache: BacktestDataCache,
    tickers: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[pd.Timestamp]:
    trading_dates: set[pd.Timestamp] = set()
    for ticker in tickers:
        features = cache.get_features(ticker)
        if features is None or features.empty:
            continue
        normalized = _normalize_feature_frame(features)
        cache.features_cache[ticker] = normalized
        cache.date_pos_cache[ticker] = {ts: idx for idx, ts in enumerate(normalized.index)}
        for ts in normalized.index:
            if start <= ts <= end:
                trading_dates.add(ts)
    return sorted(trading_dates)


def scan_entry_signal_candidates(request: EntrySignalAnalysisRequest) -> pd.DataFrame:
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
    trading_dates = _collect_trading_dates(cache, request.tickers, start, end)
    filter_variants = resolve_filter_variants_for_request(request)
    tail_guard_config = resolve_tail_guard_for_request(request)

    records: list[dict[str, Any]] = []
    total_days = len(trading_dates)
    for strategy_name in request.entry_strategies:
        strategy = load_entry_strategy(strategy_name)
        print(f"[entry-signal-analysis] scanning strategy={strategy_name}")
        for filter_name, filter_config in filter_variants:
            entry_filter = EntrySecondaryFilter.from_dict(filter_config)
            print(
                f"[entry-signal-analysis] filter={filter_name} trading_days={total_days}"
            )
            for day_index, current_date in enumerate(trading_dates, start=1):
                daily_candidates: list[DailyEntryCandidate] = []
                for ticker in request.tickers:
                    features = cache.get_features(ticker)
                    if features is None or features.empty:
                        continue
                    row_pos = cache.get_date_pos_map(ticker).get(current_date)
                    if row_pos is None:
                        continue

                    market_data = _build_market_data(
                        ticker=ticker,
                        current_date=current_date,
                        features=features,
                        row_pos=row_pos,
                        trades=cache.get_trades(ticker),
                        financials=cache.get_financials(ticker),
                        metadata=cache.get_metadata(ticker),
                    )
                    if not entry_filter.passes(market_data):
                        continue

                    try:
                        signal = generate_signal_v2(
                            market_data=market_data,
                            entry_strategy=strategy,
                        )
                    except Exception as exc:
                        print(
                            f"[entry-signal-analysis] warning: {strategy_name} {ticker} {current_date.date()} failed: {exc}"
                        )
                        continue

                    if signal.action != SignalAction.BUY:
                        continue

                    signal_metadata = dict(signal.metadata or {})
                    signal_date = current_date.date().isoformat()
                    signal_metadata.setdefault("signal_date", signal_date)
                    signal_metadata.setdefault("entry_signal_date", signal_date)
                    forward_values = compute_forward_returns(
                        features=features,
                        signal_pos=row_pos,
                        horizons=request.normalized_horizons,
                        label_mode=request.label_mode,
                    )
                    entry_price = forward_values.get("label_entry_price")
                    payload: dict[str, Any] = {
                        "entry_strategy": strategy_name,
                        "entry_filter_name": filter_name,
                        "ticker": ticker,
                        "signal_date": signal_date,
                        "confidence": float(signal.confidence),
                        "score": signal_metadata.get("score"),
                        "label_entry_date": forward_values.get("label_entry_date"),
                        "label_entry_price": entry_price,
                    }
                    payload.update(forward_values)
                    for horizon in request.normalized_horizons:
                        target_price = forward_values.get(f"forward_price_{horizon}d")
                        payload[f"forward_diff_{horizon}d"] = (
                            float(target_price) - float(entry_price)
                            if entry_price not in (None, 0) and target_price is not None
                            else None
                        )

                    daily_candidates.append(
                        DailyEntryCandidate(
                            ticker=ticker,
                            entry_strategy=strategy_name,
                            signal_date=signal_date,
                            signal=signal,
                            market_data=market_data,
                            payload=payload,
                        )
                    )

                if daily_candidates:
                    records.extend(
                        select_daily_candidates(
                            daily_candidates,
                            ranking_strategy_name=request.ranking_strategy,
                            tail_guard_config=tail_guard_config,
                        )
                    )

                if day_index % 50 == 0:
                    print(
                        f"[entry-signal-analysis] {strategy_name}/{filter_name}: processed {day_index}/{total_days} days, candidates={len(records)}"
                    )

    if not records:
        return pd.DataFrame()

    frame = pd.DataFrame(records)
    sort_columns = [
        "signal_date",
        "entry_strategy",
        "entry_filter_name",
        "rank",
        "ticker",
    ]
    return frame.sort_values(sort_columns, na_position="last").reset_index(drop=True)