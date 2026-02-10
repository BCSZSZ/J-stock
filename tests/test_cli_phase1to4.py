#!/usr/bin/env python3
"""
Phase 1-4 Integration Test CLI
在真实环境中测试 Phase 1 (Config) 到 Phase 4 (Report) 的所有功能
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from src.production.config_manager import ConfigManager
from src.production.state_manager import ProductionState, StrategyGroupState, TradeHistoryManager
from src.production.signal_generator import SignalGenerator, Signal
from src.production.trade_executor import TradeExecutor
from src.production.report_builder import ReportBuilder
from src.data.stock_data_manager import StockDataManager


def test_phase1_config():
    """Test Phase 1: Configuration Loading"""
    print("\n" + "="*70)
    print("PHASE 1: Configuration Manager")
    print("="*70)
    
    try:
        # Initialize ConfigManager (Phase 1 responsibility)
        config_mgr = ConfigManager("config.json")
        print("[OK] ConfigManager initialized from config.json")
        
        # Get production config
        prod_cfg = config_mgr.get_production_config()
        print("[OK] ProductionConfig extracted")
        
        # Verify all required fields
        assert prod_cfg.monitor_list_file is not None
        assert prod_cfg.data_dir is not None
        assert prod_cfg.state_file is not None
        assert prod_cfg.default_entry_strategy is not None
        assert prod_cfg.default_exit_strategy is not None
        print("[OK] All required configuration fields present")
        
        # Verify position management settings
        assert prod_cfg.max_positions_per_group > 0
        assert 0 < prod_cfg.max_position_pct < 1.0
        assert prod_cfg.buy_threshold > 0
        print(f"[OK] Position limits: max={prod_cfg.max_positions_per_group}, " +
              f"pct={prod_cfg.max_position_pct*100:.0f}%, threshold={prod_cfg.buy_threshold}")
        
        # Verify file paths
        data_path = Path(prod_cfg.data_dir)
        if data_path.exists():
            print(f"[OK] Data directory exists: {data_path}")
        else:
            print(f"[WARN] Data directory not found (will be created): {data_path}")
        
        print("[PASS] Phase 1 Configuration Manager OK")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


def test_phase2_state():
    """Test Phase 2: State Management"""
    print("\n" + "="*70)
    print("PHASE 2: State Management (FIFO, Positions, Persistence)")
    print("="*70)
    
    # Create test state
    state_file = "test_state_cli.json"
    state = ProductionState(state_file=state_file)
    
    print(f"[OK] ProductionState initialized")
    
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
    
    print(f"[OK] Added 2 strategy groups")
    
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
    
    print(f"[OK] Added 2 positions to conservative group")
    
    # Save state
    state.save()
    print(f"[OK] State persisted to {state_file}")
    
    # Verify persistence
    state2 = ProductionState(state_file=state_file)
    if len(state2.get_all_groups()) == 2:
        print(f"[OK] State loaded from file: {len(state2.get_all_groups())} groups")
    else:
        print(f"[FAIL] State loading failed")
        return False
    
    # Test FIFO
    conservative2 = state2.get_group("conservative")
    cash_before = conservative2.cash
    
    # Sell 50 shares of 8035 at JPY 32,500
    proceeds, qty_sold = conservative2.partial_sell("8035", 50, 32500.0)
    
    print(f"[OK] FIFO sell executed: {qty_sold} @ JPY 32,500, proceeds: JPY {proceeds:,.0f}")
    
    # Cleanup
    if os.path.exists(state_file):
        os.remove(state_file)
    
    print("[PASS] Phase 2 State Management OK")
    return True


def test_phase3_signals():
    """Test Phase 3: Signal Generation & Execution"""
    print("\n" + "="*70)
    print("PHASE 3: Signal Generation & Execution")
    print("="*70)
    
    state_file = "test_state_phase3.json"
    history_file = "test_history_phase3.json"
    
    try:
        # Initialize state and history
        state = ProductionState(state_file=state_file)
        from src.production.state_manager import TradeHistoryManager
        history = TradeHistoryManager(history_file=history_file)
        
        group = state.add_group("test", "Test Group", 5000000.0)
        state.save()
        print(f"[OK] State and history initialized")
        
        # Create test signals
        buy_signal = Signal(
            group_id="test",
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
        
        print(f"[OK] BUY signal created: 8035 @ JPY 31,500, qty: 100")
        
        # Execute trade
        from src.production.trade_executor import TradeExecutor
        executor = TradeExecutor(state, history, "2026-01-21")
        
        result = executor.execute_signal(buy_signal, dry_run=False)
        
        if result.success:
            print(f"[OK] BUY executed: {result.executed_qty} @ JPY {result.executed_price:,.0f}")
        else:
            print(f"[FAIL] BUY execution failed: {result.reason}")
            return False
        
        # Verify position
        positions = group.positions
        if len(positions) > 0:
            print(f"[OK] Position recorded: {len(positions)} position(s)")
        else:
            print(f"[FAIL] No position recorded")
            return False
        
        print("[PASS] Phase 3 Signal Generation & Execution OK")
        return True
        
    finally:
        # Cleanup
        for f in [state_file, history_file]:
            if os.path.exists(f):
                os.remove(f)


def test_phase4_reports():
    """Test Phase 4: Report Building"""
    print("\n" + "="*70)
    print("PHASE 4: Report Building")
    print("="*70)
    
    state_file = "test_state_phase4.json"
    
    try:
        # Initialize state
        state = ProductionState(state_file=state_file)
        group = state.add_group("conservative", "Conservative", 5000000.0)
        
        # Add position
        group.add_position(
            ticker="8035",
            entry_price=31500.0,
            quantity=100,
            entry_date="2026-01-10",
            entry_score=75.0
        )
        state.save()
        print(f"[OK] Test state created with 1 position")
        
        # Create mock data manager
        class MockDataManager:
            def __init__(self):
                self.data_dir = Path(".")
        
        # Initialize report builder
        builder = ReportBuilder(state, MockDataManager())
        print(f"[OK] ReportBuilder initialized")
        
        # Create test signals
        signals = [
            Signal(
                group_id="conservative",
                ticker="6501",
                ticker_name="Sony",
                signal_type="BUY",
                action="BUY",
                confidence=0.8,
                score=80.0,
                reason="Bullish setup",
                current_price=28000.0,
                suggested_qty=100,
                required_capital=2800000.0,
                strategy_name="SimpleScorer"
            ),
            Signal(
                group_id="conservative",
                ticker="8035",
                ticker_name="Tokyo Electron",
                signal_type="SELL",
                action="SELL_50%",
                confidence=0.7,
                score=35.0,
                reason="Stop loss -8%",
                current_price=28980.0,
                position_qty=100,
                entry_price=31500.0,
                entry_date="2026-01-10",
                holding_days=11,
                unrealized_pl_pct=-7.97,
                strategy_name="ATRExiter"
            )
        ]
        
        # Generate report
        report = builder.generate_daily_report(signals, report_date="2026-01-21")
        
        if "Daily Trading Report" in report:
            print(f"[OK] Report generated: {len(report)} characters")
        else:
            print(f"[FAIL] Report generation failed")
            return False
        
        # Verify sections
        sections = [
            "Market Summary",
            "BUY Signals",
            "SELL Signals",
            "Portfolio Status"
        ]
        
        for section in sections:
            if section in report:
                print(f"[OK] Section present: {section}")
            else:
                print(f"[FAIL] Missing section: {section}")
                return False
        
        # Save report
        output_dir = "test_output_cli"
        filepath = builder.save_report(report, output_dir, "2026-01-21")
        
        if os.path.exists(filepath):
            print(f"[OK] Report saved: {filepath}")
        else:
            print(f"[FAIL] Report file not created")
            return False
        
        # Cleanup
        import shutil
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
        
        print("[PASS] Phase 4 Report Building OK")
        return True
        
    finally:
        # Cleanup
        if os.path.exists(state_file):
            os.remove(state_file)


def run_all_tests():
    """Run all Phase 1-4 tests"""
    print("\n" + "="*70)
    print("PHASE 1-4 INTEGRATION TEST")
    print("Testing production trading system in real environment")
    print("="*70)
    
    tests = [
        ("Phase 1: Configuration", test_phase1_config),
        ("Phase 2: State Management", test_phase2_state),
        ("Phase 3: Signal Generation", test_phase3_signals),
        ("Phase 4: Report Building", test_phase4_reports),
    ]
    
    results = []
    
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, "PASSED" if result else "FAILED"))
        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()
            results.append((name, "ERROR"))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    for name, status in results:
        status_icon = "[PASS]" if status == "PASSED" else "[FAIL]"
        print(f"{status_icon} {name}: {status}")
    
    passed = sum(1 for _, s in results if s == "PASSED")
    total = len(results)
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED - Phases 1-4 working correctly")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
