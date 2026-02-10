"""
Simplified Phase 4: Report Building Tests

Focus on core functionality without complex setups
"""

import sys
import os
from pathlib import Path
import json
import pandas as pd
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.production.report_builder import ReportBuilder, load_signals_from_file
from src.production.state_manager import ProductionState
from src.production.signal_generator import Signal
from src.production.trade_executor import ExecutionResult


def test_signal_creation():
    """TEST 1: Create and validate signals"""
    print("\n" + "="*60)
    print("TEST 1: Signal Creation")
    print("="*60)
    
    # Create BUY signal
    buy_signal = Signal(
        group_id="conservative",
        ticker="8035",
        ticker_name="Tokyo Electron",
        signal_type="BUY",
        action="BUY",
        confidence=0.85,
        score=85.5,
        reason="Strong technical setup",
        current_price=31500.0,
        suggested_qty=100,
        required_capital=3150000.0,
        strategy_name="SimpleScorer"
    )
    
    # Create SELL signal
    sell_signal = Signal(
        group_id="conservative",
        ticker="8035",
        ticker_name="Tokyo Electron",
        signal_type="SELL",
        action="SELL_50%",
        confidence=0.65,
        score=35.0,
        reason="Stop loss triggered",
        current_price=28980.0,
        position_qty=100,
        entry_price=31500.0,
        entry_date="2026-01-10",
        holding_days=11,
        unrealized_pl_pct=-7.97,
        strategy_name="ATRExiter"
    )
    
    print(f"OK - BUY signal: {buy_signal.ticker} @ JPY {buy_signal.current_price:,.0f}")
    print(f"OK - SELL signal: {sell_signal.ticker} @ JPY {sell_signal.current_price:,.0f}")
    print("PASSED - Signals created successfully")


def test_report_generation():
    """TEST 2: Generate report structure"""
    print("\n" + "="*60)
    print("TEST 2: Report Generation")
    print("="*60)
    
    # Create minimal state
    test_state_file = "test_report_state.json"
    state = ProductionState(state_file=test_state_file)
    
    # Create mock data manager
    class MockDataManager:
        def __init__(self):
            self.data_dir = Path(".")
    
    builder = ReportBuilder(state, MockDataManager())
    
    # Create test signals
    signals = [
        Signal(
            group_id="test",
            ticker="6501",
            ticker_name="Sony",
            signal_type="BUY",
            action="BUY",
            confidence=0.8,
            score=80.0,
            reason="Bullish",
            current_price=28000.0,
            suggested_qty=100,
            required_capital=2800000.0,
            strategy_name="SimpleScorer"
        ),
        Signal(
            group_id="test",
            ticker="7974",
            ticker_name="Yamaha",
            signal_type="SELL",
            action="SELL_100%",
            confidence=0.7,
            score=30.0,
            reason="Exit signal",
            current_price=5980.0,
            position_qty=500,
            entry_price=5200.0,
            entry_date="2026-01-12",
            holding_days=9,
            unrealized_pl_pct=15.0,
            strategy_name="LayeredExit"
        )
    ]
    
    # Generate report
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Verify sections
    assert "Daily Trading Report" in report
    assert "Market Summary" in report
    assert "BUY Signals" in report
    assert "SELL Signals" in report
    assert "Portfolio Status" in report
    
    print("OK - All report sections present")
    print(f"OK - Report length: {len(report)} characters")
    print("PASSED - Report generated successfully")
    
    # Cleanup
    if os.path.exists(test_state_file):
        os.remove(test_state_file)


