"""
Exit Strategy Testing Script
Test exit strategies on current or simulated positions.
"""
import os
import sys
import json
import logging
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.analysis.exiters import ATRExiter, LayeredExiter, Position
from src.analysis.scorers import EnhancedScorer

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
    
    # Load trades
    trades_path = data_root / 'raw_trades' / f"{ticker}_trades.parquet"
    if trades_path.exists():
        df_trades = pd.read_parquet(trades_path)
        if 'Section' in df_trades.columns:
            df_trades = df_trades[df_trades['Section'] == 'TSEPrime'].copy()
        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
    else:
        df_trades = pd.DataFrame()
    
    # Load financials
    financials_path = data_root / 'raw_financials' / f"{ticker}_financials.parquet"
    if financials_path.exists():
        df_financials = pd.read_parquet(financials_path)
        df_financials['DiscDate'] = pd.to_datetime(df_financials['DiscDate'])
    else:
        df_financials = pd.DataFrame()
    
    # Load metadata
    metadata_path = data_root / 'metadata' / f"{ticker}_metadata.json"
    if metadata_path.exists():
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    else:
        metadata = {}
    
    return df_features, df_trades, df_financials, metadata


def create_sample_position(ticker: str, days_ago: int = 30) -> Position:
    """Create a sample position for testing."""
    # Load current data
    df_features, _, _, _ = load_stock_data(ticker)
    
    # Entry date: N days ago
    entry_idx = len(df_features) - days_ago
    entry_date = df_features.index[entry_idx]
    entry_price = df_features.iloc[entry_idx]['Close']
    
    # Calculate peak price since entry
    peak_price = df_features.iloc[entry_idx:]['High'].max()
    
    position = Position(
        ticker=ticker,
        entry_price=entry_price,
        entry_date=pd.Timestamp(entry_date),
        entry_score=75.0,  # Assume we bought on strong signal
        quantity=100,
        peak_price_since_entry=peak_price
    )
    
    return position


def test_exit_strategy(ticker: str, exiter, position: Position = None):
    """Test exit strategy on a position."""
    print(f"\n{'='*70}")
    print(f"Testing Exit Strategy: {exiter.strategy_name}")
    print(f"Ticker: {ticker}")
    print(f"{'='*70}")
    
    # Create sample position if not provided
    if position is None:
        position = create_sample_position(ticker, days_ago=30)
        print(f"\n📌 Sample Position Created (30 days ago):")
    else:
        print(f"\n📌 Testing Your Position:")
    
    print(f"  Entry Date:     {position.entry_date.strftime('%Y-%m-%d')}")
    print(f"  Entry Price:    ¥{position.entry_price:,.0f}")
    print(f"  Entry Score:    {position.entry_score:.1f}")
    print(f"  Quantity:       {position.quantity} shares")
    print(f"  Peak Price:     ¥{position.peak_price_since_entry:,.0f}")
    
    # Load data
    df_features, df_trades, df_financials, metadata = load_stock_data(ticker)
    
    # Get current score
    scorer = EnhancedScorer()
    current_score = scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
    
    # Evaluate exit
    signal = exiter.evaluate_exit(
        position=position,
        df_features=df_features,
        df_trades=df_trades,
        df_financials=df_financials,
        metadata=metadata,
        current_score=current_score
    )
    
    # Print results
    print(f"\n📊 Current Status:")
    latest = df_features.iloc[-1]
    print(f"  Current Date:   {df_features.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Current Price:  ¥{latest['Close']:,.0f}")
    print(f"  Current Score:  {current_score.total_score:.1f}/100")
    print(f"  P&L:            {signal.profit_loss_pct:+.2f}%")
    print(f"  Holding Days:   {signal.holding_days}")
    
    print(f"\n🚨 Exit Signal:")
    print(f"  Action:         {signal.action}")
    print(f"  Urgency:        {signal.urgency}")
    print(f"  Triggered By:   {signal.triggered_by}")
    print(f"  Reason:         {signal.reason}")
    
    # Calculate potential profit/loss
    current_price = latest['Close']
    pnl_jpy = (current_price - position.entry_price) * position.quantity
    print(f"\n💰 Financial Impact:")
    print(f"  P&L (¥):        ¥{pnl_jpy:+,.0f}")
    print(f"  P&L (%):        {signal.profit_loss_pct:+.2f}%")
    
    return signal


