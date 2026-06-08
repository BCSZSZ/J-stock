from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from src.analysis.filters import EntrySecondaryFilter
from src.analysis.signals import TradingSignal, SignalAction
from src.backtest.data_cache import BacktestDataCache
from src.entry_analysis.forward_returns import compute_forward_returns
from src.entry_exit_validation.models import EntryExitValidationRequest
from src.entry_exit_validation.runtime import (
    resolve_filter_variants_for_request,
    resolve_momentum_exhaustion_for_request,
    resolve_tail_guard_for_request,
)
from src.entry_signal_analysis.scanner import (
    _build_market_data,
    _collect_trading_dates,
)
from src.entry_signal_analysis.selector import DailyEntryCandidate, select_daily_candidates
from src.signal_generator import generate_signal_v2
from src.utils.strategy_loader import load_strategy_pair


@dataclass(frozen=True)
class EntryExitCandidateContext:
    ticker: str
    entry_strategy: str
    exit_strategy: str
    entry_filter_name: str
    signal_date: str
    signal_pos: int
    entry_pos: int
    signal: TradingSignal
    payload: dict[str, object]


@dataclass(frozen=True)
class EntryExitScanResult:
    candidates: list[EntryExitCandidateContext]
    cache: BacktestDataCache


def _preload_end_date(request: EntryExitValidationRequest) -> str:
    largest_offset = max(
        [request.max_holding_trading_days, *request.normalized_horizons]
    )
    extra_days = largest_offset * 4 + 10
    end = pd.Timestamp(request.end_date).normalize()
    return (end + timedelta(days=extra_days)).date().isoformat()


def _entry_pos_for_signal(request: EntryExitValidationRequest, signal_pos: int) -> int:
    if request.execution_mode == "next_open":
        return signal_pos + 1
    return signal_pos


def scan_entry_exit_candidates(
    request: EntryExitValidationRequest,
) -> EntryExitScanResult:
    cache = BacktestDataCache(data_root=request.data_root)
    start = pd.Timestamp(request.start_date).normalize()
    end = pd.Timestamp(request.end_date).normalize()
    cache.preload_tickers(
        request.tickers,
        start_date=start.date().isoformat(),
        end_date=_preload_end_date(request),
        include_trades=True,
        include_financials=True,
        include_metadata=True,
    )
    trading_dates = _collect_trading_dates(cache, request.tickers, start, end)
    filter_variants = resolve_filter_variants_for_request(request)
    tail_guard_config = resolve_tail_guard_for_request(request)
    momentum_exhaustion_config = resolve_momentum_exhaustion_for_request(request)
    label_mode = request.execution_mode

    contexts: list[EntryExitCandidateContext] = []
    total_days = len(trading_dates)
    for entry_name in request.entry_strategies:
        for exit_name in request.exit_strategies:
            entry_strategy, _exit_strategy = load_strategy_pair(entry_name, exit_name)
            print(
                f"[entry-exit-validation] scanning entry={entry_name} exit={exit_name}"
            )
            for filter_name, filter_config in filter_variants:
                entry_filter = EntrySecondaryFilter.from_dict(filter_config)
                print(
                    f"[entry-exit-validation] filter={filter_name} trading_days={total_days}"
                )
                for day_index, current_date in enumerate(trading_dates, start=1):
                    daily_candidates: list[DailyEntryCandidate] = []
                    candidate_by_ticker: dict[str, DailyEntryCandidate] = {}
                    row_pos_by_ticker: dict[str, int] = {}

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
                                entry_strategy=entry_strategy,
                            )
                        except Exception as exc:
                            print(
                                f"[entry-exit-validation] warning: {entry_name}/{exit_name} {ticker} {current_date.date()} failed: {exc}"
                            )
                            continue

                        if signal.action != SignalAction.BUY:
                            continue

                        forward_values = compute_forward_returns(
                            features=features,
                            signal_pos=row_pos,
                            horizons=request.normalized_horizons,
                            label_mode=label_mode,
                        )
                        signal_metadata = dict(signal.metadata or {})
                        signal_date = current_date.date().isoformat()
                        signal_metadata.setdefault("signal_date", signal_date)
                        signal_metadata.setdefault("entry_signal_date", signal_date)
                        entry_price = forward_values.get("label_entry_price")
                        payload: dict[str, object] = {
                            "ticker": ticker,
                            "entry_strategy": entry_name,
                            "exit_strategy": exit_name,
                            "entry_filter_name": filter_name,
                            "signal_date": signal_date,
                            "confidence": float(signal.confidence),
                            "score": signal_metadata.get("score"),
                            "label_entry_date": forward_values.get("label_entry_date"),
                            "label_entry_price": entry_price,
                        }
                        payload.update(forward_values)

                        candidate = DailyEntryCandidate(
                            ticker=ticker,
                            entry_strategy=entry_name,
                            signal_date=signal_date,
                            signal=signal,
                            market_data=market_data,
                            payload=payload,
                        )
                        daily_candidates.append(candidate)
                        candidate_by_ticker[ticker] = candidate
                        row_pos_by_ticker[ticker] = row_pos

                    if daily_candidates:
                        selected_records = select_daily_candidates(
                            daily_candidates,
                            ranking_strategy_name=request.ranking_strategy,
                            tail_guard_config=tail_guard_config,
                            momentum_exhaustion_config=momentum_exhaustion_config,
                        )
                        for record in selected_records:
                            ticker = str(record.get("ticker"))
                            candidate = candidate_by_ticker.get(ticker)
                            if candidate is None:
                                continue
                            signal_pos = row_pos_by_ticker[ticker]
                            entry_pos = _entry_pos_for_signal(request, signal_pos)
                            contexts.append(
                                EntryExitCandidateContext(
                                    ticker=ticker,
                                    entry_strategy=entry_name,
                                    exit_strategy=exit_name,
                                    entry_filter_name=filter_name,
                                    signal_date=str(record.get("signal_date")),
                                    signal_pos=signal_pos,
                                    entry_pos=entry_pos,
                                    signal=candidate.signal,
                                    payload=dict(record),
                                )
                            )

                    if day_index % 50 == 0:
                        print(
                            f"[entry-exit-validation] {entry_name}/{exit_name}/{filter_name}: processed {day_index}/{total_days} days, candidates={len(contexts)}"
                        )

    return EntryExitScanResult(candidates=contexts, cache=cache)
