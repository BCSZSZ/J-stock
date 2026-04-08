from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis.strategies.entry.macd_precross_momentum_entry import (  # noqa: E402
    build_precross_momentum_flags,
)
from tools.generate_baseline_entry_flag_table import (  # noqa: E402
    aggregate_entries,
    load_feature_table,
    load_trade_actions,
)


DEFAULT_SOURCE_CSV = (
    "strategy_evaluation/macd_entry_variants_cli_20260407/"
    "strategy_evaluation_trades_20260407_111358.csv"
)
DEFAULT_OUTPUT_DIR = "strategy_evaluation/macd_precross_lead_scan"
DEFAULT_DATA_ROOT = "data"
DEFAULT_ENTRY_STRATEGY = "MACDCrossoverStrategy"
DEFAULT_EXIT_STRATEGY = "MVX_N3_R3p25_T1p6_D21_B20p0"
HIST_ABS_NORM_SCAN = [None, 0.004, 0.006, 0.008, 0.010, 0.012]


def _safe_float(value: Any) -> float:
    try:
        if pd.isna(value):
            return np.nan
    except TypeError:
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return np.nan


def _df_to_markdown(df: pd.DataFrame) -> str:
    table = df.fillna("N/A").astype(str)
    headers = list(table.columns)
    rows = table.values.tolist()
    separator = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(separator) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def _find_index_by_date(feature_df: pd.DataFrame, date_text: str) -> int | None:
    matches = feature_df.index[feature_df["Date"] == str(date_text)]
    if len(matches) == 0:
        return None
    return int(matches[0])


def _forward_open_return(feature_df: pd.DataFrame, entry_idx: int, bars: int) -> float:
    exit_idx = entry_idx + int(bars)
    if exit_idx >= len(feature_df):
        return np.nan
    entry_open = _safe_float(feature_df.iloc[entry_idx].get("Open"))
    exit_open = _safe_float(feature_df.iloc[exit_idx].get("Open"))
    if pd.isna(entry_open) or entry_open <= 0 or pd.isna(exit_open):
        return np.nan
    return ((exit_open / entry_open) - 1.0) * 100.0


def _extreme_return_before_index(
    feature_df: pd.DataFrame,
    entry_idx: int,
    stop_idx: int,
    price_column: str,
) -> float:
    if stop_idx <= entry_idx:
        return np.nan
    window = feature_df.iloc[entry_idx:stop_idx]
    if window.empty:
        return np.nan
    entry_open = _safe_float(feature_df.iloc[entry_idx].get("Open"))
    extreme_price = _safe_float(window[price_column].min() if price_column == "Low" else window[price_column].max())
    if pd.isna(entry_open) or entry_open <= 0 or pd.isna(extreme_price):
        return np.nan
    return ((extreme_price / entry_open) - 1.0) * 100.0


def _summarize_records(records_df: pd.DataFrame, baseline_entry_count: int, label: str) -> dict[str, Any]:
    if records_df.empty:
        return {
            "label": label,
            "sample_count": 0,
            "sample_share_baseline": 0.0,
            "avg_lead_bars": np.nan,
            "median_lead_bars": np.nan,
            "avg_lead_return_to_baseline_entry_pct": np.nan,
            "median_lead_return_to_baseline_entry_pct": np.nan,
            "positive_lead_share": np.nan,
            "avg_drawdown_before_baseline_pct": np.nan,
            "avg_runup_before_baseline_pct": np.nan,
            "avg_baseline_lifecycle_return_pct": np.nan,
            "baseline_bad_r_share": np.nan,
            "baseline_win_share": np.nan,
            "avg_pre_fwd_5d_return_pct": np.nan,
            "avg_pre_fwd_10d_return_pct": np.nan,
            "avg_pre_fwd_20d_return_pct": np.nan,
        }

    return {
        "label": label,
        "sample_count": int(len(records_df)),
        "sample_share_baseline": float(len(records_df) / baseline_entry_count) if baseline_entry_count else np.nan,
        "avg_lead_bars": float(records_df["lead_bars"].mean()),
        "median_lead_bars": float(records_df["lead_bars"].median()),
        "avg_lead_return_to_baseline_entry_pct": float(records_df["lead_return_to_baseline_entry_pct"].mean()),
        "median_lead_return_to_baseline_entry_pct": float(records_df["lead_return_to_baseline_entry_pct"].median()),
        "positive_lead_share": float(records_df["lead_return_to_baseline_entry_pct"].gt(0).mean()),
        "avg_drawdown_before_baseline_pct": float(records_df["drawdown_before_baseline_pct"].mean()),
        "avg_runup_before_baseline_pct": float(records_df["runup_before_baseline_pct"].mean()),
        "avg_baseline_lifecycle_return_pct": float(records_df["baseline_lifecycle_return_pct"].mean()),
        "baseline_bad_r_share": float(records_df["baseline_is_bad_r"].astype(bool).mean()),
        "baseline_win_share": float(records_df["baseline_lifecycle_return_pct"].gt(0).mean()),
        "avg_pre_fwd_5d_return_pct": float(records_df["pre_fwd_5d_return_pct"].mean()),
        "avg_pre_fwd_10d_return_pct": float(records_df["pre_fwd_10d_return_pct"].mean()),
        "avg_pre_fwd_20d_return_pct": float(records_df["pre_fwd_20d_return_pct"].mean()),
    }


