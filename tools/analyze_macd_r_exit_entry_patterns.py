from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


DEFAULT_TRADES_CSV = (
    "strategy_evaluation/mvxnew_1x2/strategy_evaluation_trades_20260406_184942.csv"
)
DEFAULT_SEGMENT_CSV = "strategy_evaluation/macd_segment_raw_20260406_112854.csv"
DEFAULT_JPX_CSV = "data/jpx_final_list.csv"
DEFAULT_DATA_ROOT = "data"
DEFAULT_EXIT_STRATEGY = "MVX_N3_R3p25_T1p6_D21_B20p0"
DEFAULT_OUTPUT_DIR = "strategy_evaluation/entry_risk_analysis"

R_EXIT_URGENCY = "R1_ATRTrailing"

ENTRY_JSON_FIELDS = {
    "macd": "entry_macd",
    "macd_hist": "entry_macd_hist",
    "macd_hist_prev": "entry_macd_hist_prev",
    "macd_signal": "entry_macd_signal",
}

EXIT_JSON_FIELDS = {
    "r_value": "exit_r_value",
    "pnl_pct": "exit_pnl_pct",
    "trigger": "exit_trigger",
    "sell_percentage": "exit_sell_pct_from_metadata",
    "exit_confirm_streak": "exit_confirm_streak",
}

NUMERIC_PROFILE_COLUMNS = [
    "return_pct",
    "holding_days",
    "entry_confidence",
    "entry_rsi",
    "entry_atr_ratio",
    "entry_return_5d",
    "entry_return_20d",
    "entry_macd_hist_prev",
    "entry_macd_hist_jump",
    "entry_macd_hist_jump_ratio",
    "entry_gap_ema20_pct",
    "entry_gap_sma20_pct",
    "entry_gap_ema200_pct",
    "entry_volume_ratio",
    "entry_bb_pctb",
    "entry_bb_width",
    "entry_adx_14",
    "entry_trend_strength_200",
    "entry_macd_hist",
    "entry_macd_gap",
    "entry_macd",
    "exit_r_value",
    "segment_signal_bars",
    "segment_total_bars",
    "peak_high_offset_bars",
    "peak_close_offset_bars",
    "macd_peak_offset_bars",
    "macd_hist_peak_offset_bars",
    "macd_turn_return_pct",
    "macd_hist_turn_return_pct",
    "death_return_pct",
    "lag_high_vs_macd_peak_bars",
    "lag_high_vs_macd_hist_peak_bars",
    "lag_high_vs_macd_turn_bars",
    "lag_high_vs_macd_hist_turn_bars",
]

SEGMENT_COLUMNS = [
    "ticker",
    "golden_cross_date",
    "entry_date",
    "segment_signal_bars",
    "segment_total_bars",
    "peak_high_offset_bars",
    "peak_close_offset_bars",
    "macd_peak_offset_bars",
    "macd_hist_peak_offset_bars",
    "macd_turn_return_pct",
    "macd_hist_turn_return_pct",
    "death_return_pct",
    "lag_high_vs_macd_peak_bars",
    "lag_high_vs_macd_hist_peak_bars",
    "lag_high_vs_macd_turn_bars",
    "lag_high_vs_macd_hist_turn_bars",
]

FEATURE_SNAPSHOT_COLUMNS = [
    "Date",
    "Close",
    "Volume",
    "Volume_SMA_20",
    "EMA_20",
    "EMA_200",
    "SMA_20",
    "RSI",
    "ATR_Ratio",
    "Return_5d",
    "Return_20d",
    "TrendStrength_200",
    "BB_PctB",
    "BB_Width",
    "ADX_14",
]


def normalize_code(value: object) -> Optional[str]:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def parse_json_text(text: object) -> dict:
    if pd.isna(text) or text in (None, ""):
        return {}
    try:
        value = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def safe_float(value: object) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def add_json_fields(df: pd.DataFrame, source_col: str, field_map: dict[str, str]) -> None:
    parsed = df[source_col].apply(parse_json_text)
    for json_key, target_col in field_map.items():
        df[target_col] = parsed.apply(lambda item: safe_float(item.get(json_key)) if json_key != "trigger" else item.get(json_key))


def add_hold_buckets(df: pd.DataFrame) -> None:
    bins = [-1, 3, 7, 12, 20, 9999]
    labels = ["0_3", "4_7", "8_12", "13_20", "21_plus"]
    df["holding_bucket"] = pd.cut(df["holding_days"], bins=bins, labels=labels)
    df["entry_month"] = df["entry_date"].astype(str).str.slice(5, 7)


