"""Shared scoring utilities for evaluation and walk-forward ranking."""

from __future__ import annotations

from typing import Callable, Iterable, Sequence

import pandas as pd


DEFAULT_LOWER_QUANTILE = 0.10
DEFAULT_UPPER_QUANTILE = 0.90


def robust_norm(
    series: pd.Series,
    lower_q: float = DEFAULT_LOWER_QUANTILE,
    upper_q: float = DEFAULT_UPPER_QUANTILE,
) -> pd.Series:
    """Normalize a series using winsorized quantile bounds."""
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return pd.Series(0.5, index=series.index, dtype=float)

    lo = float(numeric.quantile(lower_q))
    hi = float(numeric.quantile(upper_q))
    if hi <= lo:
        return pd.Series(0.5, index=series.index, dtype=float)

    clipped = numeric.clip(lower=lo, upper=hi)
    normalized = (clipped - lo) / (hi - lo)
    return normalized.fillna(0.5).clip(lower=0.0, upper=1.0)


def robust_inverse_norm(
    series: pd.Series,
    lower_q: float = DEFAULT_LOWER_QUANTILE,
    upper_q: float = DEFAULT_UPPER_QUANTILE,
) -> pd.Series:
    """Inverse robust normalization where smaller raw values score higher."""
    return 1.0 - robust_norm(series, lower_q=lower_q, upper_q=upper_q)


def candidate_key_columns(df: pd.DataFrame) -> list[str]:
    """Return grouping columns that uniquely identify a candidate strategy."""
    key_cols = ["entry_strategy", "exit_strategy", "entry_filter"]
    if "ranking_strategy" in df.columns:
        key_cols.append("ranking_strategy")
    return key_cols


