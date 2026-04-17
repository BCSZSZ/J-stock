"""Data endpoints: features, monitor list, benchmark."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from web.api.dependencies import get_production_config, get_project_root

router = APIRouter(prefix="/api/data", tags=["data"])


def _features_path(ticker: str) -> Path:
    root = get_project_root()
    return root / "data" / "features" / f"{ticker}_features.parquet"


@router.get("/features/{ticker}")
def get_features(
    ticker: str,
    days: int = Query(default=120, ge=1, le=2000),
) -> list[dict[str, object]]:
    path = _features_path(ticker)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No features for {ticker}")
    df = pd.read_parquet(path)
    df = df.tail(days).copy()
    df = df.reset_index()
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)
    return df.where(df.notna(), None).to_dict(orient="records")


@router.get("/features/{ticker}/chart")
def get_chart_data(
    ticker: str,
    days: int = Query(default=250, ge=1, le=2000),
) -> list[dict[str, object]]:
    """Return OHLCV in lightweight-charts compatible format."""
    path = _features_path(ticker)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No features for {ticker}")
    df = pd.read_parquet(path)
    df = df.tail(days).copy()
    df = df.reset_index()
    if "Date" in df.columns:
        df["Date"] = df["Date"].astype(str)

    records: list[dict[str, object]] = []
    for _, row in df.iterrows():
        rec: dict[str, object] = {
            "time": str(row.get("Date", "")),
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
        }
        if "Volume" in row:
            rec["volume"] = row["Volume"]
        records.append(rec)
    return records


@router.get("/monitor-list")
def get_monitor_list() -> list[str]:
    cfg = get_production_config()
    ml_path = Path(cfg.monitor_list_file)
    if not ml_path.exists():
        return []
    raw = json.loads(ml_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        tickers_raw = raw.get("tickers", [])
        return [t["code"] if isinstance(t, dict) else str(t) for t in tickers_raw]
    return [str(t) for t in raw]


@router.get("/tickers")
def list_available_tickers() -> list[str]:
    """List tickers that have feature data on disk."""
    root = get_project_root()
    features_dir = root / "data" / "features"
    if not features_dir.exists():
        return []
    return sorted(
        f.stem.replace("_features", "")
        for f in features_dir.glob("*_features.parquet")
    )


@router.get("/ticker-names")
def get_ticker_names() -> dict[str, str]:
    """Return {code: name} mapping from JPX master CSV."""
    root = get_project_root()
    csv_path = root / "data" / "jpx_final_list.csv"
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, dtype=str, usecols=["Code", "銘柄名"])
    return dict(zip(df["Code"], df["銘柄名"]))
