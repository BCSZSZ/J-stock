from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
import inspect
from typing import Any

import pandas as pd

from src.analysis.filters import EntrySecondaryFilter
from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.backtest.data_cache import BacktestDataCache
from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.runtime import (
    resolve_filter_variants_for_request,
    resolve_industry_filter_for_request,
    resolve_momentum_exhaustion_for_request,
    resolve_tail_guard_for_request,
)
from src.entry_signal_analysis.selector import DailyEntryCandidate, select_daily_candidates
from src.signal_generator import generate_signal_v2
from src.utils.forward_returns import compute_forward_returns
from src.utils.strategy_loader import load_entry_strategy, load_ranking_strategy


@dataclass(frozen=True)
class EntrySignalEventContext:
    ticker: str
    entry_strategy: str
    entry_filter_name: str
    signal_date: str
    signal_pos: int
    entry_pos: int
    signal: TradingSignal
    payload: dict[str, Any]


@dataclass(frozen=True)
class EntrySignalScanResult:
    candidates: pd.DataFrame
    event_contexts: list[EntrySignalEventContext]
    cache: BacktestDataCache
    trading_dates: list[pd.Timestamp]
    scanner_metrics: dict[str, int] = field(default_factory=dict)


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


def _signal_with_metadata(
    signal: TradingSignal,
    updates: dict[str, Any],
) -> TradingSignal:
    metadata = dict(signal.metadata or {})
    metadata.update(updates)
    return TradingSignal(
        action=signal.action,
        confidence=float(signal.confidence),
        reasons=list(signal.reasons or []),
        metadata=metadata,
        strategy_name=signal.strategy_name,
    )


def _preload_end_date(end_date: pd.Timestamp, horizons: list[int]) -> str:
    extra_days = max(horizons or [1]) * 4 + 10
    return (end_date + timedelta(days=extra_days)).date().isoformat()


def _entry_pos_for_label_mode(request: EntrySignalAnalysisRequest, signal_pos: int) -> int:
    if request.label_mode == "next_open":
        return signal_pos + 1
    return signal_pos


