from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.scanner import (
    EntrySignalEventContext,
    EntrySignalScanResult,
)
from src.entry_signal_analysis.summary import (
    _build_market_regime_lookup,
    _build_primary_stats_from_series,
)
from src.utils.industry_filter import (
    DEFAULT_INDUSTRY_REFERENCE_FILE,
    get_industry_name,
)


PRIORITY15_PATH_HORIZONS = (10, 20, 40, 60, 80)
PRIORITY15_EXIT_HORIZONS = (20, 40, 60, 80)


@dataclass(frozen=True)
class Priority15Outputs:
    event_metrics: pd.DataFrame = field(default_factory=pd.DataFrame)
    path_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    target_stop_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    target_stop_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    checkpoint_events: pd.DataFrame = field(default_factory=pd.DataFrame)
    checkpoint_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    trend_feature_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    cooldown_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    alpha_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    regime_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    stability_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    signal_decay_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    execution_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    exit_rule_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    walk_forward_summary: pd.DataFrame = field(default_factory=pd.DataFrame)
    warnings: list[str] = field(default_factory=list)


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class _FeatureView:
    frame: pd.DataFrame
    date_labels: tuple[str, ...]
    numeric_columns: dict[str, np.ndarray]

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "_FeatureView":
        numeric_columns: dict[str, np.ndarray] = {}
        for column in frame.columns:
            series = pd.to_numeric(frame[column], errors="coerce")
            if series.notna().any():
                numeric_columns[str(column)] = series.to_numpy(dtype="float64")
        return cls(
            frame=frame,
            date_labels=tuple(pd.Timestamp(value).date().isoformat() for value in frame.index),
            numeric_columns=numeric_columns,
        )

    def __len__(self) -> int:
        return len(self.frame)

    def has_column(self, column: str) -> bool:
        return column in self.numeric_columns

    def price_at(self, row_pos: int, column: str) -> float | None:
        if row_pos < 0 or row_pos >= len(self):
            return None
        values = self.numeric_columns.get(column)
        if values is None:
            return None
        value = float(values[row_pos])
        return value if math.isfinite(value) else None

    def date_at(self, row_pos: int) -> str | None:
        if row_pos < 0 or row_pos >= len(self.date_labels):
            return None
        return self.date_labels[row_pos]

    def nanmean(self, column: str, start_pos: int, end_pos: int) -> float | None:
        values = self.numeric_columns.get(column)
        if values is None:
            return None
        start = max(0, start_pos)
        end = min(len(values) - 1, end_pos)
        if start > end:
            return None
        subset = values[start : end + 1]
        if np.isnan(subset).all():
            return None
        value = float(np.nanmean(subset))
        return value if math.isfinite(value) else None

    def window(self, column: str, start_pos: int, end_pos: int) -> np.ndarray:
        values = self.numeric_columns.get(column)
        if values is None:
            return np.array([], dtype="float64")
        start = max(0, start_pos)
        end = min(len(values) - 1, end_pos)
        if start > end:
            return np.array([], dtype="float64")
        return values[start : end + 1]

    def forward_return_pct(
        self,
        *,
        signal_pos: int,
        horizon: int,
        label_mode: str,
    ) -> float | None:
        if label_mode == "next_open":
            entry_price = self.price_at(signal_pos + 1, "Open")
        else:
            entry_price = self.price_at(signal_pos, "Close")
        target_price = self.price_at(signal_pos + int(horizon), "Close")
        return _return_pct(target_price, entry_price)


def _log_priority15_stage(name: str, started_at: float, rows: int | None = None) -> None:
    rows_text = "" if rows is None else f" rows={rows}"
    print(
        f"[entry-signal-analysis] priority15 {name}: "
        f"elapsed={time.perf_counter() - started_at:.2f}s{rows_text}",
        flush=True,
    )


def _log_priority15_progress(name: str, processed: int, total: int) -> None:
    print(
        f"[entry-signal-analysis] priority15 {name}: processed {processed}/{total}",
        flush=True,
    )


def _is_missing(value: object) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return False


