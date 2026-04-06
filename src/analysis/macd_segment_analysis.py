from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

import pandas as pd

from src.data.pipeline import StockETLPipeline
from src.data.stock_data_manager import StockDataManager


DEFAULT_LOOKBACK_DAYS = 1825
DEFAULT_HISTORY_TOLERANCE_DAYS = 60
REQUIRED_ANALYSIS_COLUMNS = {
    "Date",
    "Open",
    "High",
    "Close",
    "MACD",
    "MACD_Signal",
    "MACD_Hist",
}
OVERALL_TICKER = "__ALL__"


@dataclass
class SegmentRecord:
    ticker: str
    segment_id: str
    golden_cross_date: pd.Timestamp
    death_cross_date: pd.Timestamp
    trade_df: pd.DataFrame
    row: Dict[str, Any]
    macd_turn_signal_offset: Optional[int]
    hist_turn_signal_offset: Optional[int]


def normalize_ticker_inputs(
    tickers: Optional[Sequence[str]] = None,
    tickers_csv: Optional[str] = None,
) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def _add(raw_value: str) -> None:
        value = str(raw_value).strip().upper()
        if not value:
            return
        if value.endswith(".T"):
            value = value[:-2]
        if value and value not in seen:
            seen.add(value)
            values.append(value)

    for ticker in tickers or []:
        _add(ticker)

    if tickers_csv:
        for ticker in tickers_csv.split(","):
            _add(ticker)

    return values


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    clean = df.copy()
    if "Date" in clean.columns:
        clean["Date"] = pd.to_datetime(clean["Date"])
        clean = clean.sort_values("Date").reset_index(drop=True)
    return clean


def _ts_to_str(value: Any) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _safe_idxmax(series: pd.Series) -> Optional[int]:
    clean = series.dropna()
    if clean.empty:
        return None
    return int(clean.idxmax())


def _safe_numeric(value: Any) -> Optional[float]:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _safe_ratio(numerator: Any, denominator: Any) -> Optional[float]:
    num = _safe_numeric(numerator)
    den = _safe_numeric(denominator)
    if num is None or den in (None, 0.0):
        return None
    return num / den


def _safe_return_pct(exit_price: Any, entry_price: Any) -> Optional[float]:
    exit_value = _safe_numeric(exit_price)
    entry_value = _safe_numeric(entry_price)
    if exit_value is None or entry_value in (None, 0.0):
        return None
    return ((exit_value / entry_value) - 1.0) * 100.0


def _safe_int(value: Any) -> Optional[int]:
    if value is None or pd.isna(value):
        return None
    return int(value)


def _prior_offset(signal_offset: Optional[int]) -> Optional[int]:
    if signal_offset is None:
        return None
    if int(signal_offset) <= 0:
        return None
    return int(signal_offset) - 1


def _estimate_min_history_rows(lookback_days: int) -> int:
    estimated_rows = int((lookback_days * 252) / 365)
    return max(200, estimated_rows - 10)


def _find_first_turn_down(series: pd.Series) -> Optional[int]:
    seen_rise = False
    values = series.reset_index(drop=True)
    for offset in range(1, len(values)):
        prev = values.iloc[offset - 1]
        curr = values.iloc[offset]
        if pd.isna(prev) or pd.isna(curr):
            continue
        if curr > prev:
            seen_rise = True
            continue
        if curr < prev and seen_rise:
            return offset
    return None


def _effective_signal_offset(
    signal_offset: Optional[int],
    death_signal_offset: int,
) -> tuple[int, bool]:
    if signal_offset is None:
        return death_signal_offset, True
    return signal_offset, False


def _evaluate_exit(
    trade_df: pd.DataFrame,
    signal_offset: int,
    lag_bars: int,
    peak_high: Any,
    peak_close: Any,
) -> Dict[str, Any]:
    exit_offset = min(signal_offset + lag_bars + 1, len(trade_df) - 1)
    exit_row = trade_df.iloc[exit_offset]
    entry_open = trade_df.iloc[0]["Open"]
    exit_open = exit_row["Open"]
    return {
        "exit_signal_date": _ts_to_str(trade_df.iloc[signal_offset]["Date"]),
        "exit_date": _ts_to_str(exit_row["Date"]),
        "exit_open": _safe_numeric(exit_open),
        "holding_bars": int(exit_offset),
        "return_pct": _safe_return_pct(exit_open, entry_open),
        "capture_high_ratio": _safe_ratio(exit_open, peak_high),
        "capture_close_ratio": _safe_ratio(exit_open, peak_close),
        "signal_offset_bars": int(signal_offset),
        "exit_offset_bars": int(exit_offset),
    }


