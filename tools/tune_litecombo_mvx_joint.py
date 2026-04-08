"""Screen and validate joint LiteCombo + MVX combinations against MACD baseline."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.data_cache import BacktestDataCache
from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.evaluation.strategy_evaluator import StrategyEvaluator
from src.utils.strategy_loader import (
    ENTRY_STRATEGIES,
    EXIT_STRATEGIES,
    load_entry_strategy,
    load_exit_strategy,
)

SCREEN_PERIOD = ("2023-01-01", "2025-12-31")
VALIDATION_PERIOD = ("2021-01-01", "2025-12-31")
TOP_K = 3

ENTRY_VARIANTS = [
    {
        "label": "LC_ref",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_hist_abs_norm": 0.010,
            "min_adx_14": 10.0,
            "max_return_5d": 0.08,
        },
    },
    {
        "label": "LC_adx12",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_hist_abs_norm": 0.010,
            "min_adx_14": 12.0,
            "max_return_5d": 0.08,
        },
    },
]

EXIT_VARIANTS = [
    "MVX_N3_R3p25_T1p6_D21_B20p0",
    "MVX_N3_R3p25_T1p6_D18_B20p0",
    "MVX_N3_R3p2_T1p6_D21_B20p0",
]


def _run_combo(
    tickers,
    starting_capital,
    max_positions,
    max_position_pct,
    cache,
    start_date: str,
    end_date: str,
    entry_name: str,
    entry_params: dict,
    exit_name: str,
):
    engine = PortfolioBacktestEngine(
        data_root="data",
        starting_capital=starting_capital,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        preloaded_cache=cache,
    )
    result = engine.backtest_portfolio_strategy(
        tickers=tickers,
        entry_strategy=load_entry_strategy(entry_name, entry_params),
        exit_strategy=load_exit_strategy(exit_name),
        start_date=start_date,
        end_date=end_date,
        show_daily_status=False,
        show_signal_ranking=False,
        show_signal_details=False,
        compute_benchmark=False,
    )
    return {
        "total_return_pct": result.total_return_pct,
        "annualized_return_pct": result.annualized_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "num_trades": result.num_trades,
        "win_rate_pct": result.win_rate_pct,
        "avg_holding_days": result.avg_holding_days,
        "profit_factor": result.profit_factor,
    }


def _score(df: pd.DataFrame) -> pd.Series:
    return (
        pd.to_numeric(df["annualized_return_pct"], errors="coerce")
        + 10.0 * pd.to_numeric(df["sharpe_ratio"], errors="coerce")
        - 0.5 * pd.to_numeric(df["max_drawdown_pct"], errors="coerce")
    )


def _df_to_markdown(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "strategy_evaluation" / f"litecombo_mvx_joint_tuning_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = StrategyEvaluator(data_root="data", output_dir=str(output_dir), verbose=False)
    tickers = evaluator._load_monitor_list()
    starting_capital = evaluator._get_starting_capital()
    max_positions, max_position_pct = evaluator._get_portfolio_limits()

    include_trades, include_financials, include_metadata = evaluator._resolve_aux_preload_flags(
        entry_strategies=["MACDCrossoverStrategy", "MACDPreCrossMomentumEntry"],
        exit_strategies=EXIT_VARIANTS,
        entry_mapping=ENTRY_STRATEGIES,
        exit_mapping=EXIT_STRATEGIES,
    )

    screen_cache = BacktestDataCache(data_root="data")
    screen_cache.preload_tickers(
        tickers=tickers,
        start_date=SCREEN_PERIOD[0],
        end_date=SCREEN_PERIOD[1],
        optimize_memory=True,
        include_trades=include_trades,
        include_financials=include_financials,
        include_metadata=include_metadata,
    )

    screen_rows = []
    total_screen_runs = len(ENTRY_VARIANTS) * len(EXIT_VARIANTS)
    screen_done = 0
    for entry_variant in ENTRY_VARIANTS:
        for exit_name in EXIT_VARIANTS:
            screen_done += 1
            print(
                f"[screen {screen_done}/{total_screen_runs}] {entry_variant['label']} + {exit_name}",
                flush=True,
            )
            metrics = _run_combo(
                tickers=tickers,
                starting_capital=starting_capital,
                max_positions=max_positions,
                max_position_pct=max_position_pct,
                cache=screen_cache,
                start_date=SCREEN_PERIOD[0],
                end_date=SCREEN_PERIOD[1],
                entry_name="MACDPreCrossMomentumEntry",
                entry_params=entry_variant["params"],
                exit_name=exit_name,
            )
            screen_rows.append(
                {
                    "entry_label": entry_variant["label"],
                    "entry_params": entry_variant["params"],
                    "exit_name": exit_name,
                    **metrics,
                }
            )
            pd.DataFrame(screen_rows).to_csv(output_dir / "screening_results_partial.csv", index=False, encoding="utf-8-sig")

    screen_df = pd.DataFrame(screen_rows)
    screen_df["screen_score"] = _score(screen_df)
    screen_df = screen_df.sort_values(["screen_score", "total_return_pct"], ascending=[False, False]).reset_index(drop=True)
    top_df = screen_df.head(TOP_K).copy()
    top_df["rank"] = range(1, len(top_df) + 1)

    validation_cache = BacktestDataCache(data_root="data")
    validation_cache.preload_tickers(
        tickers=tickers,
        start_date=VALIDATION_PERIOD[0],
        end_date=VALIDATION_PERIOD[1],
        optimize_memory=True,
        include_trades=include_trades,
        include_financials=include_financials,
        include_metadata=include_metadata,
    )

    validation_rows = []
    baseline_exit_names = []
    total_validation_runs = len(top_df) * 2
    validation_done = 0
    for _, row in top_df.iterrows():
        exit_name = row["exit_name"]
        baseline_exit_names.append(exit_name)

        validation_done += 1
        print(
            f"[validate {validation_done}/{total_validation_runs}] {row['entry_label']} + {exit_name}",
            flush=True,
        )
        lite_metrics = _run_combo(
            tickers=tickers,
            starting_capital=starting_capital,
            max_positions=max_positions,
            max_position_pct=max_position_pct,
            cache=validation_cache,
            start_date=VALIDATION_PERIOD[0],
            end_date=VALIDATION_PERIOD[1],
            entry_name="MACDPreCrossMomentumEntry",
            entry_params=row["entry_params"],
            exit_name=exit_name,
        )
        validation_rows.append(
            {
                "strategy_family": "LiteCombo",
                "entry_label": row["entry_label"],
                "entry_params": row["entry_params"],
                "exit_name": exit_name,
                "screen_rank": int(row["rank"]),
                **lite_metrics,
            }
        )

        validation_done += 1
        print(
            f"[validate {validation_done}/{total_validation_runs}] Baseline + {exit_name}",
            flush=True,
        )
        baseline_metrics = _run_combo(
            tickers=tickers,
            starting_capital=starting_capital,
            max_positions=max_positions,
            max_position_pct=max_position_pct,
            cache=validation_cache,
            start_date=VALIDATION_PERIOD[0],
            end_date=VALIDATION_PERIOD[1],
            entry_name="MACDCrossoverStrategy",
            entry_params={},
            exit_name=exit_name,
        )
        validation_rows.append(
            {
                "strategy_family": "Baseline",
                "entry_label": "MACD",
                "entry_params": {},
                "exit_name": exit_name,
                "screen_rank": int(row["rank"]),
                **baseline_metrics,
            }
        )
        pd.DataFrame(validation_rows).to_csv(output_dir / "validation_results_partial.csv", index=False, encoding="utf-8-sig")

    screen_df.to_csv(output_dir / "screening_results.csv", index=False, encoding="utf-8-sig")
    top_df.to_csv(output_dir / "screening_top_k.csv", index=False, encoding="utf-8-sig")

    validation_df = pd.DataFrame(validation_rows)
    validation_df.to_csv(output_dir / "validation_results.csv", index=False, encoding="utf-8-sig")

    lite_validation_df = validation_df[validation_df["strategy_family"] == "LiteCombo"].copy()
    base_validation_df = validation_df[validation_df["strategy_family"] == "Baseline"].copy()
    comparison_df = lite_validation_df.merge(
        base_validation_df,
        on=["exit_name", "screen_rank"],
        how="left",
        suffixes=("_lite", "_baseline"),
    )
    comparison_df["delta_return_pct"] = comparison_df["total_return_pct_lite"] - comparison_df["total_return_pct_baseline"]
    comparison_df["delta_sharpe"] = comparison_df["sharpe_ratio_lite"] - comparison_df["sharpe_ratio_baseline"]
    comparison_df["delta_max_drawdown_pct"] = comparison_df["max_drawdown_pct_lite"] - comparison_df["max_drawdown_pct_baseline"]
    comparison_df = comparison_df.sort_values(["delta_return_pct", "delta_sharpe"], ascending=[False, False])
    comparison_df.to_csv(output_dir / "validation_comparison.csv", index=False, encoding="utf-8-sig")

    screen_report = top_df[[
        "rank",
        "entry_label",
        "exit_name",
        "total_return_pct",
        "annualized_return_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
        "screen_score",
    ]].copy()
    validation_report = comparison_df[[
        "screen_rank",
        "entry_label_lite",
        "exit_name",
        "total_return_pct_lite",
        "total_return_pct_baseline",
        "delta_return_pct",
        "sharpe_ratio_lite",
        "sharpe_ratio_baseline",
        "delta_sharpe",
        "max_drawdown_pct_lite",
        "max_drawdown_pct_baseline",
        "delta_max_drawdown_pct",
    ]].copy()

    for df in [screen_report, validation_report]:
        for col in df.columns:
            if col.endswith("_pct"):
                df[col] = pd.to_numeric(df[col], errors="coerce").map(lambda v: f"{v:.2f}%")
            elif "sharpe" in col or col == "screen_score":
                df[col] = pd.to_numeric(df[col], errors="coerce").map(lambda v: f"{v:.2f}")

    report_path = output_dir / "litecombo_mvx_joint_tuning_report.md"
    report_path.write_text(
        "\n".join(
            [
                "# LiteCombo + MVX Joint Tuning",
                "",
                f"- Screening period: {SCREEN_PERIOD[0]} to {SCREEN_PERIOD[1]}",
                f"- Validation period: {VALIDATION_PERIOD[0]} to {VALIDATION_PERIOD[1]}",
                f"- Screened entry variants: {len(ENTRY_VARIANTS)}",
                f"- Screened exit variants: {len(EXIT_VARIANTS)}",
                f"- Top-K validated: {TOP_K}",
                "",
                "## Screening Top-K",
                "",
                _df_to_markdown(screen_report),
                "",
                "## Full-Sample Validation vs MACD Baseline",
                "",
                _df_to_markdown(validation_report),
            ]
        ),
        encoding="utf-8",
    )

    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()