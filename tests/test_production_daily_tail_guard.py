from types import SimpleNamespace

from src.cli.production_daily import (
    _calculate_add_on_order_value_cap,
    _count_positive_rank_scores,
    _exclude_same_ticker_sell_proceeds_for_add_on,
    _restore_projected_position_count_for_cancelled_add_on_sell,
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


def test_tail_guard_rank_limit_supports_min_mode() -> None:
    raw_config = {
        "production": {
            "tail_guard": {
                "enabled": True,
                "max_rank": 12,
                "rank_limit_mode": "min",
            }
        }
    }

    assert (
        _resolve_tail_guard_rank_limit(
            raw_config=raw_config,
            positive_rank_score_count=4,
        )
        == 4
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


def test_add_on_order_value_cap_uses_remaining_single_ticker_headroom() -> None:
    cap = _calculate_add_on_order_value_cap(
        total_portfolio_value=1_000_000.0,
        max_position_pct=0.20,
        signal_buy_scale=0.50,
        existing_position_value=60_000.0,
    )

    assert cap == 40_000.0


def test_add_on_order_value_cap_is_zero_when_existing_position_exceeds_target() -> None:
    cap = _calculate_add_on_order_value_cap(
        total_portfolio_value=1_000_000.0,
        max_position_pct=0.10,
        signal_buy_scale=1.0,
        existing_position_value=120_000.0,
    )

    assert cap == 0.0


def test_add_on_sizing_excludes_same_ticker_projected_sell_cash() -> None:
    cash, invested = _exclude_same_ticker_sell_proceeds_for_add_on(
        planning_cash=500_000.0,
        planning_invested_value=300_000.0,
        same_ticker_projected_sell_value=120_000.0,
        is_add_on_buy=True,
    )

    assert cash == 380_000.0
    assert invested == 420_000.0


def test_new_position_sizing_keeps_projected_sell_cash_available() -> None:
    cash, invested = _exclude_same_ticker_sell_proceeds_for_add_on(
        planning_cash=500_000.0,
        planning_invested_value=300_000.0,
        same_ticker_projected_sell_value=120_000.0,
        is_add_on_buy=False,
    )

    assert cash == 500_000.0
    assert invested == 300_000.0


def test_cancelled_full_sell_restores_projected_position_count() -> None:
    count, tickers = _restore_projected_position_count_for_cancelled_add_on_sell(
        projected_position_count=2,
        projected_existing_tickers={"8306", "8411"},
        ticker="7203",
    )

    assert count == 3
    assert tickers == {"7203", "8306", "8411"}


def test_cancelled_partial_sell_does_not_double_count_existing_ticker() -> None:
    count, tickers = _restore_projected_position_count_for_cancelled_add_on_sell(
        projected_position_count=3,
        projected_existing_tickers={"7203", "8306", "8411"},
        ticker="7203",
    )

    assert count == 3
    assert tickers == {"7203", "8306", "8411"}
