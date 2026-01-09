"""
DEPRECATED: This file is kept for backward compatibility only.
Please import from src.analysis.scorers instead:

    from src.analysis.scorers import SimpleScorer, EnhancedScorer, BaseScorer, ScoreResult

New modular structure:
    - scorers/base_scorer.py - Abstract base class
    - scorers/simple_scorer.py - Original strategy
    - scorers/enhanced_scorer.py - Japan-optimized strategy
"""

# Import everything from the new modular scorers package
from .scorers import (
    BaseScorer,
    ScoreResult,
    SimpleScorer,
    EnhancedScorer,
    StockSignalScorer
)

# Re-export for backward compatibility
__all__ = [
    'BaseScorer',
    'ScoreResult',
    'SimpleScorer',
    'EnhancedScorer',
    'StockSignalScorer',
]