def classify_stage1(df: pd.DataFrame) -> None:
    is_r = df["exit_urgency"] == R_EXIT_URGENCY
    is_positive = df["return_pct"] > 0
    df["stage1_group"] = "non_r"
    df.loc[is_r & is_positive, "stage1_group"] = "good_r"
    df.loc[is_r & ~is_positive, "stage1_group"] = "bad_r"


def classify_stage2(df: pd.DataFrame) -> pd.DataFrame:
    stage2 = df[df["stage1_group"] == "non_r"].copy()
    stage2["stage2_group"] = "negative_non_r"
    stage2.loc[stage2["return_pct"] > 0, "stage2_group"] = "positive_non_r"
    return stage2


def load_sector_lookup(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"Code": str}, encoding="utf-8-sig")
    df = df.rename(
        columns={
            "Code": "ticker",
            "銘柄名": "company_name",
            "市場・商品区分": "market_category",
            "33業種区分": "sector_33",
            "規模区分": "size_category",
        }
    )
    cols = ["ticker", "company_name", "market_category", "sector_33", "size_category"]
    df = df[cols].copy()
    df["ticker"] = df["ticker"].map(normalize_code)
    return df.dropna(subset=["ticker"]).drop_duplicates(subset=["ticker"])


def load_segment_lookup(path: Path) -> tuple[pd.DataFrame, int]:
    df = pd.read_csv(path, dtype={"ticker": str})
    df["ticker"] = df["ticker"].map(normalize_code)
    df["entry_date"] = df["entry_date"].astype(str)
    duplicate_count = int(df.duplicated(subset=["ticker", "entry_date"]).sum())
    df = df[SEGMENT_COLUMNS].copy()
    df = df.drop_duplicates(subset=["ticker", "entry_date"], keep="first")
    return df, duplicate_count


def load_feature_snapshots(data_root: Path, tickers: Iterable[str]) -> tuple[pd.DataFrame, int]:
    features_dir = data_root / "features"
    snapshots: list[pd.DataFrame] = []
    missing_files = 0

    for ticker in sorted({value for value in tickers if value}):
        feature_path = features_dir / f"{ticker}_features.parquet"
        if not feature_path.exists():
            missing_files += 1
            continue

        feature_df = pd.read_parquet(feature_path)
        if "Date" not in feature_df.columns:
            continue

        feature_df = feature_df.copy()
        feature_df["ticker"] = ticker
        feature_df["feature_date"] = pd.to_datetime(feature_df["Date"]).dt.strftime("%Y-%m-%d")

        def _get_col(name: str) -> pd.Series:
            if name in feature_df.columns:
                return pd.to_numeric(feature_df[name], errors="coerce")
            return pd.Series(pd.NA, index=feature_df.index, dtype="float64")

        close = _get_col("Close")
        ema20 = _get_col("EMA_20")
        ema200 = _get_col("EMA_200")
        sma20 = _get_col("SMA_20")
        volume = _get_col("Volume")
        volume_sma20 = _get_col("Volume_SMA_20")

        feature_df["entry_rsi"] = _get_col("RSI")
        feature_df["entry_atr_ratio"] = _get_col("ATR_Ratio")
        feature_df["entry_return_5d"] = _get_col("Return_5d")
        feature_df["entry_return_20d"] = _get_col("Return_20d")
        feature_df["entry_trend_strength_200"] = _get_col("TrendStrength_200")
        feature_df["entry_bb_pctb"] = _get_col("BB_PctB")
        feature_df["entry_bb_width"] = _get_col("BB_Width")
        feature_df["entry_adx_14"] = _get_col("ADX_14")
        feature_df["entry_gap_ema20_pct"] = (close / ema20 - 1.0) * 100.0
        feature_df["entry_gap_sma20_pct"] = (close / sma20 - 1.0) * 100.0
        feature_df["entry_gap_ema200_pct"] = (close / ema200 - 1.0) * 100.0
        feature_df["entry_volume_ratio"] = volume / volume_sma20

        keep_cols = [
            "ticker",
            "feature_date",
            "entry_rsi",
            "entry_atr_ratio",
            "entry_return_5d",
            "entry_return_20d",
            "entry_trend_strength_200",
            "entry_bb_pctb",
            "entry_bb_width",
            "entry_adx_14",
            "entry_gap_ema20_pct",
            "entry_gap_sma20_pct",
            "entry_gap_ema200_pct",
            "entry_volume_ratio",
        ]
        snapshots.append(feature_df[keep_cols])

    if not snapshots:
        return pd.DataFrame(columns=["ticker", "feature_date"]), missing_files

    snapshot_df = pd.concat(snapshots, ignore_index=True)
    snapshot_df = snapshot_df.drop_duplicates(subset=["ticker", "feature_date"], keep="last")
    return snapshot_df, missing_files


