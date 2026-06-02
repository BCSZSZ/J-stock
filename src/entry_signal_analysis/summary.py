from __future__ import annotations

from typing import Any

import pandas as pd


def _build_horizon_stats(frame: pd.DataFrame, horizons: list[int]) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for horizon in horizons:
        column = f"forward_return_{horizon}d_pct"
        diff_column = f"forward_diff_{horizon}d"
        valid = frame[column] if column in frame.columns else pd.Series(dtype=float)
        valid = pd.to_numeric(valid, errors="coerce").dropna()
        diff_series = frame[diff_column] if diff_column in frame.columns else pd.Series(dtype=float)
        diff_values = pd.to_numeric(diff_series, errors="coerce").dropna()
        wins = int((valid > 0).sum())
        losses = int((valid < 0).sum())
        flats = int((valid == 0).sum())
        count = int(len(valid))
        stats[f"{horizon}d"] = {
            "count": count,
            "wins": wins,
            "losses": losses,
            "flats": flats,
            "win_rate": float(wins / count) if count else 0.0,
            "avg_return_pct": float(valid.mean()) if count else 0.0,
            "median_return_pct": float(valid.median()) if count else 0.0,
            "avg_price_diff": float(diff_values.mean()) if len(diff_values) else 0.0,
        }
    return stats


def build_daily_summary(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    group_keys = ["entry_strategy", "entry_filter_name", "signal_date"]
    for keys, group in frame.groupby(group_keys, dropna=False):
        entry_strategy, entry_filter_name, signal_date = keys
        row: dict[str, Any] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "signal_date": signal_date,
            "candidate_count": int(len(group)),
            "selected_count": int(group["selected"].fillna(False).sum()),
            "positive_rank_score_count": int(group["positive_rank_score"].fillna(False).sum()),
            "tail_guard_limit": int(group["tail_guard_limit"].dropna().iloc[0]) if group["tail_guard_limit"].notna().any() else None,
        }
        selected = group[group["selected"] == True]  # noqa: E712
        for horizon, stats in _build_horizon_stats(selected, horizons).items():
            for key, value in stats.items():
                row[f"selected_{horizon}_{key}"] = value
        rows.append(row)

    return pd.DataFrame(rows).sort_values(["signal_date", "entry_strategy", "entry_filter_name"])


def build_strategy_summary(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for keys, group in frame.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        selected = group[group["selected"] == True]  # noqa: E712
        row: dict[str, Any] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "candidate_count": int(len(group)),
            "selected_count": int(len(selected)),
            "trading_day_count": int(group["signal_date"].nunique()),
        }
        for horizon, stats in _build_horizon_stats(selected, horizons).items():
            for key, value in stats.items():
                row[f"selected_{horizon}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["entry_strategy", "entry_filter_name"])


def build_overall_summary(frame: pd.DataFrame, horizons: list[int]) -> dict[str, Any]:
    selected = frame[frame["selected"] == True] if not frame.empty else frame
    return {
        "candidate_count": int(len(frame)),
        "selected_count": int(len(selected)),
        "trading_day_count": int(frame["signal_date"].nunique()) if not frame.empty else 0,
        **_build_horizon_stats(selected, horizons),
    }


def top_daily_windows(daily_summary: pd.DataFrame, primary_horizon: int, limit: int = 10) -> list[dict[str, Any]]:
    if daily_summary.empty:
        return []
    sort_column = f"selected_{primary_horizon}d_avg_return_pct"
    if sort_column not in daily_summary.columns:
        return []
    ranked = daily_summary.sort_values(
        [sort_column, "selected_count"],
        ascending=[False, False],
    )
    normalized = ranked.head(limit).where(pd.notna(ranked.head(limit)), None)
    return normalized.to_dict(orient="records")