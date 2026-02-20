"""
Exit策略实现

提供基于不同逻辑的退出策略
"""

from .atr_exit import ATRExitStrategy
from .score_based_exit import ScoreBasedExitStrategy, ScoreBasedExitTight, ScoreBasedExitLoose
from .layered_exit import LayeredExitStrategy
from .donchian_break_exit import DonchianBreakExit
from .gap_panic_exit import GapPanicExit
from .multiview_grid_exit import MultiViewCompositeExit

__all__ = [
    'ATRExitStrategy',
    'ScoreBasedExitStrategy',
    'ScoreBasedExitTight',
    'ScoreBasedExitLoose',
    'LayeredExitStrategy',
    'DonchianBreakExit',
    'GapPanicExit',
    'MultiViewCompositeExit',
]
