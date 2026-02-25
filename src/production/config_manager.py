"""
Phase 1: Configuration Manager
负责从 config.json 读取系统初始化参数
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ProductionConfig:
    """Production configuration from config.json"""

    # Data paths
    monitor_list_file: str
    fetch_universe_file: str
    sector_pool_file: Optional[str]
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
        "default_strategies": ["entry", "exit"],
    }

    # 默认值（G盘优先，本地回退）
    DEFAULTS = {
        "state_file": r"G:\My Drive\AI-Stock-Sync\state\production_state.json",
        "signal_file_pattern": r"G:\My Drive\AI-Stock-Sync\signals\{date}.json",
        "report_file_pattern": r"G:\My Drive\AI-Stock-Sync\reports\{date}.md",
        "history_file": r"G:\My Drive\AI-Stock-Sync\state\trade_history.json",
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
        with open(self.config_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _validate_config(self) -> None:
        """Validate that required fields exist"""
        for section, fields in self.REQUIRED_FIELDS.items():
            if section not in self.raw_config:
                raise ValueError(f"Missing required section: {section}")

            for field in fields:
                if field not in self.raw_config[section]:
                    raise ValueError(f"Missing required field: {section}.{field}")

    def _resolve_path_with_fallback(self, cloud_path: str, local_fallback: str) -> str:
        """
        智能路径解析：G盘优先，本地回退

        Args:
            cloud_path: G盘路径
            local_fallback: 本地回退路径

        Returns:
            可用的文件路径
        """
        # 如果不是 G 盘路径，直接返回
        if not cloud_path.startswith("G:\\"):
            return cloud_path

        try:
            # 提取目录部分（处理带 {date} 的 pattern）
            path_obj = Path(cloud_path)
            if "{date}" in cloud_path:
                # 对于 pattern，测试父目录
                test_dir = path_obj.parent
            else:
                # 对于文件，测试父目录
                test_dir = path_obj.parent

            # 确保目录存在
            test_dir.mkdir(parents=True, exist_ok=True)

            # 测试写入权限
            probe = test_dir / ".write_probe.tmp"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()

            return cloud_path  # G盘可用

        except Exception as e:
            # G盘不可用，回退到本地
            print(f"⚠️  G盘路径不可用，回退到本地: {local_fallback}")
            print(f"   原因: {e}")
            return local_fallback

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

        # 获取用户配置或默认值
        state_file_raw = prod_cfg.get("state_file", self.DEFAULTS["state_file"])
        history_file_raw = prod_cfg.get("history_file", self.DEFAULTS["history_file"])
        signal_pattern_raw = prod_cfg.get(
            "signal_file_pattern", self.DEFAULTS["signal_file_pattern"]
        )
        report_pattern_raw = prod_cfg.get(
            "report_file_pattern", self.DEFAULTS["report_file_pattern"]
        )

        # 应用智能回退
        state_file = self._resolve_path_with_fallback(
            state_file_raw, "production_state.json"
        )
        history_file = self._resolve_path_with_fallback(
            history_file_raw, "trade_history.json"
        )
        signal_pattern = self._resolve_path_with_fallback(
            signal_pattern_raw, "output/signals/{date}.json"
        )
        report_pattern = self._resolve_path_with_fallback(
            report_pattern_raw, "output/report/{date}.md"
        )

        return ProductionConfig(
            # Data paths
            monitor_list_file=prod_cfg.get(
                "monitor_list_file", data_cfg.get("monitor_list_file")
            ),
            fetch_universe_file=prod_cfg.get(
                "fetch_universe_file", "data/fetch_universe.json"
            ),
            sector_pool_file=prod_cfg.get("sector_pool_file"),
            data_dir=data_cfg.get("data_dir"),
            # Production settings (使用回退后的路径)
            state_file=state_file,
            signal_file_pattern=signal_pattern,
            report_file_pattern=report_pattern,
            history_file=history_file,
            # Position management
            max_positions_per_group=prod_cfg.get(
                "max_positions_per_group", portfolio_cfg.get("max_positions", 5)
            ),
            max_position_pct=prod_cfg.get(
                "max_position_pct", portfolio_cfg.get("max_position_pct", 0.30)
            ),
            buy_threshold=prod_cfg.get("buy_threshold", self.DEFAULTS["buy_threshold"]),
            # Default strategies
            default_entry_strategy=default_strat.get("entry", "SimpleScorerStrategy"),
            default_exit_strategy=default_strat.get("exit", "ATRExitStrategy"),
            # Strategy groups (optional)
            strategy_groups=prod_cfg.get("strategy_groups", None),
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

        print("\n" + "=" * 60)
        print("PRODUCTION CONFIGURATION")
        print("=" * 60)
        print(f"Monitor List:     {prod_cfg.monitor_list_file}")
        print(f"Fetch Universe:   {prod_cfg.fetch_universe_file}")
        print(f"Sector Pool File: {prod_cfg.sector_pool_file or 'AUTO(latest)'}")
        print(f"Data Directory:   {prod_cfg.data_dir}")

        # 添加路径类型标识
        if "G:\\" in prod_cfg.state_file:
            print("📁 文件位置:      G盘 (Google Drive同步)")
        else:
            print("⚠️  文件位置:      本地（G盘不可用）")

        print(f"State File:       {prod_cfg.state_file}")
        print(f"History File:     {prod_cfg.history_file}")
        print("\nPosition Management:")
        print(f"  Max Positions:  {prod_cfg.max_positions_per_group}")
        print(f"  Max Position%:  {prod_cfg.max_position_pct * 100:.0f}%")
        print(f"  Buy Threshold:  {prod_cfg.buy_threshold}")
        print("\nDefault Strategies:")
        print(f"  Entry:          {prod_cfg.default_entry_strategy}")
        print(f"  Exit:           {prod_cfg.default_exit_strategy}")
        print("=" * 60 + "\n")
