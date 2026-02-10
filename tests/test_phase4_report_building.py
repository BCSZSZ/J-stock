"""
Test Phase 4: Report Building Module

Validates ReportBuilder functionality including:
1. Report structure (all sections present)
2. BUY signals sorting by score
3. SELL signals sorting by urgency
4. Portfolio status with P&L calculations
5. Execution summary
6. File I/O (save/load)
"""

import sys
import os
from pathlib import Path
import json
import pandas as pd
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.production.report_builder import (
    ReportBuilder, 
    load_signals_from_file,
    MarketSummary
)
from src.production.state_manager import ProductionState, Position
from src.production.signal_generator import Signal
from src.production.trade_executor import ExecutionResult
from src.data.stock_data_manager import StockDataManager


def setup_test_environment():
    """Create test data and state."""
    # Create temporary test directory
    test_dir = Path("test_temp_phase4")
    test_dir.mkdir(exist_ok=True)
    
    # Create mock TOPIX benchmark data
    benchmark_dir = test_dir / "benchmarks"
    benchmark_dir.mkdir(exist_ok=True)
    
    df_topix = pd.DataFrame({
        'Date': pd.date_range('2026-01-15', '2026-01-21', freq='D'),
        'Open': [3600.0, 3620.0, 3610.0, 3650.0, 3660.0, 3670.0, 3680.0],
        'High': [3630.0, 3640.0, 3630.0, 3670.0, 3680.0, 3690.0, 3700.0],
        'Low': [3590.0, 3610.0, 3600.0, 3640.0, 3650.0, 3660.0, 3670.0],
        'Close': [3620.0, 3615.0, 3645.0, 3665.0, 3675.0, 3685.0, 3695.0]
    })
    df_topix.to_parquet(benchmark_dir / "TOPIX_benchmark.parquet", index=False)
    
    # Create test state with positions
    state_file = test_dir / "test_production_state.json"
    state = ProductionState(state_file=str(state_file))
    
    # Add groups
    conservative = state.add_group(
        group_id="conservative",
        name="Conservative Strategy",
        initial_capital=5000000.0
    )
    aggressive = state.add_group(
        group_id="aggressive",
        name="Aggressive Strategy",
        initial_capital=3000000.0
    )
    
    # Add positions to conservative group
    conservative.add_position(
        ticker="8035",
        entry_price=31500.0,
        quantity=100,
        entry_date="2026-01-10",
        entry_score=75.0
    )
    
    conservative.add_position(
        ticker="7974",
        entry_price=5200.0,
        quantity=500,
        entry_date="2026-01-12",
        entry_score=70.0
    )
    
    # Add position to aggressive group
    aggressive.add_position(
        ticker="4063",
        entry_price=6800.0,
        quantity=200,
        entry_date="2026-01-15",
        entry_score=80.0
    )
    
    state.save()
    
    # Create mock data manager
    class MockDataManager:
        def __init__(self):
            self.data_dir = test_dir
    
    data_manager = MockDataManager()
    
    return state, data_manager, test_dir


