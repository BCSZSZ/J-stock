"""
ATR退出策略

纯技术指标策略，不使用Score Utils
"""

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import detect_trend_breakdown
from typing import Optional


class ATRExitStrategy(BaseExitStrategy):
    """
    ATR退出策略 - 纯技术指标
    
    不使用Score Utils（仅使用辅助检测函数detect_trend_breakdown）
    
    4层退出逻辑:
    - P0: Hard Stop Loss (Entry - 2*ATR)
    - P1: Trailing Stop (Peak - 3*ATR)
    - P2: Momentum Exhaustion (RSI>70 AND Price<EMA20)
    - P3: Trend Breakdown (多重技术破坏)
    
    Args:
        atr_stop_multiplier: Hard Stop的ATR倍数（默认2.0）
        atr_trail_multiplier: Trailing Stop的ATR倍数（默认3.0）
        rsi_overbought: RSI超买阈值（默认70）
    """
    
    def __init__(
        self,
        atr_stop_multiplier: float = 2.0,
        atr_trail_multiplier: float = 3.0,
        rsi_overbought: float = 70.0
    ):
        super().__init__(strategy_name="ATRExitStrategy")
        self.stop_mult = atr_stop_multiplier
        self.trail_mult = atr_trail_multiplier
        self.rsi_overbought = rsi_overbought
    
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """生成退出信号"""
        
        # 更新peak price
        self.update_position(position, market_data.latest_price)
        
        df = market_data.df_features
        if df.empty:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No data"],
                strategy_name=self.strategy_name
            )
        
        latest = df.iloc[-1]
        current_price = latest['Close']
        current_atr = latest['ATR']
        current_rsi = latest['RSI']
        ema_20 = latest['EMA_20']
        
        # P0: Hard Stop Loss
        stop_loss_level = position.entry_price - (current_atr * self.stop_mult)
        if current_price < stop_loss_level:
            loss_pct = ((current_price / position.entry_price) - 1) * 100
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=[
                    f"Hard stop: ¥{current_price:,.0f} < ¥{stop_loss_level:,.0f}",
                    f"Loss: {loss_pct:.1f}%"
                ],
                metadata={
                    "trigger": "P0_HardStop",
                    "stop_level": stop_loss_level,
                    "loss_pct": loss_pct
                },
                strategy_name=self.strategy_name
            )
        
        # P1: Trailing Stop
        trailing_stop_level = position.peak_price_since_entry - (current_atr * self.trail_mult)
        if current_price < trailing_stop_level:
            profit_pct = position.peak_pnl_pct()
            current_pnl = position.current_pnl_pct(current_price)
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[
                    f"Trailing stop: ¥{current_price:,.0f} < ¥{trailing_stop_level:,.0f}",
                    f"Peak profit was +{profit_pct:.1f}%, now +{current_pnl:.1f}%"
                ],
                metadata={
                    "trigger": "P1_TrailingStop",
                    "peak_price": position.peak_price_since_entry,
                    "peak_profit_pct": profit_pct
                },
                strategy_name=self.strategy_name
            )
        
        # P2: Momentum Exhaustion
        if current_rsi > self.rsi_overbought and current_price < ema_20:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.8,
                reasons=[
                    f"Momentum exhaustion: RSI={current_rsi:.1f} (overbought)",
                    f"Price broke below EMA20"
                ],
                metadata={
                    "trigger": "P2_MomentumExhaustion",
                    "rsi": current_rsi,
                    "ema_20": ema_20
                },
                strategy_name=self.strategy_name
            )
        
        # P3: Trend Breakdown（使用Score Utils中的辅助函数）
        trend_break = detect_trend_breakdown(df)
        if trend_break:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.85,
                reasons=[f"Trend breakdown: {trend_break}"],
                metadata={
                    "trigger": "P3_TrendBreakdown",
                    "breakdown_signals": trend_break
                },
                strategy_name=self.strategy_name
            )
        
        # All clear - HOLD
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["All stop levels clear"],
            metadata={
                "hard_stop": stop_loss_level,
                "trailing_stop": trailing_stop_level,
                "current_pnl_pct": position.current_pnl_pct(current_price)
            },
            strategy_name=self.strategy_name
        )
