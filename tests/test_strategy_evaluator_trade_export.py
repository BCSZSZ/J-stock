from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.backtest.models import Trade
from src.evaluation.strategy_evaluator import AnnualStrategyResult, StrategyEvaluator


def _make_trade(
    *,
    ticker: str,
    exit_urgency: str,
    exit_reason: str,
    return_pct: float,
    return_jpy: float,
    holding_days: int,
    shares: int,
    before_qty: int,
    after_qty: int,
    sell_pct: float,
    is_full_exit: bool,
) -> Trade:
    return Trade(
        ticker=ticker,
        entry_date="2025-01-10",
        entry_price=100.0,
        entry_score=72.0,
        entry_confidence=0.8,
        entry_metadata={"score": 72.0},
        exit_date="2025-01-20",
        exit_price=110.0,
        exit_reason=exit_reason,
        exit_urgency=exit_urgency,
        holding_days=holding_days,
        shares=shares,
        return_pct=return_pct,
        return_jpy=return_jpy,
        peak_price=112.0,
        position_quantity_before_exit=before_qty,
        position_quantity_after_exit=after_qty,
        exit_sell_percentage=sell_pct,
        exit_is_full_exit=is_full_exit,
        exit_metadata={"trigger": exit_urgency, "sell_percentage": sell_pct},
    )


def test_record_trade_rows_captures_partial_and_full_exit_flags(tmp_path):
    evaluator = StrategyEvaluator(output_dir=str(tmp_path), verbose=False)
    result = SimpleNamespace(
        trades=[
            _make_trade(
                ticker="7203",
                exit_urgency="P_TP1",
                exit_reason="TP1 hit: +1.0R",
                return_pct=5.0,
                return_jpy=5000.0,
                holding_days=10,
                shares=100,
                before_qty=200,
                after_qty=100,
                sell_pct=0.5,
                is_full_exit=False,
            ),
            _make_trade(
                ticker="7203",
                exit_urgency="P_TP2",
                exit_reason="TP2 hit: +2.0R",
                return_pct=9.0,
                return_jpy=9000.0,
                holding_days=15,
                shares=100,
                before_qty=100,
                after_qty=0,
                sell_pct=1.0,
                is_full_exit=True,
            ),
        ]
    )

    evaluator._record_trade_rows(
        result=result,
        period_label="2025",
        start_date="2025-01-01",
        end_date="2025-12-31",
        topix_return=12.0,
        entry_strategy="MACDCrossoverStrategy",
        exit_strategy="MVX_N2_R3p4_T1p6_D18_B20p0",
        entry_filter_name="default",
    )

    trade_df = evaluator._create_trade_results_dataframe()

    assert len(trade_df) == 2

    tp1_row = trade_df[trade_df["exit_urgency"] == "P_TP1"].iloc[0]
    assert bool(tp1_row["exit_is_full_exit"]) is False
    assert bool(tp1_row["exit_is_partial_exit"]) is True
    assert float(tp1_row["exit_sell_percentage"]) == 0.5

    tp2_row = trade_df[trade_df["exit_urgency"] == "P_TP2"].iloc[0]
    assert bool(tp2_row["exit_is_full_exit"]) is True
    assert bool(tp2_row["exit_is_partial_exit"]) is False
    assert float(tp2_row["exit_sell_percentage"]) == 1.0


