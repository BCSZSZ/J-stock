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
        self.calls: list[date] = []

    def passes(self, market_data: object) -> bool:
        current_date = getattr(market_data, "current_date").date()
        self.calls.append(current_date)
        return True

    def passes_latest(self, latest: pd.Series) -> bool:
        self.calls.append(latest.name.date())
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


def test_scan_entry_signal_events_uses_precomputed_strategy_without_market_data(
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.scanner as scanner

    class _PrecomputedBuyEntry:
        strategy_name = "PrecomputedBuyEntry"

        def precompute_entry_signals(
            self,
            *,
            ticker: str,
            features: pd.DataFrame,
        ) -> dict[int, TradingSignal]:
            score = 10.0 if ticker == "7203" else 5.0
            return {
                row_pos: TradingSignal(
                    action=SignalAction.BUY,
                    confidence=0.9,
                    reasons=["precomputed"],
                    metadata={"score": score},
                    strategy_name=self.strategy_name,
                )
                for row_pos in range(len(features))
            }

    fake_cache = _FakeCache()
    fake_filter = _CountingFilter()
    monkeypatch.setattr(scanner, "BacktestDataCache", lambda data_root: fake_cache)
    monkeypatch.setattr(scanner.EntrySecondaryFilter, "from_dict", lambda _config: fake_filter)
    monkeypatch.setattr(scanner, "resolve_filter_variants_for_request", lambda _request: [("off", {})])
    monkeypatch.setattr(scanner, "resolve_tail_guard_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_momentum_exhaustion_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_industry_filter_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "load_entry_strategy", lambda _strategy_name: _PrecomputedBuyEntry())
    monkeypatch.setattr(
        scanner,
        "generate_signal_v2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fallback generate not expected")),
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["PrecomputedBuyEntry"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        horizons=[1],
        primary_horizon=1,
        ranking_strategy="score_only",
        entry_filter_mode="off",
    )

    scan_result = scan_entry_signal_events(request)

    assert scan_result.scanner_metrics["strategy_precompute_count"] == 2
    assert scan_result.scanner_metrics["strategy_precomputed_buy_signal_count"] == 6
    assert scan_result.scanner_metrics["market_data_build_count"] == 0
    assert scan_result.scanner_metrics["strategy_eval_count"] == 4
    assert scan_result.scanner_metrics["strategy_fast_eval_count"] == 4
    assert scan_result.scanner_metrics["strategy_fallback_eval_count"] == 0
    assert scan_result.scanner_metrics["buy_signal_count"] == 4
    assert len(scan_result.candidates) == 4
    assert len(scan_result.event_contexts) == 4


def test_scan_entry_signal_events_passes_context_to_precompute_hooks(
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.scanner as scanner

    class _ContextCache(_FakeCache):
        def get_trades(self, ticker: str) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "EnDate": ["2026-01-05"],
                    "FrgnBal": [1_000_000.0],
                    "Ticker": [ticker],
                }
            )

        def get_financials(self, ticker: str) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "DiscDate": ["2026-01-05"],
                    "Sales": [100.0],
                    "Ticker": [ticker],
                }
            )

    class _ContextPrecomputedEntry:
        strategy_name = "ContextPrecomputedEntry"
        precompute_family_key = "context_precompute"

        def build_precompute_feature_cache(
            self,
            *,
            features: pd.DataFrame,
            trades: pd.DataFrame,
            financials: pd.DataFrame,
            metadata: dict[str, object],
        ) -> dict[str, object]:
            assert not features.empty
            assert not trades.empty
            assert not financials.empty
            assert metadata["ticker"] in {"7203", "6758"}
            return {"ticker": metadata["ticker"]}

        def precompute_entry_signals(
            self,
            *,
            ticker: str,
            features: pd.DataFrame,
            trades: pd.DataFrame,
            financials: pd.DataFrame,
            metadata: dict[str, object],
            feature_cache: dict[str, object],
        ) -> dict[int, TradingSignal]:
            assert feature_cache["ticker"] == ticker
            assert not trades.empty
            assert not financials.empty
            assert metadata["ticker"] == ticker
            return {
                0: TradingSignal(
                    action=SignalAction.BUY,
                    confidence=0.9,
                    reasons=["context precomputed"],
                    metadata={"score": 10.0},
                    strategy_name=self.strategy_name,
                )
            }

    fake_cache = _ContextCache()
    fake_filter = _CountingFilter()
    monkeypatch.setattr(scanner, "BacktestDataCache", lambda data_root: fake_cache)
    monkeypatch.setattr(scanner.EntrySecondaryFilter, "from_dict", lambda _config: fake_filter)
    monkeypatch.setattr(scanner, "resolve_filter_variants_for_request", lambda _request: [("off", {})])
    monkeypatch.setattr(scanner, "resolve_tail_guard_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_momentum_exhaustion_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_industry_filter_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "load_entry_strategy", lambda _strategy_name: _ContextPrecomputedEntry())
    monkeypatch.setattr(
        scanner,
        "generate_signal_v2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fallback generate not expected")),
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["ContextPrecomputedEntry"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        horizons=[1],
        primary_horizon=1,
        ranking_strategy="score_only",
        entry_filter_mode="off",
    )

    scan_result = scan_entry_signal_events(request)

    assert scan_result.scanner_metrics["strategy_family_cache_build_count"] == 2
    assert scan_result.scanner_metrics["strategy_precompute_count"] == 2
    assert scan_result.scanner_metrics["strategy_fast_eval_count"] == 2
    assert scan_result.scanner_metrics["market_data_build_count"] == 0
    assert len(scan_result.candidates) == 2


