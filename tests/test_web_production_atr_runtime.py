import pytest

from web.api.routers.production import (
    _append_atr_runtime_flags,
    _append_held_position_buy_flags,
    _append_industry_filter_flags,
    _append_momentum_exhaustion_flags,
)
from web.api.schemas import ProductionDailyRequest


def test_production_daily_request_rejects_invalid_atr_runtime_fields() -> None:
    with pytest.raises(ValueError):
        ProductionDailyRequest(risk_per_trade_pct=0.0)

    with pytest.raises(ValueError):
        ProductionDailyRequest(atr_ratio_min=0.03, atr_ratio_max=0.015)


def test_production_daily_request_allows_ignored_atr_runtime_fields_when_fixed() -> None:
    req = ProductionDailyRequest(
        position_sizing_mode="fixed",
        risk_per_trade_pct=0.0,
        atr_stop_multiple=0.0,
    )

    assert req.position_sizing_mode == "fixed"


def test_production_daily_request_rejects_invalid_atr_range_when_fixed() -> None:
    with pytest.raises(ValueError):
        ProductionDailyRequest(
            position_sizing_mode="fixed",
            atr_ratio_min=0.03,
            atr_ratio_max=0.015,
        )


def test_production_daily_cli_args_include_atr_runtime_flags() -> None:
    req = ProductionDailyRequest(
        position_sizing_mode="atr",
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
        atr_ratio_min=0.015,
        atr_ratio_max=0.03,
    )
    args: list[str] = []

    _append_atr_runtime_flags(args, req)

    assert args == [
        "--position-sizing-mode",
        "atr",
        "--risk-per-trade-pct",
        "0.006",
        "--atr-stop-multiple",
        "2.0",
        "--atr-ratio-min",
        "0.015",
        "--atr-ratio-max",
        "0.03",
    ]


def test_production_daily_cli_args_ignore_atr_sizing_flags_when_fixed() -> None:
    req = ProductionDailyRequest(
        position_sizing_mode="fixed",
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
        atr_ratio_min=0.015,
        atr_ratio_max=0.03,
    )
    args: list[str] = []

    _append_atr_runtime_flags(args, req)

    assert args == [
        "--position-sizing-mode",
        "fixed",
        "--atr-ratio-min",
        "0.015",
        "--atr-ratio-max",
        "0.03",
    ]


def test_production_daily_cli_args_send_none_for_explicit_blank_atr_bounds() -> None:
    req = ProductionDailyRequest(atr_ratio_min=None, atr_ratio_max=None)
    args: list[str] = []

    _append_atr_runtime_flags(args, req)

    assert args == [
        "--atr-ratio-min",
        "none",
        "--atr-ratio-max",
        "none",
    ]


def test_production_daily_cli_args_include_momentum_exhaustion_flags() -> None:
    req = ProductionDailyRequest(
        momentum_exhaustion_mode="enforce",
        momentum_exhaustion_max_score=4.0,
    )
    args: list[str] = []

    _append_momentum_exhaustion_flags(args, req)

    assert args == [
        "--momentum-exhaustion-mode",
        "enforce",
        "--momentum-exhaustion-max-score",
        "4.0",
        "--momentum-exhaustion-threshold-method",
        "absolute",
    ]


def test_production_daily_cli_args_include_industry_filter_flags() -> None:
    req = ProductionDailyRequest(
        industry_filter_mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        industry_reference_file="data/jpx_final_list.csv",
    )
    args: list[str] = []

    _append_industry_filter_flags(args, req)

    assert args == [
        "--industry-filter-mode",
        "enforce",
        "--max-buy-per-industry-per-day",
        "1",
        "--max-total-positions-per-industry",
        "3",
        "--industry-reference-file",
        "data/jpx_final_list.csv",
    ]


def test_production_daily_cli_args_include_allow_held_position_buys_flag() -> None:
    req = ProductionDailyRequest(allow_held_position_buys=True)
    args: list[str] = []

    _append_held_position_buy_flags(args, req)

    assert args == ["--allow-held-position-buys"]
