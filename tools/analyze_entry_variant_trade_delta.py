from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_baseline_entry_flag_table import (  # noqa: E402
    aggregate_entries,
    load_trade_actions,
)


DEFAULT_SOURCE_CSV = (
    "strategy_evaluation/macd_entry_variants_v4_cli_20260407/"
    "strategy_evaluation_trades_20260407_121510.csv"
)
DEFAULT_OUTPUT_DIR = "strategy_evaluation/variant_delta_analysis"


def _bool_series(series: pd.Series) -> pd.Series:
    return series.astype("boolean").fillna(False)


def _summarize_entries(df: pd.DataFrame, label: str, prefix: str) -> dict[str, Any]:
    if df.empty:
        return {
            "group": label,
            "entry_count": 0,
            "total_return_jpy": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "bad_r_count": 0,
            "bad_r_share": 0.0,
            "tp1_count": 0,
            "r1_count": 0,
        }
    final_urgency = df[f"final_exit_urgency_{prefix}"].fillna("").astype(str)
    bad_r = _bool_series(df[f"is_bad_r_{prefix}"])
    return {
        "group": label,
        "entry_count": int(len(df)),
        "total_return_jpy": float(df[f"lifecycle_return_jpy_{prefix}"].sum()),
        "avg_return_pct": float(df[f"lifecycle_return_pct_{prefix}"].mean()),
        "median_return_pct": float(df[f"lifecycle_return_pct_{prefix}"].median()),
        "bad_r_count": int(bad_r.sum()),
        "bad_r_share": float(bad_r.mean()),
        "tp1_count": int((final_urgency == "P_TP1").sum()),
        "r1_count": int((final_urgency == "R1_ATRTrailing").sum()),
    }


def _category_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, prefix in [("baseline_only", "baseline"), ("variant_only", "variant")]:
        subset = df[df["category"] == label].copy()
        rows.append(_summarize_entries(subset, label, prefix))

    common = df[df["category"] == "common"].copy()
    if common.empty:
        rows.append(
            {
                "group": "common",
                "entry_count": 0,
                "total_return_jpy": 0.0,
                "avg_return_pct": 0.0,
                "median_return_pct": 0.0,
                "bad_r_count": 0,
                "bad_r_share": 0.0,
                "tp1_count": 0,
                "r1_count": 0,
                "delta_return_jpy": 0.0,
                "shares_increased_count": 0,
                "shares_decreased_count": 0,
                "shares_unchanged_count": 0,
            }
        )
    else:
        share_delta = common["initial_shares_variant"] - common["initial_shares_baseline"]
        rows.append(
            {
                "group": "common",
                "entry_count": int(len(common)),
                "total_return_jpy": float(common["lifecycle_return_jpy_variant"].sum()),
                "avg_return_pct": float(common["lifecycle_return_pct_variant"].mean()),
                "median_return_pct": float(common["lifecycle_return_pct_variant"].median()),
                "bad_r_count": int(_bool_series(common["is_bad_r_variant"]).sum()),
                "bad_r_share": float(_bool_series(common["is_bad_r_variant"]).mean()),
                "tp1_count": int((common["final_exit_urgency_variant"] == "P_TP1").sum()),
                "r1_count": int((common["final_exit_urgency_variant"] == "R1_ATRTrailing").sum()),
                "delta_return_jpy": float(
                    (common["lifecycle_return_jpy_variant"] - common["lifecycle_return_jpy_baseline"]).sum()
                ),
                "shares_increased_count": int((share_delta > 0).sum()),
                "shares_decreased_count": int((share_delta < 0).sum()),
                "shares_unchanged_count": int((share_delta == 0).sum()),
            }
        )

    summary = pd.DataFrame(rows)
    return summary


