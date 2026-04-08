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

from tools.generate_baseline_entry_flag_table import load_feature_table  # noqa: E402


DEFAULT_SOURCE_CSV = (
    "strategy_evaluation/macd_precross_entry_5y_20260408_112141/trades.csv"
)
DEFAULT_OUTPUT_DIR = "strategy_evaluation/precross2bar_helper_scan"
DEFAULT_STRATEGY_LABEL = "PreCross2Bar"
DEFAULT_DATA_ROOT = "data"


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


def _load_actions(path: Path, strategy_label: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    df = df[df["strategy_label"] == strategy_label].copy()
    df["ticker"] = df["ticker"].astype(str).str.strip()
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)
    return df


def _aggregate_entries(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, group in df.groupby("entry_key", sort=False):
        ordered = group.sort_values(["exit_date", "holding_days"], ascending=[True, True]).reset_index(drop=True)
        first = ordered.iloc[0]
        final_row = ordered.iloc[-1]
        initial_shares = int(pd.to_numeric(ordered["shares"], errors="coerce").fillna(0).sum())
        entry_price = _safe_float(first.get("entry_price"))
        total_return_jpy = float(pd.to_numeric(ordered["return_jpy"], errors="coerce").fillna(0).sum())
        lifecycle_return_pct = np.nan
        if pd.notna(entry_price) and entry_price > 0 and initial_shares > 0:
            lifecycle_return_pct = (total_return_jpy / (entry_price * initial_shares)) * 100.0
        final_urgencies = ordered["exit_urgency"].fillna("").astype(str)
        had_r_exit = final_urgencies.str.startswith("R").any()
        is_bad_r = bool(had_r_exit and total_return_jpy < 0)
        rows.append(
            {
                "entry_key": first["entry_key"],
                "ticker": first["ticker"],
                "entry_date": first["entry_date"],
                "entry_price": entry_price,
                "initial_shares": initial_shares,
                "action_count": int(len(ordered)),
                "final_exit_date": final_row["exit_date"],
                "final_exit_urgency": final_row["exit_urgency"],
                "final_exit_reason": final_row["exit_reason"],
                "lifecycle_return_jpy": total_return_jpy,
                "lifecycle_return_pct": lifecycle_return_pct,
                "is_bad_r": is_bad_r,
            }
        )
    return pd.DataFrame(rows)


def _find_signal_row(feature_df: pd.DataFrame, entry_date: str) -> pd.Series | None:
    matches = feature_df.index[feature_df["Date"] == str(entry_date)]
    if len(matches) == 0:
        return None
    entry_idx = int(matches[0])
    if entry_idx < 1:
        return None
    return feature_df.iloc[entry_idx - 1]


def _enrich_entries(entries: pd.DataFrame, data_root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cache: dict[str, pd.DataFrame | None] = {}
    for entry in entries.to_dict("records"):
        feature_df = load_feature_table(data_root, entry["ticker"], cache)
        if feature_df is None:
            continue
        signal_row = _find_signal_row(feature_df, entry["entry_date"])
        if signal_row is None:
            continue

        close = _safe_float(signal_row.get("Close"))
        ema20 = _safe_float(signal_row.get("EMA_20"))
        ema200 = _safe_float(signal_row.get("EMA_200"))
        macd_hist = _safe_float(signal_row.get("MACD_Hist"))
        volume = _safe_float(signal_row.get("Volume"))
        volume_sma_20 = _safe_float(signal_row.get("Volume_SMA_20"))

        rows.append(
            {
                **entry,
                "signal_date": str(signal_row.get("Date")),
                "entry_bb_pctb": _safe_float(signal_row.get("BB_PctB")),
                "entry_return_5d": _safe_float(signal_row.get("Return_5d")),
                "entry_return_20d": _safe_float(signal_row.get("Return_20d")),
                "entry_adx_14": _safe_float(signal_row.get("ADX_14")),
                "hist_abs_norm": (abs(macd_hist) / close) if pd.notna(macd_hist) and pd.notna(close) and close > 0 else np.nan,
                "gap_above_ema20_pct": ((close / ema20) - 1.0) * 100.0 if pd.notna(close) and pd.notna(ema20) and ema20 > 0 else np.nan,
                "above_ema200": bool(pd.notna(close) and pd.notna(ema200) and close > ema200),
                "entry_volume_ratio": (volume / volume_sma_20) if pd.notna(volume) and pd.notna(volume_sma_20) and volume_sma_20 > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _summary(df: pd.DataFrame, label: str) -> dict[str, Any]:
    if df.empty:
        return {
            "label": label,
            "entry_count": 0,
            "entry_share": 0.0,
            "avg_return_pct": np.nan,
            "median_return_pct": np.nan,
            "total_return_jpy": 0.0,
            "bad_r_share": np.nan,
            "win_share": np.nan,
        }
    return {
        "label": label,
        "entry_count": int(len(df)),
        "entry_share": np.nan,
        "avg_return_pct": float(df["lifecycle_return_pct"].mean()),
        "median_return_pct": float(df["lifecycle_return_pct"].median()),
        "total_return_jpy": float(df["lifecycle_return_jpy"].sum()),
        "bad_r_share": float(df["is_bad_r"].astype(bool).mean()),
        "win_share": float(df["lifecycle_return_pct"].gt(0).mean()),
    }


def _scan_threshold(df: pd.DataFrame, feature: str, operator: str, thresholds: list[float]) -> pd.DataFrame:
    base_count = len(df)
    base_total_return = float(df["lifecycle_return_jpy"].sum()) if not df.empty else 0.0
    rows: list[dict[str, Any]] = []
    for value in thresholds:
        if operator == "<=":
            kept = df[df[feature] <= value].copy()
        elif operator == ">=":
            kept = df[df[feature] >= value].copy()
        else:
            raise ValueError(f"Unsupported operator: {operator}")

        row = _summary(kept, f"{feature} {operator} {value}")
        row["feature"] = feature
        row["operator"] = operator
        row["threshold"] = value
        row["entry_share"] = float(len(kept) / base_count) if base_count else np.nan
        row["return_share_vs_base"] = float(row["total_return_jpy"] / base_total_return) if base_total_return else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _scan_boolean(df: pd.DataFrame, feature: str, keep_value: bool) -> pd.DataFrame:
    kept = df[df[feature].fillna(False).astype(bool) == bool(keep_value)].copy()
    row = _summary(kept, f"{feature} == {keep_value}")
    row["feature"] = feature
    row["operator"] = "=="
    row["threshold"] = keep_value
    row["entry_share"] = float(len(kept) / len(df)) if len(df) else np.nan
    row["return_share_vs_base"] = float(row["total_return_jpy"] / float(df["lifecycle_return_jpy"].sum())) if len(df) and float(df["lifecycle_return_jpy"].sum()) else np.nan
    return pd.DataFrame([row])


def _build_report(output_dir: Path, base_df: pd.DataFrame, scan_df: pd.DataFrame, best_df: pd.DataFrame, args: argparse.Namespace) -> Path:
    lines = [
        "# PreCross2Bar Helper Filter Scan",
        "",
        f"- Source trades: {args.source_csv}",
        f"- Strategy label: {args.strategy_label}",
        "- Goal: test lightweight one-dimensional helper conditions on top of PreCross2Bar.",
        "",
        "## Base summary",
        "",
        _df_to_markdown(base_df),
        "",
        "## Best retained-subset scans",
        "",
        _df_to_markdown(best_df),
        "",
        "## Full scan saved",
        "",
        f"- {output_dir / 'helper_scan.csv'}",
        f"- {output_dir / 'entry_feature_table.csv'}",
    ]
    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-csv", default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--strategy-label", default=DEFAULT_STRATEGY_LABEL)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = ROOT / args.output_dir / ts
    output_dir.mkdir(parents=True, exist_ok=True)

    actions = _load_actions(Path(args.source_csv), args.strategy_label)
    entries = _aggregate_entries(actions)
    enriched = _enrich_entries(entries, Path(args.data_root))

    base_df = pd.DataFrame([_summary(enriched, "PreCross2Bar")])
    base_df["entry_share"] = 1.0
    base_df["return_share_vs_base"] = 1.0

    scan_frames = [
        _scan_threshold(enriched, "hist_abs_norm", "<=", [0.004, 0.006, 0.008, 0.010, 0.012]),
        _scan_threshold(enriched, "gap_above_ema20_pct", "<=", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
        _scan_threshold(enriched, "entry_return_5d", "<=", [0.02, 0.04, 0.06, 0.08, 0.10]),
        _scan_threshold(enriched, "entry_return_20d", "<=", [0.04, 0.06, 0.08, 0.10, 0.15, 0.20]),
        _scan_threshold(enriched, "entry_bb_pctb", "<=", [0.75, 0.80, 0.85, 0.90, 0.95]),
        _scan_threshold(enriched, "entry_volume_ratio", ">=", [0.8, 0.9, 1.0, 1.1, 1.2]),
        _scan_threshold(enriched, "entry_adx_14", ">=", [10.0, 15.0, 20.0, 25.0]),
        _scan_boolean(enriched, "above_ema200", True),
    ]
    scan_df = pd.concat(scan_frames, ignore_index=True)
    best_df = scan_df[
        (scan_df["entry_share"] >= 0.55) & (scan_df["return_share_vs_base"] >= 0.75)
    ].sort_values(
        ["avg_return_pct", "bad_r_share", "entry_share"],
        ascending=[False, True, False],
    ).head(15)

    enriched.to_csv(output_dir / "entry_feature_table.csv", index=False, encoding="utf-8-sig")
    scan_df.to_csv(output_dir / "helper_scan.csv", index=False, encoding="utf-8-sig")
    base_df.to_csv(output_dir / "base_summary.csv", index=False, encoding="utf-8-sig")
    report_path = _build_report(output_dir, base_df, scan_df, best_df, args)

    print(output_dir)
    print(report_path)


if __name__ == "__main__":
    main()