def _find_precross_record(
    entry: dict[str, Any],
    feature_df: pd.DataFrame,
    hist_rise_days: int,
    price_rise_days: int,
    max_lead_bars: int,
    pick_mode: str,
    require_above_ema200: bool,
    max_hist_abs_norm: float | None,
    require_peak_at_window_start: bool,
) -> dict[str, Any] | None:
    baseline_entry_date = str(entry["entry_date"])
    baseline_entry_idx = _find_index_by_date(feature_df, baseline_entry_date)
    if baseline_entry_idx is None or baseline_entry_idx < 2:
        return None

    baseline_signal_idx = baseline_entry_idx - 1
    candidate_df = feature_df.iloc[: baseline_signal_idx + 1].copy()
    flags = build_precross_momentum_flags(
        candidate_df,
        hist_rise_days=hist_rise_days,
        price_rise_days=price_rise_days,
        require_hist_below_zero=True,
        max_hist_abs_norm=max_hist_abs_norm,
        require_above_ema200=require_above_ema200,
        require_peak_at_window_start=require_peak_at_window_start,
    )

    start_idx = max(0, baseline_signal_idx - max(1, int(max_lead_bars)))
    candidates = flags.index[
        (flags["signal"]) & (flags.index >= start_idx) & (flags.index < baseline_signal_idx)
    ]
    if len(candidates) == 0:
        return None

    signal_idx = int(candidates[0] if pick_mode == "earliest" else candidates[-1])
    pre_entry_idx = signal_idx + 1
    if pre_entry_idx >= baseline_entry_idx:
        return None

    pre_signal_row = candidate_df.iloc[signal_idx]
    pre_entry_row = feature_df.iloc[pre_entry_idx]
    baseline_entry_price = _safe_float(entry.get("entry_price"))
    pre_entry_price = _safe_float(pre_entry_row.get("Open"))
    if pd.isna(pre_entry_price) or pre_entry_price <= 0 or pd.isna(baseline_entry_price):
        return None

    latest_flags = flags.iloc[signal_idx]
    lead_return = ((baseline_entry_price / pre_entry_price) - 1.0) * 100.0

    return {
        "entry_key": entry["entry_key"],
        "ticker": entry["ticker"],
        "period": entry.get("period", ""),
        "baseline_signal_date": str(candidate_df.iloc[baseline_signal_idx]["Date"]),
        "baseline_entry_date": baseline_entry_date,
        "baseline_entry_price": baseline_entry_price,
        "baseline_lifecycle_return_pct": _safe_float(entry.get("lifecycle_return_pct")),
        "baseline_lifecycle_return_jpy": _safe_float(entry.get("lifecycle_return_jpy")),
        "baseline_is_bad_r": bool(entry.get("is_bad_r", False)),
        "baseline_final_exit_date": str(entry.get("final_exit_date", "")),
        "baseline_final_exit_urgency": str(entry.get("final_exit_urgency", "")),
        "pre_signal_date": str(pre_signal_row["Date"]),
        "pre_entry_date": str(pre_entry_row["Date"]),
        "pre_entry_price": pre_entry_price,
        "lead_bars": int(baseline_entry_idx - pre_entry_idx),
        "lead_return_to_baseline_entry_pct": lead_return,
        "drawdown_before_baseline_pct": _extreme_return_before_index(
            feature_df,
            pre_entry_idx,
            baseline_entry_idx,
            "Low",
        ),
        "runup_before_baseline_pct": _extreme_return_before_index(
            feature_df,
            pre_entry_idx,
            baseline_entry_idx,
            "High",
        ),
        "pre_fwd_5d_return_pct": _forward_open_return(feature_df, pre_entry_idx, 5),
        "pre_fwd_10d_return_pct": _forward_open_return(feature_df, pre_entry_idx, 10),
        "pre_fwd_20d_return_pct": _forward_open_return(feature_df, pre_entry_idx, 20),
        "pre_hist_abs_norm": _safe_float(latest_flags.get("hist_abs_norm")),
        "pre_above_ema200": bool(latest_flags.get("above_ema200", False)),
        "pre_peak_at_window_start": bool(latest_flags.get("peak_at_window_start", False)),
        "pre_volume_ratio": _safe_float(latest_flags.get("volume_ratio")),
        "pre_macd_hist": _safe_float(pre_signal_row.get("MACD_Hist")),
        "pre_close": _safe_float(pre_signal_row.get("Close")),
        "require_above_ema200": require_above_ema200,
        "max_hist_abs_norm": max_hist_abs_norm,
        "require_peak_at_window_start": require_peak_at_window_start,
    }


