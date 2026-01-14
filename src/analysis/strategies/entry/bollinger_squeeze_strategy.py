"""
Bollinger Squeeze Entry Strategy
布林带挤压突破入场策略

核心逻辑：
1. 检测布林带宽度收窄（BB_Width < 历史20分位 - 波动率挤压）
2. 等待突破信号：价格突破上轨 + 成交量放大
3. ADX > 20确认趋势强度
4. 适合捕捉震荡后的爆发行情
"""

from typing import Optional
import pandas as pd
import numpy as np

from src.analysis.signals import TradingSignal, SignalAction, MarketData
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy


class BollingerSqueezeStrategy(BaseEntryStrategy):
    """
    布林带挤压突破策略
    
    Parameters:
        squeeze_percentile: 挤压判断的百分位阈值（默认20，即BB_Width < 历史20%分位）
        adx_threshold: ADX最低阈值（默认20）
        volume_multiplier: 成交量放大倍数（默认1.5）
        min_confidence: 最低置信度（默认0.6）
    """
    
    def __init__(
        self,
        squeeze_percentile: float = 20.0,
        adx_threshold: float = 20.0,
        volume_multiplier: float = 1.5,
        min_confidence: float = 0.6
    ):
        super().__init__()
        self.squeeze_percentile = squeeze_percentile
        self.adx_threshold = adx_threshold
        self.volume_multiplier = volume_multiplier
        self.min_confidence = min_confidence
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号
        
        检测逻辑：
        1. BB_Width处于挤压状态（低于历史20分位）
        2. 价格突破上轨（BB_PctB > 1.0）
        3. 成交量放大（Volume > 1.5 * Volume_SMA_20）
        4. ADX > 20（趋势形成）
        """
        df = market_data.df_features
        
        if df.empty or len(df) < 50:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["数据不足"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检查必要字段
        required_fields = ['BB_Width', 'BB_PctB', 'ADX_14', 'Volume', 'Volume_SMA_20', 'Close']
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["缺少必要技术指标"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        reasons = []
        confidence = 0.0
        
        # 1. 布林带宽度挤压检测
        bb_width_series = df['BB_Width'].dropna()
        if len(bb_width_series) < 20:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["历史数据不足"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        squeeze_threshold = np.percentile(bb_width_series.tail(100), self.squeeze_percentile)
        is_squeezed = latest['BB_Width'] < squeeze_threshold
        
        # 2. 突破上轨检测
        breakout_upper = latest['BB_PctB'] > 1.0 and prev['BB_PctB'] <= 1.0
        
        # 3. 成交量放大
        volume_surge = (
            pd.notna(latest['Volume']) and 
            pd.notna(latest['Volume_SMA_20']) and 
            latest['Volume'] > self.volume_multiplier * latest['Volume_SMA_20']
        )
        
        # 4. ADX趋势确认
        adx_confirmed = pd.notna(latest['ADX_14']) and latest['ADX_14'] > self.adx_threshold
        
        # 综合判断
        if is_squeezed:
            reasons.append(f"布林带挤压（宽度{latest['BB_Width']:.4f} < {squeeze_threshold:.4f}）")
            confidence += 0.2
        
        if breakout_upper:
            reasons.append(f"突破上轨（PctB={latest['BB_PctB']:.2f}）")
            confidence += 0.4
        else:
            # 即使没突破，但接近上轨也加分
            if latest['BB_PctB'] > 0.8:
                reasons.append(f"接近上轨（PctB={latest['BB_PctB']:.2f}）")
                confidence += 0.2
        
        if volume_surge:
            reasons.append(f"成交量放大（{latest['Volume']/latest['Volume_SMA_20']:.2f}x）")
            confidence += 0.2
        
        if adx_confirmed:
            reasons.append(f"ADX确认趋势（{latest['ADX_14']:.1f}）")
            confidence += 0.2
        else:
            reasons.append(f"ADX偏弱（{latest['ADX_14']:.1f}）")
            confidence -= 0.1
        
        # 判定买入
        action = SignalAction.BUY if confidence >= self.min_confidence else SignalAction.HOLD
        
        if action == SignalAction.HOLD and len(reasons) == 0:
            reasons = ["无突破信号"]
        
        return TradingSignal(
            action=action,
            confidence=min(confidence, 1.0),
            reasons=reasons,
            metadata={
                "bb_width": float(latest['BB_Width']),
                "bb_pctb": float(latest['BB_PctB']),
                "adx": float(latest['ADX_14']) if pd.notna(latest['ADX_14']) else 0.0,
                "volume_ratio": float(latest['Volume'] / latest['Volume_SMA_20']) if pd.notna(latest['Volume_SMA_20']) else 0.0,
                "is_squeezed": is_squeezed,
                "breakout": breakout_upper
            },
            strategy_name="BollingerSqueezeStrategy"
        )
