"""
策略评价模块
提供年度、市场环境分类的策略性能评估
"""
from .strategy_evaluator import (
    StrategyEvaluator, 
    AnnualStrategyResult, 
    MarketRegime,
    create_annual_periods,
    create_monthly_periods,
    create_quarterly_periods
)

__all__ = [
    'StrategyEvaluator', 
    'AnnualStrategyResult', 
    'MarketRegime',
    'create_annual_periods',
    'create_monthly_periods',
    'create_quarterly_periods'
]
