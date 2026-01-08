"""
J-Stock-Analyzer Main Entry Point
Demonstrates the batch ETL pipeline with Data Lake architecture.
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

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
# TARGET TICKERS (Easy to extend - add/remove as needed)
# ============================================================
# 严选 Top 10 (Sector Balanced & Growth Oriented)
TARGET_TICKERS = [
    "8035",  # Tokyo Electron (Semi Equip)
    "8306",  # MUFG Bank (Finance)
    "7974",  # Nintendo (Gaming)
    "7011",  # Mitsubishi Heavy (Defense)
    "6861",  # Keyence (Automation)
    "8058",  # Mitsubishi Corp (Trading/Energy)
    "6501",  # Hitachi (IT/Infrastructure)
    "4063",  # Shin-Etsu Chemical (Semi Materials)
    "7203",  # Toyota (Auto)
    "4568",  # Daiichi Sankyo (Pharma)
    "6098",  # Recruit Holdings (HR Tech)
]


def main():
    """Main function to run the ETL pipeline."""
    # Load environment variables
    load_dotenv()
    
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in environment variables!")
        logger.error("Please create a .env file with: JQUANTS_API_KEY=your_key_here")
        return
    
    # Use the curated ticker list
    tickers = TARGET_TICKERS
    
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