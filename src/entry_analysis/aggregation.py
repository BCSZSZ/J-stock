from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from src.entry_analysis.models import FeatureBucketRule, FeatureCondition, FeatureLogicMode, ManualRange


def default_rules() -> list[FeatureBucketRule]:
    return [
        FeatureBucketRule(feature="RSI", mode="sliding", min=0, max=100, window=10, step=5),
        FeatureBucketRule(feature="RSI_9", mode="sliding", min=0, max=100, window=10, step=5),
        FeatureBucketRule(feature="ADX_14", mode="sliding", min=0, max=60, window=10, step=5),
        FeatureBucketRule(feature="bias_pct", mode="sliding", window=4, step=2),
        FeatureBucketRule(feature="metadata_return_5d_pct", mode="sliding", window=5, step=2.5),
        FeatureBucketRule(feature="buy_signal_streak_days", mode="sliding", window=3, step=1),
        FeatureBucketRule(feature="stale_buy_signal", mode="categorical"),
    ]


def build_preset_rules(name: str | None) -> list[FeatureBucketRule]:
    preset = (name or "default").strip().lower()
    if preset in {"default", "rsi_adx_ema"}:
        return default_rules()
    if preset == "none":
        return []
    raise ValueError(f"Unknown entry-analysis preset rules: {name}")


def _format_bound(value: float | None) -> str:
    if value is None:
        return ""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


def _manual_label(rule: FeatureBucketRule, item: ManualRange) -> str:
    if item.label:
        return item.label
    left = "-inf" if item.min is None else _format_bound(item.min)
    right = "inf" if item.max is None else _format_bound(item.max)
    return f"{rule.feature}:[{left},{right})"


def _numeric_bounds(series: pd.Series, rule: FeatureBucketRule, width: float | None) -> tuple[float, float]:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return 0.0, 0.0
    lower = float(rule.min) if rule.min is not None else math.floor(float(numeric.quantile(0.02)))
    upper = float(rule.max) if rule.max is not None else math.ceil(float(numeric.quantile(0.98)))
    if width is not None and upper <= lower:
        upper = lower + width
    return lower, upper


def assign_bucket_labels(frame: pd.DataFrame, rule: FeatureBucketRule) -> pd.Series:
    if rule.feature not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="object")

    source = frame[rule.feature]
    labels = pd.Series(pd.NA, index=frame.index, dtype="object")

    if rule.mode == "categorical":
        labels = source.astype("object").where(source.notna(), pd.NA).astype("string")
        return labels.astype("object")

    numeric = pd.to_numeric(source, errors="coerce")

    if rule.mode == "manual":
        for item in rule.ranges:
            mask = numeric.notna()
            if item.min is not None:
                mask &= numeric >= item.min
            if item.max is not None:
                mask &= numeric < item.max
            labels.loc[mask] = _manual_label(rule, item)
        return labels

    if rule.mode == "quantile":
        quantiles = max(2, int(rule.quantiles or 5))
        try:
            bins = pd.qcut(numeric, quantiles, duplicates="drop")
        except ValueError:
            return labels
        return bins.astype("string").astype("object")

    if rule.mode == "fixed":
        width = float(rule.bin_width or rule.window or 10)
        step = width
    else:
        width = float(rule.window or 10)
        step = float(rule.step or width)

    lower, upper = _numeric_bounds(numeric, rule, width)
    start = lower
    while start <= upper - width + 1e-12:
        end = start + width
        mask = (numeric >= start) & (numeric < end)
        labels.loc[mask] = f"{rule.feature}:[{_format_bound(start)},{_format_bound(end)})"
        start += step
    return labels


def _aggregate_group(
    group: pd.DataFrame,
    *,
    horizon: int,
    total_wins: int,
    total_losses: int,
    baseline_win_rate: float,
) -> dict[str, object]:
    return_col = f"forward_return_{horizon}d_pct"
    returns = pd.to_numeric(group[return_col], errors="coerce").dropna()
    is_win = returns > 0
    count = int(len(returns))
    wins = int(is_win.sum())
    losses = count - wins
    win_rate = wins / count if count else 0.0
    win_capture = wins / total_wins if total_wins else 0.0
    loss_capture = losses / total_losses if total_losses else 0.0
    lift = win_rate / baseline_win_rate if baseline_win_rate else 0.0
    avg_win = float(returns[is_win].mean()) if wins else None
    avg_loss = float(returns[~is_win].mean()) if losses else None
    return {
        "horizon": horizon,
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_return_pct": float(returns.mean()) if count else None,
        "median_return_pct": float(returns.median()) if count else None,
        "p25_return_pct": float(returns.quantile(0.25)) if count else None,
        "p75_return_pct": float(returns.quantile(0.75)) if count else None,
        "avg_win_return_pct": avg_win,
        "avg_loss_return_pct": avg_loss,
        "win_capture": win_capture,
        "loss_capture": loss_capture,
        "lift": lift,
        "edge": win_capture - loss_capture,
        "score": (win_capture - loss_capture) * math.log1p(count),
    }


