from pathlib import Path

from src.production.report_builder import AbnormalSignalTicker, ReportBuilder
from src.production.signal_generator import Signal
from src.production.state_manager import ProductionState


class MockDataManager:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.data_dir = data_root


def test_report_lists_abnormal_signal_exclusions(tmp_path: Path) -> None:
    state = ProductionState(state_file=str(tmp_path / "state.json"))
    state.add_group(
        group_id="core",
        name="Core Strategy",
        initial_capital=1_000_000.0,
    )
    builder = ReportBuilder(state, MockDataManager(tmp_path))

    report = builder.generate_daily_report(
        signals=[],
        report_date="2026-05-11",
        abnormal_tickers=[
            AbnormalSignalTicker(
                ticker="4530",
                ticker_name="久光製薬",
                latest_data_date="2026-05-08",
                expected_date="2026-05-11",
                lag_days=3,
                exclusion_reason="Missing feature data for selected signal date",
                held_by_groups=("Core Strategy",),
            )
        ],
    )

    assert "## ⚠️ Abnormal Signal Exclusions" in report
    assert "| 4530 | 久光製薬 | 2026-05-08 | 2026-05-11 | 3d | Core Strategy | Missing feature data for selected signal date |" in report


def test_report_renders_sell_execution_guidance(tmp_path: Path) -> None:
    state = ProductionState(state_file=str(tmp_path / "state.json"))
    state.add_group(
        group_id="core",
        name="Core Strategy",
        initial_capital=1_000_000.0,
    )
    builder = ReportBuilder(state, MockDataManager(tmp_path))

    tp_signal = Signal(
        group_id="core",
        ticker="7203",
        ticker_name="Toyota",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.7,
        score=0.0,
        reason="TP1 hit: +1.0R",
        current_price=1000.0,
        close_price=1000.0,
        planned_price=980.0,
        sell_price_factor=0.98,
        position_qty=200,
        planned_sell_qty=100,
        planned_sell_value=98000.0,
        strategy_name="MultiViewGridExit",
        exit_trigger="P_TP1",
        execution_intent="止盈兑现",
        execution_method="OCO（利確優先）",
        execution_summary="OCO1 指値 ¥985.00 + 不成 / OCO2 ¥928.00 触发后成行",
        execution_period="当日中",
        broker_order_type="OCO",
        oco1_price=985.0,
        oco1_condition="不成",
        oco2_trigger_price=928.0,
        oco2_order_mode="逆指値成行",
        formula_basis="TP1: OCO1=max(0.985C, C-0.5A), OCO2=C-1.8A; C=1000.00, A=40.00",
        guidance_notes="先兑现一半；若价格走弱，则由逆指値成行保护剩余仓位。",
    )
    risk_signal = Signal(
        group_id="core",
        ticker="6758",
        ticker_name="Sony",
        signal_type="SELL",
        action="SELL_100%",
        confidence=1.0,
        score=0.0,
        reason="Hard stop",
        current_price=2000.0,
        close_price=2000.0,
        sell_price_factor=0.98,
        position_qty=100,
        planned_sell_qty=100,
        planned_sell_value=196000.0,
        strategy_name="ATRExitStrategy",
        exit_trigger="P0_HardStop",
        execution_intent="风险退出",
        execution_method="Immediate Exit",
        execution_summary="成行 / 引成で当日退出を优先",
        execution_period="当日中",
        broker_order_type="通常注文",
        formula_basis="Risk exit: prioritize same-day liquidation over rebound-first OCO.",
        guidance_notes="反弹待ちをしない。寄付前なら寄成、場中なら成行を优先。",
    )

    report = builder.generate_daily_report(
        signals=[tp_signal, risk_signal],
        report_date="2026-05-12",
    )
    final_picks = builder._build_final_picks({}, [tp_signal])

    assert "| Urgency | Ticker | Action | Intent | Order | Plan | Trigger | Period | Reason |" in report
    assert "| 🚨 EMERGENCY | **6758** | SELL_100% | 风险退出 | Immediate Exit | 成行 / 引成で当日退出を优先 | P0_HardStop | 当日中 | Hard stop |" in report
    assert "- **Intent:** 风险退出" in report
    assert "- **Exit Trigger:** P0_HardStop" in report
    assert "- **Order:** Immediate Exit" in report

    assert "| Rank | Ticker | Name | Action | Intent | Order | Plan | Trigger | Period | Sell Qty | Est. Proceeds (¥) | Notes | Reason |" in final_picks
    assert "| 1 | 7203 | 7203 | SELL_50% | 止盈兑现 | OCO（利確優先） | 指値 ¥985.00 + 不成 | ¥928.00 / 逆指値成行 | 当日中 | 100 | 98,000 | 先兑现一半；若价格走弱，则由逆指値成行保护剩余仓位。 | TP1 hit: +1.0R |" in final_picks