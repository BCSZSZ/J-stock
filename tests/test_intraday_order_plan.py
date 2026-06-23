import pytest

from src.production.intraday_order_plan import (
    IntradayOrderPlanInput,
    build_intraday_order_plan,
    build_intraday_signal_candidate,
)


def test_build_intraday_order_plan_uses_actual_fill_as_anchor() -> None:
    plan = build_intraday_order_plan(
        IntradayOrderPlanInput(
            ticker="6674",
            quantity=200,
            actual_entry_price=7156.32,
            atr_value=358.12962963,
            r_multiple=0.54,
            trail_multiple=1.0,
            initial_stop_multiple=0.55,
        )
    )

    assert plan.r_value == pytest.approx(193.39)
    assert plan.tp1_price == pytest.approx(7349.71)
    assert plan.tp2_price == pytest.approx(7543.10)
    assert plan.tp1_quantity == 100
    assert plan.remaining_quantity_after_tp1 == 100
    assert plan.initial_stop_price == pytest.approx(6959.35)
    assert plan.dynamic_trail_price == pytest.approx(6798.19)
    assert plan.stop_trigger_price == pytest.approx(6959.35)
    assert plan.stop_limit_price == pytest.approx(6905.63)


def test_build_intraday_order_plan_updates_trailing_reference_from_high() -> None:
    plan = build_intraday_order_plan(
        IntradayOrderPlanInput(
            ticker="6674",
            quantity=200,
            actual_entry_price=7156.32,
            high_since_buy=7600.0,
            atr_value=358.12962963,
            r_multiple=0.54,
            trail_multiple=1.0,
            initial_stop_multiple=0.55,
        )
    )

    assert plan.initial_stop_price == pytest.approx(6959.35)
    assert plan.dynamic_trail_price == pytest.approx(7241.87)
    assert plan.stop_trigger_price == pytest.approx(7241.87)
    assert plan.stop_limit_price == pytest.approx(7188.15)


def test_build_intraday_signal_candidate_extracts_mvxwl_params() -> None:
    signal = {
        "signal_type": "BUY",
        "is_executable_buy": True,
        "ticker": "6674",
        "group_id": "group_main",
        "ticker_name": "GS Yuasa",
        "industry_name": "電気機器",
        "suggested_qty": 200,
        "current_price": 7016.0,
        "planned_price": 7156.32,
        "rank": 1,
        "rank_score": 11.03,
        "signal_metadata": {
            "ATR": 358.12962963,
            "bound_exit_strategy_name": "MVXWL_N3_R0p54_T1p0_D14_B20p0_I0p55",
        },
    }

    candidate = build_intraday_signal_candidate(
        signal,
        exit_strategy_by_group={},
        default_exit_strategy=None,
    )

    assert candidate is not None
    assert candidate.can_plan is True
    assert candidate.default_entry_price == pytest.approx(7156.32)
    assert candidate.reference_price == pytest.approx(7016.0)
    assert candidate.atr_value == pytest.approx(358.12962963)
    assert candidate.r_multiple == pytest.approx(0.54)
    assert candidate.trail_multiple == pytest.approx(1.0)
    assert candidate.initial_stop_multiple == pytest.approx(0.55)


def test_build_intraday_signal_candidate_derives_atr_from_ratio() -> None:
    signal = {
        "signal_type": "BUY",
        "ticker": "7012",
        "suggested_qty": 100,
        "close_price": 3191.0,
        "signal_metadata": {"ATR_Ratio": 0.04},
    }

    candidate = build_intraday_signal_candidate(
        signal,
        exit_strategy_by_group={"": "MVXWL_N3_R0p54_T1p0_D14_B20p0_I0p55"},
        default_exit_strategy=None,
    )

    assert candidate is not None
    assert candidate.atr_value == pytest.approx(127.64)
    assert candidate.can_plan is True
