"""
Stock Scoring Strategies

This package provides multiple scoring strategies for Japanese stock analysis.

Available Strategies:
- SimpleScorer: Original logic (40/30/20/10 weights, Foreign-only institutional)
- EnhancedScorer: Japan-optimized (35/35/20/10, Smart Money composite, EPS focus)

Usage:
    from src.analysis.scorers import SimpleScorer, EnhancedScorer
    
    scorer = EnhancedScorer()
    result = scorer.evaluate(ticker, df_features, df_trades, df_financials, metadata)
    print(result.total_score, result.signal_strength)
"""

from .base_scorer import BaseScorer, ScoreResult
from .simple_scorer import SimpleScorer
from .enhanced_scorer import EnhancedScorer

# For backward compatibility
StockSignalScorer = SimpleScorer

__all__ = [
    'BaseScorer',
    'ScoreResult',
    'SimpleScorer',
    'EnhancedScorer',
    'StockSignalScorer',
]
