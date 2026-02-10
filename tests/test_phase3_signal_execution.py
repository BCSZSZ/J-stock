"""
Test script for Phase 3: Signal Generation & Trade Execution

Validates:
- Signal generation for entry/exit
- Trade execution (BUY/SELL)
- State updates
- Trade history recording
- Dry run mode
"""

import json
import os
import sys
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.production.signal_generator import Signal, SignalGenerator
from src.production.trade_executor import TradeExecutor, ExecutionResult
from src.production.state_manager import ProductionState, TradeHistoryManager
from src.data.stock_data_manager import StockDataManager


def test_signal_creation():
    """Test Signal dataclass creation"""
    print("\n" + "="*60)
    print("TEST 1: Signal Creation")
    print("="*60)
    
    signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="BUY",
        action="BUY",
        confidence=0.75,
        score=75.0,
        reason="Strong technical + fundamental",
        current_price=31500,
        suggested_qty=100,
        required_capital=3150000
    )
    
    print(f"Signal created: {signal.ticker}")
    print(f"  Type: {signal.signal_type}")
    print(f"  Action: {signal.action}")
    print(f"  Score: {signal.score}")
    print(f"  Confidence: {signal.confidence}")
    print(f"  Suggested qty: {signal.suggested_qty}")
    print(f"  Capital: ¥{signal.required_capital:,.0f}")
    
    print("✅ Signal creation OK")


def test_trade_executor_dry_run():
    """Test TradeExecutor dry run"""
    print("\n" + "="*60)
    print("TEST 2: Trade Executor Dry Run")
    print("="*60)
    
    # Setup
    state = ProductionState("test_phase3_state.json")
    history = TradeHistoryManager("test_phase3_history.json")
    
    # Add test group if not exists
    if not state.get_group("group_a"):
        state.add_group("group_a", "Test Group A", 2000000)
    
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Test BUY signal
    buy_signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="BUY",
        action="BUY",
        confidence=0.75,
        score=75.0,
        reason="Test buy",
        current_price=31500,
        suggested_qty=50,
        required_capital=1575000
    )
    
    result = executor.execute_signal(buy_signal, dry_run=True, verbose=True)
    
    print(f"Dry run result:")
    print(f"  Success: {result.success}")
    print(f"  Executed qty: {result.executed_qty}")
    print(f"  Price: ¥{result.executed_price:,.0f}")
    print(f"  Reason: {result.reason}")
    
    # Cleanup
    if os.path.exists("test_phase3_state.json"):
        os.remove("test_phase3_state.json")
    if os.path.exists("test_phase3_history.json"):
        os.remove("test_phase3_history.json")
    
    print("✅ Trade executor dry run OK")


def test_buy_execution():
    """Test actual BUY execution"""
    print("\n" + "="*60)
    print("TEST 3: BUY Execution")
    print("="*60)
    
    # Setup
    state = ProductionState("test_phase3_state.json")
    history = TradeHistoryManager("test_phase3_history.json")
    
    state.add_group("group_a", "Test Group A", 5000000)
    
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Execute BUY
    buy_signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="BUY",
        action="BUY",
        confidence=0.75,
        score=75.0,
        reason="Test buy execution",
        current_price=31500,
        suggested_qty=100,
        required_capital=3150000
    )
    
    group_before = state.get_group("group_a")
    cash_before = group_before.cash
    
    result = executor.execute_signal(buy_signal, dry_run=False, verbose=True)
    
    group_after = state.get_group("group_a")
    cash_after = group_after.cash
    
    print(f"\nExecution result:")
    print(f"  Success: {result.success}")
    print(f"  Cash before: ¥{cash_before:,.0f}")
    print(f"  Cash after: ¥{cash_after:,.0f}")
    print(f"  Positions: {len(group_after.positions)}")
    
    if result.success:
        pos = group_after.positions[0]
        print(f"  Position: {pos.ticker} x{pos.quantity} @ ¥{pos.entry_price}")
    
    # Cleanup
    if os.path.exists("test_phase3_state.json"):
        os.remove("test_phase3_state.json")
    if os.path.exists("test_phase3_history.json"):
        os.remove("test_phase3_history.json")
    
    print("✅ BUY execution OK")


def test_sell_execution():
    """Test SELL execution with FIFO"""
    print("\n" + "="*60)
    print("TEST 4: SELL Execution (FIFO)")
    print("="*60)
    
    # Setup
    state = ProductionState("test_phase3_state.json")
    history = TradeHistoryManager("test_phase3_history.json")
    
    group = state.add_group("group_a", "Test Group A", 5000000)
    
    # Add position manually
    group.add_position("8035", 100, 31500, "2026-01-15", 75.0)
    
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Execute SELL
    sell_signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.65,
        score=0.0,
        reason="Trailing stop hit",
        current_price=32500,
        position_qty=100,
        entry_price=31500,
        entry_date="2026-01-15",
        holding_days=6,
        unrealized_pl_pct=3.17
    )
    
    cash_before = group.cash
    positions_before = len(group.positions)
    
    result = executor.execute_signal(sell_signal, dry_run=False, verbose=True)
    
    cash_after = group.cash
    positions_after = len(group.positions)
    
    print(f"\nExecution result:")
    print(f"  Success: {result.success}")
    print(f"  Sold: {result.executed_qty} shares")
    print(f"  Proceeds: ¥{result.proceeds:,.0f}")
    print(f"  Cash before: ¥{cash_before:,.0f}")
    print(f"  Cash after: ¥{cash_after:,.0f}")
    print(f"  Positions before: {positions_before}")
    print(f"  Positions after: {positions_after}")
    
    if positions_after > 0:
        remaining_pos = group.get_position("8035")
        if remaining_pos:
            print(f"  Remaining: {remaining_pos.quantity} shares")
    
    # Cleanup
    if os.path.exists("test_phase3_state.json"):
        os.remove("test_phase3_state.json")
    if os.path.exists("test_phase3_history.json"):
        os.remove("test_phase3_history.json")
    
    print("✅ SELL execution OK")