def test_signal_file_io():
    """TEST 3: Signal JSON file I/O"""
    print("\n" + "="*60)
    print("TEST 3: Signal File I/O")
    print("="*60)
    
    # Create test signals
    test_signals = [
        {
            "group_id": "conservative",
            "ticker": "8035",
            "ticker_name": "Tokyo Electron",
            "signal_type": "BUY",
            "action": "BUY",
            "confidence": 0.85,
            "score": 85.5,
            "reason": "Strong setup",
            "current_price": 31500.0,
            "suggested_qty": 100,
            "required_capital": 3150000.0,
            "strategy_name": "SimpleScorer"
        },
        {
            "group_id": "conservative",
            "ticker": "7974",
            "ticker_name": "Yamaha",
            "signal_type": "SELL",
            "action": "SELL_50%",
            "confidence": 0.65,
            "score": 40.0,
            "reason": "Take profit",
            "current_price": 5400.0,
            "position_qty": 500,
            "entry_price": 5200.0,
            "entry_date": "2026-01-12",
            "holding_days": 9,
            "unrealized_pl_pct": 3.85,
            "strategy_name": "LayeredExit"
        }
    ]
    
    # Save to JSON
    signals_file = "test_signals.json"
    with open(signals_file, 'w', encoding='utf-8') as f:
        json.dump({"signals": test_signals}, f, indent=2)
    
    print(f"OK - Saved to {signals_file}")
    
    # Load using utility function
    loaded_signals = load_signals_from_file(signals_file)
    
    assert len(loaded_signals) == 2
    assert loaded_signals[0].ticker == "8035"
    assert loaded_signals[1].ticker == "7974"
    assert loaded_signals[0].score == 85.5
    assert loaded_signals[1].score == 40.0
    
    print(f"OK - Loaded {len(loaded_signals)} signals")
    print(f"OK - Signal 1: {loaded_signals[0].ticker} score={loaded_signals[0].score}")
    print(f"OK - Signal 2: {loaded_signals[1].ticker} score={loaded_signals[1].score}")
    print("PASSED - Signal file I/O working")
    
    # Cleanup
    if os.path.exists(signals_file):
        os.remove(signals_file)


def test_report_save():
    """TEST 4: Report saving"""
    print("\n" + "="*60)
    print("TEST 4: Report File Save")
    print("="*60)
    
    state = ProductionState(state_file="test_report_state2.json")
    
    class MockDataManager:
        def __init__(self):
            self.data_dir = Path(".")
    
    builder = ReportBuilder(state, MockDataManager())
    
    # Create simple report
    signals = [
        Signal(
            group_id="test",
            ticker="6501",
            ticker_name="Sony",
            signal_type="BUY",
            action="BUY",
            confidence=0.8,
            score=80.0,
            reason="Bullish",
            current_price=28000.0,
            suggested_qty=100,
            required_capital=2800000.0,
            strategy_name="SimpleScorer"
        )
    ]
    
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Save report
    output_dir = "test_output"
    filepath = builder.save_report(
        report_content=report,
        output_dir=output_dir,
        report_date="2026-01-21"
    )
    
    assert os.path.exists(filepath)
    assert "trade_report_2026-01-21.md" in filepath
    
    # Verify content
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    assert "Daily Trading Report" in content
    assert len(content) > 500
    
    print(f"OK - Report saved to {filepath}")
    print(f"OK - File size: {len(content)} characters")
    print("PASSED - Report saved successfully")
    
    # Cleanup
    import shutil
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    if os.path.exists("test_report_state2.json"):
        os.remove("test_report_state2.json")


def test_execution_result_handling():
    """TEST 5: ExecutionResult handling"""
    print("\n" + "="*60)
    print("TEST 5: ExecutionResult Handling")
    print("="*60)
    
    # Create signal
    signal = Signal(
        group_id="conservative",
        ticker="8035",
        ticker_name="Tokyo Electron",
        signal_type="BUY",
        action="BUY",
        confidence=0.85,
        score=85.5,
        reason="Strong setup",
        current_price=31500.0,
        suggested_qty=100,
        required_capital=3150000.0,
        strategy_name="SimpleScorer"
    )
    
    # Create execution result
    result = ExecutionResult(
        success=True,
        signal=signal,
        executed_qty=100,
        executed_price=31500.0,
        reason="BUY executed successfully"
    )
    
    assert result.success
    assert result.executed_qty == 100
    assert result.signal.ticker == "8035"
    
    print(f"OK - ExecutionResult created")
    print(f"OK - Success: {result.success}")
    print(f"OK - Executed qty: {result.executed_qty}")
    print("PASSED - ExecutionResult handling works")


def run_all_tests():
    """Run all simplified Phase 4 tests"""
    print("\n" + "="*70)
    print("PHASE 4: REPORT BUILDING - SIMPLIFIED TEST SUITE")
    print("="*70)
    
    tests = [
        test_signal_creation,
        test_report_generation,
        test_signal_file_io,
        test_report_save,
        test_execution_result_handling
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\nFAILED - {e}")
            failed += 1
        except Exception as e:
            print(f"\nERROR - {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\nSUCCESS - All Phase 4 tests passed!")
    else:
        print(f"\nWARNING - {failed} test(s) failed")
    
    print("="*70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