def test_save_results_writes_trade_exports_and_filters_partial_exits(tmp_path):
    evaluator = StrategyEvaluator(output_dir=str(tmp_path), verbose=False)
    evaluator.results = [
        AnnualStrategyResult(
            period="2025",
            start_date="2025-01-01",
            end_date="2025-12-31",
            entry_strategy="MACDCrossoverStrategy",
            exit_strategy="MVX_N2_R3p4_T1p6_D18_B20p0",
            entry_filter="default",
            return_pct=25.0,
            topix_return_pct=12.0,
            alpha=13.0,
            sharpe_ratio=1.5,
            max_drawdown_pct=10.0,
            num_trades=3,
            win_rate_pct=60.0,
            avg_gain_pct=8.0,
            avg_loss_pct=-4.0,
            exit_confirmation_days=2,
        )
    ]
    evaluator.trade_results = [
        {
            "period": "2025",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "market_regime": "温和牛市 (TOPIX 0-25%)",
            "topix_return_pct": 12.0,
            "entry_strategy": "MACDCrossoverStrategy",
            "exit_strategy": "MVX_N2_R3p4_T1p6_D18_B20p0",
            "entry_filter": "default",
            "exit_confirmation_days": 2,
            "ticker": "7203",
            "entry_date": "2025-01-10",
            "entry_price": 100.0,
            "entry_score": 72.0,
            "entry_confidence": 0.8,
            "entry_metadata_json": "{}",
            "exit_date": "2025-01-20",
            "exit_price": 105.0,
            "exit_reason": "TP1 hit: +1.0R",
            "exit_urgency": "P_TP1",
            "holding_days": 10,
            "shares": 100,
            "return_pct": 5.0,
            "return_jpy": 5000.0,
            "peak_price": 106.0,
            "position_quantity_before_exit": 200,
            "position_quantity_after_exit": 0,
            "exit_sell_percentage": 0.5,
            "exit_is_full_exit": True,
            "exit_is_partial_exit": False,
            "exit_metadata_json": '{"sell_percentage": 0.5, "trigger": "P_TP1"}',
        },
        {
            "period": "2025",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "market_regime": "温和牛市 (TOPIX 0-25%)",
            "topix_return_pct": 12.0,
            "entry_strategy": "MACDCrossoverStrategy",
            "exit_strategy": "MVX_N2_R3p4_T1p6_D18_B20p0",
            "entry_filter": "default",
            "exit_confirmation_days": 2,
            "ticker": "7203",
            "entry_date": "2025-01-10",
            "entry_price": 100.0,
            "entry_score": 72.0,
            "entry_confidence": 0.8,
            "entry_metadata_json": "{}",
            "exit_date": "2025-02-10",
            "exit_price": 109.0,
            "exit_reason": "TP2 hit: +2.0R",
            "exit_urgency": "P_TP2",
            "holding_days": 20,
            "shares": 100,
            "return_pct": 9.0,
            "return_jpy": 9000.0,
            "peak_price": 112.0,
            "position_quantity_before_exit": 100,
            "position_quantity_after_exit": 0,
            "exit_sell_percentage": 1.0,
            "exit_is_full_exit": True,
            "exit_is_partial_exit": False,
            "exit_metadata_json": '{"sell_percentage": 1.0, "trigger": "P_TP2"}',
        },
        {
            "period": "2025",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
            "market_regime": "温和牛市 (TOPIX 0-25%)",
            "topix_return_pct": 12.0,
            "entry_strategy": "MACDCrossoverStrategy",
            "exit_strategy": "MVX_N2_R3p4_T1p6_D18_B20p0",
            "entry_filter": "default",
            "exit_confirmation_days": 2,
            "ticker": "6501",
            "entry_date": "2025-03-01",
            "entry_price": 200.0,
            "entry_score": 68.0,
            "entry_confidence": 0.75,
            "entry_metadata_json": "{}",
            "exit_date": "2025-03-18",
            "exit_price": 210.0,
            "exit_reason": "L2 histogram shrink x2",
            "exit_urgency": "L2_HistShrink",
            "holding_days": 17,
            "shares": 100,
            "return_pct": 5.0,
            "return_jpy": 10000.0,
            "peak_price": 212.0,
            "position_quantity_before_exit": 100,
            "position_quantity_after_exit": 0,
            "exit_sell_percentage": 1.0,
            "exit_is_full_exit": True,
            "exit_is_partial_exit": False,
            "exit_metadata_json": '{"sell_percentage": 1.0, "trigger": "L2_HistShrink"}',
        },
    ]

    files = evaluator.save_results(prefix="unit_eval")

    trades_path = Path(files["trades"])
    summary_path = Path(files["exit_trigger_summary"])
    assert trades_path.exists()
    assert summary_path.exists()

    trades_df = pd.read_csv(trades_path)
    summary_df = pd.read_csv(summary_path)
    recomputed_df = StrategyEvaluator.build_exit_trigger_summary_df(
        trades_df,
        full_exit_only=True,
    )

    assert set(trades_df["exit_urgency"]) == {"P_TP1", "P_TP2", "L2_HistShrink"}
    assert "P_TP1" not in set(summary_df["exit_urgency"])
    assert "P_TP1" not in set(recomputed_df["exit_urgency"])
    assert set(summary_df["exit_urgency"]) == {"P_TP2", "L2_HistShrink"}
    assert set(summary_df["trade_scope"]) == {"full_sell_signal_only"}