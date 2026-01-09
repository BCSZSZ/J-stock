"""
Exit Strategies Package

This package provides multiple exit strategies for position management.

Available Strategies:
- ATRExiter: Simple ATR-based stops with 4 priority levels (P0-P3)
- LayeredExiter: Comprehensive 6-layer exit system optimized for Japanese markets

Usage:
    from src.analysis.exiters import ATRExiter, Position
    
    # Create position
    position = Position(
        ticker="8035",
        entry_price=15000,
        entry_date=pd.Timestamp("2025-12-01"),
        entry_score=75.0,
        quantity=100,
        peak_price_since_entry=16500
    )
    
    # Evaluate exit
    exiter = ATRExiter()
    signal = exiter.evaluate_exit(position, df_features, df_trades, df_financials, metadata, current_score=72.0)
    
    print(signal.action)  # "HOLD" or "SELL_100%" etc.
    print(signal.reason)
"""

from .base_exiter import BaseExiter, Position, ExitSignal
from .atr_exiter import ATRExiter
from .layered_exiter import LayeredExiter

__all__ = [
    'BaseExiter',
    'Position',
    'ExitSignal',
    'ATRExiter',
    'LayeredExiter',
]
