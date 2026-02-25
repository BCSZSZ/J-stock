"""
Production Position Sync Module
Synchronize positions to monitor lists and fetch missing data.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Set

logger = logging.getLogger(__name__)


def run_sync_positions(prod_cfg, state) -> None:
    """
    Sync positions to monitor lists and fetch missing data.
    
    Steps:
    1. Collect all tickers from positions across all groups
    2. Load production monitor list
    3. Find missing tickers
    4. Fetch data for missing tickers (5 years)
    5. Update production monitor list (G Drive)
    
    Args:
        prod_cfg: Production configuration
        state: Production state
    """
    print("\n" + "=" * 70)
    print("SYNC POSITIONS TO MONITOR LISTS")
    print("=" * 70)
    
    # Step 1: Collect all position tickers
    position_tickers = _collect_position_tickers(state)
    
    if not position_tickers:
        print("\n✅ No positions found. Nothing to sync.")
        return
    
    print(f"\n[1/5] Found {len(position_tickers)} unique ticker(s) in positions:")
    for ticker in sorted(position_tickers):
        print(f"  - {ticker}")
    
    # Step 2: Load production monitor list
    prod_monitor_tickers = _load_monitor_list_simple(prod_cfg.monitor_list_file)
    
    print(f"\n[2/5] Current monitor list sizes:")
    print(f"  - Production (G Drive): {len(prod_monitor_tickers)} tickers")
    
    # Step 3: Find missing tickers
    missing_tickers = position_tickers - prod_monitor_tickers
    
    if not missing_tickers:
        print(f"\n✅ All positions are already in monitor lists. No sync needed.")
        return
    
    print(f"\n[3/5] Found {len(missing_tickers)} missing ticker(s):")
    for ticker in sorted(missing_tickers):
        print(f"  ⚠️  {ticker}")
    
    # Step 4: Fetch data for missing tickers
    print(f"\n[4/5] Fetching data for missing tickers (this may take a while)...")
    success_count = _fetch_missing_data(list(missing_tickers))
    print(f"  ✅ Successfully fetched {success_count}/{len(missing_tickers)} ticker(s)")
    
    # Step 5: Update production monitor list
    print(f"\n[5/5] Updating production monitor list...")
    
    # Update production monitor list (G Drive)
    _update_simple_monitor_list(
        prod_cfg.monitor_list_file,
        prod_monitor_tickers | missing_tickers,
        "Production trading monitor list (Auto-synced from positions)"
    )
    print(f"  ✅ Updated: {prod_cfg.monitor_list_file}")
    
    print("\n" + "=" * 70)
    print(f"SYNC COMPLETE: Added {len(missing_tickers)} ticker(s) to monitor lists")
    print("=" * 70)


def _collect_position_tickers(state) -> Set[str]:
    """Collect all unique tickers from all positions."""
    tickers = set()
    for group in state.get_all_groups():
        for pos in group.positions:
            if pos.ticker:
                tickers.add(pos.ticker)
    return tickers


def _load_monitor_list_simple(file_path: str) -> Set[str]:
    """Load simple monitor list (production format: array of strings)."""
    path = Path(file_path)
    if not path.exists():
        logger.warning(f"Monitor list not found: {file_path}")
        return set()
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        raw = data.get("tickers", []) if isinstance(data, dict) else data
        
        # Support both formats: [{"code": "8035"}, ...] and ["8035", ...]
        tickers = []
        for item in raw:
            if isinstance(item, dict):
                tickers.append(item.get("code"))
            else:
                tickers.append(str(item))
        
        return set(t for t in tickers if t)
    
    except Exception as e:
        logger.error(f"Failed to load monitor list {file_path}: {e}")
        return set()


def _fetch_missing_data(tickers: List[str]) -> int:
    """
    Fetch data for missing tickers (5 years history).
    
    Returns:
        Number of successfully fetched tickers
    """
    import os
    from dotenv import load_dotenv
    from src.data.stock_data_manager import StockDataManager
    
    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in environment")
        return 0
    
    data_manager = StockDataManager(api_key=api_key, data_root="data")
    success_count = 0
    
    for ticker in tickers:
        try:
            print(f"  Fetching {ticker}...", end=" ", flush=True)
            result = data_manager.run_full_etl(ticker, force_recompute=False)
            if result["success"]:
                success_count += 1
                print("✅")
            else:
                print(f"❌ {result.get('errors', ['Unknown error'])}")
        except Exception as e:
            print(f"❌ {str(e)}")
            logger.error(f"Failed to fetch {ticker}: {e}")
    
    return success_count


def _update_simple_monitor_list(
    file_path: str,
    tickers: Set[str],
    description: str
) -> None:
    """Update simple monitor list (production format)."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        "version": "1.0",
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "description": description,
        "tickers": sorted(tickers)
    }
    
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


