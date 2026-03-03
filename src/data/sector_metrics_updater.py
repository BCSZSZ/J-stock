"""Sector metrics updater for production and fetch workflows.

Builds daily sector-level metrics from the latest sector pool universe and
stock features. Designed to be resilient to pool composition changes.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.data.fetch_universe_builder import find_latest_sector_pool_csv


def _resolve_sector_pool_csv(sector_pool_file: Optional[str]) -> Optional[Path]:
    if not sector_pool_file:
        return None

    candidate = Path(sector_pool_file)
    if candidate.exists() and candidate.is_dir():
        return find_latest_sector_pool_csv(candidate)
    if candidate.exists() and candidate.suffix.lower() == ".csv":
        return candidate
    return None


def _pick_sector_column(df: pd.DataFrame) -> Optional[str]:
    candidates = [
        "sector_name",
        "Sector33CodeName",
        "Sector17CodeName",
        "33SectorName",
        "sector",
    ]
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _pick_volume_surge_column(df: pd.DataFrame) -> Optional[str]:
    for name in ["Volume_Surge_20_120", "Volume_Surge", "Vol_Surge"]:
        if name in df.columns:
            return name
    return None


def _build_universe_signature(df_map: pd.DataFrame) -> str:
    pairs = [f"{r['ticker']}|{r['sector']}" for _, r in df_map.sort_values(["sector", "ticker"]).iterrows()]
    payload = "\n".join(pairs).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:12]


def update_sector_metrics(
    sector_pool_file: Optional[str],
    data_root: str = "data",
    lookback_days: int = 90,
    min_names_per_sector: int = 5,
) -> Dict:
    """
    Update sector daily metrics using latest sector pool and local features.

    Returns:
        dict summary with status, coverage, and output paths.
    """
    result = {
        "status": "skipped",
        "message": "",
        "pool_file": None,
        "pool_size": 0,
        "sector_count": 0,
        "rows_written": 0,
        "metrics_file": None,
        "snapshot_file": None,
    }

    pool_csv = _resolve_sector_pool_csv(sector_pool_file)
    if not pool_csv or not pool_csv.exists():
        result["message"] = "Sector pool CSV not found"
        return result

    pool_df = pd.read_csv(pool_csv, encoding="utf-8")
    if "Code" not in pool_df.columns:
        result["message"] = "Sector pool missing Code column"
        return result

    sector_col = _pick_sector_column(pool_df)
    if not sector_col:
        result["message"] = "Sector pool missing sector column"
        return result

    universe_map = pool_df[["Code", sector_col]].copy()
    universe_map.columns = ["ticker", "sector"]
    universe_map["ticker"] = universe_map["ticker"].astype(str).str.strip().str.zfill(4)
    universe_map["sector"] = universe_map["sector"].astype(str).str.strip()
    universe_map = universe_map[
        universe_map["ticker"].ne("")
        & universe_map["sector"].ne("")
        & universe_map["sector"].ne("-")
        & universe_map["sector"].ne("Unknown")
    ].drop_duplicates(subset=["ticker"], keep="first")

    if universe_map.empty:
        result["message"] = "No valid ticker-sector mapping"
        return result

    signature = _build_universe_signature(universe_map)

    data_root_path = Path(data_root)
    features_dir = data_root_path / "features"
    metrics_file = features_dir / "sector_daily_metrics.parquet"
    snapshot_dir = data_root_path / "metadata" / "sector_overlay"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = snapshot_dir / f"universe_snapshot_{datetime.now().strftime('%Y-%m-%d')}.json"

    end_dt = pd.Timestamp.now().normalize()
    warmup_days = 25
    start_dt = end_dt - pd.Timedelta(days=max(int(lookback_days), 1) + warmup_days)

    pool_size = len(universe_map)
    sector_sizes = universe_map.groupby("sector").size().to_dict()

    snapshot_payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pool_csv": str(pool_csv),
        "pool_size": int(pool_size),
        "sector_count": int(universe_map["sector"].nunique()),
        "universe_signature": signature,
        "sector_sizes": {k: int(v) for k, v in sector_sizes.items()},
        "members": [
            {"ticker": r["ticker"], "sector": r["sector"]}
            for _, r in universe_map.sort_values(["sector", "ticker"]).iterrows()
        ],
    }
    with open(snapshot_file, "w", encoding="utf-8") as f:
        json.dump(snapshot_payload, f, indent=2, ensure_ascii=False)

    frames = []
    volume_missing = 0
    for _, row in universe_map.iterrows():
        ticker = row["ticker"]
        sector = row["sector"]
        fp = features_dir / f"{ticker}_features.parquet"
        if not fp.exists():
            continue

        try:
            df = pd.read_parquet(fp)
        except Exception:
            continue

        if df.empty or "Close" not in df.columns:
            continue

        if "Date" in df.columns:
            df = df.copy()
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
        else:
            df = df.copy().reset_index().rename(columns={df.index.name or "index": "Date"})
            if "Date" not in df.columns:
                first_col = df.columns[0]
                df = df.rename(columns={first_col: "Date"})
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
        if df.empty:
            continue

        df = df[(df["Date"] >= start_dt) & (df["Date"] <= end_dt)]
        if df.empty:
            continue

        close = pd.to_numeric(df["Close"], errors="coerce")
        ema20 = pd.to_numeric(df.get("EMA_20"), errors="coerce") if "EMA_20" in df.columns else np.nan
        ema50 = pd.to_numeric(df.get("EMA_50"), errors="coerce") if "EMA_50" in df.columns else np.nan
        atr = pd.to_numeric(df.get("ATR"), errors="coerce") if "ATR" in df.columns else np.nan

        surge_col = _pick_volume_surge_column(df)
        if surge_col:
            vol_surge = pd.to_numeric(df[surge_col], errors="coerce")
        else:
            volume_missing += 1
            if "Volume" in df.columns:
                volume = pd.to_numeric(df["Volume"], errors="coerce")
                volume_sma20 = volume.rolling(20).mean()
                vol_surge = (volume / volume_sma20).replace([np.inf, -np.inf], np.nan)
            else:
                vol_surge = np.nan

        ticker_daily = pd.DataFrame(
            {
                "Date": df["Date"],
                "sector": sector,
                "ticker": ticker,
                "close": close,
                "above_ema20": (close > ema20).astype(float),
                "above_ema50": (close > ema50).astype(float),
                "mom_5d": close.pct_change(5),
                "mom_20d": close.pct_change(20),
                "atr_ratio": (atr / close),
                "volume_surge": vol_surge,
            }
        )
        frames.append(ticker_daily)

    if not frames:
        result["message"] = "No usable feature data for sector universe"
        result["pool_file"] = str(pool_csv)
        result["pool_size"] = int(pool_size)
        result["sector_count"] = int(universe_map["sector"].nunique())
        result["snapshot_file"] = str(snapshot_file)
        return result

    all_daily = pd.concat(frames, ignore_index=True)
    all_daily = all_daily.dropna(subset=["Date", "sector"])
    all_daily["Date"] = pd.to_datetime(all_daily["Date"]).dt.normalize()

    grouped = (
        all_daily.groupby(["Date", "sector"], as_index=False)
        .agg(
            breadth_ema20=("above_ema20", "mean"),
            breadth_ema50=("above_ema50", "mean"),
            mom_5d_med=("mom_5d", "median"),
            mom_20d_med=("mom_20d", "median"),
            atr_ratio_med=("atr_ratio", "median"),
            volume_surge_med=("volume_surge", "median"),
            valid_names=("ticker", "nunique"),
        )
        .sort_values(["Date", "sector"])
    )

    size_map = universe_map.groupby("sector").size().to_dict()
    grouped["pool_size"] = grouped["sector"].map(size_map).fillna(0).astype(int)
    grouped["coverage_ratio"] = grouped["valid_names"] / grouped["pool_size"].replace(0, np.nan)
    grouped["coverage_ratio"] = grouped["coverage_ratio"].fillna(0.0)
    grouped["universe_signature"] = signature
    grouped["pool_file"] = str(pool_csv)
    grouped["is_low_coverage"] = (
        (grouped["valid_names"] < max(int(min_names_per_sector), 1))
        | (grouped["coverage_ratio"] < 0.5)
    )

    mom20_clip = grouped["mom_20d_med"].clip(-0.20, 0.20)
    mom20_norm = (mom20_clip + 0.20) / 0.40
    atr_clip = grouped["atr_ratio_med"].clip(0.0, 0.10) / 0.10
    grouped["sector_score"] = (
        100.0
        * (
            0.35 * grouped["breadth_ema20"].fillna(0.0)
            + 0.25 * grouped["breadth_ema50"].fillna(0.0)
            + 0.25 * mom20_norm.fillna(0.5)
            + 0.15 * (1.0 - atr_clip.fillna(1.0))
        )
    ).clip(0.0, 100.0)

    merge_cols = ["Date", "sector"]
    if metrics_file.exists():
        try:
            old = pd.read_parquet(metrics_file)
            if "Date" in old.columns:
                old["Date"] = pd.to_datetime(old["Date"], errors="coerce").dt.normalize()
            old = old.dropna(subset=["Date", "sector"])
            min_new_date = grouped["Date"].min()
            old = old[old["Date"] < min_new_date]
            merged = pd.concat([old, grouped], ignore_index=True)
            merged = merged.sort_values(["Date", "sector"]).drop_duplicates(subset=merge_cols, keep="last")
        except Exception:
            merged = grouped
    else:
        merged = grouped

    metrics_file.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(metrics_file, index=False)

    result.update(
        {
            "status": "ok",
            "message": "Sector metrics updated",
            "pool_file": str(pool_csv),
            "pool_size": int(pool_size),
            "sector_count": int(universe_map["sector"].nunique()),
            "rows_written": int(len(grouped)),
            "metrics_file": str(metrics_file),
            "snapshot_file": str(snapshot_file),
            "universe_signature": signature,
            "volume_fallback_tickers": int(volume_missing),
        }
    )
    return result
