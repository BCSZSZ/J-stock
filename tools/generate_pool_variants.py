"""
Generate multiple stock pool variants for evaluation comparison.

Uses local cached features (--no-fetch equivalent) to score all universe
candidates with each scoring model (v1-v8) × multiple top_n sizes.

Outputs:
    data/universe/pools/
        pool_registry.json          — Master index of all generated pools
        baseline_v1_62.json         — Snapshot of current production pool
        {model}_top{n}.json         — Pool variants (e.g., v3_top50.json)

Usage:
    python tools/generate_pool_variants.py
    python tools/generate_pool_variants.py --models v3 v5 v7 --sizes 50 70
    python tools/generate_pool_variants.py --dry-run
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

from src.data.stock_data_manager import StockDataManager
from src.universe.stock_selector import UniverseSelector

# ── Constants ──────────────────────────────────────────────────────────────

ALL_MODELS = ["v1", "v2", "v3", "v4", "v5", "v6", "v7", "v8"]
ALL_SIZES = [30, 50, 70, 100]

POOLS_DIR = PROJECT_ROOT / "data" / "universe" / "pools"
CSV_PATH = PROJECT_ROOT / "data" / "jpx_final_list.csv"
MONITOR_LIST_PATH = PROJECT_ROOT / "data" / "monitor_list.json"

# 13 manually-selected stocks always included in every pool
MANUAL_STOCKS = [
    {"code": "1321", "name": "Nikkei 225 ETF"},
    {"code": "4063", "name": "Shin-Etsu Chemical"},
    {"code": "4568", "name": "Daiichi Sankyo"},
    {"code": "6098", "name": "Recruit Holdings"},
    {"code": "6501", "name": "Hitachi"},
    {"code": "6861", "name": "Keyence"},
    {"code": "7011", "name": "Mitsubishi Heavy"},
    {"code": "7013", "name": "IHI Corp"},
    {"code": "7203", "name": "Toyota"},
    {"code": "7974", "name": "Nintendo"},
    {"code": "8035", "name": "Tokyo Electron"},
    {"code": "8058", "name": "Mitsubishi Corp"},
    {"code": "8306", "name": "MUFG Bank"},
]
MANUAL_CODES = {s["code"] for s in MANUAL_STOCKS}

# Model descriptions for registry metadata
MODEL_DESCRIPTIONS = {
    "v1": "Balanced 5-factor (Vol 25%, Liq 25%, Trend 20%, Mom 20%, VolSurge 10%)",
    "v2": "Liquidity-focused, volatility centered (Liq 30%, Trend 25%)",
    "v3": "Trend quality enhanced (ADX 20%, RSI_centered 5%)",
    "v4": "Momentum focused (Mom 25%, RSI_centered 10%)",
    "v5": "Money flow + trend (OBV 15%, ADX 15%)",
    "v6": "High-signal simplified (TrendADX avg, MomRSI avg)",
    "v7": "Volatility-neutral + heavy trend (ADX 30%)",
    "v8": "Equal-weight all 9 factors (~11% each)",
}


# ── Core Logic ─────────────────────────────────────────────────────────────

def load_universe_codes() -> list[str]:
    """Load all candidate stock codes from the JPX CSV."""
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"JPX CSV not found: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, encoding="utf-8")
    return df["Code"].astype(str).str.strip().tolist()


def extract_features_once(codes: list[str]) -> pd.DataFrame:
    """
    Extract raw features for all codes using local cached data.
    Returns a DataFrame with one row per stock (hard filters applied).
    """
    manager = StockDataManager(api_key="dummy")
    selector = UniverseSelector(
        manager, workers=1, score_model="v1", output_dir=str(POOLS_DIR.parent)
    )

    print(f"Extracting features for {len(codes)} stocks (local data only)...")
    results = []
    for i, code in enumerate(codes):
        if (i + 1) % 500 == 0:
            print(f"  [{i+1}/{len(codes)}]")
        try:
            features = selector._extract_stock_features(code, f"Stock_{code}", no_fetch=True)
            if features:
                results.append(features)
        except Exception:
            pass

    df = pd.DataFrame(results)
    print(f"  Extracted: {len(df)}/{len(codes)} stocks")

    # Apply hard filters
    df_filtered = selector.apply_hard_filters(df)
    print(f"  After hard filters: {len(df_filtered)} stocks")
    return df_filtered


def score_with_model(df_raw: pd.DataFrame, model: str) -> pd.DataFrame:
    """Score a pre-filtered DataFrame using a specific model."""
    manager = StockDataManager(api_key="dummy")
    selector = UniverseSelector(
        manager, workers=1, score_model=model, output_dir=str(POOLS_DIR.parent)
    )
    df_norm = selector.normalize_features(df_raw)
    df_scored = selector.calculate_scores(df_norm)
    return df_scored.sort_values("TotalScore", ascending=False).reset_index(drop=True)


def build_pool(df_scored: pd.DataFrame, top_n: int, model: str) -> dict:
    """
    Build a pool JSON dict from scored data.
    Selects top_n by score, then merges manual stocks (deduped).
    """
    df_top = df_scored.head(top_n).copy()
    auto_codes = set(df_top["Code"].tolist())

    tickers = []

    # Add manual stocks first
    for ms in MANUAL_STOCKS:
        source = "manual+auto" if ms["code"] in auto_codes else "manual"
        # Find score if available
        score_row = df_scored[df_scored["Code"] == ms["code"]]
        entry = {"code": ms["code"], "name": ms["name"], "source": source}
        if not score_row.empty:
            entry["total_score"] = round(float(score_row.iloc[0]["TotalScore"]), 6)
            rank_in_full = int(score_row.index[0]) + 1
            entry["universe_rank"] = rank_in_full
        tickers.append(entry)

    # Add auto-selected stocks (excluding those already in manual)
    rank = 0
    for _, row in df_top.iterrows():
        rank += 1
        if row["Code"] in MANUAL_CODES:
            continue
        tickers.append({
            "code": row["Code"],
            "name": row.get("CompanyName", f"Stock_{row['Code']}"),
            "source": "auto",
            "rank": rank,
            "total_score": round(float(row["TotalScore"]), 6),
        })

    pool_id = f"{model}_top{top_n}"
    return {
        "version": "1.0",
        "pool_id": pool_id,
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "score_model": model,
        "model_description": MODEL_DESCRIPTIONS.get(model, ""),
        "top_n_auto": top_n,
        "manual_stocks_included": True,
        "manual_stock_count": len(MANUAL_STOCKS),
        "auto_stock_count": len([t for t in tickers if t["source"] == "auto"]),
        "total_count": len(tickers),
        "tickers": tickers,
    }


def save_pool(pool: dict, path: Path) -> None:
    """Write pool JSON to disk."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(pool, f, indent=2, ensure_ascii=False)


