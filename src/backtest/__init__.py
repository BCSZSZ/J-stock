"""
Backtesting Module
Validates trading strategies on historical data.
"""
from src.backtest.engine import backtest_strategy, backtest_strategies
from src.backtest.metrics import calculate_sharpe_ratio, calculate_max_drawdown
from src.backtest.models import Trade, BacktestResult

__all__ = [
    'backtest_strategy',
    'backtest_strategies',
    'calculate_sharpe_ratio',
    'calculate_max_drawdown',
    'Trade',
    'BacktestResult',
]