def _numeric_mean(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    return _to_float(pd.to_numeric(frame[column], errors="coerce").mean())


def _numeric_median(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns:
        return None
    return _to_float(pd.to_numeric(frame[column], errors="coerce").median())


def _frame_len(frame: pd.DataFrame | _FeatureView) -> int:
    return len(frame)


def _has_column(frame: pd.DataFrame | _FeatureView, column: str) -> bool:
    if isinstance(frame, _FeatureView):
        return frame.has_column(column)
    return column in frame.columns


def _price_at(frame: pd.DataFrame | _FeatureView, row_pos: int, column: str) -> float | None:
    if isinstance(frame, _FeatureView):
        return frame.price_at(row_pos, column)
    if row_pos < 0 or row_pos >= len(frame) or column not in frame.columns:
        return None
    return _to_float(frame.iloc[row_pos].get(column))


def _date_at(frame: pd.DataFrame | _FeatureView, row_pos: int) -> str | None:
    if isinstance(frame, _FeatureView):
        return frame.date_at(row_pos)
    if row_pos < 0 or row_pos >= len(frame):
        return None
    return pd.Timestamp(frame.index[row_pos]).date().isoformat()


def _return_pct(price: float | None, entry_price: float | None) -> float | None:
    if price is None or entry_price is None or entry_price <= 0:
        return None
    return (price / entry_price - 1.0) * 100.0


def _bool_selected(frame: pd.DataFrame) -> pd.Series:
    if frame.empty or "selected" not in frame.columns:
        return pd.Series(False, index=frame.index)
    series = frame["selected"]
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(False)
    return series.astype(str).str.lower().eq("true")


def _selected_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if "selected" not in frame.columns:
        return frame.copy()
    return frame[_bool_selected(frame)].copy()


def _event_id_from_parts(row: pd.Series) -> str:
    return "::".join(
        [
            str(row.get("entry_strategy") or "unknown"),
            str(row.get("entry_filter_name") or "unknown"),
            str(row.get("ticker") or "unknown"),
            str(row.get("signal_date") or "unknown"),
        ]
    )


def _context_key(context: EntrySignalEventContext) -> tuple[str, str, str, str]:
    return (
        str(context.entry_strategy),
        str(context.entry_filter_name),
        str(context.ticker),
        str(context.signal_date),
    )


def _context_maps(
    contexts: Iterable[EntrySignalEventContext],
) -> tuple[dict[str, EntrySignalEventContext], dict[tuple[str, str, str, str], EntrySignalEventContext]]:
    by_event_id: dict[str, EntrySignalEventContext] = {}
    by_key: dict[tuple[str, str, str, str], EntrySignalEventContext] = {}
    for context in contexts:
        event_id = str(context.payload.get("event_id") or "")
        if event_id:
            by_event_id[event_id] = context
        by_key[_context_key(context)] = context
    return by_event_id, by_key


def _find_context_from_values(
    row: dict[str, object],
    by_event_id: dict[str, EntrySignalEventContext],
    by_key: dict[tuple[str, str, str, str], EntrySignalEventContext],
) -> EntrySignalEventContext | None:
    event_id = str(row.get("event_id") or "")
    if event_id and event_id in by_event_id:
        return by_event_id[event_id]
    return by_key.get(
        (
            str(row.get("entry_strategy")),
            str(row.get("entry_filter_name")),
            str(row.get("ticker")),
            str(row.get("signal_date")),
        )
    )


def _latest_existing_column(frame: pd.DataFrame, names: Iterable[str]) -> str | None:
    for name in names:
        if name in frame.columns:
            return name
    return None


def _snapshot_row(frame: pd.DataFrame | _FeatureView, row_pos: int) -> pd.Series | None:
    if isinstance(frame, _FeatureView):
        frame = frame.frame
    if row_pos < 0 or row_pos >= len(frame):
        return None
    return frame.iloc[row_pos]


def _volume_ratio(frame: pd.DataFrame | _FeatureView, row_pos: int) -> float | None:
    volume = _price_at(frame, row_pos, "Volume")
    average = _price_at(frame, row_pos, "Volume_SMA_20")
    if average is None and _has_column(frame, "Volume") and row_pos >= 0:
        start = max(0, row_pos - 19)
        if isinstance(frame, _FeatureView):
            average = frame.nanmean("Volume", start, row_pos)
        else:
            average = _to_float(pd.to_numeric(frame["Volume"].iloc[start : row_pos + 1], errors="coerce").mean())
    if volume is None or average is None or average <= 0:
        return None
    return volume / average


def _turnover(frame: pd.DataFrame | _FeatureView, row_pos: int) -> float | None:
    turnover = _price_at(frame, row_pos, "Turnover_Median_20")
    if turnover is not None:
        return turnover
    turnover = _price_at(frame, row_pos, "Turnover")
    if turnover is not None:
        return turnover
    close = _price_at(frame, row_pos, "Close")
    volume = _price_at(frame, row_pos, "Volume")
    if close is None or volume is None:
        return None
    return close * volume


def _ma_slope(frame: pd.DataFrame | _FeatureView, row_pos: int, column: str, lookback: int = 5) -> float | None:
    current = _price_at(frame, row_pos, column)
    prior = _price_at(frame, row_pos - lookback, column)
    if current is None or prior is None or prior == 0:
        return None
    return (current / prior - 1.0) * 100.0


def _append_trend_snapshot(
    values: dict[str, object],
    *,
    frame: pd.DataFrame | _FeatureView,
    row_pos: int,
    prefix: str,
    entry_price: float | None,
    entry_bb_width: float | None,
) -> None:
    if row_pos < 0 or row_pos >= _frame_len(frame):
        values[f"{prefix}_feature_available"] = False
        return

    values[f"{prefix}_feature_available"] = True
    close = _price_at(frame, row_pos, "Close")
    values[f"{prefix}_close"] = close
    for period in (20, 50, 200):
        column = f"EMA_{period}"
        ma_value = _price_at(frame, row_pos, column)
        values[f"{prefix}_close_above_ma{period}"] = (
            None if close is None or ma_value is None else close > ma_value
        )
        values[f"{prefix}_distance_to_ma{period}_pct"] = (
            None if close is None or ma_value in (None, 0) else (close / ma_value - 1.0) * 100.0
        )
        values[f"{prefix}_ma{period}_slope_5d_pct"] = _ma_slope(frame, row_pos, column)

    ema20 = _price_at(frame, row_pos, "EMA_20")
    ema50 = _price_at(frame, row_pos, "EMA_50")
    ema200 = _price_at(frame, row_pos, "EMA_200")
    values[f"{prefix}_ma_bull_stack"] = (
        None
        if close is None or ema20 is None or ema50 is None or ema200 is None
        else close > ema20 > ema50 > ema200
    )
    values[f"{prefix}_volume_ratio"] = _volume_ratio(frame, row_pos)
    values[f"{prefix}_atr_ratio"] = _price_at(frame, row_pos, "ATR_Ratio")
    values[f"{prefix}_rsi"] = _price_at(frame, row_pos, "RSI")
    values[f"{prefix}_adx_14"] = _price_at(frame, row_pos, "ADX_14")

    span_a = _price_at(frame, row_pos, "Ichi_SpanA")
    span_b = _price_at(frame, row_pos, "Ichi_SpanB")
    kijun = _price_at(frame, row_pos, "Ichi_Kijun")
    cloud_top = max(span_a, span_b) if span_a is not None and span_b is not None else None
    values[f"{prefix}_ichimoku_above_cloud"] = (
        None if close is None or cloud_top is None else close > cloud_top
    )
    values[f"{prefix}_ichimoku_cloud_bullish"] = (
        None if span_a is None or span_b is None else span_a > span_b
    )
    values[f"{prefix}_ichimoku_kijun_distance_pct"] = (
        None if close is None or kijun in (None, 0) else (close / kijun - 1.0) * 100.0
    )

    bb_width = _price_at(frame, row_pos, "BB_Width")
    values[f"{prefix}_bb_width"] = bb_width
    values[f"{prefix}_bb_expansion_from_entry_pct"] = (
        None
        if bb_width is None or entry_bb_width in (None, 0)
        else (bb_width / entry_bb_width - 1.0) * 100.0
    )
    values[f"{prefix}_return_from_entry_pct"] = _return_pct(close, entry_price)


def _path_metrics_for_horizon(
    frame: pd.DataFrame | _FeatureView,
    *,
    signal_pos: int,
    entry_pos: int,
    entry_price: float | None,
    horizon: int,
    label_mode: str,
) -> dict[str, object]:
    prefix = f"{horizon}d"
    if entry_price is None or entry_price <= 0 or entry_pos >= len(frame):
        return {
            f"MFE_{prefix}_pct": None,
            f"MAE_{prefix}_pct": None,
            f"time_to_MFE_{prefix}": None,
            f"time_to_MAE_{prefix}": None,
            f"days_underwater_{prefix}": None,
            f"profit_giveback_{prefix}_pct": None,
            f"MFE_capture_ratio_{prefix}": None,
        }

    start_pos = entry_pos if label_mode == "next_open" else entry_pos + 1
    end_pos = min(len(frame) - 1, signal_pos + int(horizon))
    if start_pos > end_pos:
        return {
            f"MFE_{prefix}_pct": None,
            f"MAE_{prefix}_pct": None,
            f"time_to_MFE_{prefix}": None,
            f"time_to_MAE_{prefix}": None,
            f"days_underwater_{prefix}": None,
            f"profit_giveback_{prefix}_pct": None,
            f"MFE_capture_ratio_{prefix}": None,
        }

    if isinstance(frame, _FeatureView):
        high_values = frame.window("High", start_pos, end_pos)
        low_values = frame.window("Low", start_pos, end_pos)
        close_values = frame.window("Close", start_pos, end_pos)
        if high_values.size == 0:
            high_values = close_values
        if low_values.size == 0:
            low_values = close_values
        if high_values.size == 0 and low_values.size == 0:
            return {
                f"MFE_{prefix}_pct": None,
                f"MAE_{prefix}_pct": None,
                f"time_to_MFE_{prefix}": None,
                f"time_to_MAE_{prefix}": None,
                f"days_underwater_{prefix}": None,
                f"profit_giveback_{prefix}_pct": None,
                f"MFE_capture_ratio_{prefix}": None,
            }
        mfe_values = (high_values / entry_price - 1.0) * 100.0
        mae_values = (low_values / entry_price - 1.0) * 100.0
        mfe = None if mfe_values.size == 0 or np.isnan(mfe_values).all() else float(np.nanmax(mfe_values))
        mae = None if mae_values.size == 0 or np.isnan(mae_values).all() else float(np.nanmin(mae_values))
        forward_return = _return_pct(frame.price_at(signal_pos + int(horizon), "Close"), entry_price)
        days_underwater = (
            None
            if close_values.size == 0 or np.isnan(close_values).all()
            else int(np.nansum(close_values < entry_price))
        )
        return {
            f"MFE_{prefix}_pct": mfe,
            f"MAE_{prefix}_pct": mae,
            f"time_to_MFE_{prefix}": (
                int(np.nanargmax(mfe_values) + 1)
                if mfe is not None and mfe_values.size > 0
                else None
            ),
            f"time_to_MAE_{prefix}": (
                int(np.nanargmin(mae_values) + 1)
                if mae is not None and mae_values.size > 0
                else None
            ),
            f"days_underwater_{prefix}": days_underwater,
            f"profit_giveback_{prefix}_pct": (
                None if mfe is None or forward_return is None else mfe - forward_return
            ),
            f"MFE_capture_ratio_{prefix}": (
                None
                if mfe is None or mfe <= 0 or forward_return is None
                else forward_return / mfe
            ),
        }

    window = frame.iloc[start_pos : end_pos + 1]
    high_col = "High" if "High" in window.columns else "Close"
    low_col = "Low" if "Low" in window.columns else "Close"
    highs = pd.to_numeric(window[high_col], errors="coerce")
    lows = pd.to_numeric(window[low_col], errors="coerce")
    closes = pd.to_numeric(window["Close"], errors="coerce") if "Close" in window.columns else pd.Series(dtype=float)
    mfe_series = (highs / entry_price - 1.0) * 100.0
    mae_series = (lows / entry_price - 1.0) * 100.0
    mfe = _to_float(mfe_series.max())
    mae = _to_float(mae_series.min())
    return_col = _price_at(frame, signal_pos + int(horizon), "Close")
    forward_return = _return_pct(return_col, entry_price)
    return {
        f"MFE_{prefix}_pct": mfe,
        f"MAE_{prefix}_pct": mae,
        f"time_to_MFE_{prefix}": (
            int(window.index.get_loc(mfe_series.idxmax()) + 1)
            if mfe is not None and not mfe_series.dropna().empty
            else None
        ),
        f"time_to_MAE_{prefix}": (
            int(window.index.get_loc(mae_series.idxmin()) + 1)
            if mae is not None and not mae_series.dropna().empty
            else None
        ),
        f"days_underwater_{prefix}": (
            int((closes < entry_price).sum()) if not closes.dropna().empty else None
        ),
        f"profit_giveback_{prefix}_pct": (
            None if mfe is None or forward_return is None else mfe - forward_return
        ),
        f"MFE_capture_ratio_{prefix}": (
            None
            if mfe is None or mfe <= 0 or forward_return is None
            else forward_return / mfe
        ),
    }


def _apply_numeric_bucket(frame: pd.DataFrame, source_column: str, target_column: str) -> None:
    if frame.empty or source_column not in frame.columns:
        frame[target_column] = "unknown"
        return
    values = pd.to_numeric(frame[source_column], errors="coerce")
    ranks = values.rank(pct=True, method="average")
    bucket = pd.Series("unknown", index=frame.index, dtype=object)
    bucket.loc[ranks.notna() & (ranks <= 1 / 3)] = "low"
    bucket.loc[ranks.notna() & (ranks > 1 / 3) & (ranks <= 2 / 3)] = "medium"
    bucket.loc[ranks.notna() & (ranks > 2 / 3)] = "high"
    frame[target_column] = bucket


def _merge_market_regime(event_metrics: pd.DataFrame, benchmark_frame: pd.DataFrame | None) -> None:
    event_metrics["market_regime"] = "unknown"
    lookup, _status, _definition = _build_market_regime_lookup(benchmark_frame)
    if event_metrics.empty or lookup.empty or "signal_date" not in event_metrics.columns:
        return
    dated = event_metrics.copy()
    dated["_signal_date_ts"] = pd.to_datetime(dated["signal_date"], errors="coerce")
    dated = dated[dated["_signal_date_ts"].notna()].sort_values("_signal_date_ts")
    if dated.empty:
        return
    merged = pd.merge_asof(
        dated[["_signal_date_ts"]].reset_index().sort_values("_signal_date_ts"),
        lookup.rename(columns={"Date": "_benchmark_date"}).sort_values("_benchmark_date"),
        left_on="_signal_date_ts",
        right_on="_benchmark_date",
        direction="backward",
    )
    for row in merged.to_dict(orient="records"):
        if row.get("market_regime"):
            event_metrics.loc[int(row["index"]), "market_regime"] = row["market_regime"]


def _benchmark_forward_return(
    benchmark_frame: pd.DataFrame | None,
    signal_date: object,
    horizon: int,
) -> float | None:
    if benchmark_frame is None or benchmark_frame.empty:
        return None
    if "Date" not in benchmark_frame.columns or "Close" not in benchmark_frame.columns:
        return None
    normalized = benchmark_frame.copy()
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce").dt.normalize()
    normalized["Close"] = pd.to_numeric(normalized["Close"], errors="coerce")
    normalized = normalized.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    if normalized.empty:
        return None
    ts = pd.Timestamp(signal_date).normalize()
    pos_candidates = normalized.index[normalized["Date"] <= ts].tolist()
    if not pos_candidates:
        return None
    start_pos = int(pos_candidates[-1])
    end_pos = start_pos + int(horizon)
    if end_pos >= len(normalized):
        return None
    start_price = _to_float(normalized.iloc[start_pos]["Close"])
    end_price = _to_float(normalized.iloc[end_pos]["Close"])
    return _return_pct(end_price, start_price)


def _benchmark_forward_lookup(
    benchmark_frame: pd.DataFrame | None,
    signal_dates: Iterable[object],
    horizons: Iterable[int],
) -> dict[tuple[str, int], float | None]:
    if benchmark_frame is None or benchmark_frame.empty:
        return {}
    if "Date" not in benchmark_frame.columns or "Close" not in benchmark_frame.columns:
        return {}
    normalized = benchmark_frame[["Date", "Close"]].copy()
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce").dt.normalize()
    normalized["Close"] = pd.to_numeric(normalized["Close"], errors="coerce")
    normalized = normalized.dropna(subset=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
    if normalized.empty:
        return {}

    dates = normalized["Date"]
    closes = normalized["Close"]
    lookup: dict[tuple[str, int], float | None] = {}
    for signal_date in sorted({str(value) for value in signal_dates if not _is_missing(value)}):
        ts = pd.Timestamp(signal_date).normalize()
        start_pos = int(dates.searchsorted(ts, side="right")) - 1
        for horizon in horizons:
            parsed_horizon = int(horizon)
            value: float | None = None
            if start_pos >= 0:
                end_pos = start_pos + parsed_horizon
                if end_pos < len(normalized):
                    value = _return_pct(
                        _to_float(closes.iloc[end_pos]),
                        _to_float(closes.iloc[start_pos]),
                    )
            lookup[(signal_date, parsed_horizon)] = value
    return lookup


def _universe_forward_medians(
    scan_result: EntrySignalScanResult,
    request: EntrySignalAnalysisRequest,
    signal_dates: list[str],
) -> dict[tuple[str, int], float | None]:
    if not signal_dates:
        return {}
    medians: dict[tuple[str, int], float | None] = {}
    unique_dates = sorted({str(value) for value in signal_dates})
    total_dates = len(unique_dates)
    feature_by_ticker = {}
    for ticker in request.tickers:
        features = scan_result.cache.get_features(ticker)
        if features is not None and not features.empty:
            feature_by_ticker[ticker] = _FeatureView.from_frame(features)
    date_pos_by_ticker = {
        ticker: scan_result.cache.get_date_pos_map(ticker)
        for ticker in request.tickers
    }
    for date_index, signal_date in enumerate(unique_dates, start=1):
        ts = pd.Timestamp(signal_date).normalize()
        values_by_horizon: dict[int, list[float]] = {h: [] for h in request.normalized_horizons}
        for ticker in request.tickers:
            feature_view = feature_by_ticker.get(ticker)
            if feature_view is None:
                continue
            signal_pos = date_pos_by_ticker.get(ticker, {}).get(ts)
            if signal_pos is None:
                continue
            for horizon in request.normalized_horizons:
                value = feature_view.forward_return_pct(
                    signal_pos=signal_pos,
                    horizon=horizon,
                    label_mode=request.label_mode,
                )
                if value is not None:
                    values_by_horizon[horizon].append(value)
        for horizon, values in values_by_horizon.items():
            medians[(signal_date, horizon)] = (
                float(pd.Series(values).median()) if values else None
            )
        if date_index % 50 == 0 or date_index == total_dates:
            _log_priority15_progress("universe_forward_medians", date_index, total_dates)
    return medians


def _add_relative_strength_ranks(event_metrics: pd.DataFrame) -> None:
    if event_metrics.empty or "entry_rs_20d_pct" not in event_metrics.columns:
        event_metrics["entry_relative_strength_rank"] = None
        return
    ranks: list[pd.Series] = []
    for _date, group in event_metrics.groupby("signal_date", dropna=False):
        numeric = pd.to_numeric(group["entry_rs_20d_pct"], errors="coerce")
        rank = numeric.rank(ascending=False, method="min", na_option="bottom")
        ranks.append(pd.Series(rank, index=group.index))
    if not ranks:
        event_metrics["entry_relative_strength_rank"] = None
        return
    event_metrics["entry_relative_strength_rank"] = pd.concat(ranks).sort_index()


def _build_event_metrics(
    scan_result: EntrySignalScanResult,
    request: EntrySignalAnalysisRequest,
    benchmark_frame: pd.DataFrame | None,
    warnings: list[str],
) -> pd.DataFrame:
    if scan_result.candidates.empty:
        return pd.DataFrame()

    event_metrics = scan_result.candidates.copy()
    if "event_id" not in event_metrics.columns:
        event_metrics["event_id"] = event_metrics.apply(_event_id_from_parts, axis=1)
    if "entry_date" not in event_metrics.columns and "label_entry_date" in event_metrics.columns:
        event_metrics["entry_date"] = event_metrics["label_entry_date"]
    if "entry_price" not in event_metrics.columns and "label_entry_price" in event_metrics.columns:
        event_metrics["entry_price"] = event_metrics["label_entry_price"]
    event_metrics["sector"] = event_metrics.get("industry_name", pd.Series(index=event_metrics.index, dtype=object))
    event_metrics["market_cap_bucket"] = "unknown"

    by_event_id, by_key = _context_maps(scan_result.event_contexts)
    reference_file = request.industry_reference_file or DEFAULT_INDUSTRY_REFERENCE_FILE
    feature_by_ticker: dict[str, _FeatureView] = {}
    for context in scan_result.event_contexts:
        if context.ticker in feature_by_ticker:
            continue
        features = scan_result.cache.get_features(context.ticker)
        if features is not None and not features.empty:
            feature_by_ticker[context.ticker] = _FeatureView.from_frame(features)
    sector_by_ticker: dict[str, object] = {}
    enriched_rows: list[dict[str, object]] = []
    total_events = int(len(event_metrics))

    for row_index, values in enumerate(event_metrics.to_dict(orient="records"), start=1):
        values["reasons_json"] = _json_dumps(values.get("reasons", []))
        values["signal_metadata_json"] = _json_dumps(values.get("signal_metadata", {}))
        context = _find_context_from_values(values, by_event_id, by_key)
        if context is None:
            enriched_rows.append(values)
            if row_index % 5000 == 0 or row_index == total_events:
                _log_priority15_progress("event_metrics", row_index, total_events)
            continue

        features = feature_by_ticker.get(context.ticker)
        if features is None:
            warnings.append(f"missing features for event {values.get('event_id')}")
            enriched_rows.append(values)
            if row_index % 5000 == 0 or row_index == total_events:
                _log_priority15_progress("event_metrics", row_index, total_events)
            continue

        entry_price = _to_float(values.get("entry_price") or values.get("label_entry_price"))
        values["signal_pos"] = int(context.signal_pos)
        values["entry_pos"] = int(context.entry_pos)
        values["entry_date"] = values.get("entry_date") or _date_at(features, context.entry_pos)
        values["entry_price"] = entry_price
        sector_value = values.get("sector")
        if _is_missing(sector_value) or not str(sector_value).strip():
            if context.ticker not in sector_by_ticker:
                sector_by_ticker[context.ticker] = get_industry_name(context.ticker, reference_file)
            values["sector"] = sector_by_ticker[context.ticker]
        else:
            values["sector"] = sector_value

        signal_close = _price_at(features, context.signal_pos, "Close")
        next_open = _price_at(features, context.signal_pos + 1, "Open")
        values["signal_close"] = signal_close
        values["signal_close_to_next_open_gap_pct"] = _return_pct(next_open, signal_close)
        entry_close = _price_at(features, context.entry_pos, "Close")
        values["entry_day_open_to_close_pct"] = _return_pct(entry_close, entry_price)
        values["adv20_jpy"] = _turnover(features, context.entry_pos)
        values["dollar_volume_jpy"] = _turnover(features, context.entry_pos)
        values["turnover_median_20_jpy"] = _turnover(features, context.entry_pos)
        atr_ratio = _price_at(features, context.entry_pos, "ATR_Ratio")
        values["entry_atr_ratio"] = atr_ratio
        values["spread_proxy_pct"] = None if atr_ratio is None else atr_ratio * 100.0 / 10.0

        entry_bb_width = _price_at(features, context.entry_pos, "BB_Width")
        values["entry_rs_20d_pct"] = _return_pct(
            _price_at(features, context.entry_pos, "Close"),
            _price_at(features, context.entry_pos - 20, "Close"),
        )
        _append_trend_snapshot(
            values,
            frame=features,
            row_pos=context.entry_pos,
            prefix="entry",
            entry_price=entry_price,
            entry_bb_width=entry_bb_width,
        )
        for checkpoint_day in request.normalized_checkpoint_days:
            pos = context.signal_pos + checkpoint_day
            prefix = f"day{checkpoint_day}"
            _append_trend_snapshot(
                values,
                frame=features,
                row_pos=pos,
                prefix=prefix,
                entry_price=entry_price,
                entry_bb_width=entry_bb_width,
            )
            strong_columns = [
                f"{prefix}_close_above_ma20",
                f"{prefix}_close_above_ma50",
                f"{prefix}_ma20_slope_5d_pct",
                f"{prefix}_return_from_entry_pct",
            ]
            strong_inputs = {key: values.get(key) for key in strong_columns}
            values[f"{prefix}_strong"] = (
                bool(strong_inputs[f"{prefix}_close_above_ma20"])
                and bool(strong_inputs[f"{prefix}_close_above_ma50"])
                and (_to_float(strong_inputs[f"{prefix}_ma20_slope_5d_pct"]) or 0.0) > 0
                and (_to_float(strong_inputs[f"{prefix}_return_from_entry_pct"]) or 0.0) > 0
            )

        for horizon in PRIORITY15_PATH_HORIZONS:
            values.update(
                _path_metrics_for_horizon(
                    features,
                    signal_pos=context.signal_pos,
                    entry_pos=context.entry_pos,
                    entry_price=entry_price,
                    horizon=horizon,
                    label_mode=request.label_mode,
                )
            )

        sorted_horizons = request.normalized_horizons
        for previous, current in zip(sorted_horizons, sorted_horizons[1:]):
            left = _to_float(values.get(f"forward_return_{previous}d_pct"))
            right = _to_float(values.get(f"forward_return_{current}d_pct"))
            values[f"marginal_return_{previous}d_to_{current}d_pct"] = (
                None if left is None or right is None else right - left
            )

        for cost_bps in request.normalized_cost_bps:
            cost_pct = (float(cost_bps) / 100.0) * 2.0
            label = _format_pct_label(cost_bps)
            for horizon in sorted_horizons:
                gross = _to_float(values.get(f"forward_return_{horizon}d_pct"))
                values[f"net_return_after_{label}bps_{horizon}d_pct"] = (
                    None if gross is None else gross - cost_pct
                )

        for offset in request.normalized_late_entry_days:
            late_entry_pos = context.entry_pos + offset
            late_entry_price = _price_at(features, late_entry_pos, "Open")
            values[f"late_entry_{offset}d_date"] = _date_at(features, late_entry_pos)
            values[f"late_entry_{offset}d_price"] = late_entry_price
            for horizon in sorted_horizons:
                base_return = _to_float(values.get(f"forward_return_{horizon}d_pct"))
                late_exit_price = _price_at(features, late_entry_pos + horizon, "Close")
                late_return = _return_pct(late_exit_price, late_entry_price)
                values[f"late_return_{offset}d_{horizon}d_pct"] = late_return
                values[f"decay_{offset}d_{horizon}d_pct"] = (
                    None if base_return is None or late_return is None else late_return - base_return
                )

        enriched_rows.append(values)
        if row_index % 5000 == 0 or row_index == total_events:
            _log_priority15_progress("event_metrics", row_index, total_events)

    event_metrics = pd.DataFrame(enriched_rows)
    _merge_market_regime(event_metrics, benchmark_frame)
    _apply_numeric_bucket(event_metrics, "adv20_jpy", "liquidity_bucket")
    _apply_numeric_bucket(event_metrics, "entry_atr_ratio", "volatility_bucket")
    _add_relative_strength_ranks(event_metrics)

    signal_date_series = event_metrics["signal_date"].astype(str) if "signal_date" in event_metrics.columns else pd.Series("", index=event_metrics.index)
    sector_series = event_metrics["sector"].astype(str) if "sector" in event_metrics.columns else pd.Series("", index=event_metrics.index)
    universe_medians = _universe_forward_medians(
        scan_result,
        request,
        list(signal_date_series.dropna().astype(str)),
    )
    topix_forward_lookup = _benchmark_forward_lookup(
        benchmark_frame,
        signal_date_series.dropna().astype(str).tolist(),
        request.normalized_horizons,
    )
    for horizon in request.normalized_horizons:
        return_col = f"forward_return_{horizon}d_pct"
        if return_col not in event_metrics.columns:
            continue
        gross_returns = pd.to_numeric(event_metrics[return_col], errors="coerce")
        universe_values = signal_date_series.map(
            lambda signal_date: universe_medians.get((str(signal_date), horizon))
        )
        topix_values = signal_date_series.map(
            lambda signal_date: topix_forward_lookup.get((str(signal_date), horizon))
        )
        sector_medians = gross_returns.groupby([signal_date_series, sector_series], dropna=False).transform("median")
        event_metrics[f"alpha_{horizon}d_vs_universe_pct"] = gross_returns - pd.to_numeric(universe_values, errors="coerce")
        event_metrics[f"alpha_{horizon}d_vs_sector_pct"] = gross_returns - sector_medians
        event_metrics[f"alpha_{horizon}d_vs_topix_pct"] = gross_returns - pd.to_numeric(topix_values, errors="coerce")

    return event_metrics


def _format_pct_label(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "p")


def _stats_dict(values: pd.Series) -> dict[str, object]:
    stats = _build_primary_stats_from_series(pd.to_numeric(values, errors="coerce"))
    return {
        "count": stats.count,
        "win_rate": stats.win_rate,
        "avg_return_pct": stats.avg_return_pct,
        "median_return_pct": stats.median_return_pct,
        "p10_return_pct": stats.p10_return_pct,
        "p25_return_pct": stats.p25_return_pct,
        "p75_return_pct": stats.p75_return_pct,
        "p90_return_pct": stats.p90_return_pct,
        "profit_factor": _profit_factor(values),
    }


def _profit_factor(values: pd.Series) -> float | None:
    valid = pd.to_numeric(values, errors="coerce").dropna()
    if valid.empty:
        return None
    gains = float(valid[valid > 0].sum())
    losses = float(valid[valid < 0].sum())
    if losses == 0:
        return None if gains == 0 else float("inf")
    return gains / abs(losses)


def _summarize_returns(
    frame: pd.DataFrame,
    *,
    group_cols: list[str],
    return_col: str,
) -> pd.DataFrame:
    if frame.empty or return_col not in frame.columns:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for keys, group in frame.groupby(group_cols, dropna=False):
        key_values = keys if isinstance(keys, tuple) else (keys,)
        row = {column: value for column, value in zip(group_cols, key_values)}
        row.update(_stats_dict(group[return_col]))
        rows.append(row)
    return pd.DataFrame(rows)


def _build_path_summary(event_metrics: pd.DataFrame) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for keys, group in selected.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        row: dict[str, object] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "event_count": int(len(group)),
        }
        for horizon in PRIORITY15_PATH_HORIZONS:
            label = f"{horizon}d"
            for metric in ("MFE", "MAE", "profit_giveback"):
                column = f"{metric}_{label}_pct"
                if column in group.columns:
                    row[f"avg_{column}"] = _to_float(pd.to_numeric(group[column], errors="coerce").mean())
                    row[f"median_{column}"] = _to_float(pd.to_numeric(group[column], errors="coerce").median())
            for metric in ("days_underwater", "MFE_capture_ratio"):
                column = f"{metric}_{label}"
                if column in group.columns:
                    row[f"avg_{column}"] = _to_float(pd.to_numeric(group[column], errors="coerce").mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _first_hit_offset(values: Iterable[object], threshold: float, *, hit_above: bool) -> int | None:
    for offset, value in enumerate(values, start=1):
        parsed = _to_float(value)
        if parsed is None:
            continue
        if hit_above and parsed >= threshold:
            return offset
        if not hit_above and parsed <= threshold:
            return offset
    return None


TARGET_STOP_EVENT_COLUMNS = [
    "event_id",
    "entry_strategy",
    "entry_filter_name",
    "ticker",
    "signal_date",
    "target_pct",
    "stop_pct",
    "horizon",
    "hit_type",
    "days_to_target",
    "days_to_stop",
    "rule_return_pct",
]


def _empty_target_stop_buffers() -> dict[str, list[object]]:
    return {column: [] for column in TARGET_STOP_EVENT_COLUMNS}


def _append_target_stop_row(
    rows: dict[str, list[object]],
    *,
    context: EntrySignalEventContext,
    target_pct: float,
    stop_pct: float,
    horizon: int,
    hit_type: str,
    days_to_target: int | None,
    days_to_stop: int | None,
    rule_return: float | None,
) -> None:
    rows["event_id"].append(context.payload.get("event_id"))
    rows["entry_strategy"].append(context.entry_strategy)
    rows["entry_filter_name"].append(context.entry_filter_name)
    rows["ticker"].append(context.ticker)
    rows["signal_date"].append(context.signal_date)
    rows["target_pct"].append(target_pct)
    rows["stop_pct"].append(stop_pct)
    rows["horizon"].append(horizon)
    rows["hit_type"].append(hit_type)
    rows["days_to_target"].append(days_to_target)
    rows["days_to_stop"].append(days_to_stop)
    rows["rule_return_pct"].append(rule_return)


def _append_target_stop_for_event(
    rows: dict[str, list[object]],
    context: EntrySignalEventContext,
    frame: pd.DataFrame,
    request: EntrySignalAnalysisRequest,
) -> int:
    entry_price = _to_float(context.payload.get("entry_price") or context.payload.get("label_entry_price"))
    if entry_price is None or entry_price <= 0:
        return 0
    start_pos = context.entry_pos if request.label_mode == "next_open" else context.entry_pos + 1
    max_horizon = max(request.normalized_target_stop_horizons, default=0)
    max_end_pos = min(len(frame) - 1, context.signal_pos + max_horizon)
    window = frame.iloc[start_pos : max_end_pos + 1] if start_pos <= max_end_pos else pd.DataFrame()
    close_values = pd.to_numeric(window["Close"], errors="coerce") if "Close" in window.columns else pd.Series(dtype=float)
    high_values = (
        pd.to_numeric(window["High"], errors="coerce")
        if "High" in window.columns
        else pd.Series(index=window.index, dtype=float)
    )
    low_values = (
        pd.to_numeric(window["Low"], errors="coerce")
        if "Low" in window.columns
        else pd.Series(index=window.index, dtype=float)
    )
    high_values = high_values.where(high_values.notna(), close_values)
    low_values = low_values.where(low_values.notna(), close_values)
    target_hit_offsets = {
        target_pct: _first_hit_offset(
            high_values.tolist(),
            entry_price * (1.0 + target_pct / 100.0),
            hit_above=True,
        )
        for target_pct in request.normalized_target_pcts
    }
    stop_hit_offsets = {
        stop_pct: _first_hit_offset(
            low_values.tolist(),
            entry_price * (1.0 - stop_pct / 100.0),
            hit_above=False,
        )
        for stop_pct in request.normalized_stop_pcts
    }
    horizon_close_returns = {
        horizon: _return_pct(_price_at(frame, context.signal_pos + horizon, "Close"), entry_price)
        for horizon in request.normalized_target_stop_horizons
    }
    appended = 0
    for horizon in request.normalized_target_stop_horizons:
        end_pos = min(len(frame) - 1, context.signal_pos + horizon)
        horizon_offset = end_pos - start_pos + 1
        for target_pct in request.normalized_target_pcts:
            target_hit_offset = target_hit_offsets.get(target_pct)
            days_to_target = (
                target_hit_offset
                if target_hit_offset is not None and target_hit_offset <= horizon_offset
                else None
            )
            for stop_pct in request.normalized_stop_pcts:
                stop_hit_offset = stop_hit_offsets.get(stop_pct)
                days_to_stop = (
                    stop_hit_offset
                    if stop_hit_offset is not None and stop_hit_offset <= horizon_offset
                    else None
                )
                hit_type = "neither"
                rule_return = horizon_close_returns.get(horizon)
                if days_to_stop is not None and (
                    days_to_target is None or days_to_stop <= days_to_target
                ):
                    hit_type = "stop_first"
                    rule_return = -stop_pct
                elif days_to_target is not None:
                    hit_type = "target_first"
                    rule_return = target_pct
                _append_target_stop_row(
                    rows,
                    context=context,
                    target_pct=target_pct,
                    stop_pct=stop_pct,
                    horizon=horizon,
                    hit_type=hit_type,
                    days_to_target=days_to_target,
                    days_to_stop=days_to_stop,
                    rule_return=rule_return,
                )
                appended += 1
    return appended


def _build_target_stop(
    scan_result: EntrySignalScanResult,
    event_metrics: pd.DataFrame,
    request: EntrySignalAnalysisRequest,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected_ids = set(_selected_frame(event_metrics).get("event_id", pd.Series(dtype=object)).astype(str))
    rows = _empty_target_stop_buffers()
    processed_selected = 0
    total_selected = len(selected_ids)
    for context in scan_result.event_contexts:
        if str(context.payload.get("event_id")) not in selected_ids:
            continue
        processed_selected += 1
        features = scan_result.cache.get_features(context.ticker)
        if features is None or features.empty:
            if processed_selected % 5000 == 0 or processed_selected == total_selected:
                _log_priority15_progress("target_stop", processed_selected, total_selected)
            continue
        _append_target_stop_for_event(rows, context, features, request)
        if processed_selected % 5000 == 0 or processed_selected == total_selected:
            _log_priority15_progress("target_stop", processed_selected, total_selected)
    events = pd.DataFrame(rows, columns=TARGET_STOP_EVENT_COLUMNS)
    if events.empty:
        return events, pd.DataFrame()

    summary_rows: list[dict[str, object]] = []
    group_cols = ["entry_strategy", "entry_filter_name", "target_pct", "stop_pct", "horizon"]
    for keys, group in events.groupby(group_cols, dropna=False):
        row = {column: value for column, value in zip(group_cols, keys)}
        count = int(len(group))
        row["event_count"] = count
        row["target_first_rate"] = float((group["hit_type"] == "target_first").mean()) if count else None
        row["stop_first_rate"] = float((group["hit_type"] == "stop_first").mean()) if count else None
        row["neither_rate"] = float((group["hit_type"] == "neither").mean()) if count else None
        row["avg_days_to_target"] = _to_float(pd.to_numeric(group["days_to_target"], errors="coerce").mean())
        row["avg_days_to_stop"] = _to_float(pd.to_numeric(group["days_to_stop"], errors="coerce").mean())
        row["expected_return_pct"] = _to_float(pd.to_numeric(group["rule_return_pct"], errors="coerce").mean())
        row["profit_factor"] = _profit_factor(group["rule_return_pct"])
        summary_rows.append(row)
    return events, pd.DataFrame(summary_rows)


def _build_checkpoint(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> tuple[pd.DataFrame, pd.DataFrame]:
    selected = _selected_frame(event_metrics)
    rows: list[dict[str, object]] = []
    for _, row in selected.iterrows():
        for day in request.normalized_checkpoint_days:
            prefix = f"day{day}"
            if f"{prefix}_feature_available" not in row:
                continue
            item = {
                "event_id": row.get("event_id"),
                "entry_strategy": row.get("entry_strategy"),
                "entry_filter_name": row.get("entry_filter_name"),
                "ticker": row.get("ticker"),
                "signal_date": row.get("signal_date"),
                "checkpoint_day": day,
                "checkpoint_return_pct": row.get(f"{prefix}_return_from_entry_pct"),
                "checkpoint_strong": row.get(f"{prefix}_strong"),
                "close_above_ma20": row.get(f"{prefix}_close_above_ma20"),
                "close_above_ma50": row.get(f"{prefix}_close_above_ma50"),
                "ma20_slope_5d_pct": row.get(f"{prefix}_ma20_slope_5d_pct"),
            }
            for future in request.normalized_horizons:
                if future > day:
                    future_return = _to_float(row.get(f"forward_return_{future}d_pct"))
                    checkpoint_return = _to_float(row.get(f"forward_return_{day}d_pct"))
                    item[f"return_{day}d_to_{future}d_pct"] = (
                        None
                        if future_return is None or checkpoint_return is None
                        else future_return - checkpoint_return
                    )
            rows.append(item)
    events = pd.DataFrame(rows)
    if events.empty:
        return events, pd.DataFrame()

    summary_rows: list[dict[str, object]] = []
    for keys, group in events.groupby(["entry_strategy", "entry_filter_name", "checkpoint_day", "checkpoint_strong"], dropna=False):
        entry_strategy, entry_filter_name, day, strong = keys
        future_cols = [col for col in group.columns if col.startswith(f"return_{day}d_to_") and col.endswith("_pct")]
        row: dict[str, object] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "checkpoint_day": day,
            "checkpoint_strong": strong,
            "event_count": int(len(group)),
            "avg_checkpoint_return_pct": _to_float(pd.to_numeric(group["checkpoint_return_pct"], errors="coerce").mean()),
        }
        for col in future_cols:
            stats = _stats_dict(group[col])
            for key, value in stats.items():
                row[f"{col}_{key}"] = value
        summary_rows.append(row)
    return events, pd.DataFrame(summary_rows)


def _build_trend_feature_summary(event_metrics: pd.DataFrame) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    metric_cols = [
        col
        for col in selected.columns
        if (
            col.startswith("entry_")
            or col.startswith("day10_")
            or col.startswith("day20_")
            or col.startswith("day40_")
        )
        and (
            col.endswith("_pct")
            or col.endswith("_ratio")
            or col.endswith("_rank")
            or col.endswith("_rsi")
            or col.endswith("_14")
            or col.endswith("_width")
        )
    ]
    rows: list[dict[str, object]] = []
    for keys, group in selected.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        row: dict[str, object] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "event_count": int(len(group)),
        }
        for col in metric_cols:
            row[f"avg_{col}"] = _to_float(pd.to_numeric(group[col], errors="coerce").mean())
            row[f"median_{col}"] = _to_float(pd.to_numeric(group[col], errors="coerce").median())
        for col in [c for c in selected.columns if c.endswith("_strong") or c.endswith("_bull_stack")]:
            if col in group.columns:
                row[f"rate_{col}"] = float(group[col].fillna(False).astype(bool).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _cooldown_filtered(group: pd.DataFrame, cooldown_days: int) -> pd.DataFrame:
    if group.empty:
        return group
    working = group.copy()
    working["_signal_ts"] = pd.to_datetime(working["signal_date"], errors="coerce")
    working = working.sort_values(["ticker", "_signal_ts"])
    kept_indices: list[int] = []
    last_kept_by_ticker: dict[str, pd.Timestamp] = {}
    for idx, row in working.iterrows():
        ticker = str(row.get("ticker"))
        signal_ts = row.get("_signal_ts")
        if pd.isna(signal_ts):
            continue
        last = last_kept_by_ticker.get(ticker)
        if last is None or (signal_ts - last).days > cooldown_days:
            kept_indices.append(idx)
            last_kept_by_ticker[ticker] = signal_ts
    return working.loc[kept_indices].drop(columns=["_signal_ts"], errors="ignore")


def _build_cooldown_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    return_col = f"forward_return_{request.primary_horizon}d_pct"
    rows: list[dict[str, object]] = []
    for keys, group in selected.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        variants: list[tuple[str, pd.DataFrame]] = [
            ("all_selected_signals", group),
            ("first_signal_per_ticker", group.sort_values("signal_date").drop_duplicates(["ticker"], keep="first")),
        ]
        for days in request.normalized_cooldown_days:
            variants.append((f"cooldown_{days}d", _cooldown_filtered(group, days)))
        for scope, scoped in variants:
            row = {
                "entry_strategy": entry_strategy,
                "entry_filter_name": entry_filter_name,
                "scope": scope,
                "event_count": int(len(scoped)),
            }
            row.update(_stats_dict(scoped[return_col] if return_col in scoped.columns else pd.Series(dtype=float)))
            rows.append(row)
    return pd.DataFrame(rows)


def _build_alpha_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for horizon in request.normalized_primary_horizons:
        for alpha_type in ("universe", "sector", "topix"):
            column = f"alpha_{horizon}d_vs_{alpha_type}_pct"
            if column not in selected.columns:
                continue
            summary = _summarize_returns(
                selected,
                group_cols=["entry_strategy", "entry_filter_name"],
                return_col=column,
            )
            if summary.empty:
                continue
            summary.insert(2, "horizon", horizon)
            summary.insert(3, "alpha_type", alpha_type)
            rows.extend(summary.to_dict(orient="records"))
    return pd.DataFrame(rows)


def _build_regime_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    return_col = f"forward_return_{request.primary_horizon}d_pct"
    if selected.empty or "market_regime" not in selected.columns:
        return pd.DataFrame()
    return _summarize_returns(
        selected,
        group_cols=["entry_strategy", "entry_filter_name", "market_regime"],
        return_col=return_col,
    )


def _build_stability_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    return_col = f"forward_return_{request.primary_horizon}d_pct"
    if selected.empty or return_col not in selected.columns:
        return pd.DataFrame()
    working = selected.copy()
    working["_signal_ts"] = pd.to_datetime(working["signal_date"], errors="coerce")
    working["year"] = working["_signal_ts"].dt.strftime("%Y")
    working["quarter"] = working["_signal_ts"].dt.to_period("Q").astype(str)
    rows: list[dict[str, object]] = []
    base_group_cols = ["entry_strategy", "entry_filter_name"]
    for slice_type, slice_col in [
        ("ticker", "ticker"),
        ("sector", "sector"),
        ("year", "year"),
        ("quarter", "quarter"),
    ]:
        summary = _summarize_returns(
            working,
            group_cols=[*base_group_cols, slice_col],
            return_col=return_col,
        )
        if summary.empty:
            continue
        summary = summary.rename(columns={slice_col: "slice_key"})
        summary.insert(2, "slice_type", slice_type)
        rows.extend(summary.to_dict(orient="records"))

    for keys, group in working.groupby(base_group_cols, dropna=False):
        entry_strategy, entry_filter_name = keys
        ticker_contrib = (
            group.groupby("ticker")[return_col]
            .sum()
            .sort_values(ascending=False)
        )
        total = float(pd.to_numeric(group[return_col], errors="coerce").sum())
        positive_years = _positive_group_ratio(group, "year", return_col)
        positive_sectors = _positive_group_ratio(group, "sector", return_col)
        rows.append(
            {
                "entry_strategy": entry_strategy,
                "entry_filter_name": entry_filter_name,
                "slice_type": "concentration",
                "slice_key": "top_ticker_contribution",
                "count": int(len(group)),
                "top5_contribution_ratio": _sum_head_ratio(ticker_contrib, 5, total),
                "top10_contribution_ratio": _sum_head_ratio(ticker_contrib, 10, total),
                "positive_year_ratio": positive_years,
                "positive_sector_ratio": positive_sectors,
            }
        )
    return pd.DataFrame(rows)


def _sum_head_ratio(values: pd.Series, count: int, total: float) -> float | None:
    if abs(total) <= 1e-12:
        return None
    return float(values.head(count).sum() / total)


def _positive_group_ratio(frame: pd.DataFrame, group_col: str, return_col: str) -> float | None:
    if group_col not in frame.columns:
        return None
    grouped = pd.to_numeric(frame[return_col], errors="coerce").groupby(frame[group_col]).mean()
    if grouped.empty:
        return None
    return float((grouped > 0).mean())


def _build_signal_decay_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    rows: list[dict[str, object]] = []
    for offset in request.normalized_late_entry_days:
        for horizon in request.normalized_horizons:
            column = f"decay_{offset}d_{horizon}d_pct"
            if column not in selected.columns:
                continue
            summary = _summarize_returns(
                selected,
                group_cols=["entry_strategy", "entry_filter_name"],
                return_col=column,
            )
            if summary.empty:
                continue
            summary.insert(2, "late_entry_days", offset)
            summary.insert(3, "horizon", horizon)
            rows.extend(summary.to_dict(orient="records"))
    return pd.DataFrame(rows)


def _build_execution_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for keys, group in selected.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
        entry_strategy, entry_filter_name = keys
        row: dict[str, object] = {
            "entry_strategy": entry_strategy,
            "entry_filter_name": entry_filter_name,
            "event_count": int(len(group)),
            "avg_close_to_next_open_gap_pct": _numeric_mean(group, "signal_close_to_next_open_gap_pct"),
            "median_adv20_jpy": _numeric_median(group, "adv20_jpy"),
            "median_turnover_jpy": _numeric_median(group, "turnover_median_20_jpy"),
            "avg_spread_proxy_pct": _numeric_mean(group, "spread_proxy_pct"),
        }
        for cost_bps in request.normalized_cost_bps:
            label = _format_pct_label(cost_bps)
            column = f"net_return_after_{label}bps_{request.primary_horizon}d_pct"
            if column in group.columns:
                row[f"avg_{column}"] = _to_float(pd.to_numeric(group[column], errors="coerce").mean())
                row[f"win_rate_{column}"] = float((pd.to_numeric(group[column], errors="coerce") > 0).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _build_exit_rule_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    if selected.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for _, row in selected.iterrows():
        base = {
            "event_id": row.get("event_id"),
            "entry_strategy": row.get("entry_strategy"),
            "entry_filter_name": row.get("entry_filter_name"),
            "ticker": row.get("ticker"),
            "signal_date": row.get("signal_date"),
        }
        for horizon in PRIORITY15_EXIT_HORIZONS:
            rows.append({**base, "exit_rule": f"fixed_{horizon}d", "return_pct": row.get(f"forward_return_{horizon}d_pct")})
        fixed40 = _to_float(row.get("forward_return_40d_pct"))
        mae40 = _to_float(row.get("MAE_40d_pct"))
        for stop_pct in (5, 8, 10):
            stop_return = -float(stop_pct) if mae40 is not None and mae40 <= -float(stop_pct) else fixed40
            rows.append({**base, "exit_rule": f"fixed_40d_hard_stop_{stop_pct}pct", "return_pct": stop_return})
        day20_strong = bool(row.get("day20_strong"))
        day40_strong = bool(row.get("day40_strong"))
        rows.append(
            {
                **base,
                "exit_rule": "day20_failure_exit_else_40d",
                "return_pct": row.get("forward_return_40d_pct") if day20_strong else row.get("forward_return_20d_pct"),
            }
        )
        rows.append(
            {
                **base,
                "exit_rule": "day20_failure_trailing_8pct_else_40d",
                "return_pct": -8.0 if day20_strong and mae40 is not None and mae40 <= -8.0 else (row.get("forward_return_40d_pct") if day20_strong else row.get("forward_return_20d_pct")),
            }
        )
        rows.append(
            {
                **base,
                "exit_rule": "day40_strong_extend_to_80d",
                "return_pct": row.get("forward_return_80d_pct") if day40_strong else row.get("forward_return_40d_pct"),
            }
        )
    events = pd.DataFrame(rows)
    if events.empty:
        return events
    return _summarize_returns(
        events,
        group_cols=["entry_strategy", "entry_filter_name", "exit_rule"],
        return_col="return_pct",
    )


def _build_walk_forward_summary(event_metrics: pd.DataFrame, request: EntrySignalAnalysisRequest) -> pd.DataFrame:
    selected = _selected_frame(event_metrics)
    return_col = f"forward_return_{request.primary_horizon}d_pct"
    if selected.empty or return_col not in selected.columns:
        return pd.DataFrame()
    working = selected.copy()
    working["_signal_ts"] = pd.to_datetime(working["signal_date"], errors="coerce")
    working["year"] = working["_signal_ts"].dt.year
    years = sorted(int(year) for year in working["year"].dropna().unique())
    rows: list[dict[str, object]] = []
    splits: list[tuple[str, set[int], set[int]]] = []
    if any(year in years for year in (2022, 2023, 2024)) and any(year in years for year in (2025, 2026)):
        splits.append(("fixed_2022_2024_train_2025_2026_test", {2022, 2023, 2024}, {2025, 2026}))
    for year in years:
        train = {candidate for candidate in years if candidate < year}
        test = {year}
        if train:
            splits.append((f"anchored_train_to_{year - 1}_test_{year}", train, test))

    for split_name, train_years, test_years in splits:
        for keys, group in working.groupby(["entry_strategy", "entry_filter_name"], dropna=False):
            entry_strategy, entry_filter_name = keys
            train_frame = group[group["year"].isin(train_years)]
            test_frame = group[group["year"].isin(test_years)]
            row: dict[str, object] = {
                "entry_strategy": entry_strategy,
                "entry_filter_name": entry_filter_name,
                "split_name": split_name,
                "train_years": ",".join(str(value) for value in sorted(train_years)),
                "test_years": ",".join(str(value) for value in sorted(test_years)),
            }
            for prefix, frame in (("train", train_frame), ("test", test_frame)):
                stats = _stats_dict(frame[return_col] if return_col in frame.columns else pd.Series(dtype=float))
                for key, value in stats.items():
                    row[f"{prefix}_{key}"] = value
            train_avg = _to_float(row.get("train_avg_return_pct"))
            test_avg = _to_float(row.get("test_avg_return_pct"))
            row["test_minus_train_avg_return_pct"] = None if train_avg is None or test_avg is None else test_avg - train_avg
            rows.append(row)
    return pd.DataFrame(rows)


def build_priority15_outputs(
    scan_result: EntrySignalScanResult,
    request: EntrySignalAnalysisRequest,
    benchmark_frame: pd.DataFrame | None = None,
) -> Priority15Outputs:
    total_started_at = time.perf_counter()
    warnings: list[str] = []

    stage_started_at = time.perf_counter()
    event_metrics = _build_event_metrics(scan_result, request, benchmark_frame, warnings)
    _log_priority15_stage("event_metrics", stage_started_at, rows=len(event_metrics))

    stage_started_at = time.perf_counter()
    target_stop_events, target_stop_summary = _build_target_stop(scan_result, event_metrics, request)
    _log_priority15_stage("target_stop", stage_started_at, rows=len(target_stop_events))

    stage_started_at = time.perf_counter()
    checkpoint_events, checkpoint_summary = _build_checkpoint(event_metrics, request)
    _log_priority15_stage("checkpoint", stage_started_at, rows=len(checkpoint_events))

    stage_started_at = time.perf_counter()
    path_summary = _build_path_summary(event_metrics)
    _log_priority15_stage("path_summary", stage_started_at, rows=len(path_summary))

    stage_started_at = time.perf_counter()
    trend_feature_summary = _build_trend_feature_summary(event_metrics)
    _log_priority15_stage(
        "trend_feature_summary",
        stage_started_at,
        rows=len(trend_feature_summary),
    )

    stage_started_at = time.perf_counter()
    cooldown_summary = _build_cooldown_summary(event_metrics, request)
    _log_priority15_stage("cooldown_summary", stage_started_at, rows=len(cooldown_summary))

    stage_started_at = time.perf_counter()
    alpha_summary = _build_alpha_summary(event_metrics, request)
    _log_priority15_stage("alpha_summary", stage_started_at, rows=len(alpha_summary))

    stage_started_at = time.perf_counter()
    regime_summary = _build_regime_summary(event_metrics, request)
    _log_priority15_stage("regime_summary", stage_started_at, rows=len(regime_summary))

    stage_started_at = time.perf_counter()
    stability_summary = _build_stability_summary(event_metrics, request)
    _log_priority15_stage("stability_summary", stage_started_at, rows=len(stability_summary))

    stage_started_at = time.perf_counter()
    signal_decay_summary = _build_signal_decay_summary(event_metrics, request)
    _log_priority15_stage(
        "signal_decay_summary",
        stage_started_at,
        rows=len(signal_decay_summary),
    )

    stage_started_at = time.perf_counter()
    execution_summary = _build_execution_summary(event_metrics, request)
    _log_priority15_stage("execution_summary", stage_started_at, rows=len(execution_summary))

    stage_started_at = time.perf_counter()
    exit_rule_summary = _build_exit_rule_summary(event_metrics, request)
    _log_priority15_stage("exit_rule_summary", stage_started_at, rows=len(exit_rule_summary))

    stage_started_at = time.perf_counter()
    walk_forward_summary = _build_walk_forward_summary(event_metrics, request)
    _log_priority15_stage("walk_forward_summary", stage_started_at, rows=len(walk_forward_summary))

    _log_priority15_stage("total", total_started_at)
    return Priority15Outputs(
        event_metrics=event_metrics,
        path_summary=path_summary,
        target_stop_events=target_stop_events,
        target_stop_summary=target_stop_summary,
        checkpoint_events=checkpoint_events,
        checkpoint_summary=checkpoint_summary,
        trend_feature_summary=trend_feature_summary,
        cooldown_summary=cooldown_summary,
        alpha_summary=alpha_summary,
        regime_summary=regime_summary,
        stability_summary=stability_summary,
        signal_decay_summary=signal_decay_summary,
        execution_summary=execution_summary,
        exit_rule_summary=exit_rule_summary,
        walk_forward_summary=walk_forward_summary,
        warnings=warnings,
    )