def test_scan_entry_signal_events_reuses_family_cache_and_forward_returns(
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.scanner as scanner

    class _FamilyPrecomputedBuyEntry:
        precompute_family_key = "fake_family"

        def __init__(self, strategy_name: str) -> None:
            self.strategy_name = strategy_name

        def build_precompute_feature_cache(self, features: pd.DataFrame) -> object:
            feature_cache = {"features_id": id(features)}
            cache_builds.append((self.strategy_name, id(features), feature_cache))
            return feature_cache

        def precompute_entry_signals(
            self,
            *,
            ticker: str,
            features: pd.DataFrame,
            feature_cache: object | None = None,
        ) -> dict[int, TradingSignal]:
            assert feature_cache is not None
            precompute_calls.append((self.strategy_name, ticker, id(feature_cache)))
            return {
                row_pos: TradingSignal(
                    action=SignalAction.BUY,
                    confidence=0.9,
                    reasons=["precomputed"],
                    metadata={"score": 10.0},
                    strategy_name=self.strategy_name,
                )
                for row_pos in range(len(features))
            }

    cache_builds: list[tuple[str, int, object]] = []
    precompute_calls: list[tuple[str, str, int]] = []
    fake_cache = _FakeCache()
    fake_filter = _CountingFilter()

    monkeypatch.setattr(scanner, "BacktestDataCache", lambda data_root: fake_cache)
    monkeypatch.setattr(scanner.EntrySecondaryFilter, "from_dict", lambda _config: fake_filter)
    monkeypatch.setattr(
        scanner,
        "resolve_filter_variants_for_request",
        lambda _request: [("f1", {}), ("f2", {})],
    )
    monkeypatch.setattr(scanner, "resolve_tail_guard_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_momentum_exhaustion_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_industry_filter_for_request", lambda _request: None)
    monkeypatch.setattr(
        scanner,
        "load_entry_strategy",
        lambda strategy_name: _FamilyPrecomputedBuyEntry(strategy_name),
    )
    monkeypatch.setattr(
        scanner,
        "generate_signal_v2",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("fallback generate not expected")),
    )

    request = EntrySignalAnalysisRequest(
        entry_strategies=["EntryA", "EntryB"],
        tickers=["7203", "6758"],
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 6),
        horizons=[1],
        primary_horizon=1,
        ranking_strategy="score_only",
        entry_filter_mode="grid",
    )

    scan_result = scan_entry_signal_events(request)

    assert scan_result.scanner_metrics["strategy_family_cache_build_count"] == 2
    assert scan_result.scanner_metrics["strategy_family_cache_reuse_count"] == 2
    assert scan_result.scanner_metrics["strategy_precompute_count"] == 4
    assert scan_result.scanner_metrics["strategy_fast_eval_count"] == 16
    assert scan_result.scanner_metrics["forward_return_cache_miss_count"] == 4
    assert scan_result.scanner_metrics["forward_return_cache_hit_count"] == 4
    assert scan_result.scanner_metrics["market_data_build_count"] == 0
    assert len(cache_builds) == 2
    assert len(precompute_calls) == 4
    assert len({cache_id for _strategy, _ticker, cache_id in precompute_calls}) == 2
    assert len(scan_result.candidates) == 16