def create_test_signals():
    """Create diverse test signals."""
    signals = [
        # BUY signals (various scores)
        Signal(
            group_id="conservative",
            ticker="6501",
            ticker_name="三菱電機",
            signal_type="BUY",
            action="BUY",
            score=85.5,
            confidence=0.85,
            reason="Strong technical + institutional inflow",
            current_price=28000.0,
            suggested_qty=100,
            required_capital=2800000.0,
            strategy_name="SimpleScorer_Conservative"
        ),
        Signal(
            group_id="aggressive",
            ticker="8306",
            ticker_name="三菱UFJ",
            signal_type="BUY",
            action="BUY",
            score=72.3,
            confidence=0.70,
            reason="Momentum breakout",
            current_price=15500.0,
            suggested_qty=150,
            required_capital=2325000.0,
            strategy_name="Ichimoku_Aggressive"
        ),
        Signal(
            group_id="conservative",
            ticker="7203",
            ticker_name="トヨタ",
            signal_type="BUY",
            action="BUY",
            score=68.0,
            confidence=0.65,
            reason="Undervalued fundamentals",
            current_price=9800.0,
            suggested_qty=200,
            required_capital=1960000.0,
            strategy_name="SimpleScorer_Conservative"
        ),
        
        # SELL signals (various urgencies)
        Signal(
            group_id="conservative",
            ticker="8035",
            ticker_name="東京エレクトロン",
            signal_type="SELL",
            action="SELL_100%",
            score=35.0,
            confidence=0.90,
            reason="Stop loss triggered at -8% (EMERGENCY)",
            current_price=28980.0,
            position_qty=100,
            entry_price=31500.0,
            entry_date="2026-01-10",
            holding_days=11,
            unrealized_pl_pct=-8.0,
            strategy_name="ATRExit_Conservative"
        ),
        Signal(
            group_id="conservative",
            ticker="7974",
            ticker_name="任天堂",
            signal_type="SELL",
            action="SELL_50%",
            score=58.5,
            confidence=0.70,
            reason="Take partial profit at +15% (MEDIUM urgency)",
            current_price=5980.0,
            position_qty=500,
            entry_price=5200.0,
            entry_date="2026-01-12",
            holding_days=9,
            unrealized_pl_pct=15.0,
            strategy_name="LayeredExit_Conservative"
        ),
        Signal(
            group_id="aggressive",
            ticker="4063",
            ticker_name="信越化学",
            signal_type="HOLD",
            action="HOLD",
            score=62.0,
            confidence=0.65,
            reason="Trailing stop not triggered (LOW urgency)",
            current_price=7100.0,
            position_qty=200,
            entry_price=6800.0,
            entry_date="2026-01-15",
            holding_days=6,
            unrealized_pl_pct=4.4,
            strategy_name="ADXExit_Aggressive"
        ),
    ]
    
    return signals


def create_test_execution_results(signals):
    """Create test execution results."""
    return [
        ExecutionResult(
            success=True,
            signal=signals[0],  # BUY 6501
            executed_qty=100,
            executed_price=28000.0,
            reason="BUY executed: 6501 x100 @ ¥28,000"
        ),
        ExecutionResult(
            success=True,
            signal=signals[3],  # SELL 8035
            executed_qty=100,
            executed_price=28980.0,
            proceeds=2898000.0,
            reason="SELL executed: 8035 x100 @ ¥28,980, Proceeds: ¥2,898,000, P&L: -8.00%"
        ),
        ExecutionResult(
            success=False,
            signal=signals[1],  # BUY 8306
            reason="Insufficient cash: required ¥2,325,000, available ¥1,500,000"
        ),
    ]


def test_report_structure():
    """TEST 1: Verify all sections present in report."""
    print("\n" + "="*60)
    print("TEST 1: Report Structure")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    signals = create_test_signals()
    execution_results = create_test_execution_results(signals)
    
    report = builder.generate_daily_report(
        signals=signals,
        execution_results=execution_results,
        report_date="2026-01-21"
    )
    
    # Verify all sections present
    required_sections = [
        "# Daily Trading Report",
        "## 📊 Market Summary",
        "## 🟢 BUY Signals",
        "## 🔴 SELL Signals",
        "## 💼 Current Portfolio Status",
        "## ✅ Execution Summary"
    ]
    
    for section in required_sections:
        assert section in report, f"Missing section: {section}"
    
    print(f"✅ All {len(required_sections)} required sections present")
    print(f"✅ Report length: {len(report)} characters")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 1 PASSED")


def test_buy_signals_sorting():
    """TEST 2: Verify BUY signals sorted by score (descending)."""
    print("\n" + "="*60)
    print("TEST 2: BUY Signals Sorting")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    signals = create_test_signals()
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Extract BUY signals section
    buy_section = report.split("## 🟢 BUY Signals")[1].split("##")[0]
    
    # Verify order: 6501 (85.5) > 8306 (72.3) > 7203 (68.0)
    assert buy_section.index("6501") < buy_section.index("8306"), "6501 should appear before 8306"
    assert buy_section.index("8306") < buy_section.index("7203"), "8306 should appear before 7203"
    
    print("✅ BUY signals correctly sorted by score:")
    print("   1. 6501 (85.5)")
    print("   2. 8306 (72.3)")
    print("   3. 7203 (68.0)")
    
    # Verify top 3 details included
    assert "Top Opportunities Details" in buy_section
    # Score should be displayed in the details section
    assert "Score:" in buy_section or "85.5" in buy_section
    
    print("✅ Top opportunities details included")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 2 PASSED")