def create_baseline_pool() -> dict:
    """Create a baseline pool from the current production monitor_list.json."""
    with open(MONITOR_LIST_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    tickers = []
    for t in data["tickers"]:
        entry = {"code": t["code"], "name": t.get("name", f"Stock_{t['code']}")}
        if "universe_rank" in t:
            entry["source"] = "auto"
            entry["universe_rank"] = t["universe_rank"]
            entry["total_score"] = t.get("universe_score", 0)
        else:
            entry["source"] = "manual"
        tickers.append(entry)

    return {
        "version": "1.0",
        "pool_id": "baseline_v1_62",
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "score_model": "v1",
        "model_description": "Production baseline — original 62-stock pool (Jan 2026)",
        "top_n_auto": 50,
        "manual_stocks_included": True,
        "manual_stock_count": len([t for t in tickers if t["source"] == "manual"]),
        "auto_stock_count": len([t for t in tickers if t["source"] == "auto"]),
        "total_count": len(tickers),
        "tickers": tickers,
    }


def build_registry(pools: list[dict], baseline_id: str) -> dict:
    """Build pool_registry.json from a list of pool dicts."""
    entries = []
    for p in pools:
        entries.append({
            "id": p["pool_id"],
            "file": f"{p['pool_id']}.json",
            "model": p["score_model"],
            "auto_n": p["top_n_auto"],
            "total": p["total_count"],
        })

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "baseline_pool": baseline_id,
        "total_pools": len(entries),
        "models_used": sorted(set(e["model"] for e in entries)),
        "sizes_used": sorted(set(e["auto_n"] for e in entries)),
        "pools": entries,
        "recommended": [],
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate stock pool variants for evaluation comparison"
    )
    parser.add_argument(
        "--models", nargs="+", default=ALL_MODELS,
        help=f"Scoring models to use (default: {ALL_MODELS})",
    )
    parser.add_argument(
        "--sizes", nargs="+", type=int, default=ALL_SIZES,
        help=f"Top-N sizes to generate (default: {ALL_SIZES})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be generated without writing files",
    )
    args = parser.parse_args()

    models = args.models
    sizes = args.sizes
    total_pools = len(models) * len(sizes) + 1  # +1 for baseline

    print(f"=" * 60)
    print(f"Pool Variant Generator")
    print(f"  Models: {models}")
    print(f"  Sizes:  {sizes}")
    print(f"  Total pools: {total_pools} ({len(models)}×{len(sizes)} + 1 baseline)")
    print(f"  Output: {POOLS_DIR}")
    print(f"=" * 60)

    if args.dry_run:
        print("\n[DRY RUN] Would generate:")
        print(f"  baseline_v1_62.json")
        for m in models:
            for s in sizes:
                n_manual = len(MANUAL_STOCKS)
                print(f"  {m}_top{s}.json  (auto={s} + manual={n_manual})")
        print(f"  pool_registry.json")
        return

    POOLS_DIR.mkdir(parents=True, exist_ok=True)

    # Step 1: Create baseline
    print("\n[1/4] Creating baseline pool from production monitor_list...")
    baseline = create_baseline_pool()
    save_pool(baseline, POOLS_DIR / "baseline_v1_62.json")
    print(f"  ✓ baseline_v1_62.json ({baseline['total_count']} stocks)")

    # Step 2: Extract features once
    print("\n[2/4] Extracting features from local data...")
    codes = load_universe_codes()
    df_raw = extract_features_once(codes)

    # Step 3: Score with each model and generate pools
    print(f"\n[3/4] Scoring and generating {len(models) * len(sizes)} pool variants...")
    all_pools = [baseline]

    for model in models:
        print(f"\n  Scoring with model {model}...")
        df_scored = score_with_model(df_raw, model)
        print(f"    Scored {len(df_scored)} stocks, "
              f"top score: {df_scored['TotalScore'].iloc[0]:.4f}, "
              f"bottom score: {df_scored['TotalScore'].iloc[-1]:.4f}")

        for size in sizes:
            pool = build_pool(df_scored, size, model)
            pool_path = POOLS_DIR / f"{model}_top{size}.json"
            save_pool(pool, pool_path)
            all_pools.append(pool)
            print(f"    ✓ {pool['pool_id']}.json ({pool['total_count']} stocks)")

    # Step 4: Build registry
    print(f"\n[4/4] Building pool registry...")
    registry = build_registry(all_pools, "baseline_v1_62")
    with open(POOLS_DIR / "pool_registry.json", "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)
    print(f"  ✓ pool_registry.json ({registry['total_pools']} pools)")

    print(f"\n{'=' * 60}")
    print(f"Done! Generated {len(all_pools)} pools in {POOLS_DIR}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
