"""
6层退出策略

混合使用Score Utils和技术指标
"""

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import (
    calculate_composite_score,
    detect_institutional_exodus,
    check_earnings_risk,
    detect_trend_breakdown,
    detect_market_deterioration
)
from typing import Optional
import pandas as pd


class LayeredExitStrategy(BaseExitStrategy):
    """
    6层退出策略 - 混合使用Score Utils和技术指标
    
    参数use_score_utils控制是否使用打分工具
    
    退出层级:
    1. Emergency - 机构大举撤离
    2. Trend Breakdown - 技术趋势破坏
    3. Market Deterioration - 市场恶化（对比入场状态）
    4. Multi-Dimensional Weakness - 多维度弱化（可选使用Score Utils）
    5. Trailing Stop - 追踪止损
    6. Time Review - 季度审查（可选使用Score Utils）
    
    Args:
        use_score_utils: 是否使用Score Utils（Layer 4和6）
        trailing_atr_mult: Trailing Stop的ATR倍数
        review_days: 审查周期（天）
    """
    
    def __init__(
        self,
        use_score_utils: bool = True,
        trailing_atr_mult: float = 2.0,
        review_days: int = 90
    ):
        super().__init__(strategy_name="LayeredExit")
        self.use_score_utils = use_score_utils
        self.trail_mult = trailing_atr_mult
        self.review_days = review_days
    
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """6层退出逻辑"""
        
        self.update_position(position, market_data.latest_price)
        
        # Layer 1: Emergency - 机构大举撤离
        if detect_institutional_exodus(market_data.df_trades, market_data.current_date):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=["EMERGENCY: Foreign institutional exodus detected"],
                metadata={"trigger": "Layer1_Emergency"},
                strategy_name=self.strategy_name
            )
        
        # Layer 2: Trend Breakdown
        trend_break = detect_trend_breakdown(market_data.df_features)
        if trend_break:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[f"Trend breakdown: {trend_break}"],
                metadata={"trigger": "Layer2_TrendBreakdown"},
                strategy_name=self.strategy_name
            )
        
        # Layer 3: Market Deterioration（对比入场状态）
        deterioration = self._check_deterioration(position, market_data)
        if deterioration:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.88,
                reasons=[deterioration],
                metadata={"trigger": "Layer3_MarketDeterioration"},
                strategy_name=self.strategy_name
            )
        
        # Layer 4: Multi-Dimensional Weakness (可选使用Score Utils)
        weakness = self._check_weakness(market_data)
        if weakness:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.85,
                reasons=[weakness],
                metadata={"trigger": "Layer4_MultiWeakness"},
                strategy_name=self.strategy_name
            )
        
        # Layer 5: Trailing Stop
        if not market_data.df_features.empty:
            latest = market_data.df_features.iloc[-1]
            trail_level = position.peak_price_since_entry - (latest['ATR'] * self.trail_mult)
            
            if latest['Close'] < trail_level:
                profit_pct = position.peak_pnl_pct()
                return TradingSignal(
                    action=SignalAction.SELL,
                    confidence=0.75,
                    reasons=[f"Trailing stop (peak profit +{profit_pct:.1f}%)"],
                    metadata={"trigger": "Layer5_TrailingStop"},
                    strategy_name=self.strategy_name
                )
        
        # Layer 6: Time Review
        days_held = (market_data.current_date - position.entry_date).days
        if days_held > 0 and days_held % self.review_days == 0:
            review = self._quarterly_review(position, market_data)
            if review:
                return TradingSignal(
                    action=SignalAction.SELL,
                    confidence=0.7,
                    reasons=[review],
                    metadata={
                        "trigger": "Layer6_TimeReview",
                        "days_held": days_held
                    },
                    strategy_name=self.strategy_name
                )
        
        # All Clear
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["All 6 layers clear"],
            metadata={"days_held": days_held},
            strategy_name=self.strategy_name
        )
    
    def _check_deterioration(
        self,
        position: Position,
        market_data: MarketData
    ) -> Optional[str]:
        """检测市场恶化（对比入场状态）"""
        
        df = market_data.df_features
        if len(df) < 10:
            return None
        
        # 获取入场时数据
        entry_idx = df.index.get_indexer([position.entry_date], method='ffill')[0]
        if entry_idx < 0 or entry_idx >= len(df):
            return None
        
        entry_data = df.iloc[entry_idx]
        current_data = df.iloc[-1]
        
        # 使用Score Utils中的辅助函数
        return detect_market_deterioration(
            entry_data,
            current_data,
            market_data.df_trades,
            position.entry_date,
            market_data.current_date
        )
    
    def _check_weakness(self, market_data: MarketData) -> Optional[str]:
        """检测多维度弱化"""
        
        if self.use_score_utils:
            # 使用Score Utils计算各组件分数
            _, breakdown = calculate_composite_score(
                market_data.df_features,
                market_data.df_trades,
                market_data.df_financials,
                market_data.metadata,
                current_date=market_data.current_date
            )
            
            weak_components = []
            if breakdown['technical'] < 35:
                weak_components.append(f"Technical({breakdown['technical']:.0f})")
            if breakdown['institutional'] < 30:
                weak_components.append(f"Institutional({breakdown['institutional']:.0f})")
            if breakdown['fundamental'] < 35:
                weak_components.append(f"Fundamental({breakdown['fundamental']:.0f})")
            
            if len(weak_components) >= 2:
                return f"Multi-weakness: {', '.join(weak_components)} scores low"
        
        else:
            # 不使用Score Utils，直接检测技术指标
            if market_data.df_features.empty:
                return None
            
            latest = market_data.df_features.iloc[-1]
            issues = []
            
            if latest['RSI'] < 35:
                issues.append("Weak RSI")
            if latest['Close'] < latest['EMA_50']:
                issues.append("Below EMA50")
            if latest['MACD_Hist'] < 0:
                issues.append("Negative MACD")
            
            if len(issues) >= 2:
                return "Technical weakness: " + " + ".join(issues)
        
        return None
    
    def _quarterly_review(
        self,
        position: Position,
        market_data: MarketData
    ) -> Optional[str]:
        """季度审查"""
        
        current_pnl = position.current_pnl_pct(market_data.latest_price)
        
        if self.use_score_utils:
            # 使用Score Utils
            score, _ = calculate_composite_score(
                market_data.df_features,
                market_data.df_trades,
                market_data.df_financials,
                market_data.metadata,
                current_date=market_data.current_date
            )
            
            # 亏损且分数低 → 退出
            if current_pnl < 0 and score < 55:
                return f"Quarterly review: Loss {current_pnl:.1f}% + low score {score:.0f}"
        
        else:
            # 不使用分数，仅基于PnL
            if current_pnl < -10:
                return f"Quarterly review: Loss {current_pnl:.1f}% (cut loss)"
        
        return None