def _build_period_category_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    periods = sorted(set(df["period_baseline"].dropna().astype(str)).union(set(df["period_variant"].dropna().astype(str))))
    for period in periods:
        period_df = df[
            (df["period_baseline"].astype(str) == period)
            | (df["period_variant"].astype(str) == period)
        ].copy()
        for label, prefix in [("baseline_only", "baseline"), ("variant_only", "variant")]:
            subset = period_df[period_df["category"] == label].copy()
            row = _summarize_entries(subset, label, prefix)
            row["period"] = period
            rows.append(row)

        common = period_df[period_df["category"] == "common"].copy()
        share_delta = common.get("initial_shares_variant", pd.Series(dtype=float)) - common.get(
            "initial_shares_baseline", pd.Series(dtype=float)
        )
        rows.append(
            {
                "period": period,
                "group": "common",
                "entry_count": int(len(common)),
                "total_return_jpy": float(common["lifecycle_return_jpy_variant"].sum()) if not common.empty else 0.0,
                "avg_return_pct": float(common["lifecycle_return_pct_variant"].mean()) if not common.empty else 0.0,
                "median_return_pct": float(common["lifecycle_return_pct_variant"].median()) if not common.empty else 0.0,
                "bad_r_count": int(_bool_series(common["is_bad_r_variant"]).sum()) if not common.empty else 0,
                "bad_r_share": float(_bool_series(common["is_bad_r_variant"]).mean()) if not common.empty else 0.0,
                "tp1_count": int((common["final_exit_urgency_variant"] == "P_TP1").sum()) if not common.empty else 0,
                "r1_count": int((common["final_exit_urgency_variant"] == "R1_ATRTrailing").sum()) if not common.empty else 0,
                "delta_return_jpy": float(
                    (common["lifecycle_return_jpy_variant"] - common["lifecycle_return_jpy_baseline"]).sum()
                ) if not common.empty else 0.0,
                "shares_increased_count": int((share_delta > 0).sum()) if not common.empty else 0,
                "shares_decreased_count": int((share_delta < 0).sum()) if not common.empty else 0,
                "shares_unchanged_count": int((share_delta == 0).sum()) if not common.empty else 0,
            }
        )
    return pd.DataFrame(rows)


def _top_entries(df: pd.DataFrame, category: str, side: str, n: int = 15) -> pd.DataFrame:
    subset = df[df["category"] == category].copy()
    if subset.empty:
        return subset

    prefix = "baseline" if category == "baseline_only" else "variant"
    cols = [
        f"period_{prefix}",
        f"ticker_{prefix}",
        f"entry_date_{prefix}",
        f"final_exit_date_{prefix}",
        f"final_exit_urgency_{prefix}",
        f"final_exit_reason_{prefix}",
        f"initial_shares_{prefix}",
        f"lifecycle_return_pct_{prefix}",
        f"lifecycle_return_jpy_{prefix}",
        f"is_bad_r_{prefix}",
    ]
    subset = subset[cols].copy()
    subset.columns = [
        "period",
        "ticker",
        "entry_date",
        "final_exit_date",
        "final_exit_urgency",
        "final_exit_reason",
        "initial_shares",
        "lifecycle_return_pct",
        "lifecycle_return_jpy",
        "is_bad_r",
    ]
    ascending = side == "worst"
    return subset.sort_values("lifecycle_return_jpy", ascending=ascending).head(n)


