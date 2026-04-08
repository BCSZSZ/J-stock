"""Evaluate annual and market-regime stability for PreCross2Bar variants."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.portfolio_engine import PortfolioBacktestEngine
from src.backtest.data_cache import BacktestDataCache
from src.evaluation.strategy_evaluator import (
    MarketRegime,
    StrategyEvaluator,
    create_annual_periods,
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
ENTRY_VARIANTS = [
    {
        "label": "Baseline",
        "strategy_name": "MACDCrossoverStrategy",
        "params": {},
        "rule_summary": "Original MACD golden-cross entry.",
    },
    {
        "label": "PreCross2Bar",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
        },
        "rule_summary": "Two-bar strict-rise pre-cross entry.",
    },
    {
        "label": "2BarRet5d008",
        "strategy_name": "MACDPreCrossMomentumEntry",
        "params": {
            "hist_rise_days": 2,
            "price_rise_days": 2,
            "max_return_5d": 0.08,
        },
        "rule_summary": "PreCross2Bar plus Return_5d <= 0.08.",
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
        "rule_summary": "PreCross2Bar plus hist_abs_norm <= 0.010, ADX_14 >= 10, Return_5d <= 0.08.",
    },
]


def _df_to_markdown(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _run_periods(
    periods,
    period_kind: str,
    tickers,
    exit_strategy,
    starting_capital,
    max_positions,
    max_position_pct,
    evaluator: StrategyEvaluator,
    output_dir: Path,
    preloaded_cache: BacktestDataCache | None,
):
    rows = []
    total_runs = len(periods) * len(ENTRY_VARIANTS)
    completed = 0
    for label, start_date, end_date in periods:
        topix_return_pct = evaluator._get_topix_return(start_date, end_date)
        market_regime = MarketRegime.classify(topix_return_pct)
        for variant in ENTRY_VARIANTS:
            completed += 1
            print(
                f"[{period_kind} {completed}/{total_runs}] {label} | {variant['label']} | TOPIX={topix_return_pct:.2f}% | regime={market_regime}",
                flush=True,
            )
            entry_strategy = load_entry_strategy(variant["strategy_name"], variant["params"])
            engine = PortfolioBacktestEngine(
                data_root="data",
                starting_capital=starting_capital,
                max_positions=max_positions,
                max_position_pct=max_position_pct,
                preloaded_cache=preloaded_cache,
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
                    "period_kind": period_kind,
                    "period": label,
                    "start_date": start_date,
                    "end_date": end_date,
                    "strategy_label": variant["label"],
                    "entry_strategy": variant["strategy_name"],
                    "entry_params": variant["params"],
                    "exit_strategy": FIXED_EXIT_STRATEGY,
                    "topix_return_pct": topix_return_pct,
                    "market_regime": market_regime,
                    "total_return_pct": result.total_return_pct,
                    "alpha_vs_topix_pct": None if topix_return_pct is None else result.total_return_pct - topix_return_pct,
                    "annualized_return_pct": result.annualized_return_pct,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown_pct": result.max_drawdown_pct,
                    "num_trades": result.num_trades,
                    "win_rate_pct": result.win_rate_pct,
                    "avg_holding_days": result.avg_holding_days,
                    "profit_factor": result.profit_factor,
                }
            )
            partial_df = pd.DataFrame(rows)
            partial_df.to_csv(
                output_dir / f"{period_kind}_results_partial.csv",
                index=False,
                encoding="utf-8-sig",
            )
    return pd.DataFrame(rows)


def _build_annual_stability(annual_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, group in annual_df.groupby("strategy_label", sort=False):
        returns = pd.to_numeric(group["total_return_pct"], errors="coerce")
        alpha = pd.to_numeric(group["alpha_vs_topix_pct"], errors="coerce")
        rows.append(
            {
                "strategy_label": label,
                "sample_count": int(len(group)),
                "positive_years": int(returns.gt(0).sum()),
                "positive_year_ratio": float(returns.gt(0).mean()),
                "positive_alpha_years": int(alpha.gt(0).sum()),
                "positive_alpha_ratio": float(alpha.gt(0).mean()),
                "avg_return_pct": float(returns.mean()),
                "std_return_pct": float(returns.std(ddof=0)),
                "worst_year_return_pct": float(returns.min()),
                "best_year_return_pct": float(returns.max()),
                "avg_alpha_pct": float(alpha.mean()),
                "avg_sharpe": float(pd.to_numeric(group["sharpe_ratio"], errors="coerce").mean()),
                "avg_max_drawdown_pct": float(pd.to_numeric(group["max_drawdown_pct"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["positive_alpha_ratio", "avg_return_pct"], ascending=[False, False])


def _build_regime_stability(quarterly_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (regime, label), group in quarterly_df.groupby(["market_regime", "strategy_label"], dropna=False, sort=False):
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
                "median_return_pct": float(returns.median()),
                "worst_period_return_pct": float(returns.min()),
                "avg_alpha_pct": float(alpha.mean()),
                "avg_sharpe": float(pd.to_numeric(group["sharpe_ratio"], errors="coerce").mean()),
                "avg_max_drawdown_pct": float(pd.to_numeric(group["max_drawdown_pct"], errors="coerce").mean()),
            }
        )
    return pd.DataFrame(rows).sort_values(["market_regime", "avg_alpha_pct"], ascending=[True, False])


def _build_report(output_dir: Path, annual_period_df: pd.DataFrame, annual_stability_df: pd.DataFrame, regime_stability_df: pd.DataFrame) -> Path:
    annual_view = annual_period_df[[
        "period",
        "strategy_label",
        "market_regime",
        "total_return_pct",
        "alpha_vs_topix_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
    ]].copy()
    annual_view["total_return_pct"] = annual_view["total_return_pct"].map(lambda v: f"{v:.2f}%")
    annual_view["alpha_vs_topix_pct"] = annual_view["alpha_vs_topix_pct"].map(lambda v: f"{v:.2f}%" if pd.notna(v) else "N/A")
    annual_view["sharpe_ratio"] = annual_view["sharpe_ratio"].map(lambda v: f"{v:.2f}")
    annual_view["max_drawdown_pct"] = annual_view["max_drawdown_pct"].map(lambda v: f"{v:.2f}%")

    annual_stability_view = annual_stability_df.copy()
    for col in ["positive_year_ratio", "positive_alpha_ratio"]:
        annual_stability_view[col] = annual_stability_view[col].map(lambda v: f"{v:.1%}")
    for col in ["avg_return_pct", "std_return_pct", "worst_year_return_pct", "best_year_return_pct", "avg_alpha_pct", "avg_max_drawdown_pct"]:
        annual_stability_view[col] = annual_stability_view[col].map(lambda v: f"{v:.2f}%")
    annual_stability_view["avg_sharpe"] = annual_stability_view["avg_sharpe"].map(lambda v: f"{v:.2f}")

    regime_view = regime_stability_df.copy()
    for col in ["positive_period_ratio", "positive_alpha_ratio"]:
        regime_view[col] = regime_view[col].map(lambda v: f"{v:.1%}")
    for col in ["avg_return_pct", "median_return_pct", "worst_period_return_pct", "avg_alpha_pct", "avg_max_drawdown_pct"]:
        regime_view[col] = regime_view[col].map(lambda v: f"{v:.2f}%")
    regime_view["avg_sharpe"] = regime_view["avg_sharpe"].map(lambda v: f"{v:.2f}")

    lines = [
        "# PreCross2Bar Stability Study",
        "",
        f"- Period range: {YEARS[0]} to {YEARS[-1]}",
        f"- Fixed exit: {FIXED_EXIT_STRATEGY}",
        "- Annual stability uses calendar years.",
        "- Market-regime stability uses calendar quarters classified by TOPIX return.",
        "",
        "## Annual period results",
        "",
        _df_to_markdown(annual_view),
        "",
        "## Annual stability summary",
        "",
        _df_to_markdown(annual_stability_view),
        "",
        "## Regime stability summary",
        "",
        _df_to_markdown(regime_view),
    ]
    report_path = output_dir / "precross2bar_stability_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / "strategy_evaluation" / f"precross2bar_stability_{ts}"
    output_dir.mkdir(parents=True, exist_ok=True)

    evaluator = StrategyEvaluator(data_root="data", output_dir=str(output_dir), verbose=False)
    tickers = evaluator._load_monitor_list()
    starting_capital = evaluator._get_starting_capital()
    max_positions, max_position_pct = evaluator._get_portfolio_limits()
    exit_strategy = load_exit_strategy(FIXED_EXIT_STRATEGY)
    annual_periods = create_annual_periods(YEARS)
    quarterly_periods = create_quarterly_periods(YEARS)

    print(f"Preloading cache for {len(tickers)} tickers...", flush=True)
    include_trades, include_financials, include_metadata = evaluator._resolve_aux_preload_flags(
        entry_strategies=sorted({variant["strategy_name"] for variant in ENTRY_VARIANTS}),
        exit_strategies=[FIXED_EXIT_STRATEGY],
        entry_mapping=ENTRY_STRATEGIES,
        exit_mapping=EXIT_STRATEGIES,
    )
    preloaded_cache = BacktestDataCache(data_root="data")
    preloaded_cache.preload_tickers(
        tickers=tickers,
        start_date=min(start for _, start, _ in annual_periods + quarterly_periods),
        end_date=max(end for _, _, end in annual_periods + quarterly_periods),
        optimize_memory=True,
        include_trades=include_trades,
        include_financials=include_financials,
        include_metadata=include_metadata,
    )
    print("Cache ready.", flush=True)

    annual_df = _run_periods(
        periods=annual_periods,
        period_kind="annual",
        tickers=tickers,
        exit_strategy=exit_strategy,
        starting_capital=starting_capital,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        evaluator=evaluator,
        output_dir=output_dir,
        preloaded_cache=preloaded_cache,
    )
    quarterly_df = _run_periods(
        periods=quarterly_periods,
        period_kind="quarterly",
        tickers=tickers,
        exit_strategy=exit_strategy,
        starting_capital=starting_capital,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        evaluator=evaluator,
        output_dir=output_dir,
        preloaded_cache=preloaded_cache,
    )

    annual_stability_df = _build_annual_stability(annual_df)
    regime_stability_df = _build_regime_stability(quarterly_df)
    report_path = _build_report(output_dir, annual_df, annual_stability_df, regime_stability_df)

    annual_df.to_csv(output_dir / "annual_results.csv", index=False, encoding="utf-8-sig")
    quarterly_df.to_csv(output_dir / "quarterly_results.csv", index=False, encoding="utf-8-sig")
    annual_stability_df.to_csv(output_dir / "annual_stability_summary.csv", index=False, encoding="utf-8-sig")
    regime_stability_df.to_csv(output_dir / "regime_stability_summary.csv", index=False, encoding="utf-8-sig")

    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()