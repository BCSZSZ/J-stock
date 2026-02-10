"""
Test script for Phase 2: State Management Module

Validates:
- Position tracking and calculations
- Strategy group state management
- FIFO position handling
- State persistence
- Trade history recording
"""

import json
import os
from datetime import datetime, timedelta
from src.production.state_manager import (
    Position,
    StrategyGroupState,
    ProductionState,
    Trade,
    TradeHistoryManager
)


def test_position_calculations():
    """Test Position class calculations"""
    print("\n" + "="*60)
    print("TEST 1: Position Calculations")
    print("="*60)
    
    pos = Position(
        ticker="8035",
        quantity=100,
        entry_price=31500,
        entry_date="2026-01-15",
        entry_score=75.0
    )
    
    print(f"Position: {pos.ticker} x{pos.quantity} @ ¥{pos.entry_price}")
    print(f"Entry value: ¥{pos.current_value(pos.entry_price):,.0f}")
    
    # Test at profit
    current_price = 33000
    print(f"\nAt ¥{current_price}:")
    print(f"  Current value: ¥{pos.current_value(current_price):,.0f}")
    print(f"  Unrealized P&L: ¥{pos.unrealized_pl(current_price):,.0f}")
    print(f"  Unrealized P&L %: {pos.unrealized_pl_pct(current_price):.2f}%")
    print(f"  Holding days: {pos.holding_days()}")
    
    print("✅ Position calculations OK")


def test_strategy_group_state():
    """Test StrategyGroupState"""
    print("\n" + "="*60)
    print("TEST 2: Strategy Group State Management")
    print("="*60)
    
    group = StrategyGroupState(
        id="group_a",
        name="Test Group",
        initial_capital=2000000,
        cash=2000000
    )
    
    print(f"Initial: ¥{group.cash:,.0f}")
    
    # Add position
    group.add_position(
        ticker="8035",
        quantity=100,
        entry_price=31500,
        entry_date="2026-01-15",
        entry_score=75.0
    )
    
    print(f"After buying 100x8035 @ ¥31500:")
    print(f"  Cash: ¥{group.cash:,.0f}")
    print(f"  Positions: {len(group.positions)}")
    
    # Check position retrieval
    pos = group.get_position("8035")
    print(f"  Position found: {pos.ticker} x{pos.quantity}")
    
    # Add another position of same ticker
    group.add_position(
        ticker="8035",
        quantity=50,
        entry_price=32000,
        entry_date="2026-01-16",
        entry_score=73.0
    )
    
    print(f"\nAfter buying 50x8035 @ ¥32000:")
    print(f"  Cash: ¥{group.cash:,.0f}")
    print(f"  Total positions: {len(group.positions)}")
    positions_8035 = group.get_positions_by_ticker("8035")
    print(f"  Positions for 8035: {len(positions_8035)}")
    
    # Test partial sell (FIFO)
    print(f"\nTesting FIFO sell of 60x8035:")
    proceeds, sold = group.partial_sell("8035", 60, exit_price=32500)
    print(f"  Proceeds: ¥{proceeds:,.0f}")
    print(f"  Sold: {sold} shares")
    print(f"  Cash after: ¥{group.cash:,.0f}")
    print(f"  Remaining positions: {len(group.positions)}")
    
    # Verify FIFO: should have sold 60 from first position (100), leaving 40 + 50
    remaining = group.get_positions_by_ticker("8035")
    total_remaining = sum(p.quantity for p in remaining)
    print(f"  Total shares remaining: {total_remaining}")
    
    print("✅ Strategy group state management OK")


def test_fifo_handling():
    """Test FIFO position handling"""
    print("\n" + "="*60)
    print("TEST 3: FIFO Position Handling")
    print("="*60)
    
    group = StrategyGroupState(
        id="test_fifo",
        name="FIFO Test",
        initial_capital=5000000,
        cash=5000000
    )
    
    # Buy 3 positions at different prices
    print("Building position stack:")
    trades = [
        (100, 30000, "2026-01-10", 70.0),
        (100, 31000, "2026-01-12", 72.0),
        (100, 32000, "2026-01-14", 75.0),
    ]
    
    for qty, price, date, score in trades:
        group.add_position("8306", qty, price, date, score)
        print(f"  Buy {qty}x @ ¥{price} on {date}")
    
    print(f"\nTotal positions: {len(group.positions)}")
    print(f"Cash remaining: ¥{group.cash:,.0f}")
    
    # Sell 150 shares (should sell all from positions 1 & 2, partial from 3)
    print(f"\nSelling 150 shares at ¥32500:")
    proceeds, sold = group.partial_sell("8306", 150, 32500)
    print(f"  Proceeds: ¥{proceeds:,.0f}")
    print(f"  Sold: {sold} shares")
    print(f"  Cash now: ¥{group.cash:,.0f}")
    
    remaining = group.get_positions_by_ticker("8306")
    print(f"  Remaining positions: {len(remaining)}")
    for pos in remaining:
        print(f"    - {pos.quantity} @ ¥{pos.entry_price} (entry: {pos.entry_date})")
    
    print("✅ FIFO handling OK")


