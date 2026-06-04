from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from src.entry_signal_analysis.summary import _build_market_regime_lookup


COMBO_KEYS = ["entry_strategy", "exit_strategy"]
SUMMARY_GROUP_FIELDS = [
    "count",
    "win_rate",
    "avg_return",
    "median_return",
    "trimmed_mean_5pct",
    "winsorized_mean_5pct",
    "p10_return",
    "p25_return",
    "p75_return",
    "p90_return",
    "avg_win",
    "avg_loss",
    "payoff_ratio",
    "expected_shortfall_5pct",
    "top_5pct_contribution_ratio",
    "mean_without_top_5pct_return_pct",
    "avg_holding_days",
    "median_holding_days",
    "stop_loss_ratio",
    "take_profit_ratio",
    "time_stop_ratio",
    "trailing_stop_ratio",
    "no_exit_ratio",
]


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return float(numerator / denominator)


def _trimmed_mean(values: pd.Series, pct: float) -> float | None:
    valid = values.dropna().sort_values().reset_index(drop=True)
    count = len(valid)
    if count == 0:
        return None
    trim = int(math.floor(count * pct))
    if trim <= 0 or trim * 2 >= count:
        return float(valid.mean())
    return float(valid.iloc[trim : count - trim].mean())


def _winsorized_mean(values: pd.Series, pct: float) -> float | None:
    valid = values.dropna()
    if valid.empty:
        return None
    lower = float(valid.quantile(pct))
    upper = float(valid.quantile(1.0 - pct))
    return float(valid.clip(lower=lower, upper=upper).mean())


def _expected_shortfall(values: pd.Series, pct: float) -> float | None:
    valid = values.dropna().sort_values().reset_index(drop=True)
    if valid.empty:
        return None
    count = max(1, int(math.ceil(len(valid) * pct)))
    return float(valid.iloc[:count].mean())


def _loss_rate(values: pd.Series, threshold_pct: float) -> float | None:
    valid = values.dropna()
    if valid.empty:
        return None
    return float((valid <= -abs(threshold_pct)).sum() / len(valid))


def _tail_count(count: int, pct: float) -> int:
    return max(1, int(math.ceil(count * pct))) if count else 0


def _tail_metrics_from_values(values: pd.Series) -> dict[str, float | None]:
    valid = values.dropna().sort_values().reset_index(drop=True)
    count = len(valid)
    if count == 0:
        return {
            "total_sum_return_pct": None,
            "top_1pct_sum_return_pct": None,
            "top_5pct_sum_return_pct": None,
            "bottom_1pct_sum_return_pct": None,
            "bottom_5pct_sum_return_pct": None,
            "top_1pct_contribution_ratio": None,
            "top_5pct_contribution_ratio": None,
            "bottom_1pct_contribution_ratio": None,
            "bottom_5pct_contribution_ratio": None,
            "sum_without_top_1pct_return_pct": None,
            "sum_without_top_5pct_return_pct": None,
            "sum_without_bottom_1pct_return_pct": None,
            "sum_without_bottom_5pct_return_pct": None,
            "mean_without_top_1pct_return_pct": None,
            "mean_without_top_5pct_return_pct": None,
            "mean_without_bottom_1pct_return_pct": None,
            "mean_without_bottom_5pct_return_pct": None,
        }

    total = float(valid.sum())

    def part(pct: float, top: bool) -> tuple[float, float, float | None]:
        n = _tail_count(count, pct)
        tail = valid.iloc[-n:] if top else valid.iloc[:n]
        tail_sum = float(tail.sum())
        remaining = valid.drop(tail.index)
        without_sum = float(remaining.sum()) if len(remaining) else 0.0
        without_mean = float(remaining.mean()) if len(remaining) else None
        return tail_sum, without_sum, without_mean

    top_1, without_top_1, mean_without_top_1 = part(0.01, True)
    top_5, without_top_5, mean_without_top_5 = part(0.05, True)
    bottom_1, without_bottom_1, mean_without_bottom_1 = part(0.01, False)
    bottom_5, without_bottom_5, mean_without_bottom_5 = part(0.05, False)
    return {
        "total_sum_return_pct": total,
        "top_1pct_sum_return_pct": top_1,
        "top_5pct_sum_return_pct": top_5,
        "bottom_1pct_sum_return_pct": bottom_1,
        "bottom_5pct_sum_return_pct": bottom_5,
        "top_1pct_contribution_ratio": _ratio(top_1, total),
        "top_5pct_contribution_ratio": _ratio(top_5, total),
        "bottom_1pct_contribution_ratio": _ratio(bottom_1, total),
        "bottom_5pct_contribution_ratio": _ratio(bottom_5, total),
        "sum_without_top_1pct_return_pct": without_top_1,
        "sum_without_top_5pct_return_pct": without_top_5,
        "sum_without_bottom_1pct_return_pct": without_bottom_1,
        "sum_without_bottom_5pct_return_pct": without_bottom_5,
        "mean_without_top_1pct_return_pct": mean_without_top_1,
        "mean_without_top_5pct_return_pct": mean_without_top_5,
        "mean_without_bottom_1pct_return_pct": mean_without_bottom_1,
        "mean_without_bottom_5pct_return_pct": mean_without_bottom_5,
    }


