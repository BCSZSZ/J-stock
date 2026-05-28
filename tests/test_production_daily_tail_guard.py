from types import SimpleNamespace

from src.cli.production_daily import (
    _count_positive_rank_scores,
    _resolve_tail_guard_rank_limit,
)


def test_tail_guard_rank_limit_is_disabled_by_default() -> None:
    assert (
        _resolve_tail_guard_rank_limit(
            raw_config={"production": {}},
            positive_rank_score_count=0,
        )
        is None
    )


def test_tail_guard_rank_limit_uses_positive_rank_score_count_when_it_is_larger() -> None:
    raw_config = {
        "production": {
            "tail_guard": {
                "enabled": True,
                "max_rank": 12,
            }
        }
    }

    assert (
        _resolve_tail_guard_rank_limit(
            raw_config=raw_config,
            positive_rank_score_count=15,
        )
        == 15
    )


def test_tail_guard_rank_limit_uses_base_rank_when_positive_rank_count_is_smaller() -> None:
    raw_config = {
        "production": {
            "tail_guard": {
                "enabled": True,
                "max_rank": 12,
            }
        }
    }

    assert (
        _resolve_tail_guard_rank_limit(
            raw_config=raw_config,
            positive_rank_score_count=4,
        )
        == 12
    )


def test_count_positive_rank_scores_counts_only_strictly_positive_values() -> None:
    signals = [
        SimpleNamespace(rank_score=2.5),
        SimpleNamespace(rank_score=0.0),
        SimpleNamespace(rank_score=-1.0),
        SimpleNamespace(rank_score=None),
        SimpleNamespace(rank_score="3.1"),
        SimpleNamespace(rank_score="bad"),
    ]

    assert _count_positive_rank_scores(signals) == 2