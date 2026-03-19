"""
Phase 1: Configuration Manager
负责从 config.json 读取系统初始化参数
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.config.runtime import is_local_path, sample_path_from_pattern
from src.config.service import load_config


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
    cash_history_file: str

    # Position management
    max_positions_per_group: int
    max_position_pct: float
    buy_threshold: float

    # Default strategies
    default_entry_strategy: str
    default_exit_strategy: str

    # Strategy groups (optional, for initialization)
    strategy_groups: Optional[List[Dict[str, Any]]] = None

    # S3 sync (optional, for local → S3 push after --input)
    ops_s3_prefix: Optional[str] = None

    # Runtime/backends
    runtime_mode: str = "local"
    storage_backend: str = "local_fs"
    state_backend: str = "json"


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

    # 默认值（本地友好，可被config覆盖）
    DEFAULTS = {
        "state_file": "output/state/production_state.json",
        "signal_file_pattern": "output/signals/{date}.json",
        "report_file_pattern": "output/reports/{date}.md",
        "history_file": "output/state/trade_history.json",
        "cash_history_file": "output/state/cash_history.json",
        "fetch_universe_file": "output/state/fetch_universe.json",
        "sector_pool_file": "G:/My Drive/AI-Stock-Sync/universe/sector_pool",
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
        return load_config(str(self.config_file))

    def _validate_config(self) -> None:
        """Validate that required fields exist"""
        for section, fields in self.REQUIRED_FIELDS.items():
            if section not in self.raw_config:
                raise ValueError(f"Missing required section: {section}")

            for field in fields:
                if field not in self.raw_config[section]:
                    raise ValueError(f"Missing required field: {section}.{field}")

    def _ensure_path_ready(self, path_value: str, is_pattern: bool = False) -> str:
        """
        Ensure local paths have parent dirs ready.
        S3 URI is allowed and returned as-is.

        Args:
            path_value: 文件路径（可含 {date} 占位符）

        Returns:
            Original path/URI
        """
        if not path_value:
            raise ValueError("Empty path is not allowed in production config")
        if not is_local_path(path_value):
            return path_value

        local_probe = sample_path_from_pattern(path_value) if is_pattern else path_value
        path_obj = Path(local_probe)
        test_dir = path_obj.parent
        test_dir.mkdir(parents=True, exist_ok=True)
        probe = test_dir / ".write_probe.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return path_value

    def _ensure_gdrive_dir_ready(self, path_value: str) -> str:
        if not is_local_path(path_value):
            return path_value
        path_obj = Path(path_value)
        path_obj.mkdir(parents=True, exist_ok=True)
        return path_value

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
        runtime_cfg = self.raw_config.get("runtime", {})

        # 获取用户配置或默认值
        state_file_raw = prod_cfg.get("state_file", self.DEFAULTS["state_file"])
        history_file_raw = prod_cfg.get("history_file", self.DEFAULTS["history_file"])
        cash_history_file_raw = prod_cfg.get(
            "cash_history_file", self.DEFAULTS["cash_history_file"]
        )
        signal_pattern_raw = prod_cfg.get(
            "signal_file_pattern", self.DEFAULTS["signal_file_pattern"]
        )
        report_pattern_raw = prod_cfg.get(
            "report_file_pattern", self.DEFAULTS["report_file_pattern"]
        )

        state_file = self._ensure_path_ready(state_file_raw)
        history_file = self._ensure_path_ready(history_file_raw)
        cash_history_file = self._ensure_path_ready(cash_history_file_raw)
        signal_pattern = self._ensure_path_ready(signal_pattern_raw, is_pattern=True)
        report_pattern = self._ensure_path_ready(report_pattern_raw, is_pattern=True)

        monitor_list_file_raw = prod_cfg.get(
            "monitor_list_file", data_cfg.get("monitor_list_file")
        )
        monitor_list_file = self._ensure_path_ready(monitor_list_file_raw)

        fetch_universe_file_raw = prod_cfg.get(
            "fetch_universe_file", self.DEFAULTS["fetch_universe_file"]
        )
        fetch_universe_file = self._ensure_path_ready(fetch_universe_file_raw)

        sector_pool_file_raw = prod_cfg.get(
            "sector_pool_file", self.DEFAULTS["sector_pool_file"]
        )
        sector_pool_file = self._ensure_gdrive_dir_ready(sector_pool_file_raw)

        prod = ProductionConfig(
            # Data paths
            monitor_list_file=monitor_list_file,
            fetch_universe_file=fetch_universe_file,
            sector_pool_file=sector_pool_file,
            data_dir=data_cfg.get("data_dir"),
            # Production settings
            state_file=state_file,
            signal_file_pattern=signal_pattern,
            report_file_pattern=report_pattern,
            history_file=history_file,
            cash_history_file=cash_history_file,
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
            ops_s3_prefix=prod_cfg.get("ops_s3_prefix", None),
            runtime_mode=str(runtime_cfg.get("mode", "local")),
            storage_backend=str(runtime_cfg.get("storage_backend", "local_fs")),
            state_backend=str(runtime_cfg.get("state_backend", "json")),
        )
        setattr(prod, "raw_config", self.raw_config)
        return prod

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

        print(f"Runtime Mode:     {prod_cfg.runtime_mode}")
        print(f"Storage Backend:  {prod_cfg.storage_backend}")
        print(f"State Backend:    {prod_cfg.state_backend}")

        print(f"State File:       {prod_cfg.state_file}")
        print(f"History File:     {prod_cfg.history_file}")
        print(f"Cash History:     {prod_cfg.cash_history_file}")
        print("\nPosition Management:")
        print(f"  Max Positions:  {prod_cfg.max_positions_per_group}")
        print(f"  Max Position%:  {prod_cfg.max_position_pct * 100:.0f}%")
        print(f"  Buy Threshold:  {prod_cfg.buy_threshold}")
        print("\nDefault Strategies:")
        print(f"  Entry:          {prod_cfg.default_entry_strategy}")
        print(f"  Exit:           {prod_cfg.default_exit_strategy}")
        print("=" * 60 + "\n")
