"""
Rank strategy variants from multi-year backtest raw CSV with normalized scoring.

Default model:
- Risk 60%: max drawdown 35% + worst-year return 25%
- Profit 40%: average alpha 25% + positive-alpha-year ratio 15%
"""

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MetricSpec:
    name: str
    source_col: str
    weight: float
    higher_is_better: bool


@dataclass(frozen=True)
class ScoringModel:
    name: str
    metrics: list[MetricSpec]


MODEL_REGISTRY: dict[str, ScoringModel] = {
    "risk60_profit40_v2": ScoringModel(
        name="risk60_profit40_v2",
        metrics=[
            MetricSpec(
                name="mdd_inverse",
                source_col="avg_mdd",
                weight=0.35,
                higher_is_better=False,
            ),
            MetricSpec(
                name="worst_year_return",
                source_col="worst_year_return",
                weight=0.25,
                higher_is_better=True,
            ),
            MetricSpec(
                name="avg_alpha",
                source_col="avg_alpha",
                weight=0.25,
                higher_is_better=True,
            ),
            MetricSpec(
                name="positive_alpha_ratio",
                source_col="positive_alpha_ratio",
                weight=0.15,
                higher_is_better=True,
            ),
        ],
    ),
    "risk60_profit40_v1": ScoringModel(
        name="risk60_profit40_v1",
        metrics=[
            MetricSpec(
                name="mdd_inverse",
                source_col="avg_mdd",
                weight=0.35,
                higher_is_better=False,
            ),
            MetricSpec(
                name="worst_year_return",
                source_col="worst_year_return",
                weight=0.25,
                higher_is_better=True,
            ),
            MetricSpec(
                name="avg_alpha",
                source_col="avg_alpha",
                weight=0.30,
                higher_is_better=True,
            ),
            MetricSpec(
                name="residual_return",
                source_col="residual_return",
                weight=0.10,
                higher_is_better=True,
            ),
        ],
    ),
}


def _minmax_normalize(series: pd.Series, higher_is_better: bool) -> pd.Series:
    series_min = float(series.min())
    series_max = float(series.max())
    span = series_max - series_min

    if span <= 1e-12:
        return pd.Series(np.full(len(series), 0.5), index=series.index)

    if higher_is_better:
        return (series - series_min) / span
    return (series_max - series) / span


def _compute_residual_return(df_summary: pd.DataFrame) -> pd.Series:
    alpha_values = df_summary["avg_alpha"].astype(float)
    return_values = df_summary["avg_return"].astype(float)

    if alpha_values.nunique() < 2:
        return return_values - return_values.mean()

    slope, intercept = np.polyfit(alpha_values.values, return_values.values, 1)
    fitted = slope * alpha_values + intercept
    residual = return_values - fitted

    if float(residual.std()) <= 1e-10:
        return return_values - return_values.mean()
    return residual


def _build_summary(df_raw: pd.DataFrame, strategy_col: str) -> pd.DataFrame:
    grouped_raw = df_raw.groupby(strategy_col)

    grouped = (
        grouped_raw
        .agg(
            avg_return=("return_pct", "mean"),
            avg_alpha=("alpha", "mean"),
            avg_mdd=("max_drawdown_pct", "mean"),
            worst_year_return=("return_pct", "min"),
            years=("period", "nunique"),
            positive_alpha_ratio=("alpha", lambda s: float((s > 0).mean())),
        )
        .reset_index()
        .rename(columns={strategy_col: "strategy"})
    )

    grouped = grouped.astype({"positive_alpha_ratio": float})

    grouped["residual_return"] = _compute_residual_return(grouped)
    return grouped


def _score_strategies(df_summary: pd.DataFrame, model: ScoringModel) -> pd.DataFrame:
    scored = df_summary.copy()
    total_weight = sum(metric.weight for metric in model.metrics)
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"Model weight sum must be 1.0, got {total_weight}")

    component_cols: list[str] = []
    for metric in model.metrics:
        if metric.source_col not in scored.columns:
            raise ValueError(f"Model metric source column not found: {metric.source_col}")
        norm_col = f"{metric.name}_norm"
        comp_col = f"{metric.name}_component"
        scored[norm_col] = _minmax_normalize(
            scored[metric.source_col], metric.higher_is_better
        )
        scored[comp_col] = scored[norm_col] * metric.weight
        component_cols.append(comp_col)

    scored["final_score"] = scored[component_cols].sum(axis=1)
    scored["rank"] = scored["final_score"].rank(ascending=False, method="dense").astype(
        int
    )
    scored = scored.sort_values(["final_score", "avg_alpha"], ascending=[False, False])
    return scored


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize and rank strategy performance from multi-year raw CSV."
    )
    parser.add_argument(
        "--raw-csv",
        required=True,
        help="Path to raw multi-year CSV (must include return_pct, alpha, max_drawdown_pct, period).",
    )
    parser.add_argument(
        "--strategy-col",
        default="exit_strategy",
        help="Strategy identifier column name in raw CSV (default: exit_strategy).",
    )
    parser.add_argument(
        "--model",
        default="risk60_profit40_v2",
        choices=sorted(MODEL_REGISTRY.keys()),
        help="Scoring model name.",
    )
    parser.add_argument(
        "--output-dir",
        default="strategy_evaluation",
        help="Output directory (default: strategy_evaluation).",
    )
    parser.add_argument(
        "--output-prefix",
        default="strategy_ranking",
        help="Output file prefix.",
    )
    args = parser.parse_args()

    raw_path = Path(args.raw_csv)
    if not raw_path.exists():
        raise FileNotFoundError(f"Raw CSV not found: {raw_path}")

    df_raw = pd.read_csv(raw_path)
    required_cols = {
        args.strategy_col,
        "period",
        "return_pct",
        "alpha",
        "max_drawdown_pct",
    }
    missing = required_cols - set(df_raw.columns)
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing))}")

    df_raw = df_raw.dropna(
        subset=[args.strategy_col, "return_pct", "alpha", "max_drawdown_pct"]
    )
    if df_raw.empty:
        raise ValueError("No valid rows left after dropping missing required values")

    model = MODEL_REGISTRY[args.model]
    summary = _build_summary(df_raw, args.strategy_col)
    ranked = _score_strategies(summary, model)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    ranking_path = out_dir / f"{args.output_prefix}_{args.model}_{ts}.csv"
    summary_path = out_dir / f"{args.output_prefix}_{args.model}_{ts}_summary.csv"

    ranked.to_csv(ranking_path, index=False)
    summary.to_csv(summary_path, index=False)

    display_cols = [
        "rank",
        "strategy",
        "final_score",
        "avg_mdd",
        "worst_year_return",
        "avg_alpha",
        "positive_alpha_ratio",
        "avg_return",
    ]
    if args.model == "risk60_profit40_v1":
        display_cols.insert(7, "residual_return")

    print("=== Strategy Ranking ===")
    print(ranked[display_cols].to_string(index=False))
    print("\nSaved files:")
    print(ranking_path)
    print(summary_path)


if __name__ == "__main__":
    main()
