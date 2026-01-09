"""
ATR-Based Exit Strategy (User's Strategy)

Simple, game-like exit logic focused on price action and ATR stops.
Philosophy: Buy needs 4 green lights (AND), Sell needs 1 red light (OR).

Priority Levels:
- P0 (HIGHEST): Hard Stop Loss (Entry - 2*ATR) - "Save your life"
- P1: Trailing Stop (Peak - 3*ATR) - "Lock in profits"
- P2: Technical Exit (RSI>70 AND Price<EMA20) - "Momentum exhaustion"
- P3: Score Decay (Score<50) - "Thesis invalidated"
"""
import pandas as pd
import numpy as np
from typing import Dict
from .base_exiter import BaseExiter, Position, ExitSignal


class ATRExiter(BaseExiter):
    """
    ATR-based exit strategy with 4 priority levels.
    Simple, decisive, game-like logic.
    """
    
    def __init__(self,
                 atr_stop_multiplier: float = 2.0,
                 atr_trail_multiplier: float = 3.0,
                 rsi_overbought: float = 70.0,
                 score_threshold: float = 50.0):
        """
        Args:
            atr_stop_multiplier: ATR multiplier for hard stop (default 2.0)
            atr_trail_multiplier: ATR multiplier for trailing stop (default 3.0)
            rsi_overbought: RSI level considered overbought (default 70)
            score_threshold: Score below which thesis is invalidated (default 50)
        """
        super().__init__(strategy_name="ATR_Exit_v1")
        self.stop_mult = atr_stop_multiplier
        self.trail_mult = atr_trail_multiplier
        self.rsi_overbought = rsi_overbought
        self.score_threshold = score_threshold
    
    def evaluate_exit(self,
                     position: Position,
                     df_features: pd.DataFrame,
                     df_trades: pd.DataFrame,
                     df_financials: pd.DataFrame,
                     metadata: dict,
                     current_score: float) -> ExitSignal:
        """
        Evaluate exit with 4-level priority system.
        First trigger wins (OR logic for exits).
        """
        # Handle ScoreResult object vs float
        from ..scorers.base_scorer import ScoreResult
        if isinstance(current_score, ScoreResult):
            score_value = current_score.total_score
        else:
            score_value = current_score
        
        # Get latest market data
        latest = self._get_latest_data(df_features)
        current_price = latest['Close']
        current_atr = latest['ATR']
        current_rsi = latest['RSI']
        ema_20 = latest['EMA_20']
        # Date is the index
        current_date = df_features.index[-1]
        if not isinstance(current_date, pd.Timestamp):
            current_date = pd.to_datetime(current_date)
        
        # Update peak price if needed
        peak_price = position.peak_price_since_entry
        if peak_price is None or current_price > peak_price:
            peak_price = current_price
        
        # =================================================================
        # P0 (HIGHEST PRIORITY): Hard Stop Loss
        # Logic: Price < Entry - 2*ATR
        # Purpose: Protect capital from black swan events
        # =================================================================
        stop_loss_level = position.entry_price - (current_atr * self.stop_mult)
        
        if current_price < stop_loss_level:
            return self._create_signal(
                position=position,
                current_price=current_price,
                current_score=score_value,
                current_date=current_date,
                action="SELL_100%",
                urgency="EMERGENCY",
                reason=f"Hard stop hit: ¥{current_price:,.0f} < ¥{stop_loss_level:,.0f} (Entry-{self.stop_mult}*ATR)",
                triggered_by="P0_HardStop"
            )
        
        # =================================================================
        # P1: Trailing Stop (Profit Protection)
        # Logic: Price < Peak - 3*ATR
        # Purpose: Lock in profits after significant gain
        # =================================================================
        trailing_stop_level = peak_price - (current_atr * self.trail_mult)
        
        if current_price < trailing_stop_level:
            profit_from_peak = ((peak_price - position.entry_price) / position.entry_price) * 100
            return self._create_signal(
                position=position,
                current_price=current_price,
                current_score=score_value,
                current_date=current_date,
                action="SELL_100%",
                urgency="HIGH",
                reason=f"Trailing stop hit: ¥{current_price:,.0f} < ¥{trailing_stop_level:,.0f} (Peak-{self.trail_mult}*ATR, was +{profit_from_peak:.1f}%)",
                triggered_by="P1_TrailingStop"
            )
        
        # =================================================================
        # P2: Technical Exit (Momentum Exhaustion)
        # Logic: RSI > 70 AND Price < EMA20
        # Purpose: Exit at peak momentum before reversal
        # =================================================================
        if current_rsi > self.rsi_overbought and current_price < ema_20:
            return self._create_signal(
                position=position,
                current_price=current_price,
                current_score=score_value,
                current_date=current_date,
                action="SELL_100%",
                urgency="MEDIUM",
                reason=f"Momentum exhaustion: RSI={current_rsi:.1f} (overbought) but broke EMA20 ¥{ema_20:,.0f}",
                triggered_by="P2_TechnicalExit"
            )
        
        # =================================================================
        # P3: Score Decay (Thesis Invalidated)
        # Logic: Score < 50
        # Purpose: Exit when original buy thesis breaks down
        # =================================================================
        if score_value < self.score_threshold:
            return self._create_signal(
                position=position,
                current_price=current_price,
                current_score=score_value,
                current_date=current_date,
                action="SELL_100%",
                urgency="HIGH",
                reason=f"Score decay: {score_value:.0f} < {self.score_threshold:.0f} (Entry was {position.entry_score:.0f}, thesis invalidated)",
                triggered_by="P3_ScoreDecay"
            )
        
        # =================================================================
        # All Clear - HOLD
        # =================================================================
        return self._create_signal(
            position=position,
            current_price=current_price,
            current_score=score_value,
            current_date=current_date,
            action="HOLD",
            urgency="LOW",
            reason=f"Trend healthy: Price ¥{current_price:,.0f} (Stop: ¥{stop_loss_level:,.0f}, Trail: ¥{trailing_stop_level:,.0f}), Score={score_value:.0f}",
            triggered_by="None"
        )
    
    def get_stop_levels(self, position: Position, current_atr: float, peak_price: float) -> Dict[str, float]:
        """
        Utility method to get current stop levels without triggering exit.
        Useful for displaying on dashboard.
        """
        return {
            "hard_stop": position.entry_price - (current_atr * self.stop_mult),
            "trailing_stop": peak_price - (current_atr * self.trail_mult),
            "distance_to_hard_stop_pct": ((position.entry_price - (current_atr * self.stop_mult)) / position.entry_price - 1) * 100,
            "distance_to_trail_stop_pct": ((peak_price - (current_atr * self.trail_mult)) / peak_price - 1) * 100
        }
