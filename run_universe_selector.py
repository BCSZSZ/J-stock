"""
Universe Selection - Production Run
Selects top 50 stocks from a predefined universe.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import logging
import json

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


def load_universe_from_file(file_path: str) -> list:
    """
    Load universe ticker list from a file.
    
    Supports:
        - TXT: One ticker per line (# for comments)
        - JSON: {"codes": ["1234", "5678", ...]}
        
    Args:
        file_path: Path to universe file.
        
    Returns:
        List of ticker codes.
    """
    path = Path(file_path)
    
    if not path.exists():
        logger.error(f"Universe file not found: {file_path}")
        return []
    
    # JSON format
    if path.suffix == '.json':
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Support multiple formats
            if 'codes' in data:
                return data['codes']
            elif 'tickers' in data:
                # monitor_list.json format
                return [t['code'] for t in data['tickers']]
            else:
                logger.error("Unknown JSON format. Expected 'codes' or 'tickers' key.")
                return []
    
    # TXT format
    elif path.suffix == '.txt':
        tickers = []
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    tickers.append(line)
        return tickers
    
    else:
        logger.error(f"Unsupported file format: {path.suffix}")
        return []


def main():
    """Run full universe selection."""
    import argparse
    
    parser = argparse.ArgumentParser(description='J-Stock Universe Selector')
    parser.add_argument(
        '--universe-file', 
        type=str,
        help='Path to file containing universe ticker codes (TXT or JSON)'
    )
    parser.add_argument(
        '--top-n', 
        type=int, 
        default=50,
        help='Number of top stocks to select (default: 50)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Run in test mode (processes only first 10 stocks)'
    )
    
    args = parser.parse_args()
    
    # Load environment
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key:
        logger.error("JQUANTS_API_KEY not found in .env file")
        return
    
    print("\n" + "="*80)
    print("J-Stock Universe Selector - Production Run")
    print("="*80 + "\n")
    
    # Initialize components
    logger.info("Initializing StockDataManager...")
    manager = StockDataManager(api_key=api_key)
    
    logger.info("Initializing UniverseSelector...")
    selector = UniverseSelector(manager)
    
    # Load universe
    ticker_list = None
    if args.universe_file:
        logger.info(f"Loading universe from file: {args.universe_file}")
        ticker_list = load_universe_from_file(args.universe_file)
        
        if not ticker_list:
            logger.error("Failed to load universe from file")
            return
        
        logger.info(f"Loaded {len(ticker_list)} tickers from file")
    else:
        logger.info("No universe file provided. Will fetch from J-Quants API.")
        logger.info("NOTE: This requires API access to /v1/listed/info endpoint")
    
    # Test mode override
    if args.test:
        logger.warning("🧪 TEST MODE: Processing only first 10 stocks")
        if ticker_list:
            ticker_list = ticker_list[:10]
    
    # Run selection
    logger.info(f"\n🚀 Starting universe selection (Top {args.top_n})...\n")
    
    df_top = selector.run_selection(
        top_n=args.top_n,
        ticker_list=ticker_list
    )
    
    if df_top.empty:
        logger.error("Selection failed - no results")
        return
    
    # Print summary
    selector.print_summary(df_top, n=20)
    
    # Save results
    logger.info("Saving selection results...")
    json_path, csv_path = selector.save_selection_results(df_top, format='both')
    
    print(f"\n✅ Selection completed successfully!")
    print(f"📄 JSON: {json_path}")
    print(f"📊 CSV:  {csv_path}\n")
    
    # Optional: Save as new monitor_list
    save_as_monitor = input("\n❓ Save top results as new monitor_list.json? (y/n): ")
    if save_as_monitor.lower() == 'y':
        import shutil
        backup_path = Path('data/monitor_list_backup.json')
        original_path = Path('data/monitor_list.json')
        
        # Backup existing
        if original_path.exists():
            shutil.copy(original_path, backup_path)
            logger.info(f"Backed up existing monitor_list to {backup_path}")
        
        # Copy new selection
        shutil.copy(json_path, original_path)
        logger.info(f"✅ Saved top {len(df_top)} stocks as new monitor_list.json")


if __name__ == "__main__":
    main()