def evaluate_ticker_readiness(
    manager: StockDataManager,
    ticker: str,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    history_tolerance_days: int = DEFAULT_HISTORY_TOLERANCE_DAYS,
) -> Dict[str, Any]:
    raw_df = _normalize_frame(manager.load_raw_prices(ticker))
    feature_df = _normalize_frame(manager.load_stock_features(ticker))

    raw_exists = not raw_df.empty
    feature_exists = not feature_df.empty
    raw_start = raw_df["Date"].min() if raw_exists else pd.NaT
    raw_end = raw_df["Date"].max() if raw_exists else pd.NaT
    feature_start = feature_df["Date"].min() if feature_exists and "Date" in feature_df.columns else pd.NaT
    feature_end = feature_df["Date"].max() if feature_exists and "Date" in feature_df.columns else pd.NaT
    history_span_days = (
        int((raw_end - raw_start).days) if raw_exists and pd.notna(raw_start) and pd.notna(raw_end) else 0
    )

    missing_columns = sorted(REQUIRED_ANALYSIS_COLUMNS - set(feature_df.columns)) if feature_exists else sorted(REQUIRED_ANALYSIS_COLUMNS)
    feature_stale = (
        raw_exists
        and feature_exists
        and pd.notna(raw_end)
        and pd.notna(feature_end)
        and pd.Timestamp(feature_end) < pd.Timestamp(raw_end)
    )

    insufficient_history = raw_exists and history_span_days < (lookback_days - history_tolerance_days)

    issues: list[str] = []
    needs_fetch = False
    needs_recompute = False

    if not raw_exists:
        issues.append("missing_raw_prices")
        needs_fetch = True
    elif insufficient_history:
        issues.append("insufficient_history")
        needs_fetch = True

    if not feature_exists:
        issues.append("missing_features")
        needs_recompute = True
    elif missing_columns:
        issues.append("missing_feature_columns")
        needs_recompute = True

    if feature_stale:
        issues.append("stale_features")
        needs_recompute = True

    return {
        "ticker": ticker,
        "raw_exists": raw_exists,
        "feature_exists": feature_exists,
        "raw_rows": int(len(raw_df)),
        "feature_rows": int(len(feature_df)),
        "raw_start_date": _ts_to_str(raw_start),
        "raw_end_date": _ts_to_str(raw_end),
        "feature_start_date": _ts_to_str(feature_start),
        "feature_end_date": _ts_to_str(feature_end),
        "history_span_days": history_span_days,
        "missing_columns": ",".join(missing_columns),
        "issues": ",".join(issues),
        "needs_fetch": needs_fetch,
        "needs_recompute": needs_recompute,
        "ready": not issues,
    }


def build_readiness_report(
    tickers: Sequence[str],
    data_root: str = "data",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    history_tolerance_days: int = DEFAULT_HISTORY_TOLERANCE_DAYS,
) -> pd.DataFrame:
    manager = StockDataManager(api_key=None, data_root=data_root)
    rows = [
        evaluate_ticker_readiness(
            manager,
            ticker,
            lookback_days=lookback_days,
            history_tolerance_days=history_tolerance_days,
        )
        for ticker in tickers
    ]
    return pd.DataFrame(rows)


