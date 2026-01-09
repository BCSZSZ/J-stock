"""
J-Stock-Analyzer Main Entry Point
Demonstrates the batch ETL pipeline with Data Lake architecture.
"""
import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
from typing import List

# Add project root to path for absolute imports (AWS Lambda compatible)
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.pipeline import StockETLPipeline, run_daily_update

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


# ============================================================
# MONITOR LIST LOADER
# ============================================================

def load_monitor_list(file_path: str = 'data/monitor_list.json') -> List[str]:
    """
    Load ticker codes from monitor_list.json.
    
    Args:
        file_path: Path to monitor list JSON file.
        
    Returns:
        List of ticker codes.
    """
    monitor_file = Path(file_path)
    
    if not monitor_file.exists():
        logger.warning(f"Monitor list not found at {file_path}, using fallback tickers")
        # Fallback to hardcoded list if JSON doesn't exist
        return [
            "8035", "8306", "7974", "7011", "6861", "8058",
            "6501", "4063", "7203", "4568", "6098"
        ]
    
    try:
        with open(monitor_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            tickers = [ticker['code'] for ticker in data.get('tickers', [])]
            logger.info(f"Loaded {len(tickers)} tickers from {file_path}")
            return tickers
    except Exception as e:
        logger.error(f"Failed to load monitor list: {e}")
        raise


def main():
    """Main function to run the ETL pipeline."""
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in environment variables!")
        logger.error("Please create a .env file with: JQUANTS_API_KEY=your_key_here")
        return
    
    # Load tickers from monitor list JSON
    tickers = load_monitor_list()
    
    logger.info("="*60)
    logger.info("J-Stock-Analyzer - Batch ETL Pipeline")
    logger.info("="*60)
    logger.info(f"Processing {len(tickers)} tickers")
    logger.info("")
    
    # Initialize pipeline
    pipeline = StockETLPipeline(api_key)
    
    # Run batch processing with full ETL
    summary = pipeline.run_batch(tickers, fetch_aux_data=True)
    
    # Print summary
    pipeline.print_summary()
    
    # Show data lake structure
    print("\n" + "="*60)
    print("Data Lake Structure Created:")
    print("="*60)
    for name, path in pipeline.manager.dirs.items():
        file_count = len(list(path.glob('*')))
        print(f"  {name:20s} {file_count} files")
    print("="*60)
    
    logger.info("\nETL Pipeline complete!")


if __name__ == "__main__":
    main()