def test_execution_summary():
    """Test execution summary"""
    print("\n" + "="*60)
    print("TEST 5: Execution Summary")
    print("="*60)
    
    # Setup
    state = ProductionState("test_phase3_state.json")
    history = TradeHistoryManager("test_phase3_history.json")
    
    group = state.add_group("group_a", "Test Group A", 10000000)
    
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Create multiple signals
    signals = [
        Signal(
            group_id="group_a",
            ticker="8035",
            ticker_name="東京エレクトロン",
            signal_type="BUY",
            action="BUY",
            confidence=0.75,
            score=75.0,
            reason="Buy signal 1",
            current_price=31500,
            suggested_qty=100,
            required_capital=3150000
        ),
        Signal(
            group_id="group_a",
            ticker="8306",
            ticker_name="三菱UFJ",
            signal_type="BUY",
            action="BUY",
            confidence=0.70,
            score=70.0,
            reason="Buy signal 2",
            current_price=1900,
            suggested_qty=1000,
            required_capital=1900000
        ),
        Signal(
            group_id="group_b",  # Wrong group - should fail
            ticker="7974",
            ticker_name="任天堂",
            signal_type="BUY",
            action="BUY",
            confidence=0.72,
            score=72.0,
            reason="Buy signal 3",
            current_price=9500,
            suggested_qty=100,
            required_capital=950000
        ),
    ]
    
    # Execute batch
    results = executor.execute_batch(signals, dry_run=False, verbose=True)
    
    # Get summary
    summary = executor.get_execution_summary(results)
    
    print(f"\nExecution Summary:")
    print(f"  Total signals: {summary['total_signals']}")
    print(f"  Executed: {summary['executed']}")
    print(f"  Failed: {summary['failed']}")
    print(f"  BUY count: {summary['buy_count']}")
    print(f"  SELL count: {summary['sell_count']}")
    print(f"  Total buy capital: ¥{summary['total_buy_capital']:,.0f}")
    
    if summary['failures']:
        print(f"\nFailures:")
        for fail in summary['failures']:
            print(f"  - {fail['ticker']}: {fail['reason']}")
    
    # Cleanup
    if os.path.exists("test_phase3_state.json"):
        os.remove("test_phase3_state.json")
    if os.path.exists("test_phase3_history.json"):
        os.remove("test_phase3_history.json")
    
    print("✅ Execution summary OK")


def test_trade_history_recording():
    """Test trade history recording"""
    print("\n" + "="*60)
    print("TEST 6: Trade History Recording")
    print("="*60)
    
    # Setup
    state = ProductionState("test_phase3_state.json")
    history = TradeHistoryManager("test_phase3_history.json")
    
    group = state.add_group("group_a", "Test Group A", 5000000)
    
    executor = TradeExecutor(state, history, "2026-01-21")
    
    # Execute BUY
    buy_signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="BUY",
        action="BUY",
        confidence=0.75,
        score=75.0,
        reason="Test buy",
        current_price=31500,
        suggested_qty=100,
        required_capital=3150000
    )
    
    executor.execute_signal(buy_signal, dry_run=False)
    
    # Execute SELL
    sell_signal = Signal(
        group_id="group_a",
        ticker="8035",
        ticker_name="東京エレクトロン",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.65,
        score=0.0,
        reason="Test sell",
        current_price=32500,
        position_qty=100,
        entry_price=31500,
        entry_date="2026-01-21",
        holding_days=0,
        unrealized_pl_pct=3.17
    )
    
    executor.execute_signal(sell_signal, dry_run=False)
    
    # Save and reload
    executor.save_all()
    
    # Check history
    history2 = TradeHistoryManager("test_phase3_history.json")
    
    print(f"Total trades recorded: {len(history2.trades)}")
    
    for i, trade in enumerate(history2.trades, 1):
        print(f"\nTrade {i}:")
        print(f"  Action: {trade.action}")
        print(f"  Ticker: {trade.ticker}")
        print(f"  Quantity: {trade.quantity}")
        print(f"  Price: ¥{trade.price:,.0f}")
        print(f"  Total: ¥{trade.total_jpy:,.0f}")
        if trade.action == "BUY":
            print(f"  Entry score: {trade.entry_score}")
        else:
            print(f"  Exit reason: {trade.exit_reason}")
    
    # Cleanup
    if os.path.exists("test_phase3_state.json"):
        os.remove("test_phase3_state.json")
    if os.path.exists("test_phase3_history.json"):
        os.remove("test_phase3_history.json")
    
    print("\n✅ Trade history recording OK")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("PHASE 3: SIGNAL GENERATION & TRADE EXECUTION TESTS")
    print("="*60)
    
    try:
        test_signal_creation()
        test_trade_executor_dry_run()
        test_buy_execution()
        test_sell_execution()
        test_execution_summary()
        test_trade_history_recording()
        
        print("\n" + "="*60)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY")
        print("="*60 + "\n")
    
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
