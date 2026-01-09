"""
Entry策略基类

定义入场策略的统一接口
"""

from abc import ABC, abstractmethod
from ..signals import TradingSignal, MarketData


class BaseEntryStrategy(ABC):
    """
    Entry策略基类
    
    职责：
    - 分析MarketData
    - 生成买入或持有信号
    
    实现自由：
    - 可以调用Score Utils
    - 可以使用纯技术指标
    - 可以混合使用
    - 内部实现完全自主
    
    使用示例:
        class MyEntryStrategy(BaseEntryStrategy):
            def generate_entry_signal(self, market_data):
                # 自定义逻辑
                if some_condition:
                    return TradingSignal(
                        action=SignalAction.BUY,
                        confidence=0.8,
                        reasons=["Condition met"],
                        metadata={"custom_data": value},
                        strategy_name=self.strategy_name
                    )
                return TradingSignal(action=SignalAction.HOLD, ...)
    """
    
    def __init__(self, strategy_name: str = "BaseEntry"):
        """
        初始化Entry策略
        
        Args:
            strategy_name: 策略名称（用于日志和识别）
        """
        self.strategy_name = strategy_name
    
    @abstractmethod
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号
        
        Args:
            market_data: 完整市场数据
                - df_features: 技术指标
                - df_trades: 机构交易
                - df_financials: 财务数据
                - metadata: 元数据（财报日历等）
            
        Returns:
            TradingSignal: 
                - action=BUY: 买入信号
                - action=HOLD: 观望
                - metadata中可以包含任何信息（如score、指标值等）
                  这些信息会保存到Position.entry_signal中供Exit策略使用
        
        注意：
        - 子类必须实现此方法
        - 返回的metadata会传递到Position，Exit策略可以访问
        - 例如：保存入场分数，Exit策略可以比较分数变化
        """
        pass
    
    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.strategy_name})"
