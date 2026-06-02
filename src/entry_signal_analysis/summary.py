from __future__ import annotations

import pandas as pd

from src.entry_signal_analysis.models import (
    EntrySignalAnalysisPrimaryGroupSummary,
    EntrySignalAnalysisPrimaryHorizonValidation,
    EntrySignalAnalysisPrimaryStats,
    SignalStrengthMetric,
)


MARKET_REGIME_LOOKBACK_DAYS = 20
MARKET_REGIME_BULL_THRESHOLD_PCT = 3.0
MARKET_REGIME_BEAR_THRESHOLD_PCT = -3.0
MARKET_REGIME_SOURCE = "TOPIX"
SIGNAL_STRENGTH_BUCKET_LIMIT = 5


def _empty_float_series() -> pd.Series:
    return pd.Series(dtype=float)


def _stringify_group_value(value: object) -> str:
    if value is None or pd.isna(value):
        return "unknown"
    return str(value)


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return _empty_float_series()
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _boolean_mask(series: pd.Series) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.lower().eq("true")


def _build_primary_stats_from_series(values: pd.Series) -> EntrySignalAnalysisPrimaryStats:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    count = int(len(valid))
    wins = int((valid > 0).sum()) if count else 0
    losses = int((valid < 0).sum()) if count else 0
    flats = int((valid == 0).sum()) if count else 0

    avg_return_pct = float(valid.mean()) if count else None
    median_return_pct = float(valid.median()) if count else None
    mean_minus_median_pct = (
        float(avg_return_pct - median_return_pct)
        if avg_return_pct is not None and median_return_pct is not None
        else None
    )
    avg_loss_pct = float(valid[valid < 0].mean()) if losses else None

    return EntrySignalAnalysisPrimaryStats(
        count=count,
        wins=wins,
        losses=losses,
        flats=flats,
        win_rate=float(wins / count) if count else None,
        avg_return_pct=avg_return_pct,
        median_return_pct=median_return_pct,
        mean_minus_median_pct=mean_minus_median_pct,
        mean_gt_median=(avg_return_pct > median_return_pct) if count else None,
        avg_loss_pct=avg_loss_pct,
        p10_return_pct=float(valid.quantile(0.10)) if count else None,
        p25_return_pct=float(valid.quantile(0.25)) if count else None,
        p50_return_pct=float(valid.quantile(0.50)) if count else None,
        p75_return_pct=float(valid.quantile(0.75)) if count else None,
        p90_return_pct=float(valid.quantile(0.90)) if count else None,
    )


def _prepare_primary_selected_frame(frame: pd.DataFrame, primary_horizon: int) -> pd.DataFrame:
    if frame.empty:
        empty = pd.DataFrame()
        empty["primary_return_pct"] = _empty_float_series()
        empty["signal_date_ts"] = pd.Series(dtype="datetime64[ns]")
        return empty

    selected = frame[frame["selected"] == True].copy() if "selected" in frame.columns else frame.copy()  # noqa: E712
    return_column = f"forward_return_{primary_horizon}d_pct"
    missing_column = f"forward_missing_{primary_horizon}d"

    if return_column not in selected.columns:
        empty = selected.iloc[0:0].copy()
        empty["primary_return_pct"] = _empty_float_series()
        empty["signal_date_ts"] = pd.Series(dtype="datetime64[ns]")
        return empty

    selected["primary_return_pct"] = pd.to_numeric(selected[return_column], errors="coerce")
    if missing_column in selected.columns:
        selected = selected[~_boolean_mask(selected[missing_column])].copy()
    selected = selected[selected["primary_return_pct"].notna()].copy()
    if "signal_date" in selected.columns:
        selected["signal_date_ts"] = pd.to_datetime(selected["signal_date"], errors="coerce")
    else:
        selected["signal_date_ts"] = pd.Series(pd.NaT, index=selected.index, dtype="datetime64[ns]")
    return selected


def _build_group_summaries(groups: list[tuple[str, pd.DataFrame]]) -> list[EntrySignalAnalysisPrimaryGroupSummary]:
    return [
        EntrySignalAnalysisPrimaryGroupSummary(
            group_key=group_key,
            group_label=group_key,
            stats=_build_primary_stats_from_series(group["primary_return_pct"]),
        )
        for group_key, group in groups
    ]


def _build_year_summaries(frame: pd.DataFrame) -> list[EntrySignalAnalysisPrimaryGroupSummary]:
    dated = frame[frame["signal_date_ts"].notna()].copy()
    if dated.empty:
        return []
    dated["signal_year"] = dated["signal_date_ts"].dt.strftime("%Y")
    groups = [
        (str(year), group)
        for year, group in dated.groupby("signal_year", sort=True, dropna=False)
    ]
    return _build_group_summaries(groups)