def load_trades(path: Path, exit_strategy: str) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"ticker": str})
    df = df[df["exit_strategy"] == exit_strategy].copy()
    df["ticker"] = df["ticker"].map(normalize_code)
    df["entry_date"] = df["entry_date"].astype(str)
    df["exit_date"] = df["exit_date"].astype(str)
    add_json_fields(df, "entry_metadata_json", ENTRY_JSON_FIELDS)
    add_json_fields(df, "exit_metadata_json", EXIT_JSON_FIELDS)
    df["entry_macd_gap"] = df["entry_macd"] - df["entry_macd_signal"]
    df["entry_macd_hist_jump"] = df["entry_macd_hist"] - df["entry_macd_hist_prev"]
    prev_abs = df["entry_macd_hist_prev"].abs().replace(0, pd.NA)
    df["entry_macd_hist_jump_ratio"] = df["entry_macd_hist"] / prev_abs
    add_hold_buckets(df)
    classify_stage1(df)
    return df


def summarize_group(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    counts = df.groupby(group_col, dropna=False).size().rename("trade_count")
    summary = df.groupby(group_col, dropna=False).agg(
        avg_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        avg_holding_days=("holding_days", "mean"),
        median_holding_days=("holding_days", "median"),
        total_return_jpy=("return_jpy", "sum"),
        avg_entry_confidence=("entry_confidence", "mean"),
        avg_entry_macd_hist=("entry_macd_hist", "mean"),
        median_entry_macd_hist=("entry_macd_hist", "median"),
        avg_entry_macd_gap=("entry_macd_gap", "mean"),
        avg_segment_total_bars=("segment_total_bars", "mean"),
        avg_peak_high_offset_bars=("peak_high_offset_bars", "mean"),
    )
    win_rate = df.groupby(group_col, dropna=False)["return_pct"].apply(lambda s: (s > 0).mean() * 100.0).rename("win_rate_pct")
    result = pd.concat([counts, summary, win_rate], axis=1).reset_index()
    result["trade_share"] = result["trade_count"] / max(len(df), 1)
    return result.sort_values("trade_count", ascending=False)


def summarize_by_dimension(df: pd.DataFrame, group_col: str, dim_col: str) -> pd.DataFrame:
    result = (
        df.groupby([group_col, dim_col], dropna=False, observed=False)
        .agg(
            trade_count=("ticker", "size"),
            avg_return_pct=("return_pct", "mean"),
            avg_holding_days=("holding_days", "mean"),
            win_rate_pct=("return_pct", lambda s: (s > 0).mean() * 100.0),
            total_return_jpy=("return_jpy", "sum"),
        )
        .reset_index()
    )
    totals = df.groupby(group_col, dropna=False).size().rename("group_total")
    result = result.merge(totals, on=group_col, how="left")
    result["share_within_group"] = result["trade_count"] / result["group_total"].replace(0, pd.NA)
    return result.sort_values([group_col, "trade_count"], ascending=[True, False])


def summarize_numeric_profile(df: pd.DataFrame, group_col: str, columns: Iterable[str]) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for col in columns:
        if col not in df.columns:
            continue
        series = df[col]
        if not pd.api.types.is_numeric_dtype(series):
            continue
        grouped = df.groupby(group_col, dropna=False)[col]
        row = {"feature": col}
        for name, values in grouped:
            row[f"{name}_mean"] = values.mean()
            row[f"{name}_median"] = values.median()
        records.append(row)
    return pd.DataFrame(records)


def summarize_target_sector(df: pd.DataFrame, group_col: str, target_group: str, min_sector_count: int = 5) -> pd.DataFrame:
    sector_df = df.dropna(subset=["sector_33"]).copy()
    totals = sector_df.groupby("sector_33").size().rename("sector_trade_count")
    target = (
        sector_df[sector_df[group_col] == target_group]
        .groupby("sector_33")
        .size()
        .rename("target_trade_count")
    )
    result = pd.concat([totals, target], axis=1).fillna(0).reset_index()
    result["target_trade_count"] = result["target_trade_count"].astype(int)
    result = result[result["sector_trade_count"] >= min_sector_count].copy()
    overall_target_share = float((sector_df[group_col] == target_group).mean()) if len(sector_df) else 0.0
    result["target_share_in_sector"] = result["target_trade_count"] / result["sector_trade_count"]
    result["overall_target_share"] = overall_target_share
    result["share_delta"] = result["target_share_in_sector"] - overall_target_share
    return result.sort_values(["share_delta", "target_trade_count"], ascending=[False, False])


def summarize_non_r_exit_types(stage2_df: pd.DataFrame) -> pd.DataFrame:
    result = (
        stage2_df.groupby(["stage2_group", "exit_urgency"], dropna=False)
        .agg(
            trade_count=("ticker", "size"),
            avg_return_pct=("return_pct", "mean"),
            avg_holding_days=("holding_days", "mean"),
            total_return_jpy=("return_jpy", "sum"),
        )
        .reset_index()
        .sort_values(["stage2_group", "trade_count"], ascending=[True, False])
    )
    return result


def fmt_float(value: object, digits: int = 2) -> str:
    if pd.isna(value):
        return "NA"
    return f"{float(value):.{digits}f}"


def frame_block(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "```text\n(empty)\n```"
    return "```text\n" + df.head(max_rows).to_string(index=False) + "\n```"


def build_key_observations(stage1_summary: pd.DataFrame, stage2_summary: pd.DataFrame) -> list[str]:
    observations: list[str] = []
    stage1 = stage1_summary.set_index("stage1_group") if not stage1_summary.empty else pd.DataFrame()
    if not stage1.empty and {"bad_r", "good_r", "non_r"}.issubset(stage1.index):
        bad = stage1.loc["bad_r"]
        good = stage1.loc["good_r"]
        non_r = stage1.loc["non_r"]
        observations.append(
            "stage1_bad_r_vs_non_r: count_share="
            f"{fmt_float(bad['trade_share'] * 100)}% vs {fmt_float(non_r['trade_share'] * 100)}%, "
            f"avg_return={fmt_float(bad['avg_return_pct'])}% vs {fmt_float(non_r['avg_return_pct'])}%"
        )
        observations.append(
            "stage1_bad_r_profile: holding_days="
            f"{fmt_float(bad['avg_holding_days'])} vs non_r {fmt_float(non_r['avg_holding_days'])}, "
            f"entry_confidence={fmt_float(bad['avg_entry_confidence'], 3)} vs non_r {fmt_float(non_r['avg_entry_confidence'], 3)}"
        )
        observations.append(
            "stage1_good_r_profile: holding_days="
            f"{fmt_float(good['avg_holding_days'])}, avg_return={fmt_float(good['avg_return_pct'])}%, "
            f"entry_macd_hist={fmt_float(good['avg_entry_macd_hist'], 3)}"
        )
    if not stage2_summary.empty and {"negative_non_r", "positive_non_r"}.issubset(set(stage2_summary["stage2_group"])):
        stage2 = stage2_summary.set_index("stage2_group")
        neg = stage2.loc["negative_non_r"]
        pos = stage2.loc["positive_non_r"]
        observations.append(
            "stage2_negative_vs_positive_non_r: trade_share="
            f"{fmt_float(neg['trade_share'] * 100)}% vs {fmt_float(pos['trade_share'] * 100)}%, "
            f"avg_return={fmt_float(neg['avg_return_pct'])}% vs {fmt_float(pos['avg_return_pct'])}%"
        )
        observations.append(
            "stage2_non_r_profile: holding_days="
            f"negative {fmt_float(neg['avg_holding_days'])} vs positive {fmt_float(pos['avg_holding_days'])}, "
            f"entry_macd_hist={fmt_float(neg['avg_entry_macd_hist'], 3)} vs {fmt_float(pos['avg_entry_macd_hist'], 3)}"
        )
    return observations


def write_report(
    output_path: Path,
    trades_df: pd.DataFrame,
    stage2_df: pd.DataFrame,
    join_stats: dict[str, object],
    stage1_summary: pd.DataFrame,
    stage1_year: pd.DataFrame,
    stage1_regime: pd.DataFrame,
    stage1_hold: pd.DataFrame,
    bad_r_sectors: pd.DataFrame,
    stage1_profile: pd.DataFrame,
    stage2_summary: pd.DataFrame,
    stage2_exit_types: pd.DataFrame,
    stage2_hold: pd.DataFrame,
    negative_non_r_sectors: pd.DataFrame,
    stage2_profile: pd.DataFrame,
) -> None:
    lines = [
        "# MACD Entry Risk Pattern Analysis",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Scope",
        "",
        f"- Trade source: {join_stats['trades_csv']}",
        f"- Exit strategy: {join_stats['exit_strategy']}",
        "- Stage 1 groups: good_r, bad_r, non_r",
        "- Stage 2 groups: positive_non_r, negative_non_r",
        "- Grouping mode: exit-action level",
        "",
        "## Join Coverage",
        "",
        f"- Production-exit trade rows: {join_stats['trade_row_count']}",
        f"- Sector join coverage: {join_stats['sector_join_rate']:.2%}",
        f"- Segment join coverage: {join_stats['segment_join_rate']:.2%}",
        f"- Entry-day feature join coverage: {join_stats['feature_join_rate']:.2%}",
        f"- Missing feature files: {join_stats['feature_missing_files']}",
        f"- Segment duplicate key rows dropped: {join_stats['segment_duplicate_count']}",
        "",
        "## Stage 1 Overview",
        "",
        frame_block(stage1_summary),
        "",
        "## Stage 1 By Year",
        "",
        frame_block(stage1_year),
        "",
        "## Stage 1 By Regime",
        "",
        frame_block(stage1_regime),
        "",
        "## Stage 1 Holding Buckets",
        "",
        frame_block(stage1_hold),
        "",
        "## Stage 1 Bad R Sector Overrepresentation",
        "",
        frame_block(bad_r_sectors),
        "",
        "## Stage 1 Numeric Feature Profile",
        "",
        frame_block(stage1_profile),
        "",
        "## Stage 2 Overview",
        "",
        frame_block(stage2_summary),
        "",
        "## Stage 2 Non-R Exit Types",
        "",
        frame_block(stage2_exit_types),
        "",
        "## Stage 2 Holding Buckets",
        "",
        frame_block(stage2_hold),
        "",
        "## Stage 2 Negative Non-R Sector Overrepresentation",
        "",
        frame_block(negative_non_r_sectors),
        "",
        "## Stage 2 Numeric Feature Profile",
        "",
        frame_block(stage2_profile),
        "",
        "## Auto Notes",
        "",
    ]
    for observation in build_key_observations(stage1_summary, stage2_summary):
        lines.append(f"- {observation}")
    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trades-csv", default=DEFAULT_TRADES_CSV)
    parser.add_argument("--segment-csv", default=DEFAULT_SEGMENT_CSV)
    parser.add_argument("--jpx-csv", default=DEFAULT_JPX_CSV)
    parser.add_argument("--data-root", default=DEFAULT_DATA_ROOT)
    parser.add_argument("--exit-strategy", default=DEFAULT_EXIT_STRATEGY)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    trades_path = Path(args.trades_csv)
    segment_path = Path(args.segment_csv)
    jpx_path = Path(args.jpx_csv)
    data_root = Path(args.data_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    trades_df = load_trades(trades_path, args.exit_strategy)
    sector_lookup = load_sector_lookup(jpx_path)
    segment_lookup, segment_duplicate_count = load_segment_lookup(segment_path)
    feature_lookup, feature_missing_files = load_feature_snapshots(data_root, trades_df["ticker"].tolist())

    trades_df = trades_df.merge(sector_lookup, on="ticker", how="left")
    trades_df = trades_df.merge(segment_lookup, on=["ticker", "entry_date"], how="left")
    trades_df["signal_date_for_features"] = trades_df["golden_cross_date"].fillna(trades_df["entry_date"])
    trades_df = trades_df.merge(
        feature_lookup,
        left_on=["ticker", "signal_date_for_features"],
        right_on=["ticker", "feature_date"],
        how="left",
    )
    if "feature_date" in trades_df.columns:
        trades_df = trades_df.drop(columns=["feature_date"])

    stage2_df = classify_stage2(trades_df)

    stage1_summary = summarize_group(trades_df, "stage1_group")
    stage1_year = summarize_by_dimension(trades_df, "stage1_group", "period")
    stage1_regime = summarize_by_dimension(trades_df, "stage1_group", "market_regime")
    stage1_hold = summarize_by_dimension(trades_df, "stage1_group", "holding_bucket")
    stage1_profile = summarize_numeric_profile(trades_df, "stage1_group", NUMERIC_PROFILE_COLUMNS)
    bad_r_sectors = summarize_target_sector(trades_df, "stage1_group", "bad_r")

    stage2_summary = summarize_group(stage2_df, "stage2_group")
    stage2_exit_types = summarize_non_r_exit_types(stage2_df)
    stage2_hold = summarize_by_dimension(stage2_df, "stage2_group", "holding_bucket")
    stage2_profile = summarize_numeric_profile(stage2_df, "stage2_group", NUMERIC_PROFILE_COLUMNS)
    negative_non_r_sectors = summarize_target_sector(stage2_df, "stage2_group", "negative_non_r")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    enriched_path = output_dir / f"entry_risk_enriched_trades_{timestamp}.csv"
    stage1_summary_path = output_dir / f"entry_risk_stage1_summary_{timestamp}.csv"
    stage1_year_path = output_dir / f"entry_risk_stage1_by_year_{timestamp}.csv"
    stage1_regime_path = output_dir / f"entry_risk_stage1_by_regime_{timestamp}.csv"
    stage1_hold_path = output_dir / f"entry_risk_stage1_by_hold_{timestamp}.csv"
    stage1_profile_path = output_dir / f"entry_risk_stage1_profile_{timestamp}.csv"
    bad_r_sectors_path = output_dir / f"entry_risk_stage1_bad_r_sectors_{timestamp}.csv"
    stage2_summary_path = output_dir / f"entry_risk_stage2_summary_{timestamp}.csv"
    stage2_exit_types_path = output_dir / f"entry_risk_stage2_exit_types_{timestamp}.csv"
    stage2_hold_path = output_dir / f"entry_risk_stage2_by_hold_{timestamp}.csv"
    stage2_profile_path = output_dir / f"entry_risk_stage2_profile_{timestamp}.csv"
    negative_non_r_sectors_path = output_dir / f"entry_risk_stage2_negative_non_r_sectors_{timestamp}.csv"
    report_path = output_dir / f"entry_risk_report_{timestamp}.md"

    trades_df.to_csv(enriched_path, index=False, encoding="utf-8-sig")
    stage1_summary.to_csv(stage1_summary_path, index=False, encoding="utf-8-sig")
    stage1_year.to_csv(stage1_year_path, index=False, encoding="utf-8-sig")
    stage1_regime.to_csv(stage1_regime_path, index=False, encoding="utf-8-sig")
    stage1_hold.to_csv(stage1_hold_path, index=False, encoding="utf-8-sig")
    stage1_profile.to_csv(stage1_profile_path, index=False, encoding="utf-8-sig")
    bad_r_sectors.to_csv(bad_r_sectors_path, index=False, encoding="utf-8-sig")
    stage2_summary.to_csv(stage2_summary_path, index=False, encoding="utf-8-sig")
    stage2_exit_types.to_csv(stage2_exit_types_path, index=False, encoding="utf-8-sig")
    stage2_hold.to_csv(stage2_hold_path, index=False, encoding="utf-8-sig")
    stage2_profile.to_csv(stage2_profile_path, index=False, encoding="utf-8-sig")
    negative_non_r_sectors.to_csv(negative_non_r_sectors_path, index=False, encoding="utf-8-sig")

    join_stats = {
        "trades_csv": str(trades_path),
        "exit_strategy": args.exit_strategy,
        "trade_row_count": len(trades_df),
        "sector_join_rate": float(trades_df["sector_33"].notna().mean()) if len(trades_df) else 0.0,
        "segment_join_rate": float(trades_df["segment_total_bars"].notna().mean()) if len(trades_df) else 0.0,
        "feature_join_rate": float(trades_df["entry_gap_ema200_pct"].notna().mean()) if len(trades_df) else 0.0,
        "feature_missing_files": feature_missing_files,
        "segment_duplicate_count": segment_duplicate_count,
    }

    write_report(
        output_path=report_path,
        trades_df=trades_df,
        stage2_df=stage2_df,
        join_stats=join_stats,
        stage1_summary=stage1_summary,
        stage1_year=stage1_year,
        stage1_regime=stage1_regime,
        stage1_hold=stage1_hold,
        bad_r_sectors=bad_r_sectors,
        stage1_profile=stage1_profile,
        stage2_summary=stage2_summary,
        stage2_exit_types=stage2_exit_types,
        stage2_hold=stage2_hold,
        negative_non_r_sectors=negative_non_r_sectors,
        stage2_profile=stage2_profile,
    )

    print(report_path)
    print(stage1_summary_path)
    print(stage2_summary_path)
    print(enriched_path)


if __name__ == "__main__":
    main()