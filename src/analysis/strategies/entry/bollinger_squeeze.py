"""
布林带挤压突破入场策略 (Bollinger Squeeze Breakout)

核心逻辑:
1. 检测布林带宽度挤压（低波动率蓄势）
2. 等待价格突破上轨 + 成交量确认
3. OBV能量潮确认机构吸筹
4. ADX确认趋势强度

适用场景: 震荡后的趋势启动点
"""

import pandas as pd
import numpy as np
from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData


class BollingerSqueezeStrategy(BaseEntryStrategy):
    """
    布林带挤压突破策略
    
    多阶段过滤:
    1. 波动率挤压: BB_Width处于历史低位（20日排名 < 30%）
    2. 价格突破: Close > BB_Upper
    3. 成交量确认: Volume > 1.3x Volume_SMA_20
    4. 能量潮确认: OBV上升趋势（5日斜率 > 0）
    5. 趋势强度: ADX_14 > 20（有明确趋势）
    
    Args:
        squeeze_percentile: 挤压判断百分位（默认30%）
        volume_multiplier: 成交量倍数（默认1.3）
        min_adx: 最低ADX阈值（默认20）
    """
    
    def __init__(
        self,
        squeeze_percentile: float = 30.0,
        volume_multiplier: float = 1.3,
        min_adx: float = 20.0
    ):
        super().__init__(strategy_name="BollingerSqueeze")
        self.squeeze_percentile = squeeze_percentile
        self.volume_multiplier = volume_multiplier
        self.min_adx = min_adx
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成布林带挤压突破信号"""
        
        df = market_data.df_features
        
        if df.empty or len(df) < 20:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                metadata={"reason": "Insufficient data"}
            )
        
        # 确保所有需要的列存在
        required_cols = ['Close', 'BB_Upper', 'BB_Lower', 'BB_Width', 'BB_PctB', 
                        'Volume', 'Volume_SMA_20', 'OBV', 'ADX_14']
        if not all(col in df.columns for col in required_cols):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                metadata={"reason": "Missing required indicators"}
            )
        
        # 获取最近数据
        recent = df.iloc[-20:]  # 最近20天
        latest = df.iloc[-1]
        
        # ========== STAGE 1: 波动率挤压检测 ==========
        # BB_Width在历史低位（20日内排名）
        bb_width_current = latest['BB_Width']
        bb_width_percentile = (recent['BB_Width'] < bb_width_current).sum() / len(recent) * 100
        
        is_squeezed = bb_width_percentile < self.squeeze_percentile
        
        # ========== STAGE 2: 价格突破上轨 ==========
        close_price = latest['Close']
        bb_upper = latest['BB_Upper']
        bb_lower = latest['BB_Lower']
        bb_pctb = latest['BB_PctB']  # (Close - Lower) / (Upper - Lower)
        
        # 价格在上轨附近或突破上轨
        is_breakout = close_price > bb_upper or bb_pctb > 0.9
        
        # ========== STAGE 3: 成交量确认 ==========
        volume = latest['Volume']
        volume_sma = latest['Volume_SMA_20']
        
        is_volume_surge = volume > (volume_sma * self.volume_multiplier) if volume_sma > 0 else False
        
        # ========== STAGE 4: OBV能量潮确认 ==========
        # 计算OBV的5日斜率
        obv_recent = recent['OBV'].tail(5)
        if len(obv_recent) >= 5:
            obv_slope = (obv_recent.iloc[-1] - obv_recent.iloc[0]) / 5
            is_obv_rising = obv_slope > 0
        else:
            is_obv_rising = False
        
        # ========== STAGE 5: 趋势强度确认 (ADX) ==========
        adx = latest['ADX_14']
        has_trend = adx > self.min_adx
        
        # ========== 综合判断 ==========
        signals = {
            "squeezed": is_squeezed,
            "breakout": is_breakout,
            "volume_surge": is_volume_surge,
            "obv_rising": is_obv_rising,
            "trend_strength": has_trend
        }
        
        # 计算置信度（每个条件20%）
        confidence = sum([
            0.25 if is_squeezed else 0.0,
            0.25 if is_breakout else 0.0,
            0.20 if is_volume_surge else 0.0,
            0.15 if is_obv_rising else 0.0,
            0.15 if has_trend else 0.0
        ])
        
        # 必须满足核心条件：挤压 + 突破
        if is_squeezed and is_breakout and confidence >= 0.6:
            action = SignalAction.BUY
        else:
            action = SignalAction.HOLD
        
        metadata = {
            "bb_width_pct": round(bb_width_percentile, 2),
            "bb_pctb": round(bb_pctb, 4),
            "volume_ratio": round(volume / volume_sma, 2) if volume_sma > 0 else 0,
            "obv_slope": round(obv_slope, 0) if 'obv_slope' in locals() else 0,
            "adx": round(adx, 2),
            "signals": signals,
            "close": round(close_price, 2),
            "bb_upper": round(bb_upper, 2)
        }
        
        return TradingSignal(
            action=action,
            confidence=confidence,
            metadata=metadata
        )