def test_scan_entry_signal_events_precomputes_momentum_rank_without_market_data(
    monkeypatch,
) -> None:
    import src.entry_signal_analysis.scanner as scanner

    class _PrecomputedBuyEntry:
        strategy_name = "PrecomputedBuyEntry"

        def precompute_entry_signals(
            self,
            *,
            ticker: str,
            features: pd.DataFrame,
        ) -> dict[int, TradingSignal]:
            return {
                row_pos: TradingSignal(
                    action=SignalAction.BUY,
                    confidence=0.9,
                    reasons=["precomputed"],
                    metadata={"score": 1.0},
                    strategy_name=self.strategy_name,
                )
                for row_pos in range(len(features))
            }

    class _MomentumCache(_FakeCache):
        def __init__(self) -> None:
            dates = pd.bdate_range("2026-01-01", periods=27)
            rising = pd.Series([100.0 + index for index in range(len(dates))], index=dates)
            flat = pd.Series([100.0 for _index in range(len(dates))], index=dates)
            self.features_cache = {
                "7203": pd.DataFrame(
                    {
                        "Open": rising + 0.1,
                        "High": rising + 1.0,
                        "Low": rising - 1.0,
                        "Close": rising,
                        "Volume": 1_000_000.0,
                    },
                    index=dates,
                ),
                "6758": pd.DataFrame(
                    {
                        "Open": flat + 0.1,
                        "High": flat + 1.0,
                        "Low": flat - 1.0,
                        "Close": flat,
                        "Volume": 1_000_000.0,
                    },
                    index=dates,
                ),
            }
            self.date_pos_cache: dict[str, dict[pd.Timestamp, int]] = {}

    fake_cache = _MomentumCache()
    fake_filter = _CountingFilter()
    target_day = pd.Timestamp("2026-02-04")
    monkeypatch.setattr(scanner, "BacktestDataCache", lambda data_root: fake_cache)
    monkeypatch.setattr(scanner.EntrySecondaryFilter, "from_dict", lambda _config: fake_filter)
    monkeypatch.setattr(scanner, "resolve_filter_variants_for_request", lambda _request: [("off", {})])
    monkeypatch.setattr(scanner, "resolve_tail_guard_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_momentum_exhaustion_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "resolve_industry_filter_for_request", lambda _request: None)
    monkeypatch.setattr(scanner, "load_entry_strategy", lambda _strategy_name: _PrecomputedBuyEntry())

    request = EntrySignalAnalysisRequest(
        entry_strategies=["PrecomputedBuyEntry"],
        tickers=["7203", "6758"],
        start_date=target_day.date(),
        end_date=target_day.date(),
        horizons=[1],
        primary_horizon=1,
        ranking_strategy="momentum",
        entry_filter_mode="off",
    )

    scan_result = scan_entry_signal_events(request)

    assert scan_result.scanner_metrics["market_data_build_count"] == 0
    assert scan_result.scanner_metrics["rank_score_precompute_count"] == 2
    ranks = {
        row["ticker"]: row["rank"]
        for row in scan_result.candidates.to_dict(orient="records")
    }
    rank_scores = {
        row["ticker"]: row["rank_score"]
        for row in scan_result.candidates.to_dict(orient="records")
    }
    assert ranks["7203"] == 1
    assert ranks["6758"] == 2
    assert rank_scores["7203"] > rank_scores["6758"]
