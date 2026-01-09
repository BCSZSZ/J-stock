"""
MACD金叉Entry策略

纯技术指标策略，不使用Score Utils
"""

from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
import numpy as np
import pandas as pd


class MACDCrossoverStrategy(BaseEntryStrategy):
    """
    MACD金叉Entry策略
    
    不使用Score Utils - 纯技术指标
    
    买入条件:
    - MACD柱由负转正（金叉）
    - 可选：成交量确认
    - 可选：趋势确认（价格在EMA200上方）
    
    Args:
        confirm_with_volume: 是否需要成交量确认
        confirm_with_trend: 是否需要趋势确认
        min_confidence: 最低置信度阈值（默认0.6）
    """
    
    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6
    ):
        super().__init__(strategy_name="MACDCrossover")
        self.confirm_volume = confirm_with_volume
        self.confirm_trend = confirm_with_trend
        self.min_confidence = min_confidence
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号"""
        
        df = market_data.df_features
        
        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name
            )
        
        # 检测MACD金叉
        macd_hist_prev = df.iloc[-2]['MACD_Hist']
        macd_hist_now = df.iloc[-1]['MACD_Hist']
        golden_cross = macd_hist_prev < 0 and macd_hist_now > 0
        
        if not golden_cross:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD golden cross"],
                metadata={
                    "macd_hist": macd_hist_now,
                    "macd_hist_prev": macd_hist_prev
                },
                strategy_name=self.strategy_name
            )
        
        # 基础信号
        reasons = ["MACD golden cross detected"]
        confidence = 0.7
        
        # 可选确认1: 成交量
        if self.confirm_volume:
            volume_now = df.iloc[-1]['Volume']
            volume_avg = df['Volume'].rolling(20).mean().iloc[-1]
            
            if pd.notna(volume_avg) and volume_avg > 0:
                volume_ratio = volume_now / volume_avg
                if volume_ratio > 1.2:
                    reasons.append(f"Volume surge (+{(volume_ratio-1)*100:.0f}%)")
                    confidence += 0.1
                else:
                    reasons.append(f"Volume normal ({volume_ratio:.2f}x avg)")
                    confidence -= 0.05
        
        # 可选确认2: 趋势
        if self.confirm_trend:
            price = df.iloc[-1]['Close']
            ema_200 = df.iloc[-1]['EMA_200']
            
            if price > ema_200:
                reasons.append(f"Above EMA200 (uptrend)")
                confidence += 0.1
            else:
                reasons.append(f"Below EMA200 (caution)")
                confidence -= 0.15
        
        confidence = np.clip(confidence, 0.0, 1.0)
        
        # 判断是否买入
        if confidence >= self.min_confidence:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "macd_hist": macd_hist_now,
                    "macd_hist_prev": macd_hist_prev,
                    "macd": df.iloc[-1]['MACD'],
                    "macd_signal": df.iloc[-1]['MACD_Signal']
                },
                strategy_name=self.strategy_name
            )
        
        # 金叉但置信度不足
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=confidence,
            reasons=reasons + [f"Confidence {confidence:.2f} < threshold {self.min_confidence}"],
            metadata={
                "macd_hist": macd_hist_now,
                "golden_cross": True,
                "low_confidence": True
            },
            strategy_name=self.strategy_name
        )