def compute_return_stats(
    frame: pd.DataFrame,
    horizon: int,
    *,
    baseline_win_rate: float | None = None,
) -> dict[str, object]:
    return_col = f"forward_return_{horizon}d_pct"
    if return_col not in frame.columns:
        return {
            "horizon": horizon,
            "count": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "avg_return_pct": None,
            "median_return_pct": None,
            "p25_return_pct": None,
            "p75_return_pct": None,
            "avg_win_return_pct": None,
            "avg_loss_return_pct": None,
            "lift": 0.0,
        }

    returns = pd.to_numeric(frame[return_col], errors="coerce").dropna()
    wins_mask = returns > 0
    count = int(len(returns))
    wins = int(wins_mask.sum())
    losses = count - wins
    win_rate = wins / count if count else 0.0
    baseline = float(baseline_win_rate or 0.0)
    return {
        "horizon": horizon,
        "count": count,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_return_pct": float(returns.mean()) if count else None,
        "median_return_pct": float(returns.median()) if count else None,
        "p25_return_pct": float(returns.quantile(0.25)) if count else None,
        "p75_return_pct": float(returns.quantile(0.75)) if count else None,
        "avg_win_return_pct": float(returns[wins_mask].mean()) if wins else None,
        "avg_loss_return_pct": float(returns[~wins_mask].mean()) if losses else None,
        "lift": win_rate / baseline if baseline else 0.0,
    }


def _condition_mask(frame: pd.DataFrame, condition: FeatureCondition) -> pd.Series:
    if condition.feature not in frame.columns:
        return pd.Series(False, index=frame.index)

    source = frame[condition.feature]
    operator = condition.operator
    if operator == "is_null":
        return source.isna()
    if operator == "not_null":
        return source.notna()

    numeric = pd.to_numeric(source, errors="coerce")
    if operator == "between":
        mask = numeric.notna()
        if condition.min is not None:
            mask &= numeric >= condition.min
        if condition.max is not None:
            mask &= numeric < condition.max
        return mask
    if operator == ">=":
        return numeric >= float(condition.value if condition.value is not None else condition.min or 0)
    if operator == ">":
        return numeric > float(condition.value if condition.value is not None else condition.min or 0)
    if operator == "<=":
        return numeric <= float(condition.value if condition.value is not None else condition.max or 0)
    if operator == "<":
        return numeric < float(condition.value if condition.value is not None else condition.max or 0)

    compare_value = condition.value
    if compare_value is None:
        compare_value = condition.min
    if compare_value is None:
        return pd.Series(False, index=frame.index)

    numeric_value = pd.to_numeric(pd.Series([compare_value]), errors="coerce").iloc[0]
    if pd.notna(numeric_value):
        return numeric == float(numeric_value) if operator == "==" else numeric != float(numeric_value)

    text = source.astype("string")
    compare_text = str(compare_value)
    return text == compare_text if operator == "==" else text != compare_text


def filter_candidates(
    candidates: pd.DataFrame,
    conditions: Iterable[FeatureCondition],
    logic: FeatureLogicMode = "all",
) -> pd.DataFrame:
    resolved = list(conditions)
    if not resolved:
        return candidates.copy()

    masks = [_condition_mask(candidates, condition) for condition in resolved]
    if logic == "any":
        combined = masks[0].copy()
        for mask in masks[1:]:
            combined |= mask
    else:
        combined = masks[0].copy()
        for mask in masks[1:]:
            combined &= mask
    return candidates.loc[combined].copy()


def aggregate_filtered_candidates(
    candidates: pd.DataFrame,
    conditions: Iterable[FeatureCondition],
    horizons: list[int],
    *,
    logic: FeatureLogicMode = "all",
    group_by: str | None = None,
    min_samples: int = 1,
) -> dict[str, object]:
    filtered = filter_candidates(candidates, conditions, logic)
    baseline = compute_baseline(candidates, horizons)
    filtered_stats: dict[str, object] = {}
    groups: list[dict[str, object]] = []

    for horizon in horizons:
        baseline_horizon = baseline.get(f"{horizon}d")
        baseline_win_rate = 0.0
        if isinstance(baseline_horizon, dict):
            baseline_win_rate = float(baseline_horizon.get("win_rate") or 0.0)
        filtered_stats[f"{horizon}d"] = compute_return_stats(
            filtered,
            horizon,
            baseline_win_rate=baseline_win_rate,
        )

        if group_by and group_by in filtered.columns:
            for bucket, group in filtered.groupby(group_by, dropna=False):
                stats = compute_return_stats(group, horizon, baseline_win_rate=baseline_win_rate)
                if int(stats["count"]) < min_samples:
                    continue
                groups.append({
                    "horizon": horizon,
                    "feature": group_by,
                    "bucket": "<NA>" if pd.isna(bucket) else str(bucket),
                    **stats,
                })

    groups.sort(key=lambda item: (int(item["horizon"]), -float(item.get("lift") or 0), -int(item.get("count") or 0)))
    return {
        "logic": logic,
        "baseline": baseline,
        "filtered": {"candidate_count": int(len(filtered)), **filtered_stats},
        "groups": groups,
    }


