from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.generate_baseline_entry_flag_table import (  # noqa: E402
    DEFAULT_DATA_ROOT,
    DEFAULT_ENTRY_STRATEGY,
    DEFAULT_EXIT_STRATEGY,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SEGMENT_CSV,
    DEFAULT_SOURCE_CSV,
    aggregate_entries,
    build_flag_table,
    load_segment_lookup,
    load_trade_actions,
)


FOCUSED_FAMILY_ORDER = [
    "fragile_below_zero_cross",
    "deep_below_zero_axis",
    "flat_ema20",
    "weak_positive_hist",
    "both_below_zero_axis",
    "low_adx",
]


def _validate_scan_levels(levels: int) -> int:
    if levels < 5 or levels % 2 == 0:
        raise ValueError("scan_levels must be an odd integer >= 5")
    return levels


def _build_scan_points(
    base: float,
    legacy_step: float,
    levels: int,
    min_value: float = 0.0,
) -> list[tuple[str, int, float]]:
    half = levels // 2
    step = (legacy_step * 2.0) / half
    points: list[tuple[str, int, float]] = []
    for offset in range(-half, half + 1):
        label = "base" if offset == 0 else f"offset_{offset:+d}"
        value = max(base + (offset * step), min_value)
        points.append((label, offset, value))
    return points


def _summarize_mask(mask: pd.Series, bad_r_mask: pd.Series) -> dict[str, Any]:
    mask_bool = mask.fillna(False).astype(bool)
    total_bad_r = int(bad_r_mask.sum())
    total_non_bad_r = int((~bad_r_mask).sum())
    bad_true = int((mask_bool & bad_r_mask).sum())
    non_bad_true = int((mask_bool & ~bad_r_mask).sum())
    total_true = bad_true + non_bad_true
    bad_rate = bad_true / total_bad_r if total_bad_r else 0.0
    non_bad_rate = non_bad_true / total_non_bad_r if total_non_bad_r else 0.0
    if non_bad_rate == 0.0:
        lift = np.inf if bad_rate > 0 else np.nan
    else:
        lift = bad_rate / non_bad_rate
    precision = bad_true / total_true if total_true else 0.0
    true_share = total_true / len(mask_bool) if len(mask_bool) else 0.0
    return {
        "bad_r_true_count": bad_true,
        "bad_r_total": total_bad_r,
        "bad_r_hit_rate": bad_rate,
        "non_bad_r_true_count": non_bad_true,
        "non_bad_r_total": total_non_bad_r,
        "non_bad_r_hit_rate": non_bad_rate,
        "total_true_count": total_true,
        "true_share": true_share,
        "precision_when_true": precision,
        "bad_r_lift": lift,
    }