def ensure_ticker_data(
    tickers: Sequence[str],
    data_root: str = "data",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    history_tolerance_days: int = DEFAULT_HISTORY_TOLERANCE_DAYS,
    api_key: Optional[str] = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    initial = build_readiness_report(
        tickers,
        data_root=data_root,
        lookback_days=lookback_days,
        history_tolerance_days=history_tolerance_days,
    )

    if initial.empty or bool(initial["ready"].all()):
        final = initial.copy()
        if not final.empty:
            final["was_auto_remediated"] = False
        return initial, final

    fetch_tickers = initial.loc[initial["needs_fetch"], "ticker"].tolist()
    recompute_only_tickers = initial.loc[
        (~initial["needs_fetch"]) & (initial["needs_recompute"]), "ticker"
    ].tolist()

    resolved_api_key = (api_key or os.getenv("JQUANTS_API_KEY") or "").strip()
    if fetch_tickers and not resolved_api_key:
        missing = ", ".join(fetch_tickers)
        raise ValueError(
            f"JQUANTS_API_KEY is required to auto-fetch missing or incomplete ticker data: {missing}"
        )

    if fetch_tickers:
        pipeline = StockETLPipeline(api_key=resolved_api_key, data_root=data_root)
        summary = pipeline.run_batch(
            fetch_tickers,
            fetch_aux_data=False,
            recompute_features=False,
            min_history_rows=_estimate_min_history_rows(lookback_days),
            initial_lookback_days=lookback_days,
        )
        if summary.get("failed"):
            failed = [
                result.get("code")
                for result in summary.get("results", [])
                if not result.get("success")
            ]
            raise ValueError(
                "Auto-remediation failed for tickers: " + ", ".join(sorted(str(code) for code in failed if code))
            )

    if recompute_only_tickers:
        manager = StockDataManager(api_key=None, data_root=data_root)
        failures: list[str] = []
        for ticker in recompute_only_tickers:
            recomputed = manager.compute_features(ticker, force_recompute=True)
            if recomputed.empty:
                failures.append(ticker)
        if failures:
            raise ValueError(
                "Feature recompute failed for tickers: " + ", ".join(sorted(failures))
            )

    final = build_readiness_report(
        tickers,
        data_root=data_root,
        lookback_days=lookback_days,
        history_tolerance_days=history_tolerance_days,
    )
    if not final.empty:
        remediated = set(initial.loc[~initial["ready"], "ticker"].tolist())
        final["was_auto_remediated"] = final["ticker"].isin(remediated)

    unresolved = final.loc[~final["ready"], "ticker"].tolist()
    if unresolved:
        raise ValueError(
            "Data is still not ready after auto-remediation: " + ", ".join(sorted(unresolved))
        )

    return initial, final


def _extract_segment_row(
    ticker: str,
    segment_id: str,
    golden_cross_date: pd.Timestamp,
    death_cross_date: pd.Timestamp,
    trade_df: pd.DataFrame,
    macd_turn_signal_offset: Optional[int],
    hist_turn_signal_offset: Optional[int],
) -> Dict[str, Any]:
    observable_df = trade_df.iloc[:-1].reset_index(drop=True)
    death_signal_offset = len(observable_df) - 1
    entry_row = trade_df.iloc[0]
    macd_peak_confirmed_offset = _prior_offset(macd_turn_signal_offset)
    hist_peak_confirmed_offset = _prior_offset(hist_turn_signal_offset)
    peak_high_offset = _safe_idxmax(observable_df["High"])
    peak_close_offset = _safe_idxmax(observable_df["Close"])
    macd_peak_offset = _safe_idxmax(observable_df["MACD"])
    hist_peak_offset = _safe_idxmax(observable_df["MACD_Hist"])

    peak_high = observable_df.iloc[peak_high_offset]["High"] if peak_high_offset is not None else pd.NA
    peak_close = observable_df.iloc[peak_close_offset]["Close"] if peak_close_offset is not None else pd.NA

    death_exit = _evaluate_exit(
        trade_df,
        signal_offset=death_signal_offset,
        lag_bars=0,
        peak_high=peak_high,
        peak_close=peak_close,
    )

    macd_effective_signal_offset, macd_fallback = _effective_signal_offset(
        macd_turn_signal_offset,
        death_signal_offset,
    )
    macd_turn_exit = _evaluate_exit(
        trade_df,
        signal_offset=macd_effective_signal_offset,
        lag_bars=0,
        peak_high=peak_high,
        peak_close=peak_close,
    )

    hist_effective_signal_offset, hist_fallback = _effective_signal_offset(
        hist_turn_signal_offset,
        death_signal_offset,
    )
    hist_turn_exit = _evaluate_exit(
        trade_df,
        signal_offset=hist_effective_signal_offset,
        lag_bars=0,
        peak_high=peak_high,
        peak_close=peak_close,
    )

    return {
        "ticker": ticker,
        "segment_id": segment_id,
        "golden_cross_date": _ts_to_str(golden_cross_date),
        "entry_date": _ts_to_str(entry_row["Date"]),
        "entry_open": _safe_numeric(entry_row["Open"]),
        "death_cross_date": _ts_to_str(death_cross_date),
        "death_confirm_signal_date": _ts_to_str(death_cross_date),
        "death_exit_date": death_exit["exit_date"],
        "death_exit_open": death_exit["exit_open"],
        "segment_signal_bars": int(death_signal_offset + 1),
        "segment_total_bars": int(len(trade_df)),
        "peak_high": _safe_numeric(peak_high),
        "peak_high_date": _ts_to_str(observable_df.iloc[peak_high_offset]["Date"]) if peak_high_offset is not None else None,
        "peak_high_offset_bars": _safe_int(peak_high_offset),
        "peak_close": _safe_numeric(peak_close),
        "peak_close_date": _ts_to_str(observable_df.iloc[peak_close_offset]["Date"]) if peak_close_offset is not None else None,
        "peak_close_offset_bars": _safe_int(peak_close_offset),
        "macd_peak": _safe_numeric(observable_df.iloc[macd_peak_offset]["MACD"]) if macd_peak_offset is not None else None,
        "macd_peak_date": _ts_to_str(observable_df.iloc[macd_peak_offset]["Date"]) if macd_peak_offset is not None else None,
        "macd_peak_offset_bars": _safe_int(macd_peak_offset),
        "macd_hist_peak": _safe_numeric(observable_df.iloc[hist_peak_offset]["MACD_Hist"]) if hist_peak_offset is not None else None,
        "macd_hist_peak_date": _ts_to_str(observable_df.iloc[hist_peak_offset]["Date"]) if hist_peak_offset is not None else None,
        "macd_hist_peak_offset_bars": _safe_int(hist_peak_offset),
        "macd_peak_confirmed_date": _ts_to_str(observable_df.iloc[macd_peak_confirmed_offset]["Date"]) if macd_peak_confirmed_offset is not None else None,
        "macd_peak_confirmed_offset_bars": _safe_int(macd_peak_confirmed_offset),
        "macd_turn_signal_date": _ts_to_str(observable_df.iloc[macd_turn_signal_offset]["Date"]) if macd_turn_signal_offset is not None else None,
        "macd_turn_signal_offset_bars": _safe_int(macd_turn_signal_offset),
        "macd_peak_confirm_signal_date": _ts_to_str(observable_df.iloc[macd_turn_signal_offset]["Date"]) if macd_turn_signal_offset is not None else None,
        "macd_peak_confirm_signal_offset_bars": _safe_int(macd_turn_signal_offset),
        "macd_turn_exit_date": macd_turn_exit["exit_date"],
        "macd_turn_exit_open": macd_turn_exit["exit_open"],
        "macd_turn_return_pct": macd_turn_exit["return_pct"],
        "macd_turn_capture_high_ratio": macd_turn_exit["capture_high_ratio"],
        "macd_turn_capture_close_ratio": macd_turn_exit["capture_close_ratio"],
        "macd_turn_fallback_to_death": macd_fallback,
        "macd_peak_confirm_exit_date": macd_turn_exit["exit_date"],
        "macd_peak_confirm_exit_open": macd_turn_exit["exit_open"],
        "macd_peak_confirm_return_pct": macd_turn_exit["return_pct"],
        "macd_peak_confirm_capture_high_ratio": macd_turn_exit["capture_high_ratio"],
        "macd_peak_confirm_capture_close_ratio": macd_turn_exit["capture_close_ratio"],
        "macd_peak_confirm_fallback_to_death": macd_fallback,
        "macd_hist_peak_confirmed_date": _ts_to_str(observable_df.iloc[hist_peak_confirmed_offset]["Date"]) if hist_peak_confirmed_offset is not None else None,
        "macd_hist_peak_confirmed_offset_bars": _safe_int(hist_peak_confirmed_offset),
        "macd_hist_turn_signal_date": _ts_to_str(observable_df.iloc[hist_turn_signal_offset]["Date"]) if hist_turn_signal_offset is not None else None,
        "macd_hist_turn_signal_offset_bars": _safe_int(hist_turn_signal_offset),
        "macd_hist_peak_confirm_signal_date": _ts_to_str(observable_df.iloc[hist_turn_signal_offset]["Date"]) if hist_turn_signal_offset is not None else None,
        "macd_hist_peak_confirm_signal_offset_bars": _safe_int(hist_turn_signal_offset),
        "macd_hist_turn_exit_date": hist_turn_exit["exit_date"],
        "macd_hist_turn_exit_open": hist_turn_exit["exit_open"],
        "macd_hist_turn_return_pct": hist_turn_exit["return_pct"],
        "macd_hist_turn_capture_high_ratio": hist_turn_exit["capture_high_ratio"],
        "macd_hist_turn_capture_close_ratio": hist_turn_exit["capture_close_ratio"],
        "macd_hist_turn_fallback_to_death": hist_fallback,
        "macd_hist_peak_confirm_exit_date": hist_turn_exit["exit_date"],
        "macd_hist_peak_confirm_exit_open": hist_turn_exit["exit_open"],
        "macd_hist_peak_confirm_return_pct": hist_turn_exit["return_pct"],
        "macd_hist_peak_confirm_capture_high_ratio": hist_turn_exit["capture_high_ratio"],
        "macd_hist_peak_confirm_capture_close_ratio": hist_turn_exit["capture_close_ratio"],
        "macd_hist_peak_confirm_fallback_to_death": hist_fallback,
        "death_return_pct": death_exit["return_pct"],
        "death_capture_high_ratio": death_exit["capture_high_ratio"],
        "death_capture_close_ratio": death_exit["capture_close_ratio"],
        "lag_high_vs_macd_peak_bars": (_safe_int(peak_high_offset) - _safe_int(macd_peak_offset)) if peak_high_offset is not None and macd_peak_offset is not None else None,
        "lag_high_vs_macd_hist_peak_bars": (_safe_int(peak_high_offset) - _safe_int(hist_peak_offset)) if peak_high_offset is not None and hist_peak_offset is not None else None,
        "lag_high_vs_macd_turn_bars": (_safe_int(peak_high_offset) - _safe_int(macd_turn_signal_offset)) if peak_high_offset is not None and macd_turn_signal_offset is not None else None,
        "lag_high_vs_macd_hist_turn_bars": (_safe_int(peak_high_offset) - _safe_int(hist_turn_signal_offset)) if peak_high_offset is not None and hist_turn_signal_offset is not None else None,
        "lag_close_vs_macd_peak_bars": (_safe_int(peak_close_offset) - _safe_int(macd_peak_offset)) if peak_close_offset is not None and macd_peak_offset is not None else None,
        "lag_close_vs_macd_hist_peak_bars": (_safe_int(peak_close_offset) - _safe_int(hist_peak_offset)) if peak_close_offset is not None and hist_peak_offset is not None else None,
    }


def extract_segment_records(ticker: str, features_df: pd.DataFrame) -> list[SegmentRecord]:
    df = _normalize_frame(features_df)
    missing_columns = REQUIRED_ANALYSIS_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"Ticker {ticker} is missing required analysis columns: {', '.join(sorted(missing_columns))}"
        )

    records: list[SegmentRecord] = []
    current_start_idx: Optional[int] = None

    for idx in range(1, len(df)):
        prev_hist = df.iloc[idx - 1]["MACD_Hist"]
        curr_hist = df.iloc[idx]["MACD_Hist"]
        if pd.isna(prev_hist) or pd.isna(curr_hist):
            continue

        if current_start_idx is None and prev_hist < 0 and curr_hist > 0:
            current_start_idx = idx
            continue

        if current_start_idx is None:
            continue

        if prev_hist > 0 and curr_hist < 0:
            golden_idx = current_start_idx
            death_idx = idx
            entry_idx = golden_idx + 1
            death_exit_idx = death_idx + 1
            current_start_idx = None

            if entry_idx >= len(df) or death_exit_idx >= len(df):
                continue

            trade_df = df.iloc[entry_idx : death_exit_idx + 1].copy().reset_index(drop=True)
            observable_df = trade_df.iloc[:-1].reset_index(drop=True)
            if observable_df.empty:
                continue

            segment_id = f"{ticker}-{pd.Timestamp(df.iloc[golden_idx]['Date']).strftime('%Y%m%d')}"
            macd_turn_signal_offset = _find_first_turn_down(observable_df["MACD"])
            hist_turn_signal_offset = _find_first_turn_down(observable_df["MACD_Hist"])
            row = _extract_segment_row(
                ticker=ticker,
                segment_id=segment_id,
                golden_cross_date=pd.Timestamp(df.iloc[golden_idx]["Date"]),
                death_cross_date=pd.Timestamp(df.iloc[death_idx]["Date"]),
                trade_df=trade_df,
                macd_turn_signal_offset=macd_turn_signal_offset,
                hist_turn_signal_offset=hist_turn_signal_offset,
            )
            records.append(
                SegmentRecord(
                    ticker=ticker,
                    segment_id=segment_id,
                    golden_cross_date=pd.Timestamp(df.iloc[golden_idx]["Date"]),
                    death_cross_date=pd.Timestamp(df.iloc[death_idx]["Date"]),
                    trade_df=trade_df,
                    row=row,
                    macd_turn_signal_offset=macd_turn_signal_offset,
                    hist_turn_signal_offset=hist_turn_signal_offset,
                )
            )

    return records


