"""
基于综合打分的Entry策略

使用Score Utils计算综合分数，达到阈值时买入
"""

from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData
from ...scoring_utils import calculate_composite_score, check_earnings_risk


class SimpleScorerStrategy(BaseEntryStrategy):
    """
    基于综合打分的Entry策略（Simple权重）
    
    权重: Technical 40%, Institutional 30%, Fundamental 20%, Volatility 10%
    使用Score Utils工具
    
    Args:
        buy_threshold: 买入阈值（默认65分）
    """
    
    def __init__(self, buy_threshold: float = 65.0):
        super().__init__(strategy_name="SimpleScorer")
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号"""
        
        # 调用Score Utils计算综合分数
        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )
        
        # 检查财报风险
        has_earnings_risk, days_until = check_earnings_risk(
            market_data.metadata,
            market_data.current_date
        )
        
        # 财报临近时降低分数
        if has_earnings_risk:
            original_score = score
            score *= 0.8  # 20% penalty
        
        # 判断是否买入
        if score >= self.threshold:
            reasons = [f"Composite score {score:.1f} >= {self.threshold}"]
            reasons.append(f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                          f"Fund={breakdown['fundamental']:.0f}, Vol={breakdown['volatility']:.0f}")
            
            if has_earnings_risk:
                reasons.append(f"Earnings in {days_until} days (penalty applied)")
            
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=min(score / 100, 1.0),
                reasons=reasons,
                metadata={
                    "score": score,
                    "breakdown": breakdown,
                    "earnings_risk": has_earnings_risk
                },
                strategy_name=self.strategy_name
            )
        
        # 观望
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {score:.1f} below threshold {self.threshold}"],
            metadata={"score": score, "breakdown": breakdown},
            strategy_name=self.strategy_name
        )


class EnhancedScorerStrategy(BaseEntryStrategy):
    """
    基于综合打分的Entry策略（Enhanced权重）
    
    权重: Technical 35%, Institutional 35%, Fundamental 20%, Volatility 10%
    更重视机构流向
    使用Score Utils工具
    
    Args:
        buy_threshold: 买入阈值（默认65分）
    """
    
    def __init__(self, buy_threshold: float = 65.0):
        super().__init__(strategy_name="EnhancedScorer")
        self.threshold = buy_threshold
        self.weights = {
            "technical": 0.35,
            "institutional": 0.35,  # 更重视机构
            "fundamental": 0.20,
            "volatility": 0.10
        }
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成入场信号"""
        
        # 调用Score Utils计算综合分数
        score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )
        
        # 检查财报风险（增强版：渐进式惩罚）
        has_earnings_risk, days_until = check_earnings_risk(
            market_data.metadata,
            market_data.current_date
        )
        
        if has_earnings_risk:
            original_score = score
            if days_until <= 1:
                score *= 0.5  # 50% penalty
            elif days_until <= 3:
                score *= 0.7  # 30% penalty
            elif days_until <= 7:
                score *= 0.85  # 15% penalty
        
        # 判断是否买入
        if score >= self.threshold:
            reasons = [f"Enhanced score {score:.1f} >= {self.threshold}"]
            reasons.append(f"Tech={breakdown['technical']:.0f}, Inst={breakdown['institutional']:.0f}, "
                          f"Fund={breakdown['fundamental']:.0f}")
            
            if has_earnings_risk:
                reasons.append(f"Earnings in {days_until} days")
            
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=min(score / 100, 1.0),
                reasons=reasons,
                metadata={
                    "score": score,
                    "breakdown": breakdown,
                    "earnings_risk": has_earnings_risk,
                    "days_until_earnings": days_until
                },
                strategy_name=self.strategy_name
            )
        
        # 观望
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[f"Score {score:.1f} below threshold {self.threshold}"],
            metadata={"score": score, "breakdown": breakdown},
            strategy_name=self.strategy_name
        )