def _build_parameter_scan(
    baseline_entries: list[dict[str, Any]],
    data_root: Path,
    hist_rise_days: int,
    price_rise_days: int,
    max_lead_bars: int,
    pick_mode: str,
    require_peak_at_window_start: bool,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    feature_cache: dict[str, pd.DataFrame | None] = {}

    for require_above_ema200 in [False, True]:
        for max_hist_abs_norm in HIST_ABS_NORM_SCAN:
            matched: list[dict[str, Any]] = []
            for entry in baseline_entries:
                feature_df = load_feature_table(data_root, entry["ticker"], feature_cache)
                if feature_df is None:
                    continue
                record = _find_precross_record(
                    entry=entry,
                    feature_df=feature_df,
                    hist_rise_days=hist_rise_days,
                    price_rise_days=price_rise_days,
                    max_lead_bars=max_lead_bars,
                    pick_mode=pick_mode,
                    require_above_ema200=require_above_ema200,
                    max_hist_abs_norm=max_hist_abs_norm,
                    require_peak_at_window_start=require_peak_at_window_start,
                )
                if record is not None:
                    matched.append(record)

            summary = _summarize_records(
                pd.DataFrame(matched),
                baseline_entry_count=len(baseline_entries),
                label="scan_combo",
            )
            summary["require_above_ema200"] = require_above_ema200
            summary["max_hist_abs_norm"] = max_hist_abs_norm
            summary["require_peak_at_window_start"] = require_peak_at_window_start
            rows.append(summary)

    return pd.DataFrame(rows).sort_values(
        ["baseline_bad_r_share", "avg_lead_return_to_baseline_entry_pct", "sample_count"],
        ascending=[True, False, False],
        na_position="last",
    )


def _build_report(
    output_dir: Path,
    overview_df: pd.DataFrame,
    parameter_scan_df: pd.DataFrame,
    matched_df: pd.DataFrame,
    baseline_entries: pd.DataFrame,
    args: argparse.Namespace,
) -> Path:
    top_scan = parameter_scan_df[parameter_scan_df["sample_count"] >= 20].head(8).copy()
    lines = [
        "# MACD Pre-Cross Lead Scan",
        "",
        f"- Source trade CSV: {args.source_csv}",
        f"- Baseline entry: {args.baseline_strategy}",
        f"- Exit strategy: {args.exit_strategy}",
        f"- Core rule: MACD_Hist[t-2] < MACD_Hist[t-1] < MACD_Hist[t] < 0 and Close[t-2] < Close[t-1] < Close[t]",
        f"- Selection mode: {args.pick_mode}",
        f"- Max lead bars before baseline cross: {args.max_lead_bars}",
        f"- Require rising window to start at negative hist peak: {args.require_peak_at_window_start}",
        "",
        "## Overview",
        "",
        _df_to_markdown(overview_df),
        "",
        "## Best helper-parameter scans",
        "",
    ]

    if top_scan.empty:
        lines.append("No parameter scan combination produced at least 20 matched samples.")
    else:
        lines.append(_df_to_markdown(top_scan))

    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"- Baseline entries analyzed: {len(baseline_entries)}",
            f"- Core pre-cross matches: {len(matched_df)}",
            f"- Coverage: {len(matched_df) / len(baseline_entries):.1%}" if len(baseline_entries) else "- Coverage: N/A",
        ]
    )

    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-csv", default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--baseline-strategy", default=DEFAULT_ENTRY_STRATEGY)
    parser.add_argument("--exit-strategy", default=DEFAULT_EXIT_STRATEGY)
    parser.add_argument("--hist-rise-days", type=int, default=3)
    parser.add_argument("--price-rise-days", type=int, default=3)
    parser.add_argument("--max-lead-bars", type=int, default=10)
    parser.add_argument("--pick-mode", choices=["earliest", "latest"], default="earliest")
    parser.add_argument("--require-peak-at-window-start", action="store_true")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_csv = Path(args.source_csv)
    data_root = Path(args.data_root)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / args.output_dir / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_actions = load_trade_actions(
        path=source_csv,
        entry_strategy=args.baseline_strategy,
        exit_strategy=args.exit_strategy,
    )
    baseline_entries = aggregate_entries(baseline_actions)
    baseline_records = baseline_entries.to_dict("records")

    feature_cache: dict[str, pd.DataFrame | None] = {}
    matched_records: list[dict[str, Any]] = []
    for entry in baseline_records:
        feature_df = load_feature_table(data_root, entry["ticker"], feature_cache)
        if feature_df is None:
            continue
        record = _find_precross_record(
            entry=entry,
            feature_df=feature_df,
            hist_rise_days=args.hist_rise_days,
            price_rise_days=args.price_rise_days,
            max_lead_bars=args.max_lead_bars,
            pick_mode=args.pick_mode,
            require_above_ema200=False,
            max_hist_abs_norm=None,
            require_peak_at_window_start=args.require_peak_at_window_start,
        )
        if record is not None:
            matched_records.append(record)

    matched_df = pd.DataFrame(matched_records)
    matched_keys = set(matched_df["entry_key"].tolist()) if not matched_df.empty else set()
    unmatched_df = baseline_entries[~baseline_entries["entry_key"].isin(matched_keys)].copy()

    overview_rows = [
        _summarize_records(matched_df, len(baseline_entries), "matched_core_precross"),
        {
            "label": "unmatched_baseline_trades",
            "sample_count": int(len(unmatched_df)),
            "sample_share_baseline": float(len(unmatched_df) / len(baseline_entries)) if len(baseline_entries) else np.nan,
            "avg_lead_bars": np.nan,
            "median_lead_bars": np.nan,
            "avg_lead_return_to_baseline_entry_pct": np.nan,
            "median_lead_return_to_baseline_entry_pct": np.nan,
            "positive_lead_share": np.nan,
            "avg_drawdown_before_baseline_pct": np.nan,
            "avg_runup_before_baseline_pct": np.nan,
            "avg_baseline_lifecycle_return_pct": float(unmatched_df["lifecycle_return_pct"].mean()) if not unmatched_df.empty else np.nan,
            "baseline_bad_r_share": float(unmatched_df["is_bad_r"].astype(bool).mean()) if not unmatched_df.empty else np.nan,
            "baseline_win_share": float(unmatched_df["lifecycle_return_pct"].gt(0).mean()) if not unmatched_df.empty else np.nan,
            "avg_pre_fwd_5d_return_pct": np.nan,
            "avg_pre_fwd_10d_return_pct": np.nan,
            "avg_pre_fwd_20d_return_pct": np.nan,
        },
    ]
    overview_df = pd.DataFrame(overview_rows)
    parameter_scan_df = _build_parameter_scan(
        baseline_entries=baseline_records,
        data_root=data_root,
        hist_rise_days=args.hist_rise_days,
        price_rise_days=args.price_rise_days,
        max_lead_bars=args.max_lead_bars,
        pick_mode=args.pick_mode,
        require_peak_at_window_start=args.require_peak_at_window_start,
    )

    matched_df.to_csv(output_dir / "matched_entries.csv", index=False, encoding="utf-8-sig")
    overview_df.to_csv(output_dir / "overview.csv", index=False, encoding="utf-8-sig")
    parameter_scan_df.to_csv(output_dir / "parameter_scan.csv", index=False, encoding="utf-8-sig")
    baseline_entries.to_csv(output_dir / "baseline_entries.csv", index=False, encoding="utf-8-sig")

    report_path = _build_report(
        output_dir=output_dir,
        overview_df=overview_df,
        parameter_scan_df=parameter_scan_df,
        matched_df=matched_df,
        baseline_entries=baseline_entries,
        args=args,
    )

    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()