def compare_exit_strategies(ticker: str, position: Position = None):
    """Compare ATRExiter vs LayeredExiter on same position."""
    print(f"\n{'='*70}")
    print(f"Exit Strategy Comparison for {ticker}")
    print(f"{'='*70}")
    
    if position is None:
        position = create_sample_position(ticker, days_ago=30)
    
    # Test both exiters
    atr_exiter = ATRExiter()
    layered_exiter = LayeredExiter()
    
    print(f"\n1️⃣  Testing ATRExiter...")
    signal_atr = test_exit_strategy(ticker, atr_exiter, position)
    
    print(f"\n\n2️⃣  Testing LayeredExiter...")
    signal_layered = test_exit_strategy(ticker, layered_exiter, position)
    
    # Comparison table
    print(f"\n{'='*70}")
    print("COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"{'Metric':<25} {'ATRExiter':<25} {'LayeredExiter':<25}")
    print("-"*70)
    print(f"{'Action':<25} {signal_atr.action:<25} {signal_layered.action:<25}")
    print(f"{'Urgency':<25} {signal_atr.urgency:<25} {signal_layered.urgency:<25}")
    print(f"{'Triggered By':<25} {signal_atr.triggered_by:<25} {signal_layered.triggered_by:<25}")
    print("-"*70)
    print(f"\nATR Reason:     {signal_atr.reason}")
    print(f"Layered Reason: {signal_layered.reason}")


def test_your_position():
    """Test with user-provided position."""
    print("\n" + "="*70)
    print("TEST YOUR POSITION")
    print("="*70)
    
    ticker = input("Enter ticker code (e.g., 8035): ").strip()
    entry_price = float(input("Enter entry price (e.g., 31000): ").strip())
    entry_date_str = input("Enter entry date (YYYY-MM-DD, e.g., 2025-12-01): ").strip()
    entry_score = float(input("Enter entry score (0-100, e.g., 75): ").strip())
    quantity = int(input("Enter quantity (e.g., 100): ").strip())
    
    # Load data to calculate peak
    df_features, _, _, _ = load_stock_data(ticker)
    entry_date = pd.Timestamp(entry_date_str)
    
    # Find peak since entry
    mask = df_features.index >= entry_date
    peak_price = df_features.loc[mask, 'High'].max()
    
    # Create position
    position = Position(
        ticker=ticker,
        entry_price=entry_price,
        entry_date=entry_date,
        entry_score=entry_score,
        quantity=quantity,
        peak_price_since_entry=peak_price
    )
    
    # Ask which exiter to test
    print("\nWhich exit strategy?")
    print("1. ATRExiter")
    print("2. LayeredExiter")
    print("3. Compare both")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        test_exit_strategy(ticker, ATRExiter(), position)
    elif choice == "2":
        test_exit_strategy(ticker, LayeredExiter(), position)
    else:
        compare_exit_strategies(ticker, position)


def main():
    """Main test function."""
    load_dotenv()
    
    print("\n" + "="*70)
    print("EXIT STRATEGY TESTING MENU")
    print("="*70)
    print("1. Test sample position (30 days ago)")
    print("2. Test your own position")
    print("3. Compare ATR vs Layered strategies")
    print("="*70)
    
    choice = input("\nEnter choice (1-3) or press Enter for option 1: ").strip()
    
    if choice == "2":
        test_your_position()
    
    elif choice == "3":
        ticker = input("Enter ticker code (e.g., 8035): ").strip()
        compare_exit_strategies(ticker)
    
    else:
        # Default: test sample position
        ticker = input("Enter ticker code (e.g., 8035, or press Enter for 8035): ").strip()
        if not ticker:
            ticker = "8035"
        
        print("\nWhich exit strategy?")
        print("1. ATRExiter")
        print("2. LayeredExiter")
        print("3. Compare both")
        
        exiter_choice = input("Enter choice (1-3) or press Enter for option 3: ").strip()
        
        if exiter_choice == "1":
            test_exit_strategy(ticker, ATRExiter())
        elif exiter_choice == "2":
            test_exit_strategy(ticker, LayeredExiter())
        else:
            compare_exit_strategies(ticker)


if __name__ == "__main__":
    main()
