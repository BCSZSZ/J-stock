from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.cli import evaluate as evaluate_cli
from src.evaluation.strategy_evaluator import StrategyEvaluator


def test_build_annual_continuous_periods_returns_full_span_for_multi_year_mode():
    args = SimpleNamespace(mode="annual", years=[2023, 2021, 2022])
    periods = [
        ("2021", "2021-01-01", "2021-12-31"),
        ("2022", "2022-01-01", "2022-12-31"),
        ("2023", "2023-01-01", "2023-12-31"),
    ]

    assert evaluate_cli._build_annual_continuous_periods(args, periods) == [
        ("2021-2023_continuous", "2021-01-01", "2023-12-31")
    ]


def test_annual_continuous_stability_rank_prefers_continuous_then_stability():
    segmented_df = pd.DataFrame(
        [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_A",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 10.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 20.0), ("2022", 18.0), ("2023", 19.0)]
        ]
        + [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_B",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 12.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 22.0), ("2022", -5.0), ("2023", 8.0)]
        ]
        + [
            {
                "period": period,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_C",
                "entry_filter": "off",
                "return_pct": value,
                "alpha": value - 5.0,
                "sharpe_ratio": 1.1,
                "max_drawdown_pct": 9.0,
                "num_trades": 10,
                "exit_confirmation_days": 1,
            }
            for period, value in [("2021", 21.0), ("2022", 15.0), ("2023", 14.0)]
        ]
    )

    continuous_df = pd.DataFrame(
        [
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_A",
                "entry_filter": "off",
                "return_pct": 95.0,
                "topix_return_pct": 20.0,
                "alpha": 75.0,
                "sharpe_ratio": 1.6,
                "max_drawdown_pct": 18.0,
                "num_trades": 30,
                "win_rate_pct": 55.0,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_B",
                "entry_filter": "off",
                "return_pct": 110.0,
                "topix_return_pct": 20.0,
                "alpha": 90.0,
                "sharpe_ratio": 1.4,
                "max_drawdown_pct": 24.0,
                "num_trades": 30,
                "win_rate_pct": 50.0,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2021-2023_continuous",
                "start_date": "2021-01-01",
                "end_date": "2023-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_C",
                "entry_filter": "off",
                "return_pct": 110.0,
                "topix_return_pct": 20.0,
                "alpha": 90.0,
                "sharpe_ratio": 1.5,
                "max_drawdown_pct": 20.0,
                "num_trades": 30,
                "win_rate_pct": 52.0,
                "exit_confirmation_days": 1,
            },
        ]
    )

    rank_df = evaluate_cli._build_annual_continuous_stability_rank_df(
        segmented_df=segmented_df,
        continuous_df=continuous_df,
    )

    assert rank_df["exit_strategy"].tolist() == ["MVX_C", "MVX_B", "MVX_A"]
    assert rank_df.iloc[0]["positive_years"] == 3
    assert rank_df.iloc[1]["positive_years"] == 2
    assert "year_return_2021" in rank_df.columns
    assert "year_return_2022" in rank_df.columns
    assert rank_df.iloc[0]["continuous_stability_rank"] == 1


def test_write_annual_continuous_stability_rank_writes_csv_and_report(tmp_path):
    segmented_path = tmp_path / "segmented.csv"
    continuous_path = tmp_path / "continuous.csv"

    pd.DataFrame(
        [
            {
                "period": "2021",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 12.0,
                "alpha": 6.0,
                "sharpe_ratio": 1.1,
                "max_drawdown_pct": 9.0,
                "num_trades": 8,
                "exit_confirmation_days": 1,
            },
            {
                "period": "2022",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 10.0,
                "alpha": 5.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 11.0,
                "num_trades": 9,
                "exit_confirmation_days": 1,
            },
        ]
    ).to_csv(segmented_path, index=False)

    pd.DataFrame(
        [
            {
                "period": "2021-2022_continuous",
                "start_date": "2021-01-01",
                "end_date": "2022-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p25_T1p6_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 28.0,
                "topix_return_pct": 12.0,
                "alpha": 16.0,
                "sharpe_ratio": 1.3,
                "max_drawdown_pct": 14.0,
                "num_trades": 17,
                "win_rate_pct": 58.0,
                "exit_confirmation_days": 1,
            },
        ]
    ).to_csv(continuous_path, index=False)

    files = evaluate_cli._write_annual_continuous_stability_rank(
        output_dir=str(tmp_path),
        prefix="annual_eval",
        segmented_raw_path=str(segmented_path),
        continuous_raw_path=str(continuous_path),
    )

    assert files is not None
    assert Path(files["continuous_stability_rank"]).exists()
    assert Path(files["continuous_stability_report"]).exists()


def test_precross_entries_use_feature_only_preload_flags():
    include_trades, include_financials, include_metadata = (
        StrategyEvaluator._resolve_aux_preload_flags(
            entry_strategies=["MACDPreCross2BarEntry"],
            exit_strategies=["MVX_N3_R3p25_T1p6_D21_B20p0"],
            entry_mapping={
                "MACDPreCross2BarEntry": (
                    "src.analysis.strategies.entry.macd_precross_momentum_entry."
                    "MACDPreCross2BarEntry"
                )
            },
            exit_mapping={
                "MVX_N3_R3p25_T1p6_D21_B20p0": (
                    "src.analysis.strategies.exit.multiview_grid_exit."
                    "MVX_N3_R3p25_T1p6_D21_B20p0"
                )
            },
        )
    )

    assert (include_trades, include_financials, include_metadata) == (
        False,
        False,
        False,
    )
