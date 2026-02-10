"""
Phase 1: Configuration Manager
负责从 config.json 读取系统初始化参数
"""

import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class ProductionConfig:
    """Production configuration from config.json"""
    # Data paths
    monitor_list_file: str
    data_dir: str
    
    # Production settings
    state_file: str
    signal_file_pattern: str
    report_file_pattern: str
    history_file: str
    
    # Position management
    max_positions_per_group: int
    max_position_pct: float
    buy_threshold: float
    
    # Default strategies
    default_entry_strategy: str
    default_exit_strategy: str
    
    # Strategy groups (optional, for initialization)
    strategy_groups: Optional[List[Dict[str, Any]]] = None


class ConfigManager:
    """
    负责加载和验证 config.json 配置
    
    责任范围:
    - 从 config.json 读取静态配置参数
    - 验证必要的字段存在
    - 提供默认值
    - 返回类型化的 ProductionConfig 对象
    
    不负责:
    - 保存运行时状态（那是 ProductionState 的工作）
    - 管理实时 positions（那是 ProductionState 的工作）
    """
    
    DEFAULT_CONFIG_FILE = "config.json"
    
    # 必需的字段
    REQUIRED_FIELDS = {
        "data": ["monitor_list_file", "data_dir"],
        "backtest": ["starting_capital_jpy"],
        "portfolio": ["max_positions", "max_position_pct"],
        "default_strategies": ["entry", "exit"]
    }
    
    # 默认值
    DEFAULTS = {
        "state_file": "production_state.json",
        "signal_file_pattern": "output/signals/{date}.json",
        "report_file_pattern": "output/report/{date}.md",
        "history_file": "trade_history.json",
        "buy_threshold": 65.0,
    }
    
    def __init__(self, config_file: str = DEFAULT_CONFIG_FILE):
        """
        Initialize ConfigManager
        
        Args:
            config_file: Path to config.json
            
        Raises:
            FileNotFoundError: If config file not found
            ValueError: If config is missing required fields
        """
        self.config_file = Path(config_file)
        if not self.config_file.exists():
            raise FileNotFoundError(f"Config file not found: {config_file}")
        
        self.raw_config = self._load_config()
        self._validate_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load config from JSON file"""
        with open(self.config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def _validate_config(self) -> None:
        """Validate that required fields exist"""
        for section, fields in self.REQUIRED_FIELDS.items():
            if section not in self.raw_config:
                raise ValueError(f"Missing required section: {section}")
            
            for field in fields:
                if field not in self.raw_config[section]:
                    raise ValueError(
                        f"Missing required field: {section}.{field}"
                    )
    
    def get_production_config(self) -> ProductionConfig:
        """
        Extract production configuration
        
        Returns:
            ProductionConfig object with all settings
        """
        data_cfg = self.raw_config.get("data", {})
        backtest_cfg = self.raw_config.get("backtest", {})
        portfolio_cfg = self.raw_config.get("portfolio", {})
        default_strat = self.raw_config.get("default_strategies", {})
        prod_cfg = self.raw_config.get("production", {})
        
        return ProductionConfig(
            # Data paths
            monitor_list_file=data_cfg.get("monitor_list_file"),
            data_dir=data_cfg.get("data_dir"),
            
            # Production settings
            state_file=prod_cfg.get("state_file", self.DEFAULTS["state_file"]),
            signal_file_pattern=prod_cfg.get(
                "signal_file_pattern", 
                self.DEFAULTS["signal_file_pattern"]
            ),
            report_file_pattern=prod_cfg.get(
                "report_file_pattern",
                self.DEFAULTS["report_file_pattern"]
            ),
            history_file=prod_cfg.get(
                "history_file",
                self.DEFAULTS["history_file"]
            ),
            
            # Position management
            max_positions_per_group=prod_cfg.get(
                "max_positions_per_group",
                portfolio_cfg.get("max_positions", 5)
            ),
            max_position_pct=prod_cfg.get(
                "max_position_pct",
                portfolio_cfg.get("max_position_pct", 0.30)
            ),
            buy_threshold=prod_cfg.get(
                "buy_threshold",
                self.DEFAULTS["buy_threshold"]
            ),
            
            # Default strategies
            default_entry_strategy=default_strat.get("entry", "SimpleScorerStrategy"),
            default_exit_strategy=default_strat.get("exit", "ATRExitStrategy"),
            
            # Strategy groups (optional)
            strategy_groups=prod_cfg.get("strategy_groups", None)
        )
    
    def get_monitor_list_path(self) -> Path:
        """Get path to monitor list file"""
        path = self.raw_config["data"]["monitor_list_file"]
        return Path(path)
    
    def get_data_dir(self) -> Path:
        """Get data directory path"""
        path = self.raw_config["data"]["data_dir"]
        return Path(path)
    
    def get_initial_capital(self) -> float:
        """Get initial capital from backtest config"""
        return self.raw_config["backtest"]["starting_capital_jpy"]
    
    def get_default_strategies(self) -> tuple:
        """
        Get default entry and exit strategies
        
        Returns:
            (entry_strategy_name, exit_strategy_name)
        """
        default_strat = self.raw_config["default_strategies"]
        return (default_strat["entry"], default_strat["exit"])
    
    def print_summary(self) -> None:
        """Print configuration summary"""
        prod_cfg = self.get_production_config()
        
        print("\n" + "="*60)
        print("PRODUCTION CONFIGURATION")
        print("="*60)
        print(f"Monitor List:     {prod_cfg.monitor_list_file}")
        print(f"Data Directory:   {prod_cfg.data_dir}")
        print(f"State File:       {prod_cfg.state_file}")
        print(f"History File:     {prod_cfg.history_file}")
        print(f"\nPosition Management:")
        print(f"  Max Positions:  {prod_cfg.max_positions_per_group}")
        print(f"  Max Position%:  {prod_cfg.max_position_pct*100:.0f}%")
        print(f"  Buy Threshold:  {prod_cfg.buy_threshold}")
        print(f"\nDefault Strategies:")
        print(f"  Entry:          {prod_cfg.default_entry_strategy}")
        print(f"  Exit:           {prod_cfg.default_exit_strategy}")
        print("="*60 + "\n")
