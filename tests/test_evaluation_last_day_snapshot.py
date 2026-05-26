from src.evaluation.strategy_evaluator import StrategyEvaluator


def test_last_day_snapshot_dataframes_include_signals_and_positions(tmp_path) -> None:
    evaluator = StrategyEvaluator(output_dir=str(tmp_path))
    evaluator.evaluation_run_snapshots = [
        {
            "period": "2026",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "snapshot_date": "2026-05-20",
            "entry_strategy": "EntryA",
            "exit_strategy": "ExitB",
            "entry_filter": "off",
            "ranking_strategy": "momentum",
            "next_pending_buy_signals": [
                {
                    "ticker": "8306",
                    "action": "BUY",
                    "confidence": 0.66,
                    "reasons": ["buy reason"],
                    "metadata": {"score": 80.0},
                    "strategy_name": "EntryA",
                }
            ],
            "next_pending_sell_signals": [],
            "final_cash_jpy": 123456.0,
            "final_open_positions": [
                {
                    "ticker": "7241",
                    "quantity": 500,
                    "entry_date": "2026-05-18",
                    "entry_price": 1044.7,
                    "signal_entry_price": 1042.0,
                    "peak_price": 1044.7,
                    "current_price": 1038.0,
                    "market_value": 519000.0,
                }
            ],
        }
    ]

    signal_df = evaluator._create_last_day_signal_dataframe()
    position_df = evaluator._create_last_day_position_dataframe()

    assert len(signal_df) == 1
    assert signal_df.iloc[0]["snapshot_date"] == "2026-05-20"
    assert signal_df.iloc[0]["signal_type"] == "BUY"
    assert signal_df.iloc[0]["ticker"] == "8306"

    assert len(position_df) == 1
    assert position_df.iloc[0]["snapshot_date"] == "2026-05-20"
    assert position_df.iloc[0]["ticker"] == "7241"
    assert position_df.iloc[0]["signal_entry_price"] == 1042.0


def test_daily_snapshot_output_is_sanitized_without_mutating_runtime_state(tmp_path) -> None:
    evaluator = StrategyEvaluator(output_dir=str(tmp_path))
    evaluator.evaluation_daily_snapshots = [
        {
            "period": "2026",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "entry_strategy": "EntryA",
            "exit_strategy": "ExitB",
            "entry_filter": "off",
            "ranking_strategy": "momentum",
            "daily_snapshots": [
                {
                    "date": "2026-05-19",
                    "cash_jpy": 100000.0,
                    "total_equity_jpy": 8200000.0,
                    "pending_buy_signals": [
                        {
                            "ticker": "8306",
                            "action": "BUY",
                            "confidence": 0.66,
                            "reasons": ["buy reason"],
                            "metadata": {"score": 80.0},
                            "strategy_name": "EntryA",
                        }
                    ],
                    "pending_sell_signals": [],
                    "open_positions": [
                        {
                            "ticker": "7241",
                            "quantity": 500,
                            "entry_date": "2026-05-18",
                            "entry_price": 1044.7,
                            "signal_entry_price": 1042.0,
                            "peak_price": 1044.7,
                            "current_price": 1038.0,
                            "market_value": 519000.0,
                        }
                    ],
                }
            ],
        }
    ]

    position_df = evaluator._create_daily_position_dataframe()
    snapshot_output = evaluator._create_daily_snapshot_output(
        evaluator.evaluation_daily_snapshots
    )

    assert "period" not in snapshot_output[0]
    output_signal = snapshot_output[0]["daily_snapshots"][0]["pending_buy_signals"][0]
    assert output_signal["ticker"] == "8306"
    assert output_signal["metadata"] == {"score": 80.0}
    assert "reasons" not in output_signal

    runtime_signal = evaluator.evaluation_daily_snapshots[0]["daily_snapshots"][0][
        "pending_buy_signals"
    ][0]
    assert runtime_signal["reasons"] == ["buy reason"]

    assert len(position_df) == 1
    assert position_df.iloc[0]["snapshot_date"] == "2026-05-19"
    assert position_df.iloc[0]["ticker"] == "7241"
    assert position_df.iloc[0]["cash_jpy"] == 100000.0