def _safe_series_median(df: pd.DataFrame, column: str) -> Optional[float]:
    clean = pd.to_numeric(df[column], errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.median())


def _safe_series_mean(df: pd.DataFrame, column: str) -> Optional[float]:
    clean = pd.to_numeric(df[column], errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.mean())


def _safe_series_mean_abs(df: pd.DataFrame, column: str) -> Optional[float]:
    clean = pd.to_numeric(df[column], errors="coerce").dropna()
    if clean.empty:
        return None
    return float(clean.abs().mean())


def _select_preferred_anchor(summary: Dict[str, Any], candidates: Sequence[tuple[str, str]]) -> str:
    best_name = "DEATH_CROSS"
    best_value: Optional[float] = None
    for anchor_name, metric_column in candidates:
        value = summary.get(metric_column)
        if value is None:
            continue
        if best_value is None or value < best_value:
            best_value = value
            best_name = anchor_name
    return best_name


def summarize_segments(segment_df: pd.DataFrame, ticker_label: str) -> Dict[str, Any]:
    summary: Dict[str, Any] = {
        "ticker": ticker_label,
        "segments": int(len(segment_df)),
        "avg_segment_signal_bars": _safe_series_mean(segment_df, "segment_signal_bars"),
        "median_segment_signal_bars": _safe_series_median(segment_df, "segment_signal_bars"),
        "avg_death_return_pct": _safe_series_mean(segment_df, "death_return_pct"),
        "median_death_return_pct": _safe_series_median(segment_df, "death_return_pct"),
        "death_win_rate_pct": None,
        "avg_death_capture_high_ratio": _safe_series_mean(segment_df, "death_capture_high_ratio"),
        "avg_death_capture_close_ratio": _safe_series_mean(segment_df, "death_capture_close_ratio"),
        "median_peak_high_offset_bars": _safe_series_median(segment_df, "peak_high_offset_bars"),
        "median_peak_close_offset_bars": _safe_series_median(segment_df, "peak_close_offset_bars"),
        "median_macd_peak_offset_bars": _safe_series_median(segment_df, "macd_peak_offset_bars"),
        "median_macd_hist_peak_offset_bars": _safe_series_median(segment_df, "macd_hist_peak_offset_bars"),
        "median_macd_turn_signal_offset_bars": _safe_series_median(segment_df, "macd_turn_signal_offset_bars"),
        "median_macd_hist_turn_signal_offset_bars": _safe_series_median(segment_df, "macd_hist_turn_signal_offset_bars"),
        "median_lag_high_vs_macd_peak_bars": _safe_series_median(segment_df, "lag_high_vs_macd_peak_bars"),
        "mean_abs_lag_high_vs_macd_peak_bars": _safe_series_mean_abs(segment_df, "lag_high_vs_macd_peak_bars"),
        "median_lag_high_vs_macd_hist_peak_bars": _safe_series_median(segment_df, "lag_high_vs_macd_hist_peak_bars"),
        "mean_abs_lag_high_vs_macd_hist_peak_bars": _safe_series_mean_abs(segment_df, "lag_high_vs_macd_hist_peak_bars"),
        "median_lag_high_vs_macd_turn_bars": _safe_series_median(segment_df, "lag_high_vs_macd_turn_bars"),
        "mean_abs_lag_high_vs_macd_turn_bars": _safe_series_mean_abs(segment_df, "lag_high_vs_macd_turn_bars"),
        "median_lag_high_vs_macd_hist_turn_bars": _safe_series_median(segment_df, "lag_high_vs_macd_hist_turn_bars"),
        "mean_abs_lag_high_vs_macd_hist_turn_bars": _safe_series_mean_abs(segment_df, "lag_high_vs_macd_hist_turn_bars"),
    }

    if len(segment_df):
        summary["death_win_rate_pct"] = float((segment_df["death_return_pct"] > 0).mean() * 100.0)

    summary["preferred_peak_anchor"] = _select_preferred_anchor(
        summary,
        [
            ("MACD", "mean_abs_lag_high_vs_macd_peak_bars"),
            ("MACD_HIST", "mean_abs_lag_high_vs_macd_hist_peak_bars"),
        ],
    )
    summary["preferred_turn_anchor"] = _select_preferred_anchor(
        summary,
        [
            ("MACD_TURN", "mean_abs_lag_high_vs_macd_turn_bars"),
            ("MACD_HIST_TURN", "mean_abs_lag_high_vs_macd_hist_turn_bars"),
        ],
    )

    if summary["preferred_turn_anchor"] == "MACD_TURN":
        derived_lag = summary.get("median_lag_high_vs_macd_turn_bars")
    elif summary["preferred_turn_anchor"] == "MACD_HIST_TURN":
        derived_lag = summary.get("median_lag_high_vs_macd_hist_turn_bars")
    else:
        derived_lag = 0.0

    summary["derived_turn_anchor"] = summary["preferred_turn_anchor"]
    summary["derived_turn_lag_bars"] = int(round(max(0.0, float(derived_lag or 0.0))))
    summary["preferred_confirmed_anchor"] = (
        "MACD_PEAK_CONFIRMED"
        if summary["preferred_turn_anchor"] == "MACD_TURN"
        else "MACD_HIST_PEAK_CONFIRMED"
        if summary["preferred_turn_anchor"] == "MACD_HIST_TURN"
        else "DEATH_CROSS_CONFIRMED"
    )
    summary["derived_confirmed_anchor"] = summary["preferred_confirmed_anchor"]
    summary["derived_confirmed_lag_bars"] = summary["derived_turn_lag_bars"]
    return summary