def _scan_single_threshold_family(
    df: pd.DataFrame,
    bad_r_mask: pd.Series,
    family: str,
    column: str,
    operator: str,
    base: float,
    legacy_step: float,
    levels: int,
    base_mask: pd.Series | None = None,
    threshold_text_template: str | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label, offset, value in _build_scan_points(base, legacy_step, levels):
        if operator == "<":
            mask = df[column] < value
        elif operator == ">":
            mask = df[column] > value
        else:
            raise ValueError(f"Unsupported operator: {operator}")
        if base_mask is not None:
            mask = base_mask.fillna(False).astype(bool) & mask.fillna(False)
        summary = _summarize_mask(mask=mask, bad_r_mask=bad_r_mask)
        rows.append(
            {
                "family": family,
                "variant_label": label,
                "variant_offset": offset,
                "parameter_count": 1,
                "operator": operator,
                "threshold_value": value,
                "threshold_text": (
                    threshold_text_template.format(value=value)
                    if threshold_text_template is not None
                    else f"{column} {operator} {value}"
                ),
                **summary,
            }
        )
    return pd.DataFrame(rows)


def _scan_fragile_family(
    df: pd.DataFrame,
    bad_r_mask: pd.Series,
    levels: int,
    flat_base: float,
    weak_base: float,
    deep_prev_base: float,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    below_zero_mask = df["both_below_zero_axis"].fillna(False).astype(bool)
    flat_points = _build_scan_points(flat_base, legacy_step=0.05, levels=levels, min_value=0.0)
    weak_points = _build_scan_points(weak_base, legacy_step=0.0002, levels=levels, min_value=0.0)
    deep_prev_points = _build_scan_points(deep_prev_base, legacy_step=0.0002, levels=levels, min_value=0.0)

    for flat_label, flat_offset, flat_value in flat_points:
        for weak_label, weak_offset, weak_value in weak_points:
            for deep_label, deep_offset, deep_value in deep_prev_points:
                mask = (
                    below_zero_mask
                    & (df["ema20_slope_pct"] < flat_value)
                    & (df["hist_now_norm"] < weak_value)
                    & (df["hist_prev_norm"] > deep_value)
                )
                summary = _summarize_mask(mask=mask, bad_r_mask=bad_r_mask)
                rows.append(
                    {
                        "family": "fragile_below_zero_cross",
                        "variant_label": (
                            f"flat:{flat_label}|weak:{weak_label}|deep:{deep_label}"
                        ),
                        "variant_offset": f"{flat_offset}/{weak_offset}/{deep_offset}",
                        "parameter_count": 3,
                        "operator": "mixed",
                        "flat_ema20_slope_pct": flat_value,
                        "weak_positive_hist_norm": weak_value,
                        "deep_negative_prev_hist_norm": deep_value,
                        "threshold_text": (
                            "both_below_zero_axis & "
                            f"ema20_slope_pct<{flat_value:.4f} & "
                            f"hist_now_norm<{weak_value:.6f} & "
                            f"hist_prev_norm>{deep_value:.6f}"
                        ),
                        **summary,
                    }
                )
    return pd.DataFrame(rows)


def _scan_fixed_family(df: pd.DataFrame, bad_r_mask: pd.Series) -> pd.DataFrame:
    mask = df["both_below_zero_axis"].fillna(False).astype(bool)
    summary = _summarize_mask(mask=mask, bad_r_mask=bad_r_mask)
    return pd.DataFrame(
        [
            {
                "family": "both_below_zero_axis",
                "variant_label": "fixed",
                "variant_offset": 0,
                "parameter_count": 0,
                "operator": "fixed",
                "threshold_text": "both_below_zero_axis",
                **summary,
            }
        ]
    )


def build_focused_parameter_scan(
    df: pd.DataFrame,
    levels: int,
    thresholds: dict[str, float],
) -> pd.DataFrame:
    bad_r_mask = df["is_bad_r"].fillna(False)
    below_zero_mask = df["both_below_zero_axis"].fillna(False).astype(bool)

    frames = [
        _scan_fragile_family(
            df=df,
            bad_r_mask=bad_r_mask,
            levels=levels,
            flat_base=thresholds["flat_ema20_slope_pct"],
            weak_base=thresholds["weak_positive_hist_norm"],
            deep_prev_base=thresholds["deep_negative_prev_hist_norm"],
        ),
        _scan_single_threshold_family(
            df=df,
            bad_r_mask=bad_r_mask,
            family="deep_below_zero_axis",
            column="zero_axis_depth_norm",
            operator=">",
            base=thresholds["deep_below_zero_axis_norm"],
            legacy_step=0.0005,
            levels=levels,
            base_mask=below_zero_mask,
            threshold_text_template="both_below_zero_axis & zero_axis_depth_norm>{value:.6f}",
        ),
        _scan_single_threshold_family(
            df=df,
            bad_r_mask=bad_r_mask,
            family="flat_ema20",
            column="ema20_slope_pct",
            operator="<",
            base=thresholds["flat_ema20_slope_pct"],
            legacy_step=0.05,
            levels=levels,
            threshold_text_template="ema20_slope_pct<{value:.4f}",
        ),
        _scan_single_threshold_family(
            df=df,
            bad_r_mask=bad_r_mask,
            family="weak_positive_hist",
            column="hist_now_norm",
            operator="<",
            base=thresholds["weak_positive_hist_norm"],
            legacy_step=0.0002,
            levels=levels,
            threshold_text_template="hist_now_norm<{value:.6f}",
        ),
        _scan_fixed_family(df=df, bad_r_mask=bad_r_mask),
        _scan_single_threshold_family(
            df=df,
            bad_r_mask=bad_r_mask,
            family="low_adx",
            column="entry_adx_14",
            operator="<",
            base=thresholds["low_adx"],
            legacy_step=5.0,
            levels=levels,
            threshold_text_template="entry_adx_14<{value:.2f}",
        ),
    ]
    scan_df = pd.concat(frames, ignore_index=True)
    scan_df["family_order"] = scan_df["family"].map(
        {name: idx for idx, name in enumerate(FOCUSED_FAMILY_ORDER)}
    )
    return scan_df.sort_values(
        ["family_order", "bad_r_lift", "precision_when_true", "total_true_count"],
        ascending=[True, False, False, False],
    ).drop(columns=["family_order"])


def _pick_best_row(df: pd.DataFrame) -> pd.Series:
    sortable = df.copy()
    sortable["_lift_sort"] = sortable["bad_r_lift"].replace(np.nan, -np.inf)
    sortable = sortable.sort_values(
        ["_lift_sort", "precision_when_true", "total_true_count", "bad_r_true_count"],
        ascending=[False, False, False, False],
    )
    return sortable.iloc[0]


def build_family_selection_summary(
    scan_df: pd.DataFrame,
    combo_min_true: int,
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    selected: dict[str, dict[str, Any]] = {}

    for family in FOCUSED_FAMILY_ORDER:
        group = scan_df[scan_df["family"] == family].copy()
        if group.empty:
            continue
        best_row = _pick_best_row(group)
        if family == "both_below_zero_axis":
            combo_row = best_row
            selection_method = "fixed"
        else:
            eligible = group[group["total_true_count"] >= combo_min_true].copy()
            if eligible.empty:
                combo_row = best_row
                selection_method = "fallback_all_rows"
            else:
                combo_row = _pick_best_row(eligible)
                selection_method = f"min_total_true_{combo_min_true}"
        selected[family] = combo_row.to_dict()
        rows.append(
            {
                "family": family,
                "best_variant_label": best_row["variant_label"],
                "best_threshold_text": best_row["threshold_text"],
                "best_bad_r_lift": best_row["bad_r_lift"],
                "best_precision_when_true": best_row["precision_when_true"],
                "best_total_true_count": int(best_row["total_true_count"]),
                "best_bad_r_true_count": int(best_row["bad_r_true_count"]),
                "combo_variant_label": combo_row["variant_label"],
                "combo_threshold_text": combo_row["threshold_text"],
                "combo_bad_r_lift": combo_row["bad_r_lift"],
                "combo_precision_when_true": combo_row["precision_when_true"],
                "combo_total_true_count": int(combo_row["total_true_count"]),
                "combo_bad_r_true_count": int(combo_row["bad_r_true_count"]),
                "combo_selection_method": selection_method,
                "combo_flat_ema20_slope_pct": combo_row.get("flat_ema20_slope_pct", np.nan),
                "combo_weak_positive_hist_norm": combo_row.get("weak_positive_hist_norm", np.nan),
                "combo_deep_negative_prev_hist_norm": combo_row.get("deep_negative_prev_hist_norm", np.nan),
                "combo_threshold_value": combo_row.get("threshold_value", np.nan),
            }
        )

    selection_df = pd.DataFrame(rows)
    selection_df["family_order"] = selection_df["family"].map(
        {name: idx for idx, name in enumerate(FOCUSED_FAMILY_ORDER)}
    )
    selection_df = selection_df.sort_values("family_order").drop(columns=["family_order"])
    return selection_df, selected


def _materialize_selected_masks(
    df: pd.DataFrame,
    selected: dict[str, dict[str, Any]],
) -> tuple[dict[str, pd.Series], dict[str, str]]:
    masks: dict[str, pd.Series] = {}
    threshold_text: dict[str, str] = {}
    below_zero_mask = df["both_below_zero_axis"].fillna(False).astype(bool)

    for family in FOCUSED_FAMILY_ORDER:
        row = selected[family]
        threshold_text[family] = str(row["threshold_text"])
        if family == "both_below_zero_axis":
            masks[family] = below_zero_mask
        elif family == "flat_ema20":
            masks[family] = (df["ema20_slope_pct"] < float(row["threshold_value"])).fillna(False)
        elif family == "weak_positive_hist":
            masks[family] = (df["hist_now_norm"] < float(row["threshold_value"])).fillna(False)
        elif family == "low_adx":
            masks[family] = (df["entry_adx_14"] < float(row["threshold_value"])).fillna(False)
        elif family == "deep_below_zero_axis":
            masks[family] = (
                below_zero_mask
                & (df["zero_axis_depth_norm"] > float(row["threshold_value"])).fillna(False)
            )
        elif family == "fragile_below_zero_cross":
            masks[family] = (
                below_zero_mask
                & (df["ema20_slope_pct"] < float(row["flat_ema20_slope_pct"])).fillna(False)
                & (df["hist_now_norm"] < float(row["weak_positive_hist_norm"])).fillna(False)
                & (df["hist_prev_norm"] > float(row["deep_negative_prev_hist_norm"])).fillna(False)
            )
        else:
            raise ValueError(f"Unsupported family: {family}")

    return masks, threshold_text


def build_combination_scan(
    df: pd.DataFrame,
    selected: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    bad_r_mask = df["is_bad_r"].fillna(False)
    masks, threshold_text = _materialize_selected_masks(df=df, selected=selected)
    rows: list[dict[str, Any]] = []

    for size in range(1, len(FOCUSED_FAMILY_ORDER) + 1):
        for combo in combinations(FOCUSED_FAMILY_ORDER, size):
            combo_mask = pd.Series(True, index=df.index)
            for family in combo:
                combo_mask = combo_mask & masks[family]
            summary = _summarize_mask(mask=combo_mask, bad_r_mask=bad_r_mask)
            rows.append(
                {
                    "combination_size": size,
                    "combination_flags": " & ".join(combo),
                    "combination_thresholds_json": json.dumps(
                        {family: threshold_text[family] for family in combo},
                        ensure_ascii=True,
                        sort_keys=True,
                    ),
                    **summary,
                }
            )

    combo_df = pd.DataFrame(rows)
    return combo_df.sort_values(
        ["bad_r_lift", "precision_when_true", "total_true_count", "combination_size"],
        ascending=[False, False, False, True],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-csv", default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--segment-csv", default=DEFAULT_SEGMENT_CSV)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--entry-strategy", default=DEFAULT_ENTRY_STRATEGY)
    parser.add_argument("--exit-strategy", default=DEFAULT_EXIT_STRATEGY)
    parser.add_argument("--scan-levels", type=int, default=9)
    parser.add_argument("--combo-min-true", type=int, default=10)
    parser.add_argument("--flat-ema20-slope-pct", type=float, default=0.25)
    parser.add_argument("--weak-positive-hist-norm", type=float, default=0.0008)
    parser.add_argument("--deep-negative-prev-hist-norm", type=float, default=0.0010)
    parser.add_argument("--low-adx", type=float, default=20.0)
    parser.add_argument("--deep-below-zero-axis-norm", type=float, default=0.0015)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scan_levels = _validate_scan_levels(int(args.scan_levels))

    source_csv = Path(args.source_csv)
    segment_csv = Path(args.segment_csv)
    data_root = Path(args.data_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    thresholds = {
        "flat_ema20_slope_pct": float(args.flat_ema20_slope_pct),
        "weak_positive_hist_norm": float(args.weak_positive_hist_norm),
        "deep_negative_prev_hist_norm": float(args.deep_negative_prev_hist_norm),
        "low_adx": float(args.low_adx),
        "deep_below_zero_axis_norm": float(args.deep_below_zero_axis_norm),
    }

    actions = load_trade_actions(
        path=source_csv,
        entry_strategy=args.entry_strategy,
        exit_strategy=args.exit_strategy,
    )
    entries = aggregate_entries(actions)
    segment_lookup = load_segment_lookup(segment_csv)
    entries = entries.merge(segment_lookup, on=["ticker", "entry_date"], how="left")

    flag_table = build_flag_table(
        entries=entries,
        data_root=data_root,
        thresholds={
            "shock_hist_jump_norm": 0.0050,
            "overheat_bb_pctb": 0.94,
            "overheat_gap_above_ema20_pct": 5.0,
            "overheat_return_20d": 0.05,
            "high_bb_pctb": 0.90,
            "far_above_ema20_pct": 4.0,
            "flat_ema20_slope_pct": thresholds["flat_ema20_slope_pct"],
            "weak_positive_hist_norm": thresholds["weak_positive_hist_norm"],
            "deep_negative_prev_hist_norm": thresholds["deep_negative_prev_hist_norm"],
            "weak_trend_strength_200": 0.02,
            "weak_volume_ratio": 1.1,
            "low_adx": thresholds["low_adx"],
            "deep_below_zero_axis_norm": thresholds["deep_below_zero_axis_norm"],
            "weak_hist_recovery_ratio": 0.8,
            "short_term_pop_return_5d": 0.05,
            "short_term_pop_max_ema20_slope_pct": 0.25,
            "early_peak_high_max_bars": 2.0,
            "short_segment_total_max_bars": 8.0,
            "fast_macd_hist_turn_max_bars": 2.0,
            "death_return_nonpositive_pct": 0.0,
            "no_high_lag_vs_hist_peak_max_bars": 0.0,
        },
    )

    param_scan_df = build_focused_parameter_scan(
        df=flag_table,
        levels=scan_levels,
        thresholds=thresholds,
    )
    selection_df, selected = build_family_selection_summary(
        scan_df=param_scan_df,
        combo_min_true=int(args.combo_min_true),
    )
    combo_df = build_combination_scan(df=flag_table, selected=selected)
    combo_filtered_df = combo_df[combo_df["total_true_count"] >= int(args.combo_min_true)].copy()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    param_scan_path = output_dir / f"focused_tradable_flag_param_scan_{ts}.csv"
    selection_path = output_dir / f"focused_tradable_flag_param_best_{ts}.csv"
    combo_path = output_dir / f"focused_tradable_flag_combo_scan_{ts}.csv"
    combo_filtered_path = output_dir / f"focused_tradable_flag_combo_scan_min_true_{ts}.csv"
    params_path = output_dir / f"focused_tradable_flag_scan_params_{ts}.json"

    param_scan_df.to_csv(param_scan_path, index=False, encoding="utf-8-sig")
    selection_df.to_csv(selection_path, index=False, encoding="utf-8-sig")
    combo_df.to_csv(combo_path, index=False, encoding="utf-8-sig")
    combo_filtered_df.to_csv(combo_filtered_path, index=False, encoding="utf-8-sig")
    params_path.write_text(
        json.dumps(
            {
                "source_csv": str(source_csv),
                "entry_strategy": args.entry_strategy,
                "exit_strategy": args.exit_strategy,
                "scan_levels": scan_levels,
                "combo_min_true": int(args.combo_min_true),
                "threshold_bases": thresholds,
                "rows": int(len(flag_table)),
                "focused_families": FOCUSED_FAMILY_ORDER,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(param_scan_path)
    print(selection_path)
    print(combo_path)
    print(combo_filtered_path)
    print(params_path)


if __name__ == "__main__":
    main()