def _exit_bucket(row: pd.Series) -> str:
    if bool(row.get("no_exit", False)):
        return "no_exit"
    text = f"{row.get('exit_reason', '')} {row.get('exit_urgency', '')}".lower()
    if "trail" in text:
        return "trailing_stop"
    if "hardstop" in text or "stop loss" in text or "stop:" in text:
        return "stop_loss"
    if "time" in text:
        return "time_stop"
    if "take" in text or "profit" in text or "tp" in text:
        return "take_profit"
    if "score" in text or "signal" in text or "trend" in text or "break" in text:
        return "signal_exit"
    return "other"


def _stats_for_frame(frame: pd.DataFrame) -> dict[str, float | int | None]:
    returns = _series(frame, "return_pct")
    count = int(len(returns))
    wins = returns[returns > 0]
    losses = returns[returns < 0]
    avg_win = float(wins.mean()) if len(wins) else None
    avg_loss = float(losses.mean()) if len(losses) else None
    holding = _series(frame, "holding_days")
    buckets = frame.apply(_exit_bucket, axis=1) if not frame.empty else pd.Series(dtype=str)
    bucket_counts = buckets.value_counts(normalize=True) if len(buckets) else pd.Series(dtype=float)

    result: dict[str, float | int | None] = {
        "count": count,
        "wins": int((returns > 0).sum()) if count else 0,
        "losses": int((returns < 0).sum()) if count else 0,
        "flats": int((returns == 0).sum()) if count else 0,
        "win_rate": float((returns > 0).sum() / count) if count else None,
        "avg_return": float(returns.mean()) if count else None,
        "median_return": float(returns.median()) if count else None,
        "trimmed_mean_1pct": _trimmed_mean(returns, 0.01),
        "trimmed_mean_5pct": _trimmed_mean(returns, 0.05),
        "winsorized_mean_1pct": _winsorized_mean(returns, 0.01),
        "winsorized_mean_5pct": _winsorized_mean(returns, 0.05),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": _ratio(avg_win, abs(avg_loss)) if avg_loss is not None else None,
        "expectancy": float(returns.mean()) if count else None,
        "median_loss": float(losses.median()) if len(losses) else None,
        "expected_shortfall_1pct": _expected_shortfall(returns, 0.01),
        "expected_shortfall_5pct": _expected_shortfall(returns, 0.05),
        "loss_rate_gt_3pct": _loss_rate(returns, 3.0),
        "loss_rate_gt_5pct": _loss_rate(returns, 5.0),
        "loss_rate_gt_10pct": _loss_rate(returns, 10.0),
        "avg_holding_days": float(holding.mean()) if len(holding) else None,
        "median_holding_days": float(holding.median()) if len(holding) else None,
        "p25_holding_days": float(holding.quantile(0.25)) if len(holding) else None,
        "p75_holding_days": float(holding.quantile(0.75)) if len(holding) else None,
        "p90_holding_days": float(holding.quantile(0.90)) if len(holding) else None,
        "max_holding_days": float(holding.max()) if len(holding) else None,
        "stop_loss_ratio": float(bucket_counts.get("stop_loss", 0.0)),
        "take_profit_ratio": float(bucket_counts.get("take_profit", 0.0)),
        "time_stop_ratio": float(bucket_counts.get("time_stop", 0.0)),
        "trailing_stop_ratio": float(bucket_counts.get("trailing_stop", 0.0)),
        "signal_exit_ratio": float(bucket_counts.get("signal_exit", 0.0)),
        "no_exit_ratio": float(bucket_counts.get("no_exit", 0.0)),
        "other_exit_ratio": float(bucket_counts.get("other", 0.0)),
    }
    for quantile in [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]:
        key = f"p{int(quantile * 100):02d}_return"
        result[key] = float(returns.quantile(quantile)) if count else None
    result["min_return"] = float(returns.min()) if count else None
    result["max_return"] = float(returns.max()) if count else None
    result.update(_tail_metrics_from_values(returns))
    return result


