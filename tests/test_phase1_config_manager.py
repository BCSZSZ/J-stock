#!/usr/bin/env python3
"""
Phase 1: Configuration Manager Test
验证从 config.json 正确读取配置
"""

import sys
import json
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from src.production.config_manager import ConfigManager, ProductionConfig


def test_config_loading():
    """Test Phase 1: Configuration Loading"""
    print("\n" + "="*70)
    print("PHASE 1: Configuration Manager")
    print("="*70)
    
    try:
        # Test 1: Load config.json
        config_mgr = ConfigManager("config.json")
        print("[OK] config.json loaded successfully")
        
        # Test 2: Get production config
        prod_cfg = config_mgr.get_production_config()
        print("[OK] ProductionConfig extracted")
        
        # Test 3: Verify required fields
        assert prod_cfg.monitor_list_file is not None, "monitor_list_file is None"
        assert prod_cfg.data_dir is not None, "data_dir is None"
        assert prod_cfg.state_file is not None, "state_file is None"
        print("[OK] All required fields present")
        
        # Test 4: Verify strategies
        assert prod_cfg.default_entry_strategy is not None
        assert prod_cfg.default_exit_strategy is not None
        print(f"[OK] Default strategies: {prod_cfg.default_entry_strategy} → {prod_cfg.default_exit_strategy}")
        
        # Test 5: Verify position management settings
        assert prod_cfg.max_positions_per_group > 0
        assert 0 < prod_cfg.max_position_pct < 1.0
        assert prod_cfg.buy_threshold > 0
        print(f"[OK] Position settings: max={prod_cfg.max_positions_per_group}, pct={prod_cfg.max_position_pct*100:.0f}%, threshold={prod_cfg.buy_threshold}")
        
        # Test 6: Print summary
        config_mgr.print_summary()
        
        print("[PASS] Phase 1 Configuration OK")
        return True
        
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = test_config_loading()
    sys.exit(0 if success else 1)
