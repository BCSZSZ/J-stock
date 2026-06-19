#!/usr/bin/env python
"""
Recompute all stock features (force refresh) to add new indicators like SMA_25.

Usage:
    python tools/recompute_all_features.py [--sample N]

Options:
    --sample N  Only process first N stocks from monitor list (default: all)
"""

import argparse
import logging
import sys
from pathlib import Path

from src.config.runtime import get_config_file_path
from src.config.service import load_config
from src.data.stock_data_manager import StockDataManager
from src.utils.universe_loader import load_tickers_from_file

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _resolve_monitor_file(config: dict[str, object]) -> Path:
    production_cfg = config.get("production", {})
    if not isinstance(production_cfg, dict):
        production_cfg = {}
    data_cfg = config.get("data", {})
    if not isinstance(data_cfg, dict):
        data_cfg = {}
    monitor_path = (
        production_cfg.get("monitor_list_file")
        or data_cfg.get("monitor_list_file")
        or "data/monitor_list.json"
    )
    return Path(str(monitor_path))


def load_monitor_list(config_path: str | Path | None = None) -> list[str]:
    """Load monitor list from the runtime-selected config."""
    resolved_config_path = (
        Path(config_path) if config_path is not None else get_config_file_path()
    )
    try:
        config = load_config(str(resolved_config_path))
        monitor_file = _resolve_monitor_file(config)
    except Exception as e:
        logger.warning(
            "Failed to load config %s: %s, using default path",
            resolved_config_path,
            e,
        )
        monitor_file = Path("data/monitor_list.json")

    if not monitor_file.exists():
        raise FileNotFoundError(f"Monitor list not found: {monitor_file}")

    return load_tickers_from_file(monitor_file)


def main():
    parser = argparse.ArgumentParser(
        description="Recompute features for all monitored stocks with force_recompute=True"
    )
    parser.add_argument(
        "--sample", type=int, default=None, help="Process only first N stocks"
    )
    args = parser.parse_args()

    # Load monitor list
    try:
        stocks = load_monitor_list()
    except FileNotFoundError as e:
        logger.error(f"Error loading monitor list: {e}")
        sys.exit(1)

    if args.sample:
        stocks = stocks[: args.sample]

    logger.info(f"Recomputing features for {len(stocks)} stocks (force_recompute=True)")
    logger.info("This will add SMA_25 and update all indicators")

    # Initialize manager (read-only, no API key needed for recompute)
    manager = StockDataManager(api_key=None, data_root="data")

    success_count = 0
    error_count = 0

    for i, code in enumerate(stocks, 1):
        try:
            logger.info(f"[{i}/{len(stocks)}] Processing {code}...")
            df = manager.compute_features(code, force_recompute=True)

            if df.empty:
                logger.warning(f"[{code}] No data after recompute")
                error_count += 1
            else:
                logger.info(
                    f"[{code}] ✓ Recomputed {len(df)} rows, {len(df.columns)} features"
                )
                success_count += 1

        except Exception as e:
            logger.error(f"[{code}] ✗ Failed: {e}")
            error_count += 1

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Recompute Summary: {success_count} succeeded, {error_count} failed")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
