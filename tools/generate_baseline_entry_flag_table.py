from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DEFAULT_SOURCE_CSV = (
    "strategy_evaluation/macd_entry_variants_cli_20260407/"
    "strategy_evaluation_trades_20260407_111358.csv"
)
DEFAULT_SEGMENT_CSV = "strategy_evaluation/macd_segment_raw_20260406_112854.csv"
DEFAULT_DATA_ROOT = "data"
DEFAULT_OUTPUT_DIR = "strategy_evaluation/baseline_flag_analysis"
DEFAULT_ENTRY_STRATEGY = "MACDCrossoverStrategy"
DEFAULT_EXIT_STRATEGY = "MVX_N3_R3p25_T1p6_D21_B20p0"


def normalize_code(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def parse_json_text(text: Any) -> dict[str, Any]:
    if pd.isna(text) or text in (None, ""):
        return {}
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_float(value: Any) -> float:
    try:
        if pd.isna(value):
            return np.nan
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def load_trade_actions(path: Path, entry_strategy: str, exit_strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    if "entry_strategy" in df.columns:
        df = df[df["entry_strategy"] == entry_strategy].copy()
    if "exit_strategy" in df.columns:
        df = df[df["exit_strategy"] == exit_strategy].copy()

    df["ticker"] = df["ticker"].map(normalize_code)
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)

    if "entry_macd" not in df.columns:
        entry_meta = df["entry_metadata_json"].apply(parse_json_text)
        df["entry_macd"] = entry_meta.apply(lambda x: safe_float(x.get("macd")))
        df["entry_macd_hist"] = entry_meta.apply(
            lambda x: safe_float(x.get("macd_hist"))
        )
        df["entry_macd_hist_prev"] = entry_meta.apply(
            lambda x: safe_float(x.get("macd_hist_prev"))
        )
        df["entry_macd_signal"] = entry_meta.apply(
            lambda x: safe_float(x.get("macd_signal"))
        )

    period_part = df["period"].astype(str) if "period" in df.columns else ""
    df["entry_key"] = (
        period_part
        + "|"
        + df["ticker"].astype(str)
        + "|"
        + df["entry_date"].astype(str)
        + "|"
        + df["entry_price"].astype(str)
    )
    return df


def aggregate_entries(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for _, group in df.groupby("entry_key", sort=False):
        ordered = group.sort_values(
            ["exit_date", "position_quantity_after_exit", "exit_is_full_exit"],
            ascending=[True, True, True],
        ).reset_index(drop=True)
        first = ordered.iloc[0]

        final_candidates = ordered[ordered["position_quantity_after_exit"] == 0]
        final_row = final_candidates.iloc[-1] if not final_candidates.empty else ordered.iloc[-1]

        initial_shares = int(
            pd.to_numeric(ordered["position_quantity_before_exit"], errors="coerce")
            .fillna(0)
            .max()
        )
        if initial_shares <= 0:
            initial_shares = int(pd.to_numeric(ordered["shares"], errors="coerce").fillna(0).sum())

        total_return_jpy = float(pd.to_numeric(ordered["return_jpy"], errors="coerce").fillna(0).sum())
        entry_price = safe_float(first.get("entry_price"))
        lifecycle_return_pct = np.nan
        if pd.notna(entry_price) and entry_price > 0 and initial_shares > 0:
            lifecycle_return_pct = (total_return_jpy / (entry_price * initial_shares)) * 100.0

        exit_path = " | ".join(
            ordered["exit_urgency"].astype(str) + ":" + ordered["exit_reason"].astype(str)
        )
        had_r_exit = ordered["exit_urgency"].astype(str).str.startswith("R").any()
        is_bad_r = bool(had_r_exit and total_return_jpy < 0)

        rows.append(
            {
                "entry_key": first["entry_key"],
                "period": first.get("period", ""),
                "ticker": first["ticker"],
                "entry_date": first["entry_date"],
                "entry_price": entry_price,
                "entry_confidence": safe_float(first.get("entry_confidence")),
                "action_count": int(len(ordered)),
                "had_partial_exit": bool(ordered.get("exit_is_partial_exit", pd.Series(False)).fillna(False).any()),
                "initial_shares": initial_shares,
                "final_exit_date": final_row["exit_date"],
                "final_exit_urgency": final_row["exit_urgency"],
                "final_exit_reason": final_row["exit_reason"],
                "exit_path": exit_path,
                "lifecycle_return_pct": lifecycle_return_pct,
                "lifecycle_return_jpy": total_return_jpy,
                "peak_price": safe_float(pd.to_numeric(ordered["peak_price"], errors="coerce").max()),
                "entry_macd": safe_float(first.get("entry_macd")),
                "entry_macd_signal": safe_float(first.get("entry_macd_signal")),
                "entry_macd_hist": safe_float(first.get("entry_macd_hist")),
                "entry_macd_hist_prev": safe_float(first.get("entry_macd_hist_prev")),
                "is_bad_r": is_bad_r,
            }
        )

    return pd.DataFrame(rows)


def load_segment_lookup(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].map(normalize_code)
    df["entry_date"] = df["entry_date"].astype(str)
    keep_cols = [
        "ticker",
        "entry_date",
        "golden_cross_date",
        "segment_total_bars",
        "peak_high_offset_bars",
        "macd_hist_turn_signal_offset_bars",
        "death_return_pct",
        "lag_high_vs_macd_hist_peak_bars",
    ]
    return df[keep_cols].drop_duplicates(subset=["ticker", "entry_date"], keep="first")


def load_feature_table(data_root: Path, ticker: str, cache: dict[str, pd.DataFrame | None]) -> pd.DataFrame | None:
    if ticker in cache:
        return cache[ticker]

    feature_path = data_root / "features" / f"{ticker}_features.parquet"
    if not feature_path.exists():
        cache[ticker] = None
        return None

    df = pd.read_parquet(feature_path)
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    cache[ticker] = df
    return df


def build_flag_table(entries: pd.DataFrame, data_root: Path, thresholds: dict[str, float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    feature_cache: dict[str, pd.DataFrame | None] = {}

    for entry in entries.to_dict("records"):
        signal_date = entry.get("golden_cross_date") or entry.get("entry_date")
        ticker = entry["ticker"]
        feature_df = load_feature_table(data_root, ticker, feature_cache)

        hist_jump_norm = np.nan
        entry_bb_pctb = np.nan
        entry_return_20d = np.nan
        gap_above_ema20_pct = np.nan
        entry_volume_ratio = np.nan
        entry_adx_14 = np.nan
        entry_trend_strength_200 = np.nan
        entry_return_5d = np.nan
        zero_axis_depth_norm = np.nan
        hist_recovery_ratio = np.nan
        both_below_zero_axis = False
        flat_ema20 = False
        weak_positive_hist = False
        deep_negative_before_cross = False
        high_bb_pctb = False
        far_above_ema20 = False
        hist_positive_growth_3d = False
        weak_trend_strength_200 = False
        weak_volume_confirmation = False
        low_adx = False
        deep_below_zero_axis = False
        weak_hist_recovery_ratio = False
        short_term_pop_weak_structure = False
        early_peak_high = False
        short_segment_total = False
        fast_macd_hist_turn = False
        death_return_nonpositive = False
        no_high_lag_vs_hist_peak = False
        ema20_slope_pct = np.nan
        hist_now_norm = np.nan
        hist_prev_norm = np.nan
        signal_date_found = False

        if feature_df is not None:
            match_idx = feature_df.index[feature_df["Date"] == signal_date]
            if len(match_idx) > 0:
                i = int(match_idx[0])
                latest = feature_df.iloc[i]
                prev1 = feature_df.iloc[i - 1] if i >= 1 else None
                prev3 = feature_df.iloc[i - 3 : i + 1] if i >= 3 else None

                close = safe_float(latest.get("Close"))
                ema20 = safe_float(latest.get("EMA_20"))
                macd = safe_float(latest.get("MACD"))
                macd_signal = safe_float(latest.get("MACD_Signal"))
                macd_hist = safe_float(latest.get("MACD_Hist"))
                prev_hist = safe_float(prev1.get("MACD_Hist")) if prev1 is not None else np.nan

                if pd.notna(close) and close > 0 and pd.notna(macd_hist) and pd.notna(prev_hist):
                    hist_jump_norm = (macd_hist - prev_hist) / close
                    hist_now_norm = macd_hist / close
                    hist_prev_norm = abs(prev_hist) / close

                entry_bb_pctb = safe_float(latest.get("BB_PctB"))
                entry_return_20d = safe_float(latest.get("Return_20d"))
                entry_return_5d = safe_float(latest.get("Return_5d"))
                entry_adx_14 = safe_float(latest.get("ADX_14"))
                entry_trend_strength_200 = safe_float(latest.get("TrendStrength_200"))
                volume_now = safe_float(latest.get("Volume"))
                volume_sma20 = safe_float(latest.get("Volume_SMA_20"))
                if pd.notna(volume_now) and pd.notna(volume_sma20) and volume_sma20 > 0:
                    entry_volume_ratio = volume_now / volume_sma20
                if pd.notna(close) and close > 0 and pd.notna(ema20) and ema20 > 0:
                    gap_above_ema20_pct = ((close / ema20) - 1.0) * 100.0

                both_below_zero_axis = bool(
                    pd.notna(macd) and pd.notna(macd_signal) and macd < 0 and macd_signal < 0
                )
                if pd.notna(close) and close > 0 and pd.notna(macd) and pd.notna(macd_signal):
                    zero_axis_depth_norm = max(abs(macd), abs(macd_signal)) / close

                if prev1 is not None:
                    prev_ema20 = safe_float(prev1.get("EMA_20"))
                    if pd.notna(prev_ema20) and prev_ema20 > 0 and pd.notna(ema20):
                        ema20_slope_pct = ((ema20 / prev_ema20) - 1.0) * 100.0
                        flat_ema20 = bool(
                            ema20_slope_pct < thresholds["flat_ema20_slope_pct"]
                        )

                weak_positive_hist = bool(
                    pd.notna(hist_now_norm)
                    and hist_now_norm < thresholds["weak_positive_hist_norm"]
                )
                deep_negative_before_cross = bool(
                    pd.notna(hist_prev_norm)
                    and hist_prev_norm > thresholds["deep_negative_prev_hist_norm"]
                )
                if pd.notna(hist_now_norm) and pd.notna(hist_prev_norm) and hist_prev_norm > 0:
                    hist_recovery_ratio = hist_now_norm / hist_prev_norm
                high_bb_pctb = bool(
                    pd.notna(entry_bb_pctb)
                    and entry_bb_pctb > thresholds["high_bb_pctb"]
                )
                far_above_ema20 = bool(
                    pd.notna(gap_above_ema20_pct)
                    and gap_above_ema20_pct > thresholds["far_above_ema20_pct"]
                )
                if prev3 is not None and len(prev3) == 4:
                    hist_values = pd.to_numeric(prev3["MACD_Hist"], errors="coerce")
                    hist_positive_growth_3d = bool(hist_values.notna().all() and hist_values.is_monotonic_increasing and hist_values.nunique() == 4)

                signal_date_found = True

        shock_cross = bool(
            pd.notna(hist_jump_norm)
            and hist_jump_norm > thresholds["shock_hist_jump_norm"]
        )
        overheat_setup = bool(
            pd.notna(entry_bb_pctb)
            and pd.notna(gap_above_ema20_pct)
            and pd.notna(entry_return_20d)
            and entry_bb_pctb > thresholds["overheat_bb_pctb"]
            and gap_above_ema20_pct > thresholds["overheat_gap_above_ema20_pct"]
            and entry_return_20d > thresholds["overheat_return_20d"]
        )
        fragile_below_zero_cross = bool(
            both_below_zero_axis
            and flat_ema20
            and deep_negative_before_cross
            and weak_positive_hist
        )
        weak_trend_strength_200 = bool(
            pd.notna(entry_trend_strength_200)
            and entry_trend_strength_200 < thresholds["weak_trend_strength_200"]
        )
        weak_volume_confirmation = bool(
            pd.notna(entry_volume_ratio)
            and entry_volume_ratio < thresholds["weak_volume_ratio"]
        )
        low_adx = bool(
            pd.notna(entry_adx_14)
            and entry_adx_14 < thresholds["low_adx"]
        )
        deep_below_zero_axis = bool(
            both_below_zero_axis
            and pd.notna(zero_axis_depth_norm)
            and zero_axis_depth_norm > thresholds["deep_below_zero_axis_norm"]
        )
        weak_hist_recovery_ratio = bool(
            pd.notna(hist_recovery_ratio)
            and hist_recovery_ratio < thresholds["weak_hist_recovery_ratio"]
        )
        short_term_pop_weak_structure = bool(
            pd.notna(entry_return_5d)
            and pd.notna(ema20_slope_pct)
            and entry_return_5d > thresholds["short_term_pop_return_5d"]
            and ema20_slope_pct < thresholds["short_term_pop_max_ema20_slope_pct"]
        )
        early_peak_high = bool(
            pd.notna(entry.get("peak_high_offset_bars"))
            and safe_float(entry.get("peak_high_offset_bars")) <= thresholds["early_peak_high_max_bars"]
        )
        short_segment_total = bool(
            pd.notna(entry.get("segment_total_bars"))
            and safe_float(entry.get("segment_total_bars")) <= thresholds["short_segment_total_max_bars"]
        )
        fast_macd_hist_turn = bool(
            pd.notna(entry.get("macd_hist_turn_signal_offset_bars"))
            and safe_float(entry.get("macd_hist_turn_signal_offset_bars")) <= thresholds["fast_macd_hist_turn_max_bars"]
        )
        death_return_nonpositive = bool(
            pd.notna(entry.get("death_return_pct"))
            and safe_float(entry.get("death_return_pct")) <= thresholds["death_return_nonpositive_pct"]
        )
        no_high_lag_vs_hist_peak = bool(
            pd.notna(entry.get("lag_high_vs_macd_hist_peak_bars"))
            and safe_float(entry.get("lag_high_vs_macd_hist_peak_bars")) <= thresholds["no_high_lag_vs_hist_peak_max_bars"]
        )

        rows.append(
            {
                **entry,
                "signal_date": signal_date,
                "signal_date_found": bool(signal_date_found),
                "hist_jump_norm": hist_jump_norm,
                "entry_bb_pctb": entry_bb_pctb,
                "entry_return_5d": entry_return_5d,
                "entry_return_20d": entry_return_20d,
                "gap_above_ema20_pct": gap_above_ema20_pct,
                "entry_volume_ratio": entry_volume_ratio,
                "entry_adx_14": entry_adx_14,
                "entry_trend_strength_200": entry_trend_strength_200,
                "ema20_slope_pct": ema20_slope_pct,
                "hist_now_norm": hist_now_norm,
                "hist_prev_norm": hist_prev_norm,
                "zero_axis_depth_norm": zero_axis_depth_norm,
                "hist_recovery_ratio": hist_recovery_ratio,
                "shock_cross": shock_cross,
                "overheat_setup": overheat_setup,
                "both_below_zero_axis": both_below_zero_axis,
                "flat_ema20": flat_ema20,
                "weak_positive_hist": weak_positive_hist,
                "deep_negative_before_cross": deep_negative_before_cross,
                "fragile_below_zero_cross": fragile_below_zero_cross,
                "high_bb_pctb": high_bb_pctb,
                "far_above_ema20": far_above_ema20,
                "hist_positive_growth_3d": hist_positive_growth_3d,
                "weak_trend_strength_200": weak_trend_strength_200,
                "weak_volume_confirmation": weak_volume_confirmation,
                "low_adx": low_adx,
                "deep_below_zero_axis": deep_below_zero_axis,
                "weak_hist_recovery_ratio": weak_hist_recovery_ratio,
                "short_term_pop_weak_structure": short_term_pop_weak_structure,
                "early_peak_high": early_peak_high,
                "short_segment_total": short_segment_total,
                "fast_macd_hist_turn": fast_macd_hist_turn,
                "death_return_nonpositive": death_return_nonpositive,
                "no_high_lag_vs_hist_peak": no_high_lag_vs_hist_peak,
            }
        )

    return pd.DataFrame(rows)


def _summarize_boolean_flag(flag_name: str, series: pd.Series, bad_r_mask: pd.Series) -> dict[str, Any]:
    flag_series = series.fillna(False).astype(bool)
    total_bad_r = int(bad_r_mask.sum())
    total_non_bad_r = int((~bad_r_mask).sum())
    bad_true = int((flag_series & bad_r_mask).sum())
    non_bad_true = int((flag_series & ~bad_r_mask).sum())
    bad_rate = bad_true / total_bad_r if total_bad_r else 0.0
    non_bad_rate = non_bad_true / total_non_bad_r if total_non_bad_r else 0.0
    precision = bad_true / (bad_true + non_bad_true) if (bad_true + non_bad_true) else 0.0
    lift = bad_rate / non_bad_rate if non_bad_rate else np.nan
    return {
        "flag": flag_name,
        "bad_r_true_count": bad_true,
        "bad_r_total": total_bad_r,
        "bad_r_hit_rate": bad_rate,
        "non_bad_r_true_count": non_bad_true,
        "non_bad_r_total": total_non_bad_r,
        "non_bad_r_hit_rate": non_bad_rate,
        "precision_when_true": precision,
        "bad_r_lift": lift,
    }


def build_flag_summary(df: pd.DataFrame, flag_cols: list[str]) -> pd.DataFrame:
    bad_r_mask = df["is_bad_r"].fillna(False)
    rows: list[dict[str, Any]] = []

    for flag in flag_cols:
        rows.append(_summarize_boolean_flag(flag, df[flag], bad_r_mask))

    return pd.DataFrame(rows).sort_values(
        ["bad_r_lift", "bad_r_true_count"], ascending=[False, False]
    )


def _build_single_threshold_variants(
    base: float,
    step: float,
    operator: str,
) -> list[tuple[str, float]]:
    offsets = [(-2, "loose_2"), (-1, "loose_1"), (0, "base"), (1, "tight_1"), (2, "tight_2")]
    variants: list[tuple[str, float]] = []
    for offset, label in offsets:
        if operator == ">":
            value = base + (offset * step)
        elif operator == "<":
            value = base - (offset * step)
        else:
            raise ValueError(f"Unsupported operator: {operator}")
        variants.append((label, value))
    return variants


def build_parameter_flag_scan(df: pd.DataFrame, thresholds: dict[str, float]) -> pd.DataFrame:
    bad_r_mask = df["is_bad_r"].fillna(False)
    rows: list[dict[str, Any]] = []

    shock_variants = _build_single_threshold_variants(
        base=thresholds["shock_hist_jump_norm"],
        step=0.0010,
        operator=">",
    )
    for label, value in shock_variants:
        series = df["hist_jump_norm"] > value
        row = _summarize_boolean_flag("shock_cross", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    bb_variants = _build_single_threshold_variants(
        base=thresholds["high_bb_pctb"],
        step=0.02,
        operator=">",
    )
    for label, value in bb_variants:
        series = df["entry_bb_pctb"] > value
        row = _summarize_boolean_flag("high_bb_pctb", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    far_variants = _build_single_threshold_variants(
        base=thresholds["far_above_ema20_pct"],
        step=1.0,
        operator=">",
    )
    for label, value in far_variants:
        series = df["gap_above_ema20_pct"] > value
        row = _summarize_boolean_flag("far_above_ema20", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    flat_variants = _build_single_threshold_variants(
        base=thresholds["flat_ema20_slope_pct"],
        step=0.05,
        operator="<",
    )
    for label, value in flat_variants:
        series = df["ema20_slope_pct"] < value
        row = _summarize_boolean_flag("flat_ema20", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    weak_variants = _build_single_threshold_variants(
        base=thresholds["weak_positive_hist_norm"],
        step=0.0002,
        operator="<",
    )
    for label, value in weak_variants:
        series = df["hist_now_norm"] < value
        row = _summarize_boolean_flag("weak_positive_hist", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    deep_variants = _build_single_threshold_variants(
        base=thresholds["deep_negative_prev_hist_norm"],
        step=0.0002,
        operator=">",
    )
    for label, value in deep_variants:
        series = df["hist_prev_norm"] > value
        row = _summarize_boolean_flag("deep_negative_before_cross", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    overheat_offsets = [(-2, "loose_2"), (-1, "loose_1"), (0, "base"), (1, "tight_1"), (2, "tight_2")]
    for offset, label in overheat_offsets:
        bb_value = max(thresholds["overheat_bb_pctb"] + (offset * 0.02), 1e-9)
        gap_value = max(thresholds["overheat_gap_above_ema20_pct"] + (offset * 1.0), 1e-9)
        ret_value = max(thresholds["overheat_return_20d"] + (offset * 0.01), 1e-9)
        series = (
            (df["entry_bb_pctb"] > bb_value)
            & (df["gap_above_ema20_pct"] > gap_value)
            & (df["entry_return_20d"] > ret_value)
        )
        row = _summarize_boolean_flag("overheat_setup", series, bad_r_mask)
        row.update(
            {
                "variant": label,
                "variant_value": f"bb>{bb_value:.2f}|gap>{gap_value:.2f}|ret20>{ret_value:.2%}",
            }
        )
        rows.append(row)

    fragile_offsets = [(-2, "loose_2"), (-1, "loose_1"), (0, "base"), (1, "tight_1"), (2, "tight_2")]
    for offset, label in fragile_offsets:
        flat_value = max(thresholds["flat_ema20_slope_pct"] - (offset * 0.05), 1e-9)
        weak_value = max(thresholds["weak_positive_hist_norm"] - (offset * 0.0002), 1e-9)
        deep_value = max(thresholds["deep_negative_prev_hist_norm"] + (offset * 0.0002), 1e-9)
        series = (
            df["both_below_zero_axis"].fillna(False).astype(bool)
            & (df["ema20_slope_pct"] < flat_value)
            & (df["hist_now_norm"] < weak_value)
            & (df["hist_prev_norm"] > deep_value)
        )
        row = _summarize_boolean_flag("fragile_below_zero_cross", series, bad_r_mask)
        row.update(
            {
                "variant": label,
                "variant_value": (
                    f"below_zero & slope<{flat_value:.2f}% & "
                    f"hist_now<{weak_value:.4f} & hist_prev>{deep_value:.4f}"
                ),
            }
        )
        rows.append(row)

    weak_trend_variants = _build_single_threshold_variants(
        base=thresholds["weak_trend_strength_200"],
        step=0.02,
        operator="<",
    )
    for label, value in weak_trend_variants:
        series = df["entry_trend_strength_200"] < value
        row = _summarize_boolean_flag("weak_trend_strength_200", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    weak_volume_variants = _build_single_threshold_variants(
        base=thresholds["weak_volume_ratio"],
        step=0.1,
        operator="<",
    )
    for label, value in weak_volume_variants:
        series = df["entry_volume_ratio"] < value
        row = _summarize_boolean_flag("weak_volume_confirmation", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    low_adx_variants = _build_single_threshold_variants(
        base=thresholds["low_adx"],
        step=5.0,
        operator="<",
    )
    for label, value in low_adx_variants:
        series = df["entry_adx_14"] < value
        row = _summarize_boolean_flag("low_adx", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    deep_zero_variants = _build_single_threshold_variants(
        base=thresholds["deep_below_zero_axis_norm"],
        step=0.0005,
        operator=">",
    )
    for label, value in deep_zero_variants:
        series = df["both_below_zero_axis"].fillna(False).astype(bool) & (df["zero_axis_depth_norm"] > value)
        row = _summarize_boolean_flag("deep_below_zero_axis", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    weak_recovery_variants = _build_single_threshold_variants(
        base=thresholds["weak_hist_recovery_ratio"],
        step=0.2,
        operator="<",
    )
    for label, value in weak_recovery_variants:
        series = df["hist_recovery_ratio"] < value
        row = _summarize_boolean_flag("weak_hist_recovery_ratio", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    pop_offsets = [(-2, "loose_2"), (-1, "loose_1"), (0, "base"), (1, "tight_1"), (2, "tight_2")]
    for offset, label in pop_offsets:
        ret_value = max(thresholds["short_term_pop_return_5d"] + (offset * 0.01), 1e-9)
        slope_value = max(thresholds["short_term_pop_max_ema20_slope_pct"] - (offset * 0.05), 1e-9)
        series = (df["entry_return_5d"] > ret_value) & (df["ema20_slope_pct"] < slope_value)
        row = _summarize_boolean_flag("short_term_pop_weak_structure", series, bad_r_mask)
        row.update(
            {
                "variant": label,
                "variant_value": f"ret5d>{ret_value:.2%}|ema20_slope<{slope_value:.2f}%",
            }
        )
        rows.append(row)

    early_peak_variants = _build_single_threshold_variants(
        base=thresholds["early_peak_high_max_bars"],
        step=1.0,
        operator="<",
    )
    for label, value in early_peak_variants:
        series = df["peak_high_offset_bars"] <= value
        row = _summarize_boolean_flag("early_peak_high", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    short_segment_variants = _build_single_threshold_variants(
        base=thresholds["short_segment_total_max_bars"],
        step=2.0,
        operator="<",
    )
    for label, value in short_segment_variants:
        series = df["segment_total_bars"] <= value
        row = _summarize_boolean_flag("short_segment_total", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    fast_turn_variants = _build_single_threshold_variants(
        base=thresholds["fast_macd_hist_turn_max_bars"],
        step=1.0,
        operator="<",
    )
    for label, value in fast_turn_variants:
        series = df["macd_hist_turn_signal_offset_bars"] <= value
        row = _summarize_boolean_flag("fast_macd_hist_turn", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    death_ret_variants = _build_single_threshold_variants(
        base=thresholds["death_return_nonpositive_pct"],
        step=1.0,
        operator="<",
    )
    for label, value in death_ret_variants:
        series = df["death_return_pct"] <= value
        row = _summarize_boolean_flag("death_return_nonpositive", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    lag_variants = _build_single_threshold_variants(
        base=thresholds["no_high_lag_vs_hist_peak_max_bars"],
        step=1.0,
        operator="<",
    )
    for label, value in lag_variants:
        series = df["lag_high_vs_macd_hist_peak_bars"] <= value
        row = _summarize_boolean_flag("no_high_lag_vs_hist_peak", series, bad_r_mask)
        row.update({"variant": label, "variant_value": value})
        rows.append(row)

    scan_df = pd.DataFrame(rows)
    if scan_df.empty:
        return scan_df
    scan_df["keep_flag_family"] = scan_df.groupby("flag")["bad_r_lift"].transform(lambda s: bool((s >= 1.0).any()))
    return scan_df.sort_values(["flag", "bad_r_lift", "bad_r_true_count"], ascending=[True, False, False])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-csv", default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--segment-csv", default=DEFAULT_SEGMENT_CSV)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--entry-strategy", default=DEFAULT_ENTRY_STRATEGY)
    parser.add_argument("--exit-strategy", default=DEFAULT_EXIT_STRATEGY)
    parser.add_argument("--shock-hist-jump-norm", type=float, default=0.0050)
    parser.add_argument("--overheat-bb-pctb", type=float, default=0.94)
    parser.add_argument("--overheat-gap-above-ema20-pct", type=float, default=5.0)
    parser.add_argument("--overheat-return-20d", type=float, default=0.05)
    parser.add_argument("--high-bb-pctb", type=float, default=0.90)
    parser.add_argument("--far-above-ema20-pct", type=float, default=4.0)
    parser.add_argument("--flat-ema20-slope-pct", type=float, default=0.25)
    parser.add_argument("--weak-positive-hist-norm", type=float, default=0.0008)
    parser.add_argument("--deep-negative-prev-hist-norm", type=float, default=0.0010)
    parser.add_argument("--weak-trend-strength-200", type=float, default=0.02)
    parser.add_argument("--weak-volume-ratio", type=float, default=1.1)
    parser.add_argument("--low-adx", type=float, default=20.0)
    parser.add_argument("--deep-below-zero-axis-norm", type=float, default=0.0015)
    parser.add_argument("--weak-hist-recovery-ratio", type=float, default=0.8)
    parser.add_argument("--short-term-pop-return-5d", type=float, default=0.05)
    parser.add_argument("--short-term-pop-max-ema20-slope-pct", type=float, default=0.25)
    parser.add_argument("--early-peak-high-max-bars", type=float, default=2.0)
    parser.add_argument("--short-segment-total-max-bars", type=float, default=8.0)
    parser.add_argument("--fast-macd-hist-turn-max-bars", type=float, default=2.0)
    parser.add_argument("--death-return-nonpositive-pct", type=float, default=0.0)
    parser.add_argument("--no-high-lag-vs-hist-peak-max-bars", type=float, default=0.0)
    parser.add_argument(
        "--scan-parameter-flags",
        action="store_true",
        help="对所有参数化flag执行5档阈值扫描，并筛掉5档lift都<1的flag家族",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_csv = Path(args.source_csv)
    segment_csv = Path(args.segment_csv)
    data_root = Path(args.data_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    thresholds = {
        "shock_hist_jump_norm": float(args.shock_hist_jump_norm),
        "overheat_bb_pctb": float(args.overheat_bb_pctb),
        "overheat_gap_above_ema20_pct": float(args.overheat_gap_above_ema20_pct),
        "overheat_return_20d": float(args.overheat_return_20d),
        "high_bb_pctb": float(args.high_bb_pctb),
        "far_above_ema20_pct": float(args.far_above_ema20_pct),
        "flat_ema20_slope_pct": float(args.flat_ema20_slope_pct),
        "weak_positive_hist_norm": float(args.weak_positive_hist_norm),
        "deep_negative_prev_hist_norm": float(args.deep_negative_prev_hist_norm),
        "weak_trend_strength_200": float(args.weak_trend_strength_200),
        "weak_volume_ratio": float(args.weak_volume_ratio),
        "low_adx": float(args.low_adx),
        "deep_below_zero_axis_norm": float(args.deep_below_zero_axis_norm),
        "weak_hist_recovery_ratio": float(args.weak_hist_recovery_ratio),
        "short_term_pop_return_5d": float(args.short_term_pop_return_5d),
        "short_term_pop_max_ema20_slope_pct": float(args.short_term_pop_max_ema20_slope_pct),
        "early_peak_high_max_bars": float(args.early_peak_high_max_bars),
        "short_segment_total_max_bars": float(args.short_segment_total_max_bars),
        "fast_macd_hist_turn_max_bars": float(args.fast_macd_hist_turn_max_bars),
        "death_return_nonpositive_pct": float(args.death_return_nonpositive_pct),
        "no_high_lag_vs_hist_peak_max_bars": float(args.no_high_lag_vs_hist_peak_max_bars),
    }

    actions = load_trade_actions(
        path=source_csv,
        entry_strategy=args.entry_strategy,
        exit_strategy=args.exit_strategy,
    )
    entries = aggregate_entries(actions)
    segment_lookup = load_segment_lookup(segment_csv)
    entries = entries.merge(segment_lookup, on=["ticker", "entry_date"], how="left")

    flag_table = build_flag_table(entries, data_root=data_root, thresholds=thresholds)

    flag_cols = [
        "is_bad_r",
        "shock_cross",
        "overheat_setup",
        "both_below_zero_axis",
        "flat_ema20",
        "weak_positive_hist",
        "deep_negative_before_cross",
        "fragile_below_zero_cross",
        "high_bb_pctb",
        "far_above_ema20",
        "hist_positive_growth_3d",
        "weak_trend_strength_200",
        "weak_volume_confirmation",
        "low_adx",
        "deep_below_zero_axis",
        "weak_hist_recovery_ratio",
        "short_term_pop_weak_structure",
        "early_peak_high",
        "short_segment_total",
        "fast_macd_hist_turn",
        "death_return_nonpositive",
        "no_high_lag_vs_hist_peak",
    ]
    summary = build_flag_summary(flag_table, flag_cols=[flag for flag in flag_cols if flag != "is_bad_r"])
    scan_df = None
    if args.scan_parameter_flags:
        scan_df = build_parameter_flag_scan(flag_table, thresholds=thresholds)

    display_cols = [
        "ticker",
        "period",
        "entry_date",
        "signal_date",
        "final_exit_date",
        "final_exit_urgency",
        "final_exit_reason",
        "lifecycle_return_pct",
        "lifecycle_return_jpy",
        "exit_path",
        "is_bad_r",
        "shock_cross",
        "overheat_setup",
        "both_below_zero_axis",
        "flat_ema20",
        "weak_positive_hist",
        "deep_negative_before_cross",
        "fragile_below_zero_cross",
        "high_bb_pctb",
        "far_above_ema20",
        "hist_positive_growth_3d",
        "weak_trend_strength_200",
        "weak_volume_confirmation",
        "low_adx",
        "deep_below_zero_axis",
        "weak_hist_recovery_ratio",
        "short_term_pop_weak_structure",
        "early_peak_high",
        "short_segment_total",
        "fast_macd_hist_turn",
        "death_return_nonpositive",
        "no_high_lag_vs_hist_peak",
    ]
    flag_table = flag_table[display_cols].sort_values(["entry_date", "ticker"]).reset_index(drop=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_path = output_dir / f"baseline_entry_flag_table_{ts}.csv"
    summary_path = output_dir / f"baseline_entry_flag_summary_{ts}.csv"
    params_path = output_dir / f"baseline_entry_flag_params_{ts}.json"
    scan_all_path = output_dir / f"baseline_parameter_flag_scan_{ts}.csv"
    scan_kept_path = output_dir / f"baseline_parameter_flag_scan_kept_{ts}.csv"

    flag_table.to_csv(detail_path, index=False, encoding="utf-8-sig")
    summary.to_csv(summary_path, index=False, encoding="utf-8-sig")
    if scan_df is not None:
        scan_df.to_csv(scan_all_path, index=False, encoding="utf-8-sig")
        scan_df[scan_df["keep_flag_family"]].to_csv(scan_kept_path, index=False, encoding="utf-8-sig")
    params_path.write_text(json.dumps({
        "source_csv": str(source_csv),
        "entry_strategy": args.entry_strategy,
        "exit_strategy": args.exit_strategy,
        "thresholds": thresholds,
        "rows": int(len(flag_table)),
        "scan_parameter_flags": bool(args.scan_parameter_flags),
    }, ensure_ascii=True, indent=2), encoding="utf-8")

    print(detail_path)
    print(summary_path)
    if args.scan_parameter_flags:
        print(scan_all_path)
        print(scan_kept_path)
    print(params_path)


if __name__ == "__main__":
    main()