"""
Bollinger Dynamic Exit Strategy
布林带动态退出策略

核心逻辑：
1. P0: 紧急止损（价格跌破下轨）
2. P1: 利润保护（BB_PctB从高位回落 + OBV转负）
3. P2: 超买退出（BB_PctB > 0.9 + KDJ超买死叉）
4. 动态适应波动率，利用布林带相对位置判断
"""

from typing import Optional
import pandas as pd
import numpy as np

from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class BollingerDynamicExit(BaseExitStrategy):
    """
    布林带动态退出策略
    
    Parameters:
        emergency_pctb: 紧急止损PctB阈值（默认0.0，跌破下轨）
        profit_pctb_threshold: 利润保护PctB阈值（默认0.7）
        overbought_pctb: 超买PctB阈值（默认0.9）
        stoch_overbought: KDJ超买阈值（默认70）
        obv_lookback: OBV趋势判断期（默认10）
    """
    
    def __init__(
        self,
        emergency_pctb: float = 0.0,
        profit_pctb_threshold: float = 0.7,
        overbought_pctb: float = 0.9,
        stoch_overbought: float = 70.0,
        obv_lookback: int = 10
    ):
        super().__init__()
        self.emergency_pctb = emergency_pctb
        self.profit_pctb_threshold = profit_pctb_threshold
        self.overbought_pctb = overbought_pctb
        self.stoch_overbought = stoch_overbought
        self.obv_lookback = obv_lookback
    
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """
        生成退出信号
        
        分层检测：
        P0: 跌破下轨（BB_PctB < 0）
        P1: 从高位回落 + OBV转负
        P2: 超买区 + KDJ死叉
        """
        df = market_data.df_features
        
        if df.empty:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["数据不足"],
                strategy_name="BollingerDynamicExit"
            )
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        
        # 检查必要字段
        required_fields = ['Close', 'BB_PctB', 'Stoch_K', 'Stoch_D', 'OBV']
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["缺少必要技术指标"],
                strategy_name="BollingerDynamicExit"
            )
        
        current_price = latest['Close']
        pnl_pct = (current_price / position.entry_price - 1) * 100
        
        reasons = []
        confidence = 0.0
        
        # P0: 紧急止损 - 跌破下轨
        if latest['BB_PctB'] < self.emergency_pctb:
            reasons.append(f"[P0] 跌破下轨（PctB={latest['BB_PctB']:.2f}）")
            confidence = 1.0
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "exit_layer": "P0_Emergency",
                    "bb_pctb": float(latest['BB_PctB']),
                    "pnl_pct": float(pnl_pct)
                },
                strategy_name="BollingerDynamicExit"
            )
        
        # P1: 利润保护 - 从高位回落 + OBV转负
        if pnl_pct > 5:  # 有利润时才考虑
            pctb_falling = prev['BB_PctB'] > self.profit_pctb_threshold and latest['BB_PctB'] < self.profit_pctb_threshold
            
            # OBV趋势判断
            obv_series = df['OBV'].dropna()
            if len(obv_series) >= self.obv_lookback:
                obv_slope = (obv_series.iloc[-1] - obv_series.iloc[-self.obv_lookback]) / self.obv_lookback
                obv_turning_negative = obv_slope < 0
            else:
                obv_turning_negative = False
                obv_slope = 0
            
            if pctb_falling and obv_turning_negative:
                reasons.append(f"[P1] 从高位回落（PctB {prev['BB_PctB']:.2f}→{latest['BB_PctB']:.2f}）")
                reasons.append(f"OBV转负（斜率{obv_slope:.0e}）")
                confidence = 0.85
                return TradingSignal(
                    action=SignalAction.SELL,
                    confidence=confidence,
                    reasons=reasons,
                    metadata={
                        "exit_layer": "P1_ProfitProtection",
                        "bb_pctb": float(latest['BB_PctB']),
                        "obv_slope": float(obv_slope),
                        "pnl_pct": float(pnl_pct)
                    },
                    strategy_name="BollingerDynamicExit"
                )
        
        # P2: 超买退出 - PctB超高 + KDJ死叉
        k_cur = latest['Stoch_K']
        d_cur = latest['Stoch_D']
        k_prev = prev['Stoch_K']
        d_prev = prev['Stoch_D']
        
        stoch_death_cross = (
            pd.notna(k_cur) and pd.notna(d_cur) and
            pd.notna(k_prev) and pd.notna(d_prev) and
            k_prev > d_prev and k_cur < d_cur
        )
        stoch_overbought = k_cur > self.stoch_overbought if pd.notna(k_cur) else False
        
        if latest['BB_PctB'] > self.overbought_pctb and stoch_death_cross and stoch_overbought:
            reasons.append(f"[P2] 超买区（PctB={latest['BB_PctB']:.2f}）")
            reasons.append(f"KDJ死叉（K={k_cur:.1f} D={d_cur:.1f}）")
            confidence = 0.80
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=confidence,
                reasons=reasons,
                metadata={
                    "exit_layer": "P2_Overbought",
                    "bb_pctb": float(latest['BB_PctB']),
                    "stoch_k": float(k_cur),
                    "pnl_pct": float(pnl_pct)
                },
                strategy_name="BollingerDynamicExit"
            )
        
        # 持仓
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["未触发退出条件"],
            metadata={
                "bb_pctb": float(latest['BB_PctB']),
                "stoch_k": float(k_cur) if pd.notna(k_cur) else 0.0,
                "pnl_pct": float(pnl_pct)
            },
            strategy_name="BollingerDynamicExit"
        )
