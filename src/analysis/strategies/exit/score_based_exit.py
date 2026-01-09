"""
基于打分的Exit策略

使用Score Utils计算当前分数，与入场分数比较
"""

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
from ...scoring_utils import calculate_composite_score


class ScoreBasedExitStrategy(BaseExitStrategy):
    """
    基于打分的Exit策略
    
    使用Score Utils工具
    
    退出逻辑:
    - 计算当前综合分数
    - 与入场分数比较
    - 如果分数下降超过buffer阈值 → SELL
    
    适合与ScorerStrategy配合使用
    
    Args:
        score_buffer: 分数衰减阈值（默认15分）
        weights: 打分权重（默认Simple权重）
    """
    
    def __init__(
        self,
        score_buffer: float = 15.0,
        weights: dict = None
    ):
        super().__init__(strategy_name="ScoreBasedExit")
        self.score_buffer = score_buffer
        self.weights = weights or {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }
    
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """生成基于分数的退出信号"""
        
        # 更新peak price
        self.update_position(position, market_data.latest_price)
        
        # 调用Score Utils计算当前分数
        current_score, breakdown = calculate_composite_score(
            market_data.df_features,
            market_data.df_trades,
            market_data.df_financials,
            market_data.metadata,
            weights=self.weights,
            current_date=market_data.current_date
        )
        
        # 获取入场时的分数（从entry_signal的metadata中）
        entry_score = position.entry_signal.metadata.get('score', 65.0)
        
        # 判断是否退出
        score_decay = entry_score - current_score
        
        if score_decay > self.score_buffer:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=min(score_decay / 50, 1.0),
                reasons=[
                    f"Score decay: {current_score:.1f} < {entry_score:.1f} - {self.score_buffer}",
                    f"Breakdown: Tech={breakdown['technical']:.0f}, "
                    f"Inst={breakdown['institutional']:.0f}, "
                    f"Fund={breakdown['fundamental']:.0f}"
                ],
                metadata={
                    "trigger": "ScoreDecay",
                    "current_score": current_score,
                    "entry_score": entry_score,
                    "decay": score_decay,
                    "breakdown": breakdown
                },
                strategy_name=self.strategy_name
            )
        
        # HOLD
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[
                f"Score {current_score:.1f} healthy (entry={entry_score:.1f})",
                f"Decay {score_decay:.1f} < buffer {self.score_buffer}"
            ],
            metadata={
                "current_score": current_score,
                "entry_score": entry_score,
                "breakdown": breakdown
            },
            strategy_name=self.strategy_name
        )
