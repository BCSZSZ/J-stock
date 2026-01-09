"""
Layered Exit Strategy (Research-Based Strategy)

Comprehensive 6-layer exit system optimized for Japanese stock market.
Based on EXIT_STRATEGY_RESEARCH.md findings.

Layer 1: EMERGENCY - Immediate exits (earnings miss, institutional exodus)
Layer 2: SCORE-BASED - Primary decision logic with time-dependent tightening
Layer 3: COMPONENT BREAKDOWN - Individual pillar deterioration
Layer 4: JAPANESE MARKET TRIGGERS - Cultural specifics (guidance, retail trap)
Layer 5: TRAILING STOP - ATR-adjusted profit protection
Layer 6: TIME-BASED REVIEW - Quarterly re-evaluation
"""
import pandas as pd
import numpy as np
from datetime import timedelta
from typing import Dict, Optional
from .base_exiter import BaseExiter, Position, ExitSignal


class LayeredExiter(BaseExiter):
    """
    Sophisticated 6-layer exit strategy for Japanese equities.
    Mirrors the 4-component scoring system with additional risk layers.
    """
    
    def __init__(self,
                 emergency_foreign_exodus_threshold: float = -50_000_000,  # ¥50M net selling in 2 weeks
                 score_exit_buffer_buy: int = 10,      # BUY (65-79) exits at 55
                 score_exit_buffer_strong: int = 20,   # STRONG_BUY (80+) exits at 60
                 institutional_floor: float = 25.0,
                 fundamental_floor: float = 35.0,
                 technical_floor: float = 30.0,
                 volatility_floor: float = 25.0,
                 trailing_atr_multiplier: float = 2.0,
                 quarterly_review_days: int = 90):
        """
        Args:
            emergency_foreign_exodus_threshold: Net foreign selling to trigger emergency exit
            score_exit_buffer_buy: Points below entry for BUY positions
            score_exit_buffer_strong: Points below entry for STRONG_BUY positions
            institutional_floor: Min acceptable institutional score
            fundamental_floor: Min acceptable fundamental score
            technical_floor: Min acceptable technical score
            volatility_floor: Min acceptable volatility score
            trailing_atr_multiplier: ATR multiplier for trailing stop
            quarterly_review_days: Days between forced reviews
        """
        super().__init__(strategy_name="Layered_Exit_v1")
        self.foreign_exodus_threshold = emergency_foreign_exodus_threshold
        self.score_buffer_buy = score_exit_buffer_buy
        self.score_buffer_strong = score_exit_buffer_strong
        self.inst_floor = institutional_floor
        self.fund_floor = fundamental_floor
        self.tech_floor = technical_floor
        self.vol_floor = volatility_floor
        self.trail_mult = trailing_atr_multiplier
        self.review_days = quarterly_review_days
    
    def evaluate_exit(self,
                     position: Position,
                     df_features: pd.DataFrame,
                     df_trades: pd.DataFrame,
                     df_financials: pd.DataFrame,
                     metadata: dict,
                     current_score: float,
                     score_breakdown: Optional[Dict[str, float]] = None) -> ExitSignal:
        """
        Evaluate exit through 6 layers (first trigger wins).
        """
        # Handle ScoreResult object vs float
        from ..scorers.base_scorer import ScoreResult
        if isinstance(current_score, ScoreResult):
            score_value = current_score.total_score
            score_breakdown = current_score.breakdown
        else:
            score_value = current_score
        
        # Get latest market data
        latest = self._get_latest_data(df_features)
        current_price = latest['Close']
        # Date is the index
        current_date = df_features.index[-1]
        if not isinstance(current_date, pd.Timestamp):
            current_date = pd.to_datetime(current_date)
        
        # Update peak price
        peak_price = position.peak_price_since_entry
        if peak_price is None or current_price > peak_price:
            peak_price = current_price
        
        holding_days = self._get_holding_days(position.entry_date, current_date)
        
        # =================================================================
        # LAYER 1: EMERGENCY EXITS (Highest Priority)
        # =================================================================
        emergency = self._check_emergency(df_financials, df_trades, metadata, current_date, latest)
        if emergency:
            return self._create_signal(
                position, current_price, score_value, current_date,
                "SELL_100%", "EMERGENCY", emergency, "Layer1_Emergency"
            )
        
        # =================================================================
        # LAYER 2: SCORE-BASED EXIT (Primary Logic)
        # =================================================================
        score_exit = self._check_score_exit(position, score_value, holding_days)
        if score_exit:
            return self._create_signal(
                position, current_price, score_value, current_date,
                "SELL_100%", "HIGH", score_exit, "Layer2_ScoreBased"
            )
        
        # =================================================================
        # LAYER 3: COMPONENT BREAKDOWN (Diagnostic)
        # =================================================================
        if score_breakdown:
            component_exit = self._check_component_breakdown(score_breakdown)
            if component_exit:
                return self._create_signal(
                    position, current_price, score_value, current_date,
                    "SELL_100%", "HIGH", component_exit, "Layer3_ComponentBreakdown"
                )
        
        # =================================================================
        # LAYER 4: JAPANESE MARKET TRIGGERS
        # =================================================================
        japan_trigger = self._check_japanese_triggers(df_trades, df_financials, metadata, current_date, score_value)
        if japan_trigger:
            action = japan_trigger.get('action', 'SELL_100%')
            urgency = japan_trigger.get('urgency', 'MEDIUM')
            return self._create_signal(
                position, current_price, score_value, current_date,
                action, urgency, japan_trigger['reason'], "Layer4_JapanTrigger"
            )
        
        # =================================================================
        # LAYER 5: TRAILING STOP (Profit Protection)
        # =================================================================
        trailing_exit = self._check_trailing_stop(position, current_price, peak_price, latest['ATR'])
        if trailing_exit:
            return self._create_signal(
                position, current_price, score_value, current_date,
                "SELL_100%", "MEDIUM", trailing_exit, "Layer5_TrailingStop"
            )
        
        # =================================================================
        # LAYER 6: TIME-BASED REVIEW (Quarterly)
        # =================================================================
        if holding_days > 0 and holding_days % self.review_days == 0:
            review_action = self._quarterly_review(score_value, self._calculate_pnl(position.entry_price, current_price))
            if review_action != "HOLD":
                return self._create_signal(
                    position, current_price, score_value, current_date,
                    review_action, "MEDIUM", f"Quarterly review (Day {holding_days}): Position reassessment", "Layer6_TimeReview"
                )
        
        # =================================================================
        # ALL CLEAR - HOLD
        # =================================================================
        return self._create_signal(
            position, current_price, score_value, current_date,
            "HOLD", "LOW", f"All 6 layers clear. Score={score_value:.0f}, Days={holding_days}", "None"
        )
    
    # =====================================================================
    # LAYER IMPLEMENTATIONS
    # =====================================================================
    
    def _check_emergency(self, df_financials, df_trades, metadata, current_date, latest) -> Optional[str]:
        """Layer 1: Emergency exits."""
        
        # 1. Earnings miss + guidance cut
        if not df_financials.empty and len(df_financials) >= 2:
            df_fins = df_financials.sort_values('DiscDate')
            latest_fin = df_fins.iloc[-1]
            
            forecast_sales = pd.to_numeric(latest_fin.get('FSales', 0), errors='coerce')
            actual_sales = pd.to_numeric(latest_fin.get('Sales', 0), errors='coerce')
            
            if pd.notna(forecast_sales) and pd.notna(actual_sales) and forecast_sales > 0:
                if actual_sales < forecast_sales * 0.95:  # Missed by >5%
                    # Check if guidance was also cut
                    next_forecast = pd.to_numeric(latest_fin.get('NxSales', 0), errors='coerce')
                    if pd.notna(next_forecast) and next_forecast < actual_sales * 0.95:
                        return "EMERGENCY: Earnings miss + guidance cut detected"
        
        # 2. Foreign investor exodus (2-week window)
        if not df_trades.empty:
            df_trades = df_trades.copy()
            df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
            two_weeks_ago = current_date - timedelta(days=14)
            recent = df_trades[(df_trades['EnDate'] > two_weeks_ago) & (df_trades['EnDate'] <= current_date)]
            
            if not recent.empty and 'FrgnBal' in recent.columns:
                net_foreign = recent['FrgnBal'].sum()
                if net_foreign < self.foreign_exodus_threshold:
                    return f"EMERGENCY: Foreign exodus ¥{net_foreign/1_000_000:.0f}M in 2 weeks"
        
        # 3. Major gap down (>10%)
        if 'Open' in latest and latest['Open'] < latest['Close'] * 0.9:
            gap_pct = ((latest['Open'] - latest['Close']) / latest['Close']) * 100
            return f"EMERGENCY: Gap down {gap_pct:.1f}%"
        
        # 4. Earnings in 24 hours (don't hold overnight)
        if metadata and 'earnings_calendar' in metadata:
            for event in metadata['earnings_calendar']:
                try:
                    evt_date = pd.to_datetime(event['Date'])
                    if 0 <= (evt_date - current_date).days <= 1:
                        return "EMERGENCY: Earnings in 24 hours, exit before close"
                except:
                    continue
        
        return None
    
    def _check_score_exit(self, position, current_score, holding_days) -> Optional[str]:
        """Layer 2: Score-based exit with time-dependent tightening."""
        
        # Determine exit threshold based on entry score
        if position.entry_score >= 80:
            base_exit = 60  # STRONG_BUY gets 20-point buffer
        elif position.entry_score >= 65:
            base_exit = 55  # BUY gets 10-point buffer
        else:
            return None  # Should never happen (didn't enter)
        
        # Tighten over time (winners should keep winning)
        if holding_days > 180:  # 6 months
            base_exit += 10
        elif holding_days > 90:  # 3 months
            base_exit += 5
        
        if current_score < base_exit:
            return f"Score deterioration: {current_score:.0f} < {base_exit:.0f} (Entry={position.entry_score:.0f}, Days={holding_days})"
        
        return None
    
    def _check_component_breakdown(self, breakdown: Dict[str, float]) -> Optional[str]:
        """Layer 3: Individual component catastrophic failure."""
        
        if breakdown.get('Institutional', 100) < self.inst_floor:
            return f"Institutional breakdown: {breakdown['Institutional']:.0f} < {self.inst_floor:.0f} (Smart money exiting)"
        
        if breakdown.get('Fundamental', 100) < self.fund_floor:
            return f"Fundamental breakdown: {breakdown['Fundamental']:.0f} < {self.fund_floor:.0f} (Business deteriorating)"
        
        if breakdown.get('Technical', 100) < self.tech_floor:
            return f"Technical breakdown: {breakdown['Technical']:.0f} < {self.tech_floor:.0f} (Trend broken)"
        
        if breakdown.get('Volatility', 100) < self.vol_floor:
            return f"Volatility spike: {breakdown['Volatility']:.0f} < {self.vol_floor:.0f} (Regime change)"
        
        return None
    
    def _check_japanese_triggers(self, df_trades, df_financials, metadata, current_date, current_score) -> Optional[Dict]:
        """Layer 4: Japanese market specific triggers."""
        
        # 1. Guidance revision check
        if not df_financials.empty:
            latest_fin = df_financials.sort_values('DiscDate').iloc[-1]
            current_sales = pd.to_numeric(latest_fin.get('Sales', 0), errors='coerce')
            next_forecast = pd.to_numeric(latest_fin.get('NxSales', 0), errors='coerce')
            
            if pd.notna(current_sales) and pd.notna(next_forecast) and current_sales > 0:
                if next_forecast < current_sales * 0.95:  # Guiding >5% down sequentially
                    return {'action': 'SELL_100%', 'urgency': 'HIGH', 'reason': 'Guidance revision: Company guiding down >5%'}
        
        # 2. Retail trap (retail buying while institutions sell)
        if not df_trades.empty:
            df_trades = df_trades.copy()
            df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
            recent = df_trades.tail(4)  # Last 4 weeks
            
            if 'IndBal' in recent.columns and 'FrgnBal' in recent.columns:
                retail_flow = recent['IndBal'].sum()
                foreign_flow = recent['FrgnBal'].sum()
                
                if retail_flow > 0 and foreign_flow < 0 and retail_flow > abs(foreign_flow) * 0.5:
                    return {'action': 'SELL_50%', 'urgency': 'MEDIUM', 'reason': 'Retail trap: Distribution into dumb money'}
        
        # 3. Earnings proximity (progressive)
        if metadata and 'earnings_calendar' in metadata:
            for event in metadata['earnings_calendar']:
                try:
                    evt_date = pd.to_datetime(event['Date'])
                    days_until = (evt_date - current_date).days
                    
                    if days_until <= 3 and current_score < 75:
                        return {'action': 'SELL_50%', 'urgency': 'MEDIUM', 'reason': f'Earnings in {days_until} days, score<75'}
                    elif days_until <= 7 and current_score < 70:
                        return {'action': 'SELL_25%', 'urgency': 'LOW', 'reason': f'Earnings in {days_until} days, reducing exposure'}
                except:
                    continue
        
        return None
    
    def _check_trailing_stop(self, position, current_price, peak_price, current_atr) -> Optional[str]:
        """Layer 5: ATR-adjusted trailing stop."""
        
        trailing_level = peak_price - (self.trail_mult * current_atr)
        
        if current_price < trailing_level:
            peak_gain = ((peak_price - position.entry_price) / position.entry_price) * 100
            return f"Trailing stop: ¥{current_price:,.0f} < ¥{trailing_level:,.0f} (Peak was +{peak_gain:.1f}%, now protecting gains)"
        
        return None
    
    def _quarterly_review(self, current_score, pnl_pct) -> str:
        """Layer 6: Quarterly review decision."""
        
        if current_score >= 70 and pnl_pct > 5:
            return "HOLD"  # Strong winner
        elif current_score >= 60 and pnl_pct > 0:
            return "HOLD"  # Modest winner
        elif current_score >= 55:
            return "SELL_50%"  # Mediocre, trim
        else:
            return "SELL_100%"  # Deteriorating