def _build_month_summaries(frame: pd.DataFrame) -> list[EntrySignalAnalysisPrimaryGroupSummary]:
    dated = frame[frame["signal_date_ts"].notna()].copy()
    if dated.empty:
        return []
    dated["signal_month"] = dated["signal_date_ts"].dt.strftime("%Y-%m")
    groups = [
        (str(month), group)
        for month, group in dated.groupby("signal_month", sort=True, dropna=False)
    ]
    return _build_group_summaries(groups)


def _build_entry_filter_summaries(frame: pd.DataFrame) -> list[EntrySignalAnalysisPrimaryGroupSummary]:
    if frame.empty or "entry_filter_name" not in frame.columns:
        return []
    groups = [
        (_stringify_group_value(filter_name), group)
        for filter_name, group in frame.groupby("entry_filter_name", sort=True, dropna=False)
    ]
    return _build_group_summaries(groups)


def _normalize_benchmark_frame(benchmark_frame: pd.DataFrame | None) -> pd.DataFrame:
    if benchmark_frame is None or benchmark_frame.empty:
        return pd.DataFrame()
    if "Date" not in benchmark_frame.columns or "Close" not in benchmark_frame.columns:
        return pd.DataFrame()
    normalized = benchmark_frame.copy()
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce").dt.normalize()
    normalized["Close"] = pd.to_numeric(normalized["Close"], errors="coerce")
    normalized = normalized.dropna(subset=["Date", "Close"])
    normalized = normalized.sort_values("Date")
    normalized = normalized.drop_duplicates(subset=["Date"], keep="last")
    return normalized.reset_index(drop=True)


def _build_market_regime_lookup(
    benchmark_frame: pd.DataFrame | None,
) -> tuple[pd.DataFrame, str, str]:
    definition = (
        f"{MARKET_REGIME_SOURCE} trailing {MARKET_REGIME_LOOKBACK_DAYS}-trading-day return: "
        f"bull >= {MARKET_REGIME_BULL_THRESHOLD_PCT:.1f}%, "
        f"bear <= {MARKET_REGIME_BEAR_THRESHOLD_PCT:.1f}%, otherwise sideways"
    )
    normalized = _normalize_benchmark_frame(benchmark_frame)
    if normalized.empty:
        return pd.DataFrame(), "missing_benchmark_data", definition
    if len(normalized) <= MARKET_REGIME_LOOKBACK_DAYS:
        return pd.DataFrame(), "insufficient_benchmark_history", definition

    normalized["trailing_return_pct"] = (
        normalized["Close"].pct_change(periods=MARKET_REGIME_LOOKBACK_DAYS) * 100.0
    )
    normalized["market_regime"] = "sideways"
    normalized.loc[
        normalized["trailing_return_pct"] >= MARKET_REGIME_BULL_THRESHOLD_PCT,
        "market_regime",
    ] = "bull"
    normalized.loc[
        normalized["trailing_return_pct"] <= MARKET_REGIME_BEAR_THRESHOLD_PCT,
        "market_regime",
    ] = "bear"
    normalized.loc[normalized["trailing_return_pct"].isna(), "market_regime"] = "unknown"
    return normalized[["Date", "market_regime"]].copy(), "available", definition


def _build_market_regime_summaries(
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame | None,
) -> tuple[list[EntrySignalAnalysisPrimaryGroupSummary], str, str]:
    lookup, status, definition = _build_market_regime_lookup(benchmark_frame)
    if frame.empty or lookup.empty or "signal_date_ts" not in frame.columns:
        return [], status, definition

    dated = frame[frame["signal_date_ts"].notna()].copy()
    if dated.empty:
        return [], "missing_signal_dates", definition

    merged = pd.merge_asof(
        dated.sort_values("signal_date_ts"),
        lookup.rename(columns={"Date": "benchmark_date"}).sort_values("benchmark_date"),
        left_on="signal_date_ts",
        right_on="benchmark_date",
        direction="backward",
    )
    merged = merged[merged["market_regime"].notna()].copy()
    if merged.empty:
        return [], "no_matching_benchmark_dates", definition

    order = {"bull": 0, "sideways": 1, "bear": 2, "unknown": 3}
    summaries = [
        EntrySignalAnalysisPrimaryGroupSummary(
            group_key=_stringify_group_value(regime),
            group_label=_stringify_group_value(regime),
            stats=_build_primary_stats_from_series(group["primary_return_pct"]),
        )
        for regime, group in merged.groupby("market_regime", sort=False, dropna=False)
    ]
    summaries.sort(key=lambda item: order.get(item.group_key, 99))
    return summaries, status, definition


def _resolve_signal_strength_metric(frame: pd.DataFrame) -> SignalStrengthMetric | None:
    for metric in ("rank_score", "score", "confidence"):
        if metric in frame.columns and pd.to_numeric(frame[metric], errors="coerce").notna().any():
            return metric  # type: ignore[return-value]
    return None