def _group_stats(
    frame: pd.DataFrame,
    group_keys: list[str],
    include_fields: Iterable[str] | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=group_keys + list(include_fields or SUMMARY_GROUP_FIELDS))
    rows: list[dict[str, object]] = []
    fields = list(include_fields) if include_fields is not None else None
    for keys, group in frame.groupby(group_keys, dropna=False, sort=True):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row: dict[str, object] = dict(zip(group_keys, key_values))
        stats = _stats_for_frame(group)
        if fields is not None:
            row.update({field: stats.get(field) for field in fields})
        else:
            row.update(stats)
        rows.append(row)
    return pd.DataFrame(rows)


def build_combo_summary(frame: pd.DataFrame) -> pd.DataFrame:
    summary = _group_stats(frame, COMBO_KEYS)
    if summary.empty:
        return summary
    return summary.sort_values(
        ["trimmed_mean_5pct", "median_return", "count"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)


def build_tail_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    fields = list(_tail_metrics_from_values(pd.Series(dtype=float)).keys())
    return _group_stats(frame, COMBO_KEYS, include_fields=fields)


def build_exit_reason_summary(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=COMBO_KEYS + ["exit_reason", "exit_reason_count", "exit_reason_ratio"]
        )
    working = frame.copy()
    working["exit_reason_bucket"] = working.apply(_exit_bucket, axis=1)
    rows: list[dict[str, object]] = []
    for keys, group in working.groupby(COMBO_KEYS, dropna=False, sort=True):
        total = len(group)
        for reason, reason_group in group.groupby("exit_reason_bucket", dropna=False, sort=True):
            rows.append(
                {
                    "entry_strategy": keys[0],
                    "exit_strategy": keys[1],
                    "exit_reason": reason,
                    "exit_reason_count": int(len(reason_group)),
                    "exit_reason_ratio": float(len(reason_group) / total) if total else None,
                }
            )
    return pd.DataFrame(rows)


def build_vs_fixed_horizon(frame: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=COMBO_KEYS)
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(COMBO_KEYS, dropna=False, sort=True):
        row: dict[str, object] = {"entry_strategy": keys[0], "exit_strategy": keys[1]}
        exit_returns = _series(group, "return_pct")
        avg_holding = _series(group, "holding_days").mean()
        for horizon in horizons:
            fixed = _series(group, f"forward_return_{horizon}d_pct")
            row[f"avg_return_vs_fixed_{horizon}d"] = (
                float(exit_returns.mean() - fixed.mean()) if len(exit_returns) and len(fixed) else None
            )
            row[f"median_return_vs_fixed_{horizon}d"] = (
                float(exit_returns.median() - fixed.median()) if len(exit_returns) and len(fixed) else None
            )
            row[f"trimmed5_vs_fixed_{horizon}d"] = (
                _trimmed_mean(exit_returns, 0.05) - _trimmed_mean(fixed, 0.05)
                if _trimmed_mean(exit_returns, 0.05) is not None and _trimmed_mean(fixed, 0.05) is not None
                else None
            )
            row[f"p10_vs_fixed_{horizon}d"] = (
                float(exit_returns.quantile(0.10) - fixed.quantile(0.10))
                if len(exit_returns) and len(fixed)
                else None
            )
            row[f"avg_holding_days_vs_{horizon}d"] = (
                float(avg_holding - horizon) if not pd.isna(avg_holding) else None
            )
        rows.append(row)
    return pd.DataFrame(rows)


def attach_market_regime(
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str, str]:
    if frame.empty:
        return frame.copy(), "empty", ""
    lookup, status, definition = _build_market_regime_lookup(benchmark_frame)
    working = frame.copy()
    working["signal_date_ts"] = pd.to_datetime(working["signal_date"], errors="coerce")
    working["market_regime"] = "unknown"
    if lookup.empty:
        return working, status, definition
    dated = working.loc[working["signal_date_ts"].notna(), ["signal_date_ts"]].copy()
    if dated.empty:
        return working, "missing_signal_dates", definition
    dated["_source_index"] = dated.index
    merged = pd.merge_asof(
        dated.sort_values("signal_date_ts"),
        lookup.rename(
            columns={"Date": "benchmark_date", "market_regime": "market_regime_lookup"}
        ).sort_values("benchmark_date"),
        left_on="signal_date_ts",
        right_on="benchmark_date",
        direction="backward",
    )
    assigned = merged.set_index("_source_index")["market_regime_lookup"].fillna("unknown")
    working.loc[assigned.index, "market_regime"] = assigned
    return working, status, definition


def attach_time_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy()
    dates = pd.to_datetime(working["signal_date"], errors="coerce")
    working["year"] = dates.dt.strftime("%Y")
    working["month"] = dates.dt.strftime("%m")
    working["year_month"] = dates.dt.strftime("%Y-%m")
    return working


def attach_signal_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy()
    metric = next(
        (
            column
            for column in ["rank_score", "score", "confidence"]
            if column in working.columns and pd.to_numeric(working[column], errors="coerce").notna().any()
        ),
        None,
    )
    working["rank_score_bucket"] = "unknown"
    if metric is None:
        return working
    for entry_name, group in working.groupby("entry_strategy", dropna=False):
        values = pd.to_numeric(group[metric], errors="coerce")
        valid_index = values[values.notna()].index
        if len(valid_index) == 0:
            continue
        unique_count = int(values.loc[valid_index].nunique())
        bucket_count = min(5, unique_count)
        if bucket_count <= 1:
            working.loc[valid_index, "rank_score_bucket"] = "Q1 weakest"
            continue
        buckets = pd.qcut(
            values.loc[valid_index],
            q=bucket_count,
            labels=False,
            duplicates="drop",
        )
        for idx, bucket in buckets.items():
            if pd.isna(bucket):
                continue
            bucket_number = int(bucket) + 1
            label = f"Q{bucket_number}"
            if bucket_number == 1:
                label = "Q1 weakest"
            elif bucket_number == bucket_count:
                label = f"Q{bucket_number} strongest"
            working.loc[idx, "rank_score_bucket"] = label
    return working


def build_by_year(frame: pd.DataFrame) -> pd.DataFrame:
    return _group_stats(frame, COMBO_KEYS + ["year"], include_fields=SUMMARY_GROUP_FIELDS)


def build_by_month(frame: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "count",
        "win_rate",
        "avg_return",
        "median_return",
        "trimmed_mean_5pct",
        "p10_return",
        "avg_loss",
        "expected_shortfall_5pct",
        "avg_holding_days",
    ]
    return _group_stats(frame, COMBO_KEYS + ["year_month"], include_fields=fields)


def build_by_market_regime(frame: pd.DataFrame) -> pd.DataFrame:
    return _group_stats(
        frame,
        COMBO_KEYS + ["market_regime"],
        include_fields=SUMMARY_GROUP_FIELDS,
    )


def build_by_signal_bucket(frame: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "count",
        "win_rate",
        "avg_return",
        "median_return",
        "trimmed_mean_5pct",
        "winsorized_mean_5pct",
        "p10_return",
        "p25_return",
        "p75_return",
        "p90_return",
        "avg_loss",
        "expected_shortfall_5pct",
        "top_5pct_contribution_ratio",
        "mean_without_top_5pct_return_pct",
        "avg_holding_days",
        "median_holding_days",
    ]
    return _group_stats(
        frame,
        COMBO_KEYS + ["rank_score_bucket"],
        include_fields=fields,
    )


def build_rankings(summary: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if summary.empty:
        return pd.DataFrame(), pd.DataFrame()
    robust = summary.sort_values(
        [
            "trimmed_mean_5pct",
            "median_return",
            "mean_without_top_5pct_return_pct",
            "top_5pct_contribution_ratio",
            "count",
        ],
        ascending=[False, False, False, True, False],
        na_position="last",
    ).reset_index(drop=True)
    robust.insert(0, "robustness_rank", range(1, len(robust) + 1))

    risk = summary.sort_values(
        [
            "p10_return",
            "expected_shortfall_5pct",
            "avg_loss",
            "loss_rate_gt_5pct",
            "avg_holding_days",
        ],
        ascending=[False, False, False, True, True],
        na_position="last",
    ).reset_index(drop=True)
    risk.insert(0, "risk_rank", range(1, len(risk) + 1))
    return robust, risk


def build_warnings(summary: pd.DataFrame, min_samples: int) -> list[str]:
    if summary.empty:
        return ["No simulated trades were produced."]
    warnings: list[str] = []
    low_count = summary[summary["count"] < min_samples]
    if not low_count.empty:
        warnings.append(f"{len(low_count)} combinations have count below {min_samples}.")
    tail_dependent = summary[
        pd.to_numeric(summary["top_5pct_contribution_ratio"], errors="coerce") > 0.5
    ]
    if not tail_dependent.empty:
        warnings.append(
            f"{len(tail_dependent)} combinations rely on top 5pct for more than 50pct of total summed return."
        )
    negative_without_top = summary[
        pd.to_numeric(summary["mean_without_top_5pct_return_pct"], errors="coerce") < 0
    ]
    if not negative_without_top.empty:
        warnings.append(
            f"{len(negative_without_top)} combinations have negative mean_without_top_5pct_return_pct."
        )
    high_no_exit = summary[pd.to_numeric(summary["no_exit_ratio"], errors="coerce") > 0.3]
    if not high_no_exit.empty:
        warnings.append(f"{len(high_no_exit)} combinations have no_exit_ratio above 30pct.")
    return warnings