def test_sell_signals_sorting():
    """TEST 3: Verify SELL signals sorted by urgency."""
    print("\n" + "="*60)
    print("TEST 3: SELL Signals Sorting")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    signals = create_test_signals()
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Extract SELL signals section
    sell_section = report.split("## 🔴 SELL Signals")[1].split("##")[0]
    
    # Verify order: EMERGENCY (8035) > MEDIUM (7974) > LOW (4063)
    # Note: The actual urgency values are derived in the report builder
    assert "8035" in sell_section
    assert "7974" in sell_section
    assert "4063" in sell_section
    
    # Check that EMERGENCY signal (8035) appears before others
    pos_8035 = sell_section.index("8035")
    pos_7974 = sell_section.index("7974")
    pos_4063 = sell_section.index("4063")
    
    assert pos_8035 < pos_7974, "8035 (EMERGENCY) should appear before 7974 (MEDIUM)"
    assert pos_7974 < pos_4063, "7974 (MEDIUM) should appear before 4063 (LOW)"
    
    print("✅ SELL signals correctly sorted by urgency:")
    print("   1. 8035 (EMERGENCY - derived from STOP loss reason)")
    print("   2. 7974 (MEDIUM - SELL_50% action)")
    print("   3. 4063 (LOW - HOLD action)")
    
    # Verify urgency indicators in report
    assert "🚨" in sell_section, "EMERGENCY icon should be present"
    assert "⚡" in sell_section, "MEDIUM icon should be present"
    assert "ℹ️" in sell_section, "LOW icon should be present"
    
    print("✅ Urgency icons displayed correctly")
    
    # Verify high urgency details
    assert "High Urgency Details" in sell_section
    assert "Stop loss" in sell_section or "STOP" in sell_section.upper()
    
    print("✅ High urgency details included")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 3 PASSED")


def test_portfolio_status():
    """TEST 4: Verify portfolio status with P&L calculations."""
    print("\n" + "="*60)
    print("TEST 4: Portfolio Status & P&L")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    # Update positions with current prices for P&L calc (use peak_price)
    conservative = state.strategy_groups["conservative"]
    conservative.positions[0].peak_price = 32500.0  # 8035: +1000 (3.17%)
    conservative.positions[1].peak_price = 5400.0   # 7974: +200 (3.85%)
    
    aggressive = state.strategy_groups["aggressive"]
    aggressive.positions[0].peak_price = 7100.0     # 4063: +300 (4.41%)
    
    state.save()
    
    signals = create_test_signals()
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Extract portfolio section
    portfolio_section = report.split("## 💼 Current Portfolio Status")[1].split("##")[0]
    
    # Verify both groups present
    assert "conservative" in portfolio_section.lower()
    assert "aggressive" in portfolio_section.lower()
    
    print("✅ Both strategy groups displayed")
    
    # Verify positions table
    assert "| Ticker | Shares | Avg Price | Current Price | P&L (¥) | P&L (%) | Value (¥) |" in portfolio_section
    
    # Verify position data
    assert "8035" in portfolio_section
    assert "7974" in portfolio_section
    assert "4063" in portfolio_section
    
    print("✅ All 3 positions listed")
    
    # Verify P&L calculations (approx)
    assert "+3.17%" in portfolio_section or "+3.2%" in portfolio_section  # 8035
    assert "+3.85%" in portfolio_section or "+3.8%" in portfolio_section  # 7974
    assert "+4.41%" in portfolio_section or "+4.4%" in portfolio_section  # 4063
    
    print("✅ P&L calculations correct:")
    print("   - 8035: +3.17% (¥32,500 vs ¥31,500)")
    print("   - 7974: +3.85% (¥5,400 vs ¥5,200)")
    print("   - 4063: +4.41% (¥7,100 vs ¥6,800)")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 4 PASSED")


def test_execution_summary():
    """TEST 5: Verify execution summary section."""
    print("\n" + "="*60)
    print("TEST 5: Execution Summary")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    signals = create_test_signals()
    execution_results = create_test_execution_results(signals)
    
    report = builder.generate_daily_report(
        signals=signals,
        execution_results=execution_results,
        report_date="2026-01-21"
    )
    
    # Extract execution section
    exec_section = report.split("## ✅ Execution Summary")[1].split("---")[0]
    
    # Verify counts
    assert "Total Signals Processed:** 3" in exec_section
    assert "Successful Executions:** 2" in exec_section
    assert "Failed Executions:** 1" in exec_section
    
    print("✅ Execution counts correct (3 total: 2 success, 1 failed)")
    
    # Verify successful executions table
    assert "✅ Successful Executions" in exec_section
    assert "6501" in exec_section  # BUY
    assert "8035" in exec_section  # SELL
    
    print("✅ Successful executions displayed:")
    print("   - BUY 6501 x100 @ ¥28,000")
    print("   - SELL 8035 x100 @ ¥28,980")
    
    # Verify failed executions
    assert "❌ Failed Executions" in exec_section
    assert "8306" in exec_section
    assert "Insufficient cash" in exec_section
    
    print("✅ Failed execution displayed with reason")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 5 PASSED")


