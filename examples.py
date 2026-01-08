"""
Advanced Usage Examples for J-Stock-Analyzer (Data Lake Architecture)
Demonstrates the ETL pipeline and data lake features.
"""
import os
from dotenv import load_dotenv
from src.data.stock_data_manager import StockDataManager
from src.data.pipeline import StockETLPipeline, run_daily_update
import pandas as pd

# Load environment
load_dotenv()
api_key = os.getenv('JQUANTS_API_KEY')


# ============================================================
# Example 1: Single Stock ETL (Full Pipeline)
# ============================================================
def example_single_stock_etl():
    """Complete ETL for a single stock."""
    print("Example 1: Single Stock Full ETL")
    print("-" * 60)
    
    manager = StockDataManager(api_key=api_key)
    
    ticker = '6758'  # Sony
    result = manager.run_full_etl(ticker)
    
    print(f"Result: {result}")
    
    # Show what was created
    print("\nFiles created:")
    for name, path in manager.dirs.items():
        files = list(path.glob(f"{ticker}*"))
        if files:
            print(f"  {name:20s} {len(files)} files")
            for f in files:
                print(f"    - {f.name}")


# ============================================================
# Example 2: Batch Processing with Progress Bar
# ============================================================
def example_batch_processing():
    """Process multiple stocks with tqdm progress bar."""
    print("\nExample 2: Batch Processing")
    print("-" * 60)
    
    pipeline = StockETLPipeline(api_key=api_key)
    
    tickers = ['6758', '7203', '9984', '6861']  # Sony, Toyota, SoftBank, Keyence
    
    summary = pipeline.run_batch(tickers, fetch_aux_data=True)
    pipeline.print_summary()
    
    # Show failed tickers
    failed = pipeline.get_failed_tickers()
    if failed:
        print(f"\nFailed tickers: {failed}")


# ============================================================
# Example 3: Access Data Lake Layers
# ============================================================
def example_read_data_lake():
    """Read data from different layers of the data lake."""
    print("\nExample 3: Reading from Data Lake")
    print("-" * 60)
    
    manager = StockDataManager(api_key=api_key)
    ticker = '6758'
    
    # Read raw prices
    raw_path = manager.dirs['raw_prices'] / f"{ticker}.parquet"
    if raw_path.exists():
        df_raw = pd.read_parquet(raw_path)
        print(f"\n📊 Raw Prices: {len(df_raw)} rows")
        print(df_raw.tail(3))
    
    # Read features (with indicators)
    features_path = manager.dirs['features'] / f"{ticker}_features.parquet"
    if features_path.exists():
        df_features = pd.read_parquet(features_path)
        print(f"\n🔬 Features: {len(df_features)} rows, {len(df_features.columns)} columns")
        print(df_features[['Date', 'Close', 'EMA_20', 'RSI', 'MACD']].tail(3))
    
    # Read financials
    fin_path = manager.dirs['raw_financials'] / f"{ticker}_financials.parquet"
    if fin_path.exists():
        df_fin = pd.read_parquet(fin_path)
        print(f"\n💰 Financials: {len(df_fin)} records")
        print(df_fin.head(2))


# ============================================================
# Example 4: Incremental Update Demo
# ============================================================
def example_incremental_update():
    """Demonstrate incremental update logic."""
    print("\nExample 4: Incremental Update")
    print("-" * 60)
    
    manager = StockDataManager(api_key=api_key)
    ticker = '6758'
    
    # First run (or if data exists, will just update)
    print("Run 1: Fetching/updating data...")
    df1 = manager.fetch_and_update_ohlc(ticker)
    print(f"  Rows after run 1: {len(df1)}")
    
    # Second run immediately (should skip - already up-to-date)
    print("\nRun 2: Fetching/updating data again...")
    df2 = manager.fetch_and_update_ohlc(ticker)
    print(f"  Rows after run 2: {len(df2)}")
    
    print(f"\n✅ Incremental logic works! (Same row count: {len(df1) == len(df2)})")


# ============================================================
# Example 5: Custom Feature Engineering
# ============================================================
def example_custom_features():
    """Add custom features to the data lake."""
    print("\nExample 5: Custom Feature Engineering")
    print("-" * 60)
    
    manager = StockDataManager(api_key=api_key)
    ticker = '6758'
    
    # Load existing features
    features_path = manager.dirs['features'] / f"{ticker}_features.parquet"
    if not features_path.exists():
        print("Run compute_features() first!")
        return
    
    df = pd.read_parquet(features_path)
    
    # Add custom features
    df['Price_Change_%'] = df['Close'].pct_change() * 100
    df['Volume_Ratio'] = df['Volume'] / df['Volume_SMA_20']
    df['EMA_Cross'] = (df['EMA_20'] > df['EMA_50']).astype(int)
    
    # Save back
    manager._atomic_save(df, features_path)
    
    print(f"✅ Added 3 custom features")
    print(f"Columns: {list(df.columns[-6:])}")


# ============================================================
# Example 6: Daily Update Workflow (for Cron Jobs)
# ============================================================
def example_daily_workflow():
    """Simulate a daily update workflow."""
    print("\nExample 6: Daily Update Workflow")
    print("-" * 60)
    
    tickers = ['6758', '7203']
    
    # Use convenience function (fast - no aux data)
    run_daily_update(api_key, tickers)


# ============================================================
# Example 7: Screen Stocks Using Features
# ============================================================
def example_screening():
    """Screen stocks based on technical conditions."""
    print("\nExample 7: Stock Screening")
    print("-" * 60)
    
    manager = StockDataManager(api_key=api_key)
    features_dir = manager.dirs['features']
    
    bullish_stocks = []
    
    # Scan all feature files
    for file_path in features_dir.glob('*_features.parquet'):
        ticker = file_path.stem.replace('_features', '')
        df = pd.read_parquet(file_path)
        
        if df.empty:
            continue
        
        latest = df.iloc[-1]
        
        # Screening criteria
        is_above_ema_200 = latest['Close'] > latest['EMA_200']
        is_rsi_bullish = 40 < latest['RSI'] < 70
        is_macd_positive = latest['MACD'] > latest['MACD_Signal']
        
        if is_above_ema_200 and is_rsi_bullish and is_macd_positive:
            bullish_stocks.append({
                'ticker': ticker,
                'price': latest['Close'],
                'rsi': latest['RSI'],
                'macd': latest['MACD']
            })
            print(f"✅ {ticker}: Bullish")
        else:
            print(f"⚠️  {ticker}: Not bullish")
    
    if bullish_stocks:
        print(f"\n🎯 Found {len(bullish_stocks)} bullish stocks!")
    else:
        print("\n😞 No bullish stocks found")


# ============================================================
# Run Examples
# ============================================================
if __name__ == "__main__":
    print("="*60)
    print("J-Stock-Analyzer - Data Lake Examples")
    print("="*60)
    
    examples = [
        ("Single Stock ETL", example_single_stock_etl),
        ("Batch Processing", example_batch_processing),
        ("Read Data Lake", example_read_data_lake),
        ("Incremental Update", example_incremental_update),
        ("Custom Features", example_custom_features),
        ("Daily Workflow", example_daily_workflow),
        ("Stock Screening", example_screening),
    ]
    
    print("\nAvailable Examples:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    
    print("\nUncomment the example you want to run below:")
    print("-" * 60)
    
    # Uncomment to run specific examples:
    # example_single_stock_etl()
    # example_batch_processing()
    # example_read_data_lake()
    # example_incremental_update()
    # example_custom_features()
    # example_daily_workflow()
    # example_screening()

