"""Shared scoring utilities for evaluation and walk-forward ranking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

import pandas as pd


DEFAULT_LOWER_QUANTILE = 0.10
DEFAULT_UPPER_QUANTILE = 0.90


@dataclass(frozen=True)
class ScoreComponentSpec:
    name: str
    source_col: str
    weight: float
    higher_is_better: bool


MDD_WIN_V1_COMPONENTS = (
    ScoreComponentSpec(
        name="mean_return",
        source_col="mean_return",
        weight=0.25,
        higher_is_better=True,
    ),
    ScoreComponentSpec(
        name="recent_return",
        source_col="recent_return",
        weight=0.15,
        higher_is_better=True,
    ),
    ScoreComponentSpec(
        name="avg_mdd",
        source_col="avg_mdd",
        weight=0.25,
        higher_is_better=False,
    ),
    ScoreComponentSpec(
        name="worst_mdd",
        source_col="worst_mdd",
        weight=0.10,
        higher_is_better=False,
    ),
    ScoreComponentSpec(
        name="mean_win_rate",
        source_col="mean_win_rate",
        weight=0.20,
        higher_is_better=True,
    ),
    ScoreComponentSpec(
        name="mean_sharpe",
        source_col="mean_sharpe",
        weight=0.05,
        higher_is_better=True,
    ),
)


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


def period_sort_values(series: pd.Series) -> pd.Series:
    text = series.astype(str)
    extracted = text.str.extract(r"(-?\d+(?:\.\d+)?)", expand=False)
    numeric = pd.to_numeric(extracted, errors="coerce")
    fallback = text.rank(method="dense").astype(float)
    return numeric.fillna(fallback)


def apply_weighted_score(
    df: pd.DataFrame,
    components: Sequence[ScoreComponentSpec],
    *,
    score_col: str,
    complexity_penalty_col: str | None = None,
) -> pd.DataFrame:
    """Apply robust-normalized weighted components to a candidate summary frame."""
    if df.empty:
        return pd.DataFrame()

    total_weight = sum(component.weight for component in components)
    if abs(total_weight - 1.0) > 1e-9:
        raise ValueError(f"Score component weight sum must be 1.0, got {total_weight}")

    ensure_columns(df, [component.source_col for component in components])
    if complexity_penalty_col is not None:
        ensure_columns(df, [complexity_penalty_col])

    out = df.copy()
    score_series = pd.Series(0.0, index=out.index, dtype=float)
    for component in components:
        norm_col = f"{component.name}_norm"
        component_col = f"{component.name}_component"
        if component.higher_is_better:
            out[norm_col] = robust_norm(out[component.source_col])
        else:
            out[norm_col] = robust_inverse_norm(out[component.source_col])
        out[component_col] = out[norm_col] * component.weight
        score_series = score_series + out[component_col]

    penalty = (
        pd.to_numeric(out[complexity_penalty_col], errors="coerce").fillna(0.0)
        if complexity_penalty_col is not None
        else 0.0
    )
    out[score_col] = (100.0 * score_series - penalty).clip(lower=0.0, upper=100.0)
    return out


def summarize_prs_train_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate train-window metrics required by PRS-Train and Final PRS."""
    if df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(df)
    ensure_columns(df, key_cols + ["period", "return_pct", "alpha", "max_drawdown_pct"])
    numeric_df = df.copy()
    for optional_col in ["win_rate_pct", "sharpe_ratio"]:
        if optional_col not in numeric_df.columns:
            numeric_df[optional_col] = pd.NA
    numeric_df = coerce_score_columns(
        numeric_df,
        ["return_pct", "alpha", "max_drawdown_pct", "win_rate_pct", "sharpe_ratio"],
    )
    grouped = (
        numeric_df.groupby(key_cols, dropna=False)
        .agg(
            mean_train_return=("return_pct", "mean"),
            mean_train_alpha=("alpha", "mean"),
            avg_train_mdd=("max_drawdown_pct", "mean"),
            worst_train_mdd=("max_drawdown_pct", "max"),
            worst_train_year_alpha=("alpha", "min"),
            train_positive_alpha_ratio=("alpha", lambda s: positive_ratio(s)),
            std_train_yearly_alpha=("alpha", lambda s: series_std(s)),
            mean_train_win_rate=("win_rate_pct", "mean"),
            mean_train_sharpe=("sharpe_ratio", "mean"),
            period_count=("period", "nunique"),
        )
        .reset_index()
    )

    recent_rows = (
        numeric_df.assign(_period_sort_key=period_sort_values(numeric_df["period"]))
        .sort_values(key_cols + ["_period_sort_key", "period"], kind="mergesort")
        .groupby(key_cols, dropna=False)
        .tail(1)[key_cols + ["return_pct"]]
        .rename(columns={"return_pct": "recent_train_return"})
    )
    return grouped.merge(recent_rows, on=key_cols, how="left")