def test_save_and_load_report():
    """TEST 6: Verify report file I/O."""
    print("\n" + "="*60)
    print("TEST 6: Report File I/O")
    print("="*60)
    
    state, data_manager, test_dir = setup_test_environment()
    builder = ReportBuilder(state, data_manager)
    
    signals = create_test_signals()
    report = builder.generate_daily_report(signals, report_date="2026-01-21")
    
    # Save report
    output_dir = test_dir / "output"
    filepath = builder.save_report(
        report_content=report,
        output_dir=str(output_dir),
        report_date="2026-01-21"
    )
    
    print(f"✅ Report saved to: {filepath}")
    
    # Verify file exists
    assert os.path.exists(filepath), f"Report file not found: {filepath}"
    expected_filename = "trade_report_2026-01-21.md"
    assert expected_filename in filepath
    
    print(f"✅ File exists: {expected_filename}")
    
    # Load and verify content
    with open(filepath, 'r', encoding='utf-8') as f:
        loaded_content = f.read()
    
    assert loaded_content == report, "Loaded content doesn't match original"
    assert len(loaded_content) > 1000, f"Report too short: {len(loaded_content)} chars"
    
    print(f"✅ Content verified: {len(loaded_content)} characters")
    
    # Test signal file I/O
    signals_file = test_dir / "signals_test.json"
    signals_data = {
        "date": "2026-01-21",
        "signals": [
            {
                "group_id": signal.group_id,
                "ticker": signal.ticker,
                "ticker_name": signal.ticker_name,
                "signal_type": signal.signal_type,
                "action": signal.action,
                "confidence": signal.confidence,
                "score": signal.score,
                "reason": signal.reason,
                "current_price": signal.current_price,
                "position_qty": signal.position_qty,
                "entry_price": signal.entry_price,
                "entry_date": signal.entry_date,
                "holding_days": signal.holding_days,
                "unrealized_pl_pct": signal.unrealized_pl_pct,
                "suggested_qty": signal.suggested_qty,
                "required_capital": signal.required_capital,
                "strategy_name": signal.strategy_name,
                "timestamp": signal.timestamp
            }
            for signal in signals
        ]
    }
    
    with open(signals_file, 'w', encoding='utf-8') as f:
        json.dump(signals_data, f, indent=2)
    
    print(f"✅ Signals saved to: {signals_file}")
    
    # Load signals using utility function
    from src.production.report_builder import load_signals_from_file
    loaded_signals = load_signals_from_file(str(signals_file))
    
    assert len(loaded_signals) == len(signals), \
        f"Signal count mismatch: {len(loaded_signals)} vs {len(signals)}"
    assert loaded_signals[0].ticker == signals[0].ticker
    assert loaded_signals[0].score == signals[0].score
    
    print(f"✅ Signals loaded correctly: {len(loaded_signals)} signals")
    
    # Cleanup
    import shutil
    shutil.rmtree(test_dir, ignore_errors=True)
    
    print("✅ TEST 6 PASSED")


def run_all_tests():
    """Run all Phase 4 tests."""
    print("\n" + "="*70)
    print("PHASE 4: REPORT BUILDING - COMPREHENSIVE TEST SUITE")
    print("="*70)
    
    tests = [
        test_report_structure,
        test_buy_signals_sorting,
        test_sell_signals_sorting,
        test_portfolio_status,
        test_execution_summary,
        test_save_and_load_report
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"\n❌ TEST FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        except Exception as e:
            print(f"\n❌ TEST ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print(f"✅ Tests Passed: {passed}/{len(tests)}")
    print(f"❌ Tests Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED! Phase 4 implementation validated.")
    else:
        print(f"\n⚠️ {failed} test(s) failed. Please review.")
    
    print("="*70)


if __name__ == "__main__":
    run_all_tests()

