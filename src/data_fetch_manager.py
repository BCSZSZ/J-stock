"""
J-Stock-Analyzer Data Fetch Manager
数据抓取管理器 - 从JQuants API批量获取股票数据
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import List

from dotenv import load_dotenv

# Add project root to path for absolute imports (AWS Lambda compatible)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.client.jquants_client import JQuantsV2Client
from src.data.benchmark_manager import update_benchmarks
from src.data.pipeline import StockETLPipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


# ============================================================
# MONITOR LIST LOADER
# ============================================================


def load_monitor_list(file_path: str = "data/monitor_list.json") -> List[str]:
    """
    Load ticker codes from monitor list file (single source of truth).

    Args:
        file_path: Path to monitor list file (default: data/monitor_list.json).

    Returns:
        List of ticker codes.

    Raises:
        FileNotFoundError: If monitor list file does not exist.
    """
    monitor_file = Path(file_path)

    if not monitor_file.exists():
        logger.error(f"Monitor list not found at {file_path}")
        raise FileNotFoundError(f"Monitor list file does not exist: {file_path}")

    try:
        # JSON format with tickers array
        if monitor_file.suffix == ".json":
            with open(monitor_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                tickers = [stock["code"] for stock in data["tickers"]]
                logger.info(f"Loaded {len(tickers)} stocks from {file_path}")
                return tickers

        # TXT format (legacy support)
        tickers = []
        with open(monitor_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    tickers.append(line)
        logger.info(f"Loaded {len(tickers)} tickers from {file_path}")
        return tickers

    except Exception as e:
        logger.error(f"Failed to load monitor list: {e}")
        raise


def main(recompute_features: bool = False):
    """Main function to run the ETL pipeline."""
    # Load environment variables
    load_dotenv()

    api_key = os.getenv("JQUANTS_API_KEY")

    if not api_key and not recompute_features:
        logger.error("JQUANTS_API_KEY not found in environment variables!")
        logger.error("Please create a .env file with: JQUANTS_API_KEY=your_key_here")
        return

    # Load tickers from monitor list JSON
    tickers = load_monitor_list()

    logger.info("=" * 60)
    logger.info("J-Stock-Analyzer - Batch ETL Pipeline")
    logger.info("=" * 60)
    logger.info(f"Processing {len(tickers)} tickers")
    logger.info("")

    if not recompute_features:
        # Step 1: Update benchmark data (TOPIX)
        logger.info("Updating benchmark indices (TOPIX)...")
        client = JQuantsV2Client(api_key)
        benchmark_result = update_benchmarks(client)

        if benchmark_result["success"]:
            logger.info(
                f"✅ TOPIX updated: {benchmark_result['topix_records']} records"
            )
        else:
            logger.warning(
                f"⚠️ TOPIX update issue: {benchmark_result.get('error', 'Unknown')}"
            )

    # Step 2: Initialize pipeline
    pipeline = StockETLPipeline(api_key)

    # Step 3: Run batch processing with full ETL or recompute-only
    summary = pipeline.run_batch(
        tickers,
        fetch_aux_data=not recompute_features,
        recompute_features=recompute_features,
    )

    # Step 4: Print summary
    pipeline.print_summary()

    # Show data lake structure
    print("\n" + "=" * 60)
    print("Data Lake Structure Created:")
    print("=" * 60)
    for name, path in pipeline.manager.dirs.items():
        file_count = len(list(path.glob("*")))
        print(f"  {name:20s} {file_count} files")
    print("=" * 60)

    logger.info("\nETL Pipeline complete!")


if __name__ == "__main__":
    main()