def _top_common_delta(df: pd.DataFrame, side: str, n: int = 15) -> pd.DataFrame:
    subset = df[df["category"] == "common"].copy()
    if subset.empty:
        return subset
    subset["delta_return_jpy"] = (
        subset["lifecycle_return_jpy_variant"] - subset["lifecycle_return_jpy_baseline"]
    )
    cols = [
        "period_baseline",
        "ticker_baseline",
        "entry_date_baseline",
        "initial_shares_baseline",
        "initial_shares_variant",
        "lifecycle_return_pct_baseline",
        "lifecycle_return_jpy_baseline",
        "lifecycle_return_jpy_variant",
        "delta_return_jpy",
    ]
    subset = subset[cols].copy()
    subset.columns = [
        "period",
        "ticker",
        "entry_date",
        "initial_shares_baseline",
        "initial_shares_variant",
        "lifecycle_return_pct",
        "baseline_return_jpy",
        "variant_return_jpy",
        "delta_return_jpy",
    ]
    ascending = side == "worst"
    return subset.sort_values("delta_return_jpy", ascending=ascending).head(n)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-csv", default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--baseline-strategy", default="MACDCrossoverStrategy")
    parser.add_argument("--variant-strategy", default="MACDCrossoverFragileBelowZeroFilterV4")
    parser.add_argument("--exit-strategy", default="MVX_N3_R3p25_T1p6_D21_B20p0")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_csv = Path(args.source_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_actions = load_trade_actions(
        path=source_csv,
        entry_strategy=args.baseline_strategy,
        exit_strategy=args.exit_strategy,
    )
    variant_actions = load_trade_actions(
        path=source_csv,
        entry_strategy=args.variant_strategy,
        exit_strategy=args.exit_strategy,
    )

    baseline_entries = aggregate_entries(baseline_actions).add_suffix("_baseline")
    variant_entries = aggregate_entries(variant_actions).add_suffix("_variant")

    merged = baseline_entries.merge(
        variant_entries,
        left_on="entry_key_baseline",
        right_on="entry_key_variant",
        how="outer",
        indicator=True,
    )
    merged["entry_key"] = merged["entry_key_baseline"].fillna(merged["entry_key_variant"])
    merged["category"] = merged["_merge"].map(
        {
            "left_only": "baseline_only",
            "right_only": "variant_only",
            "both": "common",
        }
    )

    category_summary = _category_summary(merged)
    period_category_summary = _build_period_category_summary(merged)
    baseline_only_worst = _top_entries(merged, category="baseline_only", side="worst")
    baseline_only_best = _top_entries(merged, category="baseline_only", side="best")
    variant_only_worst = _top_entries(merged, category="variant_only", side="worst")
    variant_only_best = _top_entries(merged, category="variant_only", side="best")
    common_delta_worst = _top_common_delta(merged, side="worst")
    common_delta_best = _top_common_delta(merged, side="best")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_path = output_dir / f"variant_trade_delta_detail_{ts}.csv"
    category_summary_path = output_dir / f"variant_trade_delta_summary_{ts}.csv"
    period_summary_path = output_dir / f"variant_trade_delta_by_period_{ts}.csv"
    baseline_only_worst_path = output_dir / f"variant_trade_delta_baseline_only_worst_{ts}.csv"
    baseline_only_best_path = output_dir / f"variant_trade_delta_baseline_only_best_{ts}.csv"
    variant_only_worst_path = output_dir / f"variant_trade_delta_variant_only_worst_{ts}.csv"
    variant_only_best_path = output_dir / f"variant_trade_delta_variant_only_best_{ts}.csv"
    common_delta_worst_path = output_dir / f"variant_trade_delta_common_worst_{ts}.csv"
    common_delta_best_path = output_dir / f"variant_trade_delta_common_best_{ts}.csv"
    params_path = output_dir / f"variant_trade_delta_params_{ts}.json"

    merged.to_csv(merged_path, index=False, encoding="utf-8-sig")
    category_summary.to_csv(category_summary_path, index=False, encoding="utf-8-sig")
    period_category_summary.to_csv(period_summary_path, index=False, encoding="utf-8-sig")
    baseline_only_worst.to_csv(baseline_only_worst_path, index=False, encoding="utf-8-sig")
    baseline_only_best.to_csv(baseline_only_best_path, index=False, encoding="utf-8-sig")
    variant_only_worst.to_csv(variant_only_worst_path, index=False, encoding="utf-8-sig")
    variant_only_best.to_csv(variant_only_best_path, index=False, encoding="utf-8-sig")
    common_delta_worst.to_csv(common_delta_worst_path, index=False, encoding="utf-8-sig")
    common_delta_best.to_csv(common_delta_best_path, index=False, encoding="utf-8-sig")
    params_path.write_text(
        json.dumps(
            {
                "source_csv": str(source_csv),
                "baseline_strategy": args.baseline_strategy,
                "variant_strategy": args.variant_strategy,
                "exit_strategy": args.exit_strategy,
                "baseline_entry_count": int(len(baseline_entries)),
                "variant_entry_count": int(len(variant_entries)),
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(category_summary_path)
    print(period_summary_path)
    print(baseline_only_worst_path)
    print(baseline_only_best_path)
    print(variant_only_worst_path)
    print(variant_only_best_path)
    print(common_delta_worst_path)
    print(common_delta_best_path)
    print(params_path)


if __name__ == "__main__":
    main()