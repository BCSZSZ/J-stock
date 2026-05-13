from src.cli.production_daily import (
    _apply_signal_semantic_metadata,
    _build_sell_execution_guidance,
    _derive_signal_semantic_metadata,
)
from src.production.signal_generator import Signal


def test_signal_semantics_for_executable_buy() -> None:
    signal = Signal(
        group_id="core",
        ticker="8306",
        ticker_name="MUFG",
        signal_type="BUY",
        action="BUY",
        confidence=0.66,
        score=0.0,
        reason="momentum buy",
        current_price=1000.0,
        suggested_qty=100,
        required_capital=100000.0,
        rank=2,
        rank_score=3.14,
        strategy_name="MACDPreCross2BarEntry",
    )

    semantics = _derive_signal_semantic_metadata(signal)

    assert semantics.momentum_rank == 2
    assert semantics.momentum_value == 3.14
    assert semantics.is_executable is True
    assert semantics.is_executable_buy is True
    assert semantics.is_executable_sell is False


def test_signal_semantics_for_partial_sell() -> None:
    signal = Signal(
        group_id="core",
        ticker="7974",
        ticker_name="Nintendo",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.0,
        score=0.0,
        reason="trim",
        current_price=5000.0,
        position_qty=200,
        planned_sell_qty=100,
        planned_sell_value=500000.0,
        strategy_name="LayeredExit",
        exit_trigger="P_TP1",
        execution_intent="止盈兑现",
        execution_method="OCO（利確優先）",
        execution_summary="OCO1 指値 ¥5,050.00 + 不成 / OCO2 ¥4,850.00 触发后成行",
        execution_period="当日中",
        broker_order_type="OCO",
        oco1_price=5050.0,
        oco1_condition="不成",
        oco2_trigger_price=4850.0,
        oco2_order_mode="逆指値成行",
        formula_basis="TP1: OCO1=max(0.985C, C-0.5A), OCO2=C-1.8A",
        guidance_notes="先兑现一半；若价格走弱，则由逆指値成行保护剩余仓位。",
    )

    enriched = _apply_signal_semantic_metadata([signal])[0]

    assert enriched.momentum_rank is None
    assert enriched.momentum_value is None
    assert enriched.is_executable is True
    assert enriched.is_executable_buy is False
    assert enriched.is_executable_sell is True
    assert enriched.exit_trigger == "P_TP1"
    assert enriched.execution_intent == "止盈兑现"
    assert enriched.execution_method == "OCO（利確優先）"
    assert enriched.oco1_price == 5050.0
    assert enriched.oco2_trigger_price == 4850.0


def test_build_sell_execution_guidance_for_take_profit_uses_oco() -> None:
    guidance = _build_sell_execution_guidance(
        action="SELL_50%",
        trigger="P_TP1",
        reason="TP1 hit: +1.0R",
        close_price=1000.0,
        atr_value=40.0,
        sell_price_factor=0.98,
    )

    assert guidance.exit_trigger == "P_TP1"
    assert guidance.execution_intent == "止盈兑现"
    assert guidance.execution_method == "OCO（利確優先）"
    assert guidance.broker_order_type == "OCO"
    assert guidance.oco1_condition == "不成"
    assert guidance.oco2_order_mode == "逆指値成行"
    assert guidance.execution_period == "当日中"
    assert guidance.oco1_price == 985.0
    assert guidance.oco2_trigger_price == 928.0