def _build_daily_entry_candidate(
    *,
    request: EntrySignalAnalysisRequest,
    strategy_name: str,
    filter_name: str,
    ticker: str,
    current_date: pd.Timestamp,
    signal: TradingSignal,
    market_data: MarketData | None,
    forward_values: dict[str, Any],
) -> DailyEntryCandidate:
    signal_metadata = dict(signal.metadata or {})
    signal_date = current_date.date().isoformat()
    signal_metadata.setdefault("signal_date", signal_date)
    signal_metadata.setdefault("entry_signal_date", signal_date)
    entry_price = forward_values.get("label_entry_price")
    payload: dict[str, Any] = {
        "event_id": f"{strategy_name}::{filter_name}::{ticker}::{signal_date}",
        "entry_strategy": strategy_name,
        "entry_filter_name": filter_name,
        "ticker": ticker,
        "signal_date": signal_date,
        "entry_date": forward_values.get("label_entry_date"),
        "entry_price": entry_price,
        "confidence": float(signal.confidence),
        "score": signal_metadata.get("score"),
        "reasons": list(signal.reasons or []),
        "signal_metadata": signal_metadata,
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

    return DailyEntryCandidate(
        ticker=ticker,
        entry_strategy=strategy_name,
        signal_date=signal_date,
        signal=signal,
        market_data=market_data,
        payload=payload,
    )


def _precompute_strategy_signals(
    *,
    strategies: dict[str, object],
    features_by_ticker: dict[str, pd.DataFrame],
    trades_by_ticker: dict[str, pd.DataFrame],
    financials_by_ticker: dict[str, pd.DataFrame],
    metadata_by_ticker: dict[str, Any],
    scanner_metrics: dict[str, int],
) -> dict[tuple[str, str], dict[int, TradingSignal]]:
    precomputed: dict[tuple[str, str], dict[int, TradingSignal]] = {}
    family_cache_by_ticker: dict[tuple[str, str], object] = {}
    for strategy_name, strategy in strategies.items():
        precompute = getattr(strategy, "precompute_entry_signals", None)
        if not callable(precompute):
            continue
        family_key = getattr(strategy, "precompute_family_key", None)
        family_key_text = str(family_key) if family_key else None
        build_feature_cache = getattr(strategy, "build_precompute_feature_cache", None)
        for ticker, features in features_by_ticker.items():
            precompute_kwargs: dict[str, Any] = {
                "ticker": ticker,
                "features": features,
                "trades": trades_by_ticker.get(ticker, pd.DataFrame()),
                "financials": financials_by_ticker.get(ticker, pd.DataFrame()),
                "metadata": metadata_by_ticker.get(ticker, {}),
            }
            feature_cache: object | None = None
            if family_key_text and callable(build_feature_cache):
                cache_key = (family_key_text, ticker)
                if cache_key in family_cache_by_ticker:
                    scanner_metrics["strategy_family_cache_reuse_count"] += 1
                    feature_cache = family_cache_by_ticker[cache_key]
                else:
                    scanner_metrics["strategy_family_cache_build_count"] += 1
                    try:
                        feature_cache = _call_strategy_hook(
                            build_feature_cache,
                            precompute_kwargs,
                        )
                    except Exception as exc:
                        scanner_metrics["strategy_family_cache_failure_count"] += 1
                        print(
                            f"[entry-signal-analysis] warning: {strategy_name} {ticker} "
                            f"family cache failed: {exc}"
                        )
                        feature_cache = None
                    else:
                        family_cache_by_ticker[cache_key] = feature_cache
            scanner_metrics["strategy_precompute_count"] += 1
            try:
                signals_by_pos = _call_strategy_hook(
                    precompute,
                    {**precompute_kwargs, "feature_cache": feature_cache},
                )
            except Exception as exc:
                scanner_metrics["strategy_precompute_failure_count"] += 1
                print(
                    f"[entry-signal-analysis] warning: {strategy_name} {ticker} precompute failed: {exc}"
                )
                continue
            buy_signals = {
                int(row_pos): signal
                for row_pos, signal in signals_by_pos.items()
                if signal.action == SignalAction.BUY
            }
            scanner_metrics["strategy_precomputed_buy_signal_count"] += len(buy_signals)
            precomputed[(strategy_name, ticker)] = buy_signals
    return precomputed


def _call_strategy_hook(hook: object, kwargs: dict[str, Any]) -> Any:
    if not callable(hook):
        raise TypeError("strategy hook is not callable")
    signature = inspect.signature(hook)
    parameters = signature.parameters
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    ):
        return hook(**kwargs)
    supported_kwargs = {
        name: value
        for name, value in kwargs.items()
        if name in parameters
    }
    return hook(**supported_kwargs)


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


