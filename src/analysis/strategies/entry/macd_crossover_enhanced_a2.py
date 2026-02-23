"""
MACD金叉Entry策略 - 方案A_V2版本 (改进的价量维度优化)

基于方案A的失败经验，进行调整：
1. 删除 Close > Open 过滤（太严格）
2. 降低成交量倍数从 1.5x → 1.2x（平衡有效性）
"""

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


class MACDCrossoverEnhancedA2(BaseEntryStrategy):
    """
    MACD金叉Entry策略 - 方案A_V2版本 (改进的价量维度优化)

    买入条件:
    1. MACD柱由负转正（金叉）
    2. + Volume > 1.2x 5日均量（经优化的成交量突破）[方案A_V2改进]
    3. 可选：趋势确认（价格在EMA200上方）

    改进说明：
    - 删除了过于严格的 Close > Open 检查
    - 将成交量倍数从 1.5x 优化为 1.2x（平衡点）
    - 保留EMA200趋势确认

    Args:
        confirm_with_volume: 是否需要成交量确认（默认True）
        confirm_with_trend: 是否需要趋势确认（默认True）
        volume_surge_ratio: 成交量倍数阈值（默认1.2x，优化过）
        min_confidence: 最低置信度阈值（默认0.6）
    """

    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        volume_surge_ratio: float = 1.2,
        min_confidence: float = 0.6,
    ):
        super().__init__(strategy_name="MACDCrossoverEnhancedA2")
        self.confirm_volume = confirm_with_volume
        self.confirm_trend = confirm_with_trend
        self.volume_surge_ratio = volume_surge_ratio
        self.min_confidence = min_confidence

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号 - 方案A_V2版本（改进的价量维度优化）"""

        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        # Step 1: 检测MACD金叉
        macd_hist_prev = df.iloc[-2]["MACD_Hist"]
        macd_hist_now = df.iloc[-1]["MACD_Hist"]
        golden_cross = macd_hist_prev < 0 and macd_hist_now > 0

        if not golden_cross:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD golden cross"],
                metadata={"macd_hist": macd_hist_now, "macd_hist_prev": macd_hist_prev},
                strategy_name=self.strategy_name,
            )

        # 基础信号
        reasons = ["MACD golden cross detected"]
        confidence = 0.7

        # Step 2: 改进版 - 成交量确认（1.2x，相对平衡）
        if self.confirm_volume:
            volume_now = df.iloc[-1]["Volume"]

            # 计算5日平均成交量
            volume_5d_avg = df["Volume"].iloc[-5:].mean()

            if pd.notna(volume_5d_avg) and volume_5d_avg > 0:
                volume_ratio = volume_now / volume_5d_avg
                if volume_ratio > self.volume_surge_ratio:
                    reasons.append(
                        f"Volume surge: {volume_ratio:.2f}x ({self.volume_surge_ratio}x) ✓"
                    )
                    confidence += 0.12
                else:
                    reasons.append(
                        f"Volume normal: {volume_ratio:.2f}x (< {self.volume_surge_ratio}x)"
                    )
                    confidence -= 0.1

        # Step 3: 可选确认 - 趋势（EMA200）
        if self.confirm_trend:
            price = df.iloc[-1]["Close"]
            ema_200 = df.iloc[-1]["EMA_200"]

            if price > ema_200:
                reasons.append("Above EMA200 (uptrend ✓)")
                confidence += 0.1
            else:
                reasons.append("Below EMA200 (caution ⚠)")
                confidence -= 0.15

        confidence = np.clip(confidence, 0.0, 1.0)

        # Step 4: 判断是否买入
        if confidence >= self.min_confidence:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "macd_hist": macd_hist_now,
                    "macd_hist_prev": macd_hist_prev,
                    "macd": df.iloc[-1]["MACD"],
                    "macd_signal": df.iloc[-1]["MACD_Signal"],
                    "volume_ratio": volume_ratio if self.confirm_volume else None,
                },
                strategy_name=self.strategy_name,
            )

        # 金叉但置信度不足
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=confidence,
            reasons=reasons
            + [f"Confidence {confidence:.2f} < threshold {self.min_confidence}"],
            metadata={
                "macd_hist": macd_hist_now,
                "golden_cross": True,
                "low_confidence": True,
            },
            strategy_name=self.strategy_name,
        )


class MACDCrossoverEnhancedA2_V11(MACDCrossoverEnhancedA2):
    """MACDCrossoverEnhancedA2 with fixed volume_surge_ratio=1.1."""

    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            volume_surge_ratio=1.1,
            min_confidence=min_confidence,
        )
        self.strategy_name = "MACDCrossoverEnhancedA2_V11"


class MACDCrossoverEnhancedA2_V12(MACDCrossoverEnhancedA2):
    """MACDCrossoverEnhancedA2 with fixed volume_surge_ratio=1.2."""

    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            volume_surge_ratio=1.2,
            min_confidence=min_confidence,
        )
        self.strategy_name = "MACDCrossoverEnhancedA2_V12"


class MACDCrossoverEnhancedA2_V13(MACDCrossoverEnhancedA2):
    """MACDCrossoverEnhancedA2 with fixed volume_surge_ratio=1.3."""

    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
    ):
        super().__init__(
            confirm_with_volume=confirm_with_volume,
            confirm_with_trend=confirm_with_trend,
            volume_surge_ratio=1.3,
            min_confidence=min_confidence,
        )
        self.strategy_name = "MACDCrossoverEnhancedA2_V13"