def _build_signal_strength_summaries(
    frame: pd.DataFrame,
) -> tuple[SignalStrengthMetric | None, str | None, list[EntrySignalAnalysisPrimaryGroupSummary]]:
    metric = _resolve_signal_strength_metric(frame)
    if metric is None:
        return None, None, []

    working = frame.copy()
    working["signal_strength_value"] = pd.to_numeric(working[metric], errors="coerce")
    working = working[working["signal_strength_value"].notna()].copy()
    if working.empty:
        return metric, None, []

    bucket_count = min(SIGNAL_STRENGTH_BUCKET_LIMIT, int(working["signal_strength_value"].nunique()))
    if bucket_count <= 1:
        working["signal_strength_bucket"] = "Q1"
        bucket_count = 1
    else:
        bucket_codes = pd.qcut(
            working["signal_strength_value"],
            q=bucket_count,
            labels=False,
            duplicates="drop",
        )
        if bucket_codes.isna().all():
            working["signal_strength_bucket"] = "Q1"
            bucket_count = 1
        else:
            working["signal_strength_bucket"] = bucket_codes.astype("Int64").map(
                lambda value: f"Q{int(value) + 1}" if pd.notna(value) else None
            )
            bucket_count = int(working["signal_strength_bucket"].dropna().nunique())

    summaries: list[EntrySignalAnalysisPrimaryGroupSummary] = []
    for bucket_index in range(bucket_count):
        bucket_key = f"Q{bucket_index + 1}"
        group = working[working["signal_strength_bucket"] == bucket_key]
        if group.empty:
            continue
        label = bucket_key
        if bucket_index == 0:
            label = f"{bucket_key} weakest"
        elif bucket_index == bucket_count - 1:
            label = f"{bucket_key} strongest"
        summaries.append(
            EntrySignalAnalysisPrimaryGroupSummary(
                group_key=bucket_key,
                group_label=label,
                stats=_build_primary_stats_from_series(group["primary_return_pct"]),
                strength_min=float(group["signal_strength_value"].min()),
                strength_max=float(group["signal_strength_value"].max()),
            )
        )

    return metric, f"quantile_{bucket_count}", summaries


def _build_horizon_stats(frame: pd.DataFrame, horizons: list[int]) -> dict[str, dict[str, object]]:
    stats: dict[str, dict[str, object]] = {}
    for horizon in horizons:
        column = f"forward_return_{horizon}d_pct"
        diff_column = f"forward_diff_{horizon}d"
        valid = _numeric_series(frame, column)
        diff_values = _numeric_series(frame, diff_column)
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

    rows: list[dict[str, object]] = []
    group_keys = ["entry_strategy", "entry_filter_name", "signal_date"]
    for keys, group in frame.groupby(group_keys, dropna=False):
        entry_strategy, entry_filter_name, signal_date = keys
        row: dict[str, object] = {
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

    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        selected = group[group["selected"] == True]  # noqa: E712
        row: dict[str, object] = {
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


def build_overall_summary(frame: pd.DataFrame, horizons: list[int]) -> dict[str, object]:
    selected = frame[frame["selected"] == True] if not frame.empty else frame
    return {
        "candidate_count": int(len(frame)),
        "selected_count": int(len(selected)),
        "trading_day_count": int(frame["signal_date"].nunique()) if not frame.empty else 0,
        **_build_horizon_stats(selected, horizons),
    }


def build_primary_horizon_validation(
    frame: pd.DataFrame,
    primary_horizon: int,
    benchmark_frame: pd.DataFrame | None = None,
) -> EntrySignalAnalysisPrimaryHorizonValidation:
    selected = _prepare_primary_selected_frame(frame, primary_horizon)
    signal_strength_metric, bucket_method, by_signal_strength_bucket = (
        _build_signal_strength_summaries(selected)
    )
    by_market_regime, market_regime_status, market_regime_definition = (
        _build_market_regime_summaries(selected, benchmark_frame)
    )

    return EntrySignalAnalysisPrimaryHorizonValidation(
        primary_horizon=primary_horizon,
        primary_horizon_label=f"{primary_horizon}d",
        primary_return_column=f"forward_return_{primary_horizon}d_pct",
        signal_strength_metric=signal_strength_metric,
        signal_strength_bucket_method=bucket_method,
        market_regime_source=MARKET_REGIME_SOURCE,
        market_regime_status=market_regime_status,
        market_regime_definition=market_regime_definition,
        overall=_build_primary_stats_from_series(selected["primary_return_pct"]),
        by_year=_build_year_summaries(selected),
        by_month=_build_month_summaries(selected),
        by_market_regime=by_market_regime,
        by_entry_filter=_build_entry_filter_summaries(selected),
        by_signal_strength_bucket=by_signal_strength_bucket,
    )


def top_daily_windows(daily_summary: pd.DataFrame, primary_horizon: int, limit: int = 10) -> list[dict[str, object]]:
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