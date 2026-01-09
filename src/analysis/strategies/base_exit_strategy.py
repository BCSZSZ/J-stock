"""
Exit策略基类

定义退出策略的统一接口
"""

from abc import ABC, abstractmethod
from ..signals import TradingSignal, MarketData, Position


class BaseExitStrategy(ABC):
    """
    Exit策略基类
    
    职责：
    - 分析持仓信息和当前市场数据
    - 生成卖出或持有信号
    
    实现自由：
    - 可以调用Score Utils
    - 可以使用纯技术指标
    - 可以混合使用
    - 可以访问Entry信号的metadata（如入场分数）
    - 内部实现完全自主
    
    使用示例:
        class MyExitStrategy(BaseExitStrategy):
            def generate_exit_signal(self, position, market_data):
                # 可以访问入场信息
                entry_score = position.entry_signal.metadata.get('score', 0)
                
                # 自定义退出逻辑
                if should_exit:
                    return TradingSignal(
                        action=SignalAction.SELL,
                        confidence=0.9,
                        reasons=["Exit condition met"],
                        metadata={"trigger": "my_trigger"},
                        strategy_name=self.strategy_name
                    )
                return TradingSignal(action=SignalAction.HOLD, ...)
    """
    
    def __init__(self, strategy_name: str = "BaseExit"):
        """
        初始化Exit策略
        
        Args:
            strategy_name: 策略名称（用于日志和识别）
        """
        self.strategy_name = strategy_name
    
    @abstractmethod
    def generate_exit_signal(
        self, 
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """
        生成退出信号
        
        Args:
            position: 当前持仓信息
                - entry_price: 入场价格
                - entry_date: 入场日期
                - entry_signal: 入场时的TradingSignal（含metadata）
                - peak_price_since_entry: 入场后最高价
            market_data: 当前市场数据
                - df_features: 技术指标
                - df_trades: 机构交易
                - df_financials: 财务数据
                - metadata: 元数据
            
        Returns:
            TradingSignal:
                - action=SELL: 卖出信号
                - action=HOLD: 持有
                - metadata中可以包含触发原因等信息
        
        注意：
        - 子类必须实现此方法
        - 可以通过position.entry_signal.metadata访问入场时的信息
        - 例如：entry_score = position.entry_signal.metadata.get('score')
        - 完全自主决定是否使用这些信息
        """
        pass
    
    def update_position(self, position: Position, current_price: float):
        """
        更新持仓信息
        
        默认实现：更新peak_price_since_entry
        子类可以重写以添加自定义逻辑
        
        Args:
            position: 持仓对象（会被原地修改）
            current_price: 当前价格
        """
        if current_price > position.peak_price_since_entry:
            position.peak_price_since_entry = current_price
    
    def __repr__(self):
        return f"{self.__class__.__name__}(name={self.strategy_name})"