def positive_ratio(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return 0.0
    return float((numeric > 0).mean())


def series_std(series: pd.Series) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return 0.0
    return float(numeric.std(ddof=0))


def coerce_score_columns(df: pd.DataFrame, columns: Sequence[str]) -> pd.DataFrame:
    out = df.copy()
    for column in columns:
        if column in out.columns:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    return out


def ensure_columns(df: pd.DataFrame, required: Iterable[str]) -> None:
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for scoring: {missing}")


def summarize_prs_train_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate train-window metrics required by PRS-Train and Final PRS."""
    if df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(df)
    ensure_columns(df, key_cols + ["period", "return_pct", "alpha", "max_drawdown_pct"])
    numeric_df = coerce_score_columns(df, ["return_pct", "alpha", "max_drawdown_pct"])
    return (
        numeric_df.groupby(key_cols, dropna=False)
        .agg(
            mean_train_return=("return_pct", "mean"),
            mean_train_alpha=("alpha", "mean"),
            avg_train_mdd=("max_drawdown_pct", "mean"),
            worst_train_year_alpha=("alpha", "min"),
            train_positive_alpha_ratio=("alpha", lambda s: positive_ratio(s)),
            std_train_yearly_alpha=("alpha", lambda s: series_std(s)),
            period_count=("period", "nunique"),
        )
        .reset_index()
    )


def apply_prs_train_score(
    summary_df: pd.DataFrame,
    complexity_penalty_resolver: Callable[[str, str], float] | None = None,
) -> pd.DataFrame:
    """Apply the agreed PRS-Train formula to aggregated train metrics."""
    if summary_df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(summary_df)
    ensure_columns(
        summary_df,
        key_cols
        + [
            "mean_train_return",
            "mean_train_alpha",
            "avg_train_mdd",
            "worst_train_year_alpha",
            "train_positive_alpha_ratio",
            "std_train_yearly_alpha",
            "period_count",
        ],
    )

    resolver = complexity_penalty_resolver or (lambda _entry, _exit: 0.0)
    out = summary_df.copy()
    out["mean_train_alpha_norm"] = robust_norm(out["mean_train_alpha"])
    out["avg_train_mdd_norm"] = robust_inverse_norm(out["avg_train_mdd"])
    out["worst_train_year_alpha_norm"] = robust_norm(out["worst_train_year_alpha"])
    out["std_train_yearly_alpha_norm"] = robust_inverse_norm(
        out["std_train_yearly_alpha"]
    )
    out["mean_train_return_norm"] = robust_norm(out["mean_train_return"])
    out["complexity_penalty"] = out.apply(
        lambda row: float(
            resolver(
                str(row["entry_strategy"]),
                str(row["exit_strategy"]),
            )
        ),
        axis=1,
    )
    out["prs_train_score"] = (
        100.0
        * (
            0.35 * out["mean_train_alpha_norm"]
            + 0.20 * out["train_positive_alpha_ratio"]
            + 0.15 * out["avg_train_mdd_norm"]
            + 0.12 * out["worst_train_year_alpha_norm"]
            + 0.10 * out["std_train_yearly_alpha_norm"]
            + 0.08 * out["mean_train_return_norm"]
        )
        - out["complexity_penalty"]
    ).clip(lower=0.0, upper=100.0)
    out = out.sort_values(
        ["prs_train_score", "mean_train_alpha", "mean_train_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    out.insert(0, "rank", range(1, len(out) + 1))
    return out


def rank_final_prs(
    oos_panel_df: pd.DataFrame,
    complexity_penalty_resolver: Callable[[str, str], float] | None = None,
) -> pd.DataFrame:
    """Apply the agreed Final PRS formula to the all-candidate OOS panel."""
    if oos_panel_df.empty:
        return pd.DataFrame()

    working = oos_panel_df.copy()
    key_cols = candidate_key_columns(working)
    if "mean_train_alpha" not in working.columns:
        working["mean_train_alpha"] = pd.NA

    ensure_columns(
        working,
        key_cols + ["test_year", "return_pct", "alpha", "max_drawdown_pct", "mean_train_alpha"],
    )
    working = coerce_score_columns(
        working,
        ["test_year", "return_pct", "alpha", "max_drawdown_pct", "mean_train_alpha"],
    )

    grouped = (
        working.groupby(key_cols, dropna=False)
        .agg(
            oos_fold_count=("test_year", "nunique"),
            mean_oos_return=("return_pct", "mean"),
            mean_oos_alpha=("alpha", "mean"),
            avg_oos_mdd=("max_drawdown_pct", "mean"),
            worst_oos_year_alpha=("alpha", "min"),
            oos_positive_alpha_ratio=("alpha", lambda s: positive_ratio(s)),
            std_oos_yearly_alpha=("alpha", lambda s: series_std(s)),
            mean_train_alpha=("mean_train_alpha", "mean"),
        )
        .reset_index()
    )
    if grouped.empty:
        return grouped

    sort_cols = ["test_year"]
    if "period" in working.columns:
        sort_cols.append("period")
    recent_rows = (
        working.sort_values(sort_cols)
        .groupby(key_cols, dropna=False)
        .tail(1)[key_cols + ["test_year", "alpha", "return_pct"]]
        .rename(
            columns={
                "test_year": "recent_test_year",
                "alpha": "recent_oos_alpha",
                "return_pct": "recent_oos_return",
            }
        )
    )
    grouped = grouped.merge(recent_rows, on=key_cols, how="left")

    resolver = complexity_penalty_resolver or (lambda _entry, _exit: 0.0)
    grouped["train_oos_alpha_gap"] = (
        grouped["mean_train_alpha"] - grouped["mean_oos_alpha"]
    ).abs()
    grouped["mean_oos_alpha_norm"] = robust_norm(grouped["mean_oos_alpha"])
    grouped["avg_oos_mdd_norm"] = robust_inverse_norm(grouped["avg_oos_mdd"])
    grouped["worst_oos_year_alpha_norm"] = robust_norm(grouped["worst_oos_year_alpha"])
    grouped["train_oos_alpha_gap_norm"] = robust_inverse_norm(
        grouped["train_oos_alpha_gap"]
    )
    grouped["std_oos_yearly_alpha_norm"] = robust_inverse_norm(
        grouped["std_oos_yearly_alpha"]
    )
    grouped["recent_oos_alpha_norm"] = robust_norm(grouped["recent_oos_alpha"])
    grouped["recent_oos_return_norm"] = robust_norm(grouped["recent_oos_return"])
    grouped["recent_oos_health"] = (
        0.70 * grouped["recent_oos_alpha_norm"]
        + 0.30 * grouped["recent_oos_return_norm"]
    )
    grouped["complexity_penalty"] = grouped.apply(
        lambda row: float(
            resolver(
                str(row["entry_strategy"]),
                str(row["exit_strategy"]),
            )
        ),
        axis=1,
    )
    grouped["final_prs_score"] = (
        100.0
        * (
            0.30 * grouped["mean_oos_alpha_norm"]
            + 0.18 * grouped["oos_positive_alpha_ratio"]
            + 0.15 * grouped["avg_oos_mdd_norm"]
            + 0.12 * grouped["worst_oos_year_alpha_norm"]
            + 0.10 * grouped["train_oos_alpha_gap_norm"]
            + 0.08 * grouped["std_oos_yearly_alpha_norm"]
            + 0.07 * grouped["recent_oos_health"]
        )
        - grouped["complexity_penalty"]
    ).clip(lower=0.0, upper=100.0)
    grouped = grouped.sort_values(
        ["final_prs_score", "mean_oos_alpha", "mean_oos_return"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    grouped.insert(0, "rank", range(1, len(grouped) + 1))
    return grouped