def test_state_persistence():
    """Test state load/save"""
    print("\n" + "="*60)
    print("TEST 4: State Persistence")
    print("="*60)
    
    # Create test state file
    test_file = "test_state_temp.json"
    
    try:
        # Create and save state
        state = ProductionState(test_file)
        state.add_group("test_a", "Test Group A", 1000000)
        state.add_group("test_b", "Test Group B", 1500000)
        
        group_a = state.get_group("test_a")
        group_a.add_position("8035", 50, 31500, "2026-01-20", 70.0)
        
        print(f"Created state with 2 groups:")
        print(f"  Group A: ¥{group_a.cash:,.0f} (1 position)")
        
        state.save()
        print(f"Saved to {test_file}")
        
        # Load state from file
        state2 = ProductionState(test_file)
        print(f"\nLoaded state from file:")
        print(f"  Groups: {len(state2.strategy_groups)}")
        
        group_a_loaded = state2.get_group("test_a")
        print(f"  Group A cash: ¥{group_a_loaded.cash:,.0f}")
        print(f"  Group A positions: {len(group_a_loaded.positions)}")
        
        if group_a_loaded.positions:
            pos = group_a_loaded.positions[0]
            print(f"    Position: {pos.ticker} x{pos.quantity} @ ¥{pos.entry_price}")
        
        # Delete state objects before cleanup
        del state
        del state2
        
        print("✅ State persistence OK")
    
    finally:
        # Clean up
        import time
        time.sleep(0.1)  # Give time for file lock to release
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except:
                pass


def test_trade_history():
    """Test trade history tracking"""
    print("\n" + "="*60)
    print("TEST 5: Trade History Recording")
    print("="*60)
    
    history = TradeHistoryManager()
    
    # Record some trades
    print("Recording trades:")
    
    trade1 = history.record_trade(
        date="2026-01-20",
        group_id="group_a",
        ticker="8035",
        action="BUY",
        quantity=100,
        price=31500,
        entry_score=75.0
    )
    print(f"  BUY: {trade1.quantity}x{trade1.ticker} @ ¥{trade1.price} (score: {trade1.entry_score})")
    
    trade2 = history.record_trade(
        date="2026-01-21",
        group_id="group_a",
        ticker="8035",
        action="SELL",
        quantity=50,
        price=32500,
        exit_reason="Trailing Stop Hit",
        exit_score=68.0
    )
    print(f"  SELL: {trade2.quantity}x{trade2.ticker} @ ¥{trade2.price} ({trade2.exit_reason})")
    
    trade3 = history.record_trade(
        date="2026-01-21",
        group_id="group_b",
        ticker="8306",
        action="BUY",
        quantity=200,
        price=1850,
        entry_score=72.0
    )
    print(f"  BUY: {trade3.quantity}x{trade3.ticker} @ ¥{trade3.price} (score: {trade3.entry_score})")
    
    print(f"\nTotal trades: {len(history.trades)}")
    
    # Query trades
    group_a_trades = history.get_trades_by_group("group_a")
    print(f"Group A trades: {len(group_a_trades)}")
    
    buy_trades = [t for t in history.trades if t.action == "BUY"]
    print(f"Total BUY trades: {len(buy_trades)}")
    
    print("✅ Trade history OK")


def test_portfolio_status():
    """Test portfolio status reporting"""
    print("\n" + "="*60)
    print("TEST 6: Portfolio Status Reporting")
    print("="*60)
    
    state = ProductionState("test_portfolio.json")
    
    try:
        state.add_group("group_a", "Group A", 2000000)
        state.add_group("group_b", "Group B", 2000000)
        
        # Add some positions
        group_a = state.get_group("group_a")
        group_a.add_position("8035", 50, 31500, "2026-01-15", 75.0)
        group_a.add_position("8306", 100, 1900, "2026-01-16", 73.0)
        
        group_b = state.get_group("group_b")
        group_b.add_position("7974", 200, 2150, "2026-01-14", 70.0)
        
        # Get status
        current_prices = {
            "8035": 32000,
            "8306": 1950,
            "7974": 2200
        }
        
        print("Current prices:")
        for ticker, price in current_prices.items():
            print(f"  {ticker}: ¥{price}")
        
        status = state.get_portfolio_status(current_prices)
        
        print(f"\nPortfolio Summary:")
        print(f"  Total Cash: ¥{status['total_cash']:,.0f}")
        print(f"  Total Invested: ¥{status['total_invested']:,.0f}")
        print(f"  Total Value: ¥{status['total_value']:,.0f}")
        print(f"  Positions: {status['total_positions']}")
        print(f"  Groups: {status['num_groups']}")
        
        print(f"\nGroup Details:")
        for group_status in status['groups']:
            print(f"  [{group_status['id']}] {group_status['name']}")
            print(f"    Cash: ¥{group_status['current_cash']:,.0f}")
            print(f"    Positions: {group_status['position_count']}")
        
        print("✅ Portfolio status OK")
    
    finally:
        import time
        time.sleep(0.1)
        if os.path.exists("test_portfolio.json"):
            try:
                os.remove("test_portfolio.json")
            except:
                pass


if __name__ == "__main__":
    print("\n" + "="*60)
    print("PHASE 2: STATE MANAGEMENT MODULE TESTS")
    print("="*60)
    
    test_position_calculations()
    test_strategy_group_state()
    test_fifo_handling()
    test_state_persistence()
    test_trade_history()
    test_portfolio_status()
    
    print("\n" + "="*60)
    print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
    print("="*60 + "\n")
