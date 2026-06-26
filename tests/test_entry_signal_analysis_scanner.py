from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from src.analysis.signals import SignalAction, TradingSignal
from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.scanner import scan_entry_signal_events


class _FakeCache:
    def __init__(self) -> None:
        dates = pd.bdate_range("2026-01-05", periods=3)
        frame = pd.DataFrame(
            {
                "Open": [100.0, 101.0, 102.0],
                "High": [101.0, 102.0, 103.0],
                "Low": [99.0, 100.0, 101.0],
                "Close": [100.5, 101.5, 102.5],
                "Volume": [1_000_000.0, 1_000_000.0, 1_000_000.0],
            },
            index=dates,
        )
        self.features_cache = {
            "7203": frame.copy(),
            "6758": frame.copy(),
        }
        self.date_pos_cache: dict[str, dict[pd.Timestamp, int]] = {}

    def preload_tickers(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def get_features(self, ticker: str) -> pd.DataFrame | None:
        return self.features_cache.get(ticker)

    def get_date_pos_map(self, ticker: str) -> dict[pd.Timestamp, int]:
        return self.date_pos_cache.get(ticker, {})

    def get_trades(self, _ticker: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_financials(self, _ticker: str) -> pd.DataFrame:
        return pd.DataFrame()

    def get_metadata(self, ticker: str) -> dict[str, object]:
        return {"ticker": ticker}


class _CountingFilter:
    def __init__(self) -> None:
        self.calls: list[tuple[str, date]] = []

    def passes(self, market_data: object) -> bool:
        ticker = getattr(market_data, "ticker")
        current_date = getattr(market_data, "current_date").date()
        self.calls.append((ticker, current_date))
        return True


def test_scan_entry_signal_events_shares_market_data_per_ticker_date(
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.scanner as scanner

    fake_cache = _FakeCache()
    fake_filter = _CountingFilter()
    select_calls: list[list[str]] = []

    monkeypatch.setattr(scanner, "BacktestDataCache", lambda data_root: fake_cache)
    monkeypatch.setattr(scanner.EntrySecondaryFilter, "from_dict", lambda _config: fake_filter)
    monkeypatch.setattr(scanner, "resolve_filter_variants_for_request", lambda _request: [("off", {})])
    monkeypatch.setattr(scanner, "resolve_tail_guard_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_momentum_exhaustion_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_industry_filter_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "load_entry_strategy", lambda strategy_name: strategy_name)

    def fake_generate_signal_v2(*, market_data: object, entry_strategy: str) -> TradingSignal:
        ticker = getattr(market_data, "ticker")
        return TradingSignal(
            action=SignalAction.BUY,
            confidence=0.9 if ticker == "7203" else 0.7,
            reasons=[entry_strategy],
            metadata={"score": 10.0 if entry_strategy == "EntryA" else 5.0},
            strategy_name=entry_strategy,
        )

    def fake_select_daily_candidates(candidates, **_kwargs):
        strategies = [candidate.entry_strategy for candidate in candidates]
        select_calls.append(strategies)
        records: list[dict[str, object]] = []
        for rank, candidate in enumerate(candidates, start=1):
            record = dict(candidate.payload)
            record.update(
                {
                    "rank": rank,
                    "rank_score": float(len(candidates) - rank + 1),
                    "positive_rank_score": True,
                    "positive_rank_score_count": len(candidates),
                    "tail_guard_limit": None,
                    "selected": True,
                    "ranking_strategy": "fake",
                }
            )
            records.append(record)
        return records

    monkeypatch.setattr(scanner, "generate_signal_v2", fake_generate_signal_v2)
    monkeypatch.setattr(scanner, "select_daily_candidates", fake_select_daily_candidates)

    request = EntrySignalAnalysisRequest(
        entry_strategies=["EntryA", "EntryB"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        horizons=[1],
        primary_horizon=1,
        ranking_strategy="fake",
        entry_filter_mode="off",
    )

    scan_result = scan_entry_signal_events(request)

    assert len(fake_filter.calls) == 4
    assert len(select_calls) == 4
    assert all(len(set(strategies)) == 1 for strategies in select_calls)
    assert scan_result.scanner_metrics["market_data_build_count"] == 4
    assert scan_result.scanner_metrics["filter_pass_count"] == 4
    assert scan_result.scanner_metrics["strategy_eval_count"] == 8
    assert scan_result.scanner_metrics["buy_signal_count"] == 8
    assert scan_result.scanner_metrics["annotated_event_count"] == 8
    assert scan_result.scanner_metrics["selected_event_count"] == 8
    assert len(scan_result.candidates) == 8
    assert len(scan_result.event_contexts) == 8
    assert set(scan_result.candidates["entry_strategy"]) == {"EntryA", "EntryB"}
