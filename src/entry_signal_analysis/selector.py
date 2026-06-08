from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.analysis.signals import MarketData, TradingSignal
from src.utils.strategy_loader import load_ranking_strategy
from src.utils.tail_guard import (
    count_positive_priority_scores,
    resolve_tail_guard_rank_limit,
)
from src.utils.momentum_exhaustion import (
    MomentumExhaustionConfig,
    evaluate_momentum_exhaustion,
)
from src.utils.industry_filter import (
    IndustryFilterConfig,
    evaluate_industry_filter_for_ranked_tickers,
    normalize_ticker_code,
)


@dataclass(frozen=True)
class DailyEntryCandidate:
    ticker: str
    entry_strategy: str
    signal_date: str
    signal: TradingSignal
    market_data: MarketData | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)


def _build_ranking_inputs(
    candidates: Sequence[DailyEntryCandidate],
) -> tuple[dict[str, TradingSignal], dict[str, MarketData]]:
    signals: dict[str, TradingSignal] = {}
    market_data_dict: dict[str, MarketData] = {}
    for candidate in candidates:
        if candidate.ticker in signals:
            raise ValueError(
                "daily entry candidate set must not contain duplicate tickers "
                f"within one strategy/date group: {candidate.ticker}"
            )
        signals[candidate.ticker] = candidate.signal
        if candidate.market_data is not None:
            market_data_dict[candidate.ticker] = candidate.market_data
    return signals, market_data_dict


def select_daily_candidates(
    candidates: Sequence[DailyEntryCandidate],
    ranking_strategy_name: str,
    tail_guard_config: Mapping[str, object] | None,
    momentum_exhaustion_config: MomentumExhaustionConfig | Mapping[str, object] | None = None,
    industry_filter_config: IndustryFilterConfig | Mapping[str, object] | None = None,
) -> list[dict[str, Any]]:
    if not candidates:
        return []

    signals, market_data_dict = _build_ranking_inputs(candidates)
    ranker = load_ranking_strategy(ranking_strategy_name or "default")
    ranked = ranker.rank_buy_signals(signals, market_data_dict)
    positive_rank_score_count = count_positive_priority_scores(ranked)
    tail_guard_limit = resolve_tail_guard_rank_limit(
        tail_guard_config,
        positive_rank_score_count=positive_rank_score_count,
    )
    rank_map: dict[str, tuple[int, float]] = {
        ticker: (index + 1, float(priority))
        for index, (ticker, _signal, priority) in enumerate(ranked)
    }
    industry_decisions = evaluate_industry_filter_for_ranked_tickers(
        [ticker for ticker, _signal, _priority in ranked],
        industry_filter_config,
        existing_position_tickers=None,
    )

    annotated: list[dict[str, Any]] = []
    ranking_name = str(ranking_strategy_name or "default")
    for candidate in candidates:
        rank, rank_score = rank_map.get(candidate.ticker, (None, None))
        exhaustion_decision = evaluate_momentum_exhaustion(
            rank_score,
            momentum_exhaustion_config,
        )
        selected = rank is not None and (
            tail_guard_limit is None or rank <= tail_guard_limit
        ) and not exhaustion_decision.filtered
        industry_decision = industry_decisions.get(normalize_ticker_code(candidate.ticker))
        if industry_decision is not None and industry_decision.filtered:
            selected = False
        record = dict(candidate.payload)
        record.update({
            "ticker": candidate.ticker,
            "entry_strategy": candidate.entry_strategy,
            "signal_date": candidate.signal_date,
            "rank": rank,
            "rank_score": rank_score,
            "positive_rank_score": bool(
                rank_score is not None and float(rank_score) > 0
            ),
            "positive_rank_score_count": int(positive_rank_score_count),
            "tail_guard_limit": tail_guard_limit,
            "selected": selected,
            "ranking_strategy": ranking_name,
        })
        record.update(exhaustion_decision.to_metadata())
        if industry_decision is not None:
            record.update(industry_decision.to_metadata())
        annotated.append(record)

    return annotated
