"""Build a unified fetch universe JSON for data preparation workflows."""

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd


def _load_tickers_from_json(path: Path) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    raw = data.get("tickers", []) if isinstance(data, dict) else data
    tickers: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            code = item.get("code")
        else:
            code = str(item)
        if code:
            tickers.append(str(code).strip())
    return tickers


def _load_sector_pool_tickers(path: Path) -> List[str]:
    df = pd.read_csv(path, encoding="utf-8")
    if "Code" not in df.columns:
        return []
    return [str(code).strip().zfill(4) for code in df["Code"].tolist() if str(code).strip()]


def find_latest_sector_pool_csv(sector_pool_dir: Path) -> Optional[Path]:
    if not sector_pool_dir.exists():
        return None

    candidates = list(sector_pool_dir.glob("sector_pool_33x*to*_*_*.csv"))
    if not candidates:
        return None

    return max(candidates, key=lambda p: p.stat().st_mtime)


def build_fetch_universe_file(
    monitor_list_file: str,
    output_file: str = "data/fetch_universe.json",
    sector_pool_file: Optional[str] = None,
) -> Tuple[str, int, int]:
    """
    Build unified fetch universe from monitor list + sector pool.

    Returns:
        (output_file_path, merged_count, sector_pool_count)
    """
    monitor_path = Path(monitor_list_file)
    if not monitor_path.exists():
        raise FileNotFoundError(f"Monitor list not found: {monitor_list_file}")

    monitor_tickers = _load_tickers_from_json(monitor_path)

    sector_pool_count = 0
    sector_tickers: List[str] = []
    source_sector_pool = None

    if sector_pool_file:
        pool_path = Path(sector_pool_file)
    else:
        pool_path = find_latest_sector_pool_csv(Path("data/universe/sector_pool"))

    if pool_path and pool_path.exists():
        sector_tickers = _load_sector_pool_tickers(pool_path)
        sector_pool_count = len(set(sector_tickers))
        source_sector_pool = str(pool_path)

    merged = sorted(set(monitor_tickers) | set(sector_tickers))

    payload = {
        "version": "1.0",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "description": "Unified fetch universe for fetch --all and production --daily fetch step",
        "sources": {
            "monitor_list_file": str(monitor_path),
            "sector_pool_file": source_sector_pool,
        },
        "counts": {
            "monitor_tickers": len(set(monitor_tickers)),
            "sector_pool_tickers": sector_pool_count,
            "merged_tickers": len(merged),
        },
        "tickers": merged,
    }

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    return str(out_path), len(merged), sector_pool_count
