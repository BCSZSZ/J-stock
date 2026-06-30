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
from .immediate_rebound_entry import (
    IMMEDIATE_REBOUND_ENTRY_NAMES,
    ImmediateReboundADXTrendPullbackEntry,
    ImmediateReboundBBMidPullbackEntry,
    ImmediateReboundEMA20TouchEntry,
    ImmediateReboundEMA50SupportEntry,
    ImmediateReboundEntry,
    ImmediateReboundLowerShadowUptrendEntry,
    ImmediateReboundMACDPositivePullbackEntry,
    ImmediateReboundNarrowRedUptrendEntry,
    ImmediateReboundOversoldUptrendEntry,
    ImmediateReboundRSI4555PullbackEntry,
    ImmediateReboundRedCloseNearHighEntry,
    ImmediateReboundThreeDaySnapbackEntry,
    ImmediateReboundTwoDownEMA20Entry,
)
from .moving_average_crossover_entry import MovingAverageCrossoverEntry
from .rule_based_crossover_entry import (
    CrossReboundKDJRSIEntry,
    CrossTrendMACDVolumeEntry,
    CrossTrendMACDVolumeLooseEntry,
    RuleBasedCrossoverEntry,
)
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
    "RuleBasedCrossoverEntry",
    "CrossTrendMACDVolumeEntry",
    "CrossTrendMACDVolumeLooseEntry",
    "CrossReboundKDJRSIEntry",
    "ImmediateReboundEntry",
    "ImmediateReboundOversoldUptrendEntry",
    "ImmediateReboundEMA50SupportEntry",
    "ImmediateReboundTwoDownEMA20Entry",
    "ImmediateReboundNarrowRedUptrendEntry",
    "ImmediateReboundADXTrendPullbackEntry",
    "ImmediateReboundMACDPositivePullbackEntry",
    "ImmediateReboundLowerShadowUptrendEntry",
    "ImmediateReboundRSI4555PullbackEntry",
    "ImmediateReboundRedCloseNearHighEntry",
    "ImmediateReboundBBMidPullbackEntry",
    "ImmediateReboundEMA20TouchEntry",
    "ImmediateReboundThreeDaySnapbackEntry",
    "IMMEDIATE_REBOUND_ENTRY_NAMES",
]
