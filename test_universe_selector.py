"""
Universe Selection Test Script
Tests the stock selector with limited stocks for debugging.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.data.stock_data_manager import StockDataManager
from src.universe.stock_selector import UniverseSelector

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_test_tickers(limit: int = 10) -> list:
    """Load ticker codes from monitor_list for testing."""
    import json
    
    # Try JSON format first
    json_path = Path('data/monitor_list.json')
    if json_path.exists():
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            tickers = [item['code'] for item in data.get('tickers', [])]
            logger.info(f"Loaded {len(tickers)} tickers from monitor_list.json")
            return tickers[:limit]
    
    # Fallback to TXT format
    txt_path = Path('data/monitor_list.txt')
    if txt_path.exists():
        tickers = []
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    tickers.append(line)
        logger.info(f"Loaded {len(tickers)} tickers from monitor_list.txt")
        return tickers[:limit]
    
    # Hardcoded fallback
    logger.warning("No monitor_list found, using hardcoded tickers")
    return ["8035", "8306", "7974", "7011", "6861", "8058", "6501", "4063", "7203", "1321"][:limit]


def main():
    """Run universe selection test."""
    # Load environment
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in .env file")
        return
    
    print("\n" + "="*80)
    print("J-Stock Universe Selector - Test Mode")
    print("="*80 + "\n")
    
    # Initialize components
    logger.info("Initializing StockDataManager...")
    manager = StockDataManager(api_key=api_key)
    
    logger.info("Initializing UniverseSelector...")
    selector = UniverseSelector(manager)
    
    # Load test tickers from monitor_list
    test_tickers = load_test_tickers(limit=10)
    logger.info(f"Test tickers: {test_tickers}")
    
    # Run selection in TEST MODE (only 10 stocks)
    logger.info("\n🧪 Starting selection in TEST MODE (using monitor_list tickers)...\n")
    
    df_top = selector.run_selection(
        top_n=5,  # Select top 5 from test set
        ticker_list=test_tickers  # Use monitor_list instead of API fetch
    )
    
    if df_top.empty:
        logger.error("Selection failed - no results")
        return
    
    # Print summary
    selector.print_summary(df_top, n=10)
    
    # Save results
    logger.info("Saving selection results...")
    json_path, csv_path = selector.save_selection_results(df_top, format='both')
    
    print(f"\n✅ Test completed successfully!")
    print(f"📄 JSON: {json_path}")
    print(f"📊 CSV:  {csv_path}\n")


if __name__ == "__main__":
    main()