def scan_entry_signal_events(request: EntrySignalAnalysisRequest) -> EntrySignalScanResult:
    cache = BacktestDataCache(data_root=request.data_root)
    start = pd.Timestamp(request.start_date).normalize()
    end = pd.Timestamp(request.end_date).normalize()
    cache.preload_tickers(
        request.tickers,
        start_date=start.date().isoformat(),
        end_date=_preload_end_date(end, request.required_analysis_horizons),
        include_trades=True,
        include_financials=True,
        include_metadata=True,
    )
    trading_dates = _collect_trading_dates(cache, request.tickers, start, end)
    filter_variants = resolve_filter_variants_for_request(request)
    tail_guard_config = resolve_tail_guard_for_request(request)
    momentum_exhaustion_config = resolve_momentum_exhaustion_for_request(request)
    industry_filter_config = resolve_industry_filter_for_request(request)
    strategies = {
        strategy_name: load_entry_strategy(strategy_name)
        for strategy_name in request.entry_strategies
    }
    ranker = load_ranking_strategy(request.ranking_strategy)
    ranker_requires_market_data = bool(ranker.requires_market_data())
    rank_feature_source = getattr(ranker, "_delegate", ranker)
    rank_score_from_features = getattr(rank_feature_source, "score_from_features", None)
    rank_score_metadata_key_fn = getattr(rank_feature_source, "metadata_rank_score_key", None)
    ranker_uses_feature_score = bool(
        ranker_requires_market_data and callable(rank_score_from_features)
    )
    rank_score_metadata_key = (
        str(rank_score_metadata_key_fn())
        if callable(rank_score_metadata_key_fn)
        else "rank_feature_score"
    )
    if ranker_uses_feature_score:
        ranker_requires_market_data = False
    for strategy_name in strategies:
        print(f"[entry-signal-analysis] scanning strategy={strategy_name}")

    features_by_ticker: dict[str, pd.DataFrame] = {}
    date_pos_by_ticker: dict[str, dict[pd.Timestamp, int]] = {}
    trades_by_ticker: dict[str, pd.DataFrame] = {}
    financials_by_ticker: dict[str, pd.DataFrame] = {}
    metadata_by_ticker: dict[str, Any] = {}
    for ticker in request.tickers:
        features = cache.get_features(ticker)
        if features is None or features.empty:
            continue
        features_by_ticker[ticker] = features
        date_pos_by_ticker[ticker] = cache.get_date_pos_map(ticker)
        trades_by_ticker[ticker] = cache.get_trades(ticker)
        financials_by_ticker[ticker] = cache.get_financials(ticker)
        metadata_by_ticker[ticker] = cache.get_metadata(ticker)

    records: list[dict[str, Any]] = []
    contexts: list[EntrySignalEventContext] = []
    scanner_metrics: dict[str, int] = {
        "market_data_build_count": 0,
        "filter_pass_count": 0,
        "strategy_eval_count": 0,
        "strategy_fast_eval_count": 0,
        "strategy_fallback_eval_count": 0,
        "strategy_precompute_count": 0,
        "strategy_precompute_failure_count": 0,
        "strategy_precomputed_buy_signal_count": 0,
        "strategy_family_cache_build_count": 0,
        "strategy_family_cache_reuse_count": 0,
        "strategy_family_cache_failure_count": 0,
        "forward_return_cache_hit_count": 0,
        "forward_return_cache_miss_count": 0,
        "rank_score_precompute_count": 0,
        "rank_score_precompute_failure_count": 0,
        "buy_signal_count": 0,
        "annotated_event_count": 0,
        "selected_event_count": 0,
    }
    precomputed_signals = _precompute_strategy_signals(
        strategies=strategies,
        features_by_ticker=features_by_ticker,
        trades_by_ticker=trades_by_ticker,
        financials_by_ticker=financials_by_ticker,
        metadata_by_ticker=metadata_by_ticker,
        scanner_metrics=scanner_metrics,
    )
    forward_values_cache: dict[
        tuple[str, int, str, tuple[int, ...]],
        dict[str, Any],
    ] = {}
    total_days = len(trading_dates)
    for filter_name, filter_config in filter_variants:
        entry_filter = EntrySecondaryFilter.from_dict(filter_config)
        print(
            f"[entry-signal-analysis] filter={filter_name} trading_days={total_days}"
        )
        for day_index, current_date in enumerate(trading_dates, start=1):
            daily_candidates_by_strategy: dict[str, list[DailyEntryCandidate]] = {
                strategy_name: [] for strategy_name in strategies
            }
            candidate_by_strategy_ticker: dict[tuple[str, str], DailyEntryCandidate] = {}
            row_pos_by_ticker: dict[str, int] = {}
            for ticker in request.tickers:
                features = features_by_ticker.get(ticker)
                if features is None:
                    continue
                row_pos = date_pos_by_ticker.get(ticker, {}).get(current_date)
                if row_pos is None:
                    continue

                if not entry_filter.passes_latest(features.iloc[row_pos]):
                    continue
                scanner_metrics["filter_pass_count"] += 1
                row_pos_by_ticker[ticker] = row_pos
                forward_values: dict[str, Any] | None = None
                market_data: MarketData | None = None

                def get_market_data() -> MarketData:
                    nonlocal market_data
                    if market_data is None:
                        market_data = _build_market_data(
                            ticker=ticker,
                            current_date=current_date,
                            features=features,
                            row_pos=row_pos,
                            trades=trades_by_ticker.get(ticker, pd.DataFrame()),
                            financials=financials_by_ticker.get(ticker, pd.DataFrame()),
                            metadata=metadata_by_ticker.get(ticker, {}),
                        )
                        scanner_metrics["market_data_build_count"] += 1
                    return market_data

                for strategy_name, strategy in strategies.items():
                    scanner_metrics["strategy_eval_count"] += 1
                    strategy_signals = precomputed_signals.get((strategy_name, ticker))
                    if strategy_signals is not None:
                        scanner_metrics["strategy_fast_eval_count"] += 1
                        signal = strategy_signals.get(row_pos)
                        if signal is None:
                            continue
                    else:
                        scanner_metrics["strategy_fallback_eval_count"] += 1
                        try:
                            signal = generate_signal_v2(
                                market_data=get_market_data(),
                                entry_strategy=strategy,
                            )
                        except Exception as exc:
                            print(
                                f"[entry-signal-analysis] warning: {strategy_name} {ticker} {current_date.date()} failed: {exc}"
                            )
                            continue

                    if signal.action != SignalAction.BUY:
                        continue

                    scanner_metrics["buy_signal_count"] += 1
                    if forward_values is None:
                        forward_cache_key = (
                            ticker,
                            int(row_pos),
                            str(request.label_mode),
                            tuple(request.normalized_horizons),
                        )
                        cached_forward_values = forward_values_cache.get(forward_cache_key)
                        if cached_forward_values is None:
                            scanner_metrics["forward_return_cache_miss_count"] += 1
                            forward_values = compute_forward_returns(
                                features=features,
                                signal_pos=row_pos,
                                horizons=request.normalized_horizons,
                                label_mode=request.label_mode,
                            )
                            forward_values_cache[forward_cache_key] = forward_values
                        else:
                            scanner_metrics["forward_return_cache_hit_count"] += 1
                            forward_values = cached_forward_values
                    candidate_signal = signal
                    if ranker_uses_feature_score and callable(rank_score_from_features):
                        try:
                            rank_score = float(rank_score_from_features(features, row_pos))
                        except Exception as exc:
                            scanner_metrics["rank_score_precompute_failure_count"] += 1
                            print(
                                f"[entry-signal-analysis] warning: rank score {ticker} "
                                f"{current_date.date()} failed: {exc}"
                            )
                        else:
                            scanner_metrics["rank_score_precompute_count"] += 1
                            candidate_signal = _signal_with_metadata(
                                signal,
                                {rank_score_metadata_key: rank_score},
                            )
                    candidate_market_data = (
                        get_market_data() if ranker_requires_market_data else None
                    )
                    candidate = _build_daily_entry_candidate(
                        request=request,
                        strategy_name=strategy_name,
                        filter_name=filter_name,
                        ticker=ticker,
                        current_date=current_date,
                        signal=candidate_signal,
                        market_data=candidate_market_data,
                        forward_values=forward_values,
                    )
                    daily_candidates_by_strategy[strategy_name].append(candidate)
                    candidate_by_strategy_ticker[(strategy_name, ticker)] = candidate

            for strategy_name, daily_candidates in daily_candidates_by_strategy.items():
                if not daily_candidates:
                    continue
                selected_records = select_daily_candidates(
                    daily_candidates,
                    ranker=ranker,
                    tail_guard_config=tail_guard_config,
                    momentum_exhaustion_config=momentum_exhaustion_config,
                    industry_filter_config=industry_filter_config,
                )
                records.extend(selected_records)
                scanner_metrics["annotated_event_count"] += len(selected_records)
                scanner_metrics["selected_event_count"] += sum(
                    1 for record in selected_records if bool(record.get("selected"))
                )
                for record in selected_records:
                    ticker = str(record.get("ticker"))
                    candidate = candidate_by_strategy_ticker.get((strategy_name, ticker))
                    if candidate is None:
                        continue
                    signal_pos = row_pos_by_ticker[ticker]
                    contexts.append(
                        EntrySignalEventContext(
                            ticker=ticker,
                            entry_strategy=strategy_name,
                            entry_filter_name=filter_name,
                            signal_date=str(record.get("signal_date")),
                            signal_pos=signal_pos,
                            entry_pos=_entry_pos_for_label_mode(request, signal_pos),
                            signal=candidate.signal,
                            payload=dict(record),
                        )
                    )

            if day_index % 50 == 0:
                print(
                    f"[entry-signal-analysis] {filter_name}: processed {day_index}/{total_days} days, candidates={len(records)}"
                )

    if not records:
        return EntrySignalScanResult(
            candidates=pd.DataFrame(),
            event_contexts=[],
            cache=cache,
            trading_dates=trading_dates,
            scanner_metrics=scanner_metrics,
        )

    frame = pd.DataFrame(records)
    sort_columns = [
        "signal_date",
        "entry_strategy",
        "entry_filter_name",
        "rank",
        "ticker",
    ]
    frame = frame.sort_values(sort_columns, na_position="last").reset_index(drop=True)
    return EntrySignalScanResult(
        candidates=frame,
        event_contexts=contexts,
        cache=cache,
        trading_dates=trading_dates,
        scanner_metrics=scanner_metrics,
    )


def scan_entry_signal_candidates(request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    return scan_entry_signal_events(request).candidates
