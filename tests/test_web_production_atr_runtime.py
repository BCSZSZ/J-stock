import pytest

from web.api.routers.production import _append_atr_runtime_flags
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
        atr_ratio_min=0.03,
        atr_ratio_max=0.015,
    )

    assert req.position_sizing_mode == "fixed"


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


def test_production_daily_cli_args_ignore_atr_runtime_flags_when_fixed() -> None:
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
    ]