def apply_prs_train_score(
    summary_df: pd.DataFrame,
    complexity_penalty_resolver: Callable[[str, str], float] | None = None,
) -> pd.DataFrame:
    """Apply the agreed PRS-Train formula to aggregated train metrics."""
    if summary_df.empty:
        return pd.DataFrame()

    key_cols = candidate_key_columns(summary_df)
    working_summary = summary_df.copy()
    if "recent_train_return" not in working_summary.columns:
        working_summary["recent_train_return"] = working_summary.get("mean_train_return")
    if "worst_train_mdd" not in working_summary.columns:
        working_summary["worst_train_mdd"] = working_summary.get("avg_train_mdd")
    for optional_col in ["mean_train_win_rate", "mean_train_sharpe"]:
        if optional_col not in working_summary.columns:
            working_summary[optional_col] = pd.NA

    ensure_columns(
        working_summary,
        key_cols
        + [
            "mean_train_return",
            "mean_train_alpha",
            "avg_train_mdd",
            "worst_train_mdd",
            "worst_train_year_alpha",
            "train_positive_alpha_ratio",
            "std_train_yearly_alpha",
            "recent_train_return",
            "mean_train_win_rate",
            "mean_train_sharpe",
            "period_count",
        ],
    )

    resolver = complexity_penalty_resolver or (lambda _entry, _exit: 0.0)
    out = working_summary.copy()
    out["complexity_penalty"] = out.apply(
        lambda row: float(
            resolver(
                str(row["entry_strategy"]),
                str(row["exit_strategy"]),
            )
        ),
        axis=1,
    )
    out = apply_weighted_score(
        out.rename(
            columns={
                "mean_train_return": "mean_return",
                "recent_train_return": "recent_return",
                "avg_train_mdd": "avg_mdd",
                "worst_train_mdd": "worst_mdd",
                "mean_train_win_rate": "mean_win_rate",
                "mean_train_sharpe": "mean_sharpe",
            }
        ),
        MDD_WIN_V1_COMPONENTS,
        score_col="prs_train_score",
        complexity_penalty_col="complexity_penalty",
    ).rename(
        columns={
            "mean_return": "mean_train_return",
            "recent_return": "recent_train_return",
            "avg_mdd": "avg_train_mdd",
            "worst_mdd": "worst_train_mdd",
            "mean_win_rate": "mean_train_win_rate",
            "mean_sharpe": "mean_train_sharpe",
            "mean_return_norm": "mean_train_return_norm",
            "recent_return_norm": "recent_train_return_norm",
            "avg_mdd_norm": "avg_train_mdd_norm",
            "worst_mdd_norm": "worst_train_mdd_norm",
            "mean_win_rate_norm": "mean_train_win_rate_norm",
            "mean_sharpe_norm": "mean_train_sharpe_norm",
            "mean_return_component": "mean_train_return_component",
            "recent_return_component": "recent_train_return_component",
            "avg_mdd_component": "avg_train_mdd_component",
            "worst_mdd_component": "worst_train_mdd_component",
            "mean_win_rate_component": "mean_train_win_rate_component",
            "mean_sharpe_component": "mean_train_sharpe_component",
        }
    )
    out = out.sort_values(
        ["prs_train_score", "mean_train_return", "mean_train_win_rate"],
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
    for optional_col in ["win_rate_pct", "sharpe_ratio"]:
        if optional_col not in working.columns:
            working[optional_col] = pd.NA

    ensure_columns(
        working,
        key_cols
        + [
            "test_year",
            "return_pct",
            "alpha",
            "max_drawdown_pct",
            "mean_train_alpha",
            "win_rate_pct",
            "sharpe_ratio",
        ],
    )
    working = coerce_score_columns(
        working,
        [
            "test_year",
            "return_pct",
            "alpha",
            "max_drawdown_pct",
            "mean_train_alpha",
            "win_rate_pct",
            "sharpe_ratio",
        ],
    )

    grouped = (
        working.groupby(key_cols, dropna=False)
        .agg(
            oos_fold_count=("test_year", "nunique"),
            mean_oos_return=("return_pct", "mean"),
            mean_oos_alpha=("alpha", "mean"),
            avg_oos_mdd=("max_drawdown_pct", "mean"),
            worst_oos_mdd=("max_drawdown_pct", "max"),
            worst_oos_year_alpha=("alpha", "min"),
            oos_positive_alpha_ratio=("alpha", lambda s: positive_ratio(s)),
            std_oos_yearly_alpha=("alpha", lambda s: series_std(s)),
            mean_oos_win_rate=("win_rate_pct", "mean"),
            mean_oos_sharpe=("sharpe_ratio", "mean"),
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
    grouped["avg_oos_mdd_legacy_norm"] = robust_inverse_norm(grouped["avg_oos_mdd"])
    grouped["worst_oos_year_alpha_norm"] = robust_norm(grouped["worst_oos_year_alpha"])
    grouped["train_oos_alpha_gap_norm"] = robust_inverse_norm(
        grouped["train_oos_alpha_gap"]
    )
    grouped["std_oos_yearly_alpha_norm"] = robust_inverse_norm(
        grouped["std_oos_yearly_alpha"]
    )
    grouped["recent_oos_alpha_norm"] = robust_norm(grouped["recent_oos_alpha"])
    grouped["recent_oos_return_health_norm"] = robust_norm(grouped["recent_oos_return"])
    grouped["recent_oos_health"] = (
        0.70 * grouped["recent_oos_alpha_norm"]
        + 0.30 * grouped["recent_oos_return_health_norm"]
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
    grouped = apply_weighted_score(
        grouped.rename(
            columns={
                "mean_oos_return": "mean_return",
                "recent_oos_return": "recent_return",
                "avg_oos_mdd": "avg_mdd",
                "worst_oos_mdd": "worst_mdd",
                "mean_oos_win_rate": "mean_win_rate",
                "mean_oos_sharpe": "mean_sharpe",
            }
        ),
        MDD_WIN_V1_COMPONENTS,
        score_col="final_prs_score",
        complexity_penalty_col="complexity_penalty",
    ).rename(
        columns={
            "mean_return": "mean_oos_return",
            "recent_return": "recent_oos_return",
            "avg_mdd": "avg_oos_mdd",
            "worst_mdd": "worst_oos_mdd",
            "mean_win_rate": "mean_oos_win_rate",
            "mean_sharpe": "mean_oos_sharpe",
            "mean_return_norm": "mean_oos_return_norm",
            "recent_return_norm": "recent_oos_return_norm",
            "avg_mdd_norm": "avg_oos_mdd_norm",
            "worst_mdd_norm": "worst_oos_mdd_norm",
            "mean_win_rate_norm": "mean_oos_win_rate_norm",
            "mean_sharpe_norm": "mean_oos_sharpe_norm",
            "mean_return_component": "mean_oos_return_component",
            "recent_return_component": "recent_oos_return_component",
            "avg_mdd_component": "avg_oos_mdd_component",
            "worst_mdd_component": "worst_oos_mdd_component",
            "mean_win_rate_component": "mean_oos_win_rate_component",
            "mean_sharpe_component": "mean_oos_sharpe_component",
        }
    )
    grouped = grouped.sort_values(
        ["final_prs_score", "mean_oos_return", "mean_oos_win_rate"],
        ascending=[False, False, False],
    ).reset_index(drop=True)
    grouped.insert(0, "rank", range(1, len(grouped) + 1))
    return grouped
