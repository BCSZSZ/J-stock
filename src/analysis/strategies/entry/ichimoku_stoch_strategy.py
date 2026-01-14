"""
Ichimoku + Stochastic Entry Strategy
一目均衡表 + KDJ组合入场策略

核心逻辑：
1. 一目均衡表云层多头排列（价格 > 云层，SpanA > SpanB）
2. KDJ超卖后金叉（Stoch_K < 30 → K上穿D）
3. OBV能量潮确认（机构吸筹）
4. 适合震荡市场寻找低吸机会
"""

from typing import Optional
import pandas as pd
import numpy as np

from src.analysis.signals import TradingSignal, SignalAction, MarketData
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy


class IchimokuStochStrategy(BaseEntryStrategy):
    """
    一目均衡表 + KDJ策略
    
    Parameters:
        stoch_oversold: KDJ超卖阈值（默认30）
        obv_lookback: OBV趋势判断回望期（默认20）
        min_confidence: 最低置信度（默认0.6）
        require_cloud_bullish: 是否强制要求云层多头（默认True）
    """
    
    def __init__(
        self,
        stoch_oversold: float = 30.0,
        obv_lookback: int = 20,
        min_confidence: float = 0.6,
        require_cloud_bullish: bool = True
    ):
        super().__init__()
        self.stoch_oversold = stoch_oversold
        self.obv_lookback = obv_lookback
        self.min_confidence = min_confidence
        self.require_cloud_bullish = require_cloud_bullish
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号
        
        检测逻辑：
        1. 价格在云层上方（Close > max(Ichi_SpanA, Ichi_SpanB)）
        2. 云层多头（Ichi_SpanA > Ichi_SpanB）
        3. KDJ超卖后金叉（K < 30且K上穿D）
        4. OBV上升（机构吸筹确认）
        """
        df = market_data.df_features
        
        if df.empty or len(df) < 30:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["数据不足"],
                strategy_name="IchimokuStochStrategy"
            )
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检查必要字段
        required_fields = ['Close', 'Ichi_SpanA', 'Ichi_SpanB', 'Stoch_K', 'Stoch_D', 'OBV']
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["缺少必要技术指标"],
                strategy_name="IchimokuStochStrategy"
            )
        
        reasons = []
        confidence = 0.0
        
        # 1. 云层位置判断
        cloud_top = max(latest['Ichi_SpanA'], latest['Ichi_SpanB']) if pd.notna(latest['Ichi_SpanA']) and pd.notna(latest['Ichi_SpanB']) else latest['Close']
        cloud_bottom = min(latest['Ichi_SpanA'], latest['Ichi_SpanB']) if pd.notna(latest['Ichi_SpanA']) and pd.notna(latest['Ichi_SpanB']) else latest['Close']
        
        above_cloud = latest['Close'] > cloud_top
        cloud_bullish = latest['Ichi_SpanA'] > latest['Ichi_SpanB'] if pd.notna(latest['Ichi_SpanA']) and pd.notna(latest['Ichi_SpanB']) else False
        
        # 2. KDJ金叉检测
        k_cur = latest['Stoch_K']
        d_cur = latest['Stoch_D']
        k_prev = prev['Stoch_K']
        d_prev = prev['Stoch_D']
        
        stoch_crossover = (
            pd.notna(k_cur) and pd.notna(d_cur) and
            pd.notna(k_prev) and pd.notna(d_prev) and
            k_prev < d_prev and k_cur > d_cur
        )
        stoch_oversold = k_cur < self.stoch_oversold if pd.notna(k_cur) else False
        
        # 3. OBV趋势判断
        obv_series = df['OBV'].dropna()
        if len(obv_series) >= self.obv_lookback:
            obv_slope = (obv_series.iloc[-1] - obv_series.iloc[-self.obv_lookback]) / self.obv_lookback
            obv_rising = obv_slope > 0
        else:
            obv_rising = False
            obv_slope = 0
        
        # 综合判断
        if above_cloud:
            reasons.append(f"价格云上（¥{latest['Close']:.0f} > ¥{cloud_top:.0f}）")
            confidence += 0.25
        else:
            reasons.append(f"价格云下（¥{latest['Close']:.0f} < ¥{cloud_top:.0f}）")
            if self.require_cloud_bullish:
                confidence -= 0.3
        
        if cloud_bullish:
            reasons.append("云层多头")
            confidence += 0.15
        else:
            reasons.append("云层空头")
            if self.require_cloud_bullish:
                confidence -= 0.2
        
        if stoch_crossover:
            if stoch_oversold:
                reasons.append(f"KDJ超卖金叉（K={k_cur:.1f} D={d_cur:.1f}）")
                confidence += 0.4
            else:
                reasons.append(f"KDJ金叉（K={k_cur:.1f} D={d_cur:.1f}）")
                confidence += 0.25
        elif stoch_oversold:
            reasons.append(f"KDJ超卖区（K={k_cur:.1f}）")
            confidence += 0.1
        
        if obv_rising:
            reasons.append(f"OBV上升（斜率{obv_slope:.0e}）")
            confidence += 0.2
        else:
            reasons.append(f"OBV下降（斜率{obv_slope:.0e}）")
            confidence -= 0.1
        
        # 判定买入
        action = SignalAction.BUY if confidence >= self.min_confidence else SignalAction.HOLD
        
        if action == SignalAction.HOLD and len(reasons) == 0:
            reasons = ["条件未满足"]
        
        return TradingSignal(
            action=action,
            confidence=min(max(confidence, 0.0), 1.0),
            reasons=reasons,
            metadata={
                "close": float(latest['Close']),
                "cloud_top": float(cloud_top),
                "cloud_bottom": float(cloud_bottom),
                "above_cloud": above_cloud,
                "cloud_bullish": cloud_bullish,
                "stoch_k": float(k_cur) if pd.notna(k_cur) else 0.0,
                "stoch_d": float(d_cur) if pd.notna(d_cur) else 0.0,
                "stoch_crossover": stoch_crossover,
                "obv_slope": float(obv_slope)
            },
            strategy_name="IchimokuStochStrategy"
        )
