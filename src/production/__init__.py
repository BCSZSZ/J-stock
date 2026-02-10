"""
Production Trading System

Modules for multi-strategy-group portfolio management and execution.
"""

from .config_manager import (
    ConfigManager,
    ProductionConfig
)

from .state_manager import (
    Position,
    StrategyGroupState,
    ProductionState,
    Trade,
    TradeHistoryManager
)

from .signal_generator import (
    Signal,
    SignalGenerator
)

from .trade_executor import (
    ExecutionResult,
    TradeExecutor
)

from .report_builder import (
    ReportBuilder,
    MarketSummary,
    load_signals_from_file
)

__all__ = [
    # Configuration (Phase 1)
    'ConfigManager',
    'ProductionConfig',
    
    # State Management (Phase 2)
    'Position',
    'StrategyGroupState',
    'ProductionState',
    'Trade',
    'TradeHistoryManager',
    
    # Signal Generation (Phase 3)
    'Signal',
    'SignalGenerator',
    
    # Trade Execution (Phase 3)
    'ExecutionResult',
    'TradeExecutor',
    
    # Report Building (Phase 4)
    'ReportBuilder',
    'MarketSummary',
    'load_signals_from_file',
]