def _baseline_for_horizon(frame: pd.DataFrame, horizon: int) -> tuple[int, int, float]:
    return_col = f"forward_return_{horizon}d_pct"
    returns = pd.to_numeric(frame[return_col], errors="coerce").dropna()
    wins = int((returns > 0).sum())
    losses = int((returns <= 0).sum())
    baseline_win_rate = wins / len(returns) if len(returns) else 0.0
    return wins, losses, baseline_win_rate


def aggregate_candidates(
    candidates: pd.DataFrame,
    rules: Iterable[FeatureBucketRule],
    horizons: list[int],
    *,
    min_samples: int = 30,
    include_joint: bool = True,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()

    resolved_rules = list(rules)
    records: list[dict[str, object]] = []
    bucket_columns: list[tuple[FeatureBucketRule, str]] = []

    working = candidates.copy()
    for index, rule in enumerate(resolved_rules):
        bucket_col = f"__bucket_{index}"
        working[bucket_col] = assign_bucket_labels(working, rule)
        bucket_columns.append((rule, bucket_col))

    for horizon in horizons:
        return_col = f"forward_return_{horizon}d_pct"
        if return_col not in working.columns:
            continue
        horizon_frame = working[working[return_col].notna()].copy()
        total_wins, total_losses, baseline_win_rate = _baseline_for_horizon(horizon_frame, horizon)

        for rule, bucket_col in bucket_columns:
            subset = horizon_frame[horizon_frame[bucket_col].notna()]
            for bucket, group in subset.groupby(bucket_col, dropna=False):
                metrics = _aggregate_group(
                    group,
                    horizon=horizon,
                    total_wins=total_wins,
                    total_losses=total_losses,
                    baseline_win_rate=baseline_win_rate,
                )
                if metrics["count"] < min_samples:
                    continue
                records.append({
                    "analysis_type": "marginal",
                    "features": rule.feature,
                    "bucket": str(bucket),
                    **metrics,
                })

        if include_joint and len(bucket_columns) >= 2:
            joint_cols = [bucket_col for _, bucket_col in bucket_columns]
            subset = horizon_frame.dropna(subset=joint_cols)
            if not subset.empty:
                groupby_cols = joint_cols
                for keys, group in subset.groupby(groupby_cols, dropna=False):
                    if not isinstance(keys, tuple):
                        keys = (keys,)
                    metrics = _aggregate_group(
                        group,
                        horizon=horizon,
                        total_wins=total_wins,
                        total_losses=total_losses,
                        baseline_win_rate=baseline_win_rate,
                    )
                    if metrics["count"] < min_samples:
                        continue
                    feature_names = [rule.feature for rule, _ in bucket_columns]
                    records.append({
                        "analysis_type": "joint",
                        "features": " & ".join(feature_names),
                        "bucket": " | ".join(str(key) for key in keys),
                        **metrics,
                    })

    if not records:
        return pd.DataFrame()
    result = pd.DataFrame(records)
    return result.sort_values(["horizon", "score", "count"], ascending=[True, False, False])


def compute_baseline(candidates: pd.DataFrame, horizons: list[int]) -> dict[str, object]:
    baseline: dict[str, object] = {"candidate_count": int(len(candidates))}
    for horizon in horizons:
        return_col = f"forward_return_{horizon}d_pct"
        if return_col not in candidates.columns:
            continue
        returns = pd.to_numeric(candidates[return_col], errors="coerce").dropna()
        wins = int((returns > 0).sum())
        losses = int((returns <= 0).sum())
        baseline[f"{horizon}d"] = {
            "count": int(len(returns)),
            "wins": wins,
            "losses": losses,
            "win_rate": wins / len(returns) if len(returns) else 0.0,
            "avg_return_pct": float(returns.mean()) if len(returns) else None,
            "median_return_pct": float(returns.median()) if len(returns) else None,
        }
    return baseline
