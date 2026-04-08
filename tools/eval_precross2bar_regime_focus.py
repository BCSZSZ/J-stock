"""Run focused quarterly market-regime comparison for Baseline vs 2BarLiteCombo."""

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
from src.evaluation.strategy_evaluator import (
    MarketRegime,
    StrategyEvaluator,
    create_quarterly_periods,
)
from src.utils.strategy_loader import (
    ENTRY_STRATEGIES,
    EXIT_STRATEGIES,
    load_entry_strategy,
    load_exit_strategy,
)

YEARS = [2021, 2022, 2023, 2024, 2025]
FIXED_EXIT_STRATEGY = "MVX_N3_R3p25_T1p6_D21_B20p0"
FOCUS_VARIANTS = [
    {
        "label": "Baseline",
        "strategy_name": "MACDCrossoverStrategy",
        "params": {},
    },
    {
        "label": "2BarLiteCombo",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_hist_abs_norm": 0.01,
            "min_adx_14": 10.0,
            "max_return_5d": 0.08,
        },
    },
]


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


def _build_regime_summary(quarterly_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (regime, label), group in quarterly_df.groupby(["market_regime", "strategy_label"], sort=False):
        returns = pd.to_numeric(group["total_return_pct"], errors="coerce")
        alpha = pd.to_numeric(group["alpha_vs_topix_pct"], errors="coerce")
        rows.append(
            {
                "market_regime": regime,
                "strategy_label": label,
                "sample_count": int(len(group)),
                "positive_period_ratio": float(returns.gt(0).mean()),
                "positive_alpha_ratio": float(alpha.gt(0).mean()),
                "avg_return_pct": float(returns.mean()),
                "avg_alpha_pct": float(alpha.mean()),
                "worst_period_return_pct": float(returns.min()),
                "avg_sharpe": float(pd.to_numeric(group["sharpe_ratio"], errors="coerce").mean()),
                "avg_max_drawdown_pct": float(pd.to_numeric(group["max_drawdown_pct"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["market_regime", "avg_alpha_pct"], ascending=[True, False])


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "strategy_evaluation" / f"precross2bar_regime_focus_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = StrategyEvaluator(data_root="data", output_dir=str(output_dir), verbose=False)
    tickers = evaluator._load_monitor_list()
    max_positions, max_position_pct = evaluator._get_portfolio_limits()
    starting_capital = evaluator._get_starting_capital()
    exit_strategy = load_exit_strategy(FIXED_EXIT_STRATEGY)
    periods = create_quarterly_periods(YEARS)

    include_trades, include_financials, include_metadata = evaluator._resolve_aux_preload_flags(
        entry_strategies=sorted({variant["strategy_name"] for variant in FOCUS_VARIANTS}),
        exit_strategies=[FIXED_EXIT_STRATEGY],
        entry_mapping=ENTRY_STRATEGIES,
        exit_mapping=EXIT_STRATEGIES,
    )
    cache = BacktestDataCache(data_root="data")
    cache.preload_tickers(
        tickers=tickers,
        start_date=min(start for _, start, _ in periods),
        end_date=max(end for _, _, end in periods),
        optimize_memory=True,
        include_trades=include_trades,
        include_financials=include_financials,
        include_metadata=include_metadata,
    )

    rows = []
    total_runs = len(periods) * len(FOCUS_VARIANTS)
    completed = 0
    for period_label, start_date, end_date in periods:
        topix_return_pct = evaluator._get_topix_return(start_date, end_date)
        market_regime = MarketRegime.classify(topix_return_pct)
        for variant in FOCUS_VARIANTS:
            completed += 1
            print(
                f"[{completed}/{total_runs}] {period_label} | {variant['label']} | TOPIX={topix_return_pct:.2f}% | regime={market_regime}",
                flush=True,
            )
            entry_strategy = load_entry_strategy(variant["strategy_name"], variant["params"])
            engine = PortfolioBacktestEngine(
                data_root="data",
                starting_capital=starting_capital,
                max_positions=max_positions,
                max_position_pct=max_position_pct,
                preloaded_cache=cache,
            )
            result = engine.backtest_portfolio_strategy(
                tickers=tickers,
                entry_strategy=entry_strategy,
                exit_strategy=exit_strategy,
                start_date=start_date,
                end_date=end_date,
                show_daily_status=False,
                show_signal_ranking=False,
                show_signal_details=False,
                compute_benchmark=False,
            )
            rows.append(
                {
                    "period": period_label,
                    "start_date": start_date,
                    "end_date": end_date,
                    "strategy_label": variant["label"],
                    "topix_return_pct": topix_return_pct,
                    "market_regime": market_regime,
                    "total_return_pct": result.total_return_pct,
                    "alpha_vs_topix_pct": result.total_return_pct - topix_return_pct,
                    "annualized_return_pct": result.annualized_return_pct,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown_pct": result.max_drawdown_pct,
                    "num_trades": result.num_trades,
                    "win_rate_pct": result.win_rate_pct,
                }
            )
            pd.DataFrame(rows).to_csv(output_dir / "quarterly_results_partial.csv", index=False, encoding="utf-8-sig")

    quarterly_df = pd.DataFrame(rows)
    regime_summary_df = _build_regime_summary(quarterly_df)

    quarterly_df.to_csv(output_dir / "quarterly_results.csv", index=False, encoding="utf-8-sig")
    regime_summary_df.to_csv(output_dir / "regime_summary.csv", index=False, encoding="utf-8-sig")

    report_df = regime_summary_df.copy()
    for col in ["positive_period_ratio", "positive_alpha_ratio"]:
        report_df[col] = report_df[col].map(lambda v: f"{v:.1%}")
    for col in ["avg_return_pct", "avg_alpha_pct", "worst_period_return_pct", "avg_max_drawdown_pct"]:
        report_df[col] = report_df[col].map(lambda v: f"{v:.2f}%")
    report_df["avg_sharpe"] = report_df["avg_sharpe"].map(lambda v: f"{v:.2f}")

    report_path = output_dir / "precross2bar_regime_focus_report.md"
    report_path.write_text(
        "\n".join(
            [
                "# Baseline vs 2BarLiteCombo Regime Focus",
                "",
                f"- Years: {YEARS[0]} to {YEARS[-1]}",
                f"- Exit: {FIXED_EXIT_STRATEGY}",
                "- Period granularity: calendar quarter",
                "",
                "## Regime summary",
                "",
                _df_to_markdown(report_df),
            ]
        ),
        encoding="utf-8",
    )

    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()