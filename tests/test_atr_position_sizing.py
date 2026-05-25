import pytest

from src.utils.atr_position_sizing import (
    AtrPositionSizingConfig,
    AtrSizingInput,
    calculate_atr_position_size,
    parse_portfolio_sizing_config,
)


def test_atr_position_size_uses_fixed_risk_for_nine_million_capital() -> None:
    config = AtrPositionSizingConfig(
        risk_per_trade_pct=0.006,
        atr_stop_multiple=2.0,
    )

    result = calculate_atr_position_size(
        AtrSizingInput(
            ticker="7203",
            planning_price=1000.0,
            portfolio_value_jpy=9_000_000.0,
            available_cash_jpy=9_000_000.0,
            atr_jpy=20.0,
            lot_size=100,
            config=config,
            atr_ratio=0.02,
        )
    )

    assert result.quantity == 1300
    assert result.required_capital_jpy == pytest.approx(1_300_000.0)
    assert result.risk_amount_jpy == pytest.approx(54_000.0)
    assert result.per_share_risk_jpy == pytest.approx(40.0)
    assert result.atr_ratio == pytest.approx(0.02)
    assert result.blocking_reason is None


def test_atr_position_size_respects_available_cash_after_risk_formula() -> None:
    result = calculate_atr_position_size(
        AtrSizingInput(
            ticker="7203",
            planning_price=1000.0,
            portfolio_value_jpy=9_000_000.0,
            available_cash_jpy=500_000.0,
            atr_jpy=20.0,
            lot_size=100,
            config=AtrPositionSizingConfig(),
        )
    )

    assert result.quantity == 500
    assert result.required_capital_jpy == pytest.approx(500_000.0)


def test_atr_position_size_reports_invalid_atr_without_fallback() -> None:
    result = calculate_atr_position_size(
        AtrSizingInput(
            ticker="7203",
            planning_price=1000.0,
            portfolio_value_jpy=9_000_000.0,
            available_cash_jpy=9_000_000.0,
            atr_jpy=0.0,
            lot_size=100,
            config=AtrPositionSizingConfig(),
        )
    )

    assert result.quantity == 0
    assert result.blocking_reason == "invalid_atr"


def test_parse_portfolio_sizing_config_accepts_atr_profile_overrides() -> None:
    sizing = parse_portfolio_sizing_config(
        {"max_positions": 7, "max_position_pct": 0.18},
        {
            "position_sizing_mode": "atr",
            "atr_position_sizing": {
                "risk_per_trade_pct": 0.0075,
                "atr_stop_multiple": 2.0,
            },
        },
    )

    assert sizing.mode == "atr"
    assert sizing.unlimited_positions is True
    assert sizing.max_positions == 7
    assert sizing.max_position_pct == pytest.approx(0.18)
    assert sizing.atr.risk_per_trade_pct == pytest.approx(0.0075)