def build_segment_summaries(segment_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    per_ticker_rows = [
        summarize_segments(group.reset_index(drop=True), ticker)
        for ticker, group in segment_df.groupby("ticker", sort=True)
    ]
    by_ticker = pd.DataFrame(per_ticker_rows)
    overall = pd.DataFrame([summarize_segments(segment_df.reset_index(drop=True), OVERALL_TICKER)])
    return by_ticker, overall


def _build_derived_rule_map(
    per_ticker_summary: pd.DataFrame,
) -> Dict[str, Dict[str, Any]]:
    mapping: Dict[str, Dict[str, Any]] = {}
    for _, row in per_ticker_summary.iterrows():
        mapping[str(row["ticker"])] = {
            "anchor": row.get("derived_confirmed_anchor") or row.get("derived_turn_anchor") or "DEATH_CROSS_CONFIRMED",
            "lag_bars": int(row.get("derived_confirmed_lag_bars") or row.get("derived_turn_lag_bars") or 0),
        }
    return mapping


def _rule_signal_offset(record: SegmentRecord, rule_name: str) -> tuple[int, bool, Optional[str]]:
    death_signal_offset = len(record.trade_df) - 2
    if rule_name in {"death_cross", "death_cross_confirmed"}:
        return death_signal_offset, False, None
    if rule_name in {"macd_turn_down", "macd_peak_confirmed"}:
        offset, fallback = _effective_signal_offset(record.macd_turn_signal_offset, death_signal_offset)
        return offset, fallback, None
    if rule_name in {"macd_hist_turn_down", "macd_hist_peak_confirmed"}:
        offset, fallback = _effective_signal_offset(record.hist_turn_signal_offset, death_signal_offset)
        return offset, fallback, None
    raise ValueError(f"Unsupported rule: {rule_name}")


def build_rule_details(
    records: Sequence[SegmentRecord],
    derived_rule_map: Dict[str, Dict[str, Any]],
) -> pd.DataFrame:
    rows: list[Dict[str, Any]] = []
    for record in records:
        peak_high = record.row["peak_high"]
        peak_close = record.row["peak_close"]
        base_rules = [
            ("death_cross_confirmed", "Death Cross Confirmed", 0, None),
            ("macd_peak_confirmed", "MACD Peak Confirmed", 0, None),
            ("macd_hist_peak_confirmed", "MACD Hist Peak Confirmed", 0, None),
        ]

        derived_cfg = derived_rule_map.get(record.ticker, {"anchor": "DEATH_CROSS_CONFIRMED", "lag_bars": 0})
        derived_anchor = str(derived_cfg.get("anchor") or "DEATH_CROSS_CONFIRMED")
        derived_lag_bars = int(derived_cfg.get("lag_bars") or 0)
        if derived_anchor in {"MACD_PEAK_CONFIRMED", "MACD_TURN"}:
            derived_signal_offset, derived_fallback = _effective_signal_offset(
                record.macd_turn_signal_offset,
                len(record.trade_df) - 2,
            )
        elif derived_anchor in {"MACD_HIST_PEAK_CONFIRMED", "MACD_HIST_TURN"}:
            derived_signal_offset, derived_fallback = _effective_signal_offset(
                record.hist_turn_signal_offset,
                len(record.trade_df) - 2,
            )
        else:
            derived_signal_offset = len(record.trade_df) - 2
            derived_fallback = False

        for rule_name, rule_label, lag_bars, anchor_name in base_rules:
            signal_offset, fallback_to_death, _ = _rule_signal_offset(record, rule_name)
            metrics = _evaluate_exit(
                record.trade_df,
                signal_offset=signal_offset,
                lag_bars=lag_bars,
                peak_high=peak_high,
                peak_close=peak_close,
            )
            rows.append(
                {
                    "ticker": record.ticker,
                    "segment_id": record.segment_id,
                    "rule_name": rule_name,
                    "rule_label": rule_label,
                    "derived_anchor": anchor_name,
                    "derived_lag_bars": lag_bars,
                    "fallback_to_death": fallback_to_death,
                    "entry_date": record.row["entry_date"],
                    "entry_open": record.row["entry_open"],
                    **metrics,
                }
            )

        derived_metrics = _evaluate_exit(
            record.trade_df,
            signal_offset=derived_signal_offset,
            lag_bars=derived_lag_bars,
            peak_high=peak_high,
            peak_close=peak_close,
        )
        rows.append(
            {
                "ticker": record.ticker,
                "segment_id": record.segment_id,
                "rule_name": "derived_confirmed_lag",
                "rule_label": "Derived Confirmed Lag",
                "derived_anchor": derived_anchor,
                "derived_lag_bars": derived_lag_bars,
                "fallback_to_death": derived_fallback,
                "entry_date": record.row["entry_date"],
                "entry_open": record.row["entry_open"],
                **derived_metrics,
            }
        )

    return pd.DataFrame(rows)


def _collapse_text(values: Iterable[Any]) -> Optional[str]:
    unique = sorted(
        {
            str(value)
            for value in values
            if value is not None and not pd.isna(value) and str(value) != ""
        }
    )
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return "MIXED"


def _collapse_int(values: Iterable[Any]) -> Optional[int]:
    unique = sorted({int(value) for value in values if value is not None and not pd.isna(value)})
    if not unique:
        return None
    if len(unique) == 1:
        return unique[0]
    return None


def summarize_rule_details(rule_df: pd.DataFrame) -> pd.DataFrame:
    def _summarize(group: pd.DataFrame, ticker_value: str, rule_name: str) -> Dict[str, Any]:
        return {
            "ticker": ticker_value,
            "rule_name": rule_name,
            "rule_label": _collapse_text(group["rule_label"]),
            "derived_anchor": _collapse_text(group["derived_anchor"]),
            "derived_lag_bars": _collapse_int(group["derived_lag_bars"]),
            "segments": int(len(group)),
            "avg_return_pct": _safe_series_mean(group, "return_pct"),
            "median_return_pct": _safe_series_median(group, "return_pct"),
            "win_rate_pct": float((group["return_pct"] > 0).mean() * 100.0) if len(group) else None,
            "avg_capture_high_ratio": _safe_series_mean(group, "capture_high_ratio"),
            "median_capture_high_ratio": _safe_series_median(group, "capture_high_ratio"),
            "avg_capture_close_ratio": _safe_series_mean(group, "capture_close_ratio"),
            "median_capture_close_ratio": _safe_series_median(group, "capture_close_ratio"),
            "avg_holding_bars": _safe_series_mean(group, "holding_bars"),
            "median_holding_bars": _safe_series_median(group, "holding_bars"),
            "fallback_rate_pct": float(group["fallback_to_death"].mean() * 100.0) if len(group) else None,
        }

    rows: list[Dict[str, Any]] = []
    for (ticker, rule_name), group in rule_df.groupby(["ticker", "rule_name"], sort=True):
        rows.append(_summarize(group.reset_index(drop=True), str(ticker), str(rule_name)))

    for rule_name, group in rule_df.groupby("rule_name", sort=True):
        rows.append(_summarize(group.reset_index(drop=True), OVERALL_TICKER, str(rule_name)))

    return pd.DataFrame(rows)


def run_multi_ticker_macd_segment_analysis(
    tickers: Sequence[str],
    data_root: str = "data",
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    history_tolerance_days: int = DEFAULT_HISTORY_TOLERANCE_DAYS,
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_tickers = normalize_ticker_inputs(tickers=tickers)
    if not normalized_tickers:
        raise ValueError("At least one ticker must be provided")

    initial_readiness, final_readiness = ensure_ticker_data(
        normalized_tickers,
        data_root=data_root,
        lookback_days=lookback_days,
        history_tolerance_days=history_tolerance_days,
        api_key=api_key,
    )

    manager = StockDataManager(api_key=None, data_root=data_root)
    all_records: list[SegmentRecord] = []
    for ticker in normalized_tickers:
        features_df = manager.load_stock_features(ticker)
        records = extract_segment_records(ticker, features_df)
        all_records.extend(records)

    if not all_records:
        raise ValueError("No complete MACD bullish segments were found for the requested tickers")

    segments_df = pd.DataFrame([record.row for record in all_records]).sort_values(
        ["ticker", "entry_date", "segment_id"]
    ).reset_index(drop=True)
    summary_by_ticker_df, summary_overall_df = build_segment_summaries(segments_df)
    derived_rule_map = _build_derived_rule_map(summary_by_ticker_df)
    rule_details_df = build_rule_details(all_records, derived_rule_map).sort_values(
        ["ticker", "rule_name", "entry_date", "segment_id"]
    ).reset_index(drop=True)
    rule_summary_df = summarize_rule_details(rule_details_df).sort_values(
        ["ticker", "rule_name"]
    ).reset_index(drop=True)

    return {
        "tickers": normalized_tickers,
        "initial_readiness": initial_readiness,
        "final_readiness": final_readiness,
        "segments": segments_df,
        "summary_by_ticker": summary_by_ticker_df,
        "summary_overall": summary_overall_df,
        "rule_details": rule_details_df,
        "rule_summary": rule_summary_df,
        "derived_rule_map": derived_rule_map,
    }


def save_macd_segment_analysis_outputs(
    analysis_result: Dict[str, Any],
    output_dir: str,
    timestamp: str,
    prefix: str = "macd_segment",
) -> Dict[str, Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    files = {
        "readiness": output_path / f"{prefix}_readiness_{timestamp}.csv",
        "segments": output_path / f"{prefix}_raw_{timestamp}.csv",
        "summary_by_ticker": output_path / f"{prefix}_summary_by_ticker_{timestamp}.csv",
        "summary_overall": output_path / f"{prefix}_summary_overall_{timestamp}.csv",
        "rule_details": output_path / f"{prefix}_rule_details_{timestamp}.csv",
        "rule_summary": output_path / f"{prefix}_rule_comparison_{timestamp}.csv",
    }

    analysis_result["final_readiness"].to_csv(files["readiness"], index=False)
    analysis_result["segments"].to_csv(files["segments"], index=False)
    analysis_result["summary_by_ticker"].to_csv(files["summary_by_ticker"], index=False)
    analysis_result["summary_overall"].to_csv(files["summary_overall"], index=False)
    analysis_result["rule_details"].to_csv(files["rule_details"], index=False)
    analysis_result["rule_summary"].to_csv(files["rule_summary"], index=False)
    return files