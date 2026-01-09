"""
Scorer Testing Script
Test scoring strategies on monitor list stocks.
"""
import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.analysis.scorers import SimpleScorer, EnhancedScorer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_stock_data(ticker: str, data_root: str = './data'):
    """Load all data for a ticker."""
    data_root = Path(data_root)
    
    # Load features
    features_path = data_root / 'features' / f"{ticker}_features.parquet"
    if not features_path.exists():
        raise FileNotFoundError(f"Features not found for {ticker}. Run 'python src/main.py' first.")
    
    df_features = pd.read_parquet(features_path)
    if 'Date' in df_features.columns:
        df_features['Date'] = pd.to_datetime(df_features['Date'])
        df_features = df_features.set_index('Date')
    else:
        df_features.index = pd.to_datetime(df_features.index)
    
    # Load trades (optional)
    trades_path = data_root / 'raw_trades' / f"{ticker}_trades.parquet"
    if trades_path.exists():
        df_trades = pd.read_parquet(trades_path)
        if 'Section' in df_trades.columns:
            df_trades = df_trades[df_trades['Section'] == 'TSEPrime'].copy()
        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
    else:
        df_trades = pd.DataFrame()
    
    # Load financials (optional)
    financials_path = data_root / 'raw_financials' / f"{ticker}_financials.parquet"
    if financials_path.exists():
        df_financials = pd.read_parquet(financials_path)
        df_financials['DiscDate'] = pd.to_datetime(df_financials['DiscDate'])
    else:
        df_financials = pd.DataFrame()
    
    # Load metadata (optional)
    metadata_path = data_root / 'metadata' / f"{ticker}_metadata.json"
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    else:
        metadata = {}
    
    return df_features, df_trades, df_financials, metadata


def test_single_ticker(ticker: str, scorer):
    """Test scorer on a single ticker."""
    print(f"\n{'='*70}")
    print(f"Testing {ticker} with {scorer.strategy_name}")
    print(f"{'='*70}")
    
    try:
        # Load data
        df_features, df_trades, df_financials, metadata = load_stock_data(ticker)
        
        # Run scorer
        result = scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
        
        # Print results
        print(f"\n📊 Score Result:")
        print(f"  Ticker:         {result.ticker}")
        print(f"  Total Score:    {result.total_score:.1f}/100")
        print(f"  Signal:         {result.signal_strength}")
        print(f"  Strategy:       {result.strategy_name}")
        
        print(f"\n🔍 Score Breakdown:")
        for component, score in result.breakdown.items():
            print(f"  {component:20s} {score:6.1f}")
        
        if result.risk_flags:
            print(f"\n⚠️  Risk Flags: {', '.join(result.risk_flags)}")
        
        print(f"\n📈 Latest Data:")
        latest = df_features.iloc[-1]
        print(f"  Date:           {df_features.index[-1].strftime('%Y-%m-%d')}")
        print(f"  Close:          ¥{latest['Close']:,.0f}")
        print(f"  RSI:            {latest['RSI']:.1f}")
        print(f"  MACD:           {latest['MACD']:.2f}")
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to test {ticker}: {e}")
        return None


def test_all_monitor_list(scorer_class=EnhancedScorer):
    """Test scorer on all stocks in monitor list."""
    print("\n" + "="*70)
    print(f"Testing All Monitor List Stocks with {scorer_class.__name__}")
    print("="*70)
    
    # Load monitor list
    monitor_file = Path('data/monitor_list.json')
    with open(monitor_file, 'r', encoding='utf-8') as f:
        data = json.load(f)
        tickers = [ticker['code'] for ticker in data.get('tickers', [])]
    
    print(f"\nFound {len(tickers)} tickers in monitor list")
    
    # Test each ticker
    scorer = scorer_class()
    results = []
    
    for ticker in tickers:
        result = test_single_ticker(ticker, scorer)
        if result:
            results.append(result)
    
    # Summary table
    print("\n" + "="*70)
    print("SUMMARY - All Stocks Ranked by Score")
    print("="*70)
    print(f"{'Ticker':<8} {'Name':<20} {'Score':<8} {'Signal':<15} {'Risk Flags'}")
    print("-"*70)
    
    # Sort by score
    results.sort(key=lambda x: x.total_score, reverse=True)
    
    for result in results:
        # Get name from monitor list
        ticker_info = next((t for t in data['tickers'] if t['code'] == result.ticker), None)
        name = ticker_info['name'][:18] if ticker_info else "Unknown"
        
        risk_str = ", ".join(result.risk_flags) if result.risk_flags else "-"
        
        print(f"{result.ticker:<8} {name:<20} {result.total_score:6.1f}   {result.signal_strength:<15} {risk_str}")
    
    print("="*70)


def compare_scorers(ticker: str):
    """Compare SimpleScorer vs EnhancedScorer on same stock."""
    print(f"\n{'='*70}")
    print(f"Scorer Comparison for {ticker}")
    print(f"{'='*70}")
    
    # Load data once
    df_features, df_trades, df_financials, metadata = load_stock_data(ticker)
    
    # Test both scorers
    simple = SimpleScorer()
    enhanced = EnhancedScorer()
    
    result_simple = simple.evaluate(ticker, df_features, df_trades, df_financials, metadata)
    result_enhanced = enhanced.evaluate(ticker, df_features, df_trades, df_financials, metadata)
    
    # Print comparison
    print(f"\n{'Metric':<25} {'SimpleScorer':<20} {'EnhancedScorer':<20}")
    print("-"*70)
    print(f"{'Total Score':<25} {result_simple.total_score:6.1f}/100         {result_enhanced.total_score:6.1f}/100")
    print(f"{'Signal':<25} {result_simple.signal_strength:<20} {result_enhanced.signal_strength:<20}")
    
    print(f"\n{'Component Breakdown':<25} {'Simple':<20} {'Enhanced':<20}")
    print("-"*70)
    
    for component in result_simple.breakdown.keys():
        simple_val = result_simple.breakdown.get(component, 0)
        enhanced_val = result_enhanced.breakdown.get(component, 0)
        diff = enhanced_val - simple_val
        diff_str = f"({diff:+.1f})"
        print(f"{component:<25} {simple_val:6.1f}              {enhanced_val:6.1f} {diff_str}")


def main():
    """Main test function."""
    load_dotenv()
    
    print("\n" + "="*70)
    print("SCORER TESTING MENU")
    print("="*70)
    print("1. Test single ticker with EnhancedScorer")
    print("2. Test all monitor list stocks")
    print("3. Compare SimpleScorer vs EnhancedScorer")
    print("4. Quick test on random ticker")
    print("="*70)
    
    choice = input("\nEnter choice (1-4) or press Enter for option 2: ").strip()
    
    if choice == "1":
        ticker = input("Enter ticker code (e.g., 8035): ").strip()
        test_single_ticker(ticker, EnhancedScorer())
    
    elif choice == "3":
        ticker = input("Enter ticker code (e.g., 8035): ").strip()
        compare_scorers(ticker)
    
    elif choice == "4":
        ticker = "8035"  # Default
        test_single_ticker(ticker, EnhancedScorer())
    
    else:
        # Default: test all
        test_all_monitor_list(EnhancedScorer)


if __name__ == "__main__":
    main()
