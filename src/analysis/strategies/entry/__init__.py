"""
Entry策略实现

提供基于不同逻辑的入场策略
"""

from .macd_crossover import MACDCrossoverStrategy
from .macd_crossover_entry_variants import (
    MACDCrossoverFragileBelowZeroDownweightV6,
    MACDCrossoverFragileBelowZeroFilterV4,
    MACDCrossoverFragileBelowZeroLowADXFilterV5,
    MACDCrossoverFollowThroughFilterV3,
    MACDCrossoverShockFilterV1,
    MACDCrossoverShockOverheatFilterV2,
)
from .macd_crossover_precross_entry import MACDCrossoverWithPreCrossEntry
from .macd_enhanced_fundamental import MACDEnhancedFundamentalStrategy
from .macd_hysteresis_entry import (
    MACDHistHysteresisEntry,
    MACDHistHysteresisPreCrossEntry,
)
from .moving_average_crossover_entry import MovingAverageCrossoverEntry
from .scorer_strategy import EnhancedScorerStrategy, SimpleScorerStrategy

__all__ = [
    "SimpleScorerStrategy",
    "EnhancedScorerStrategy",
    "MACDCrossoverStrategy",
    "MACDCrossoverShockFilterV1",
    "MACDCrossoverShockOverheatFilterV2",
    "MACDCrossoverFollowThroughFilterV3",
    "MACDCrossoverFragileBelowZeroFilterV4",
    "MACDCrossoverFragileBelowZeroLowADXFilterV5",
    "MACDCrossoverFragileBelowZeroDownweightV6",
    "MACDCrossoverWithPreCrossEntry",
    "MACDEnhancedFundamentalStrategy",
    "MACDHistHysteresisEntry",
    "MACDHistHysteresisPreCrossEntry",
    "MovingAverageCrossoverEntry",
]
