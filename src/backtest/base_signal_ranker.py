"""
Base Signal Ranker Protocol

Defines the interface for pluggable signal ranking strategies.
All ranking strategies must implement this protocol.
"""

from typing import Dict, List, Optional, Protocol, Tuple

from ..analysis.signals import MarketData, TradingSignal


class BaseSignalRanker(Protocol):
    """
    信号排序器协议。

    所有排序策略须实现此接口，用于在多个买入信号同时触发时决定优先级。
    """

    @property
    def name(self) -> str:
        """排序策略的唯一标识名称。"""
        ...

    def requires_market_data(self) -> bool:
        """是否需要 market_data_dict 来计算排序。"""
        ...

    def rank_buy_signals(
        self,
        signals: Dict[str, TradingSignal],
        market_data_dict: Dict[str, MarketData],
        top_k: Optional[int] = None,
    ) -> List[Tuple[str, TradingSignal, float]]:
        """
        对买入信号进行排序。

        Args:
            signals: {ticker: TradingSignal} 字典
            market_data_dict: {ticker: MarketData} 字典
            top_k: 仅返回前 K 个信号（可选）

        Returns:
            排序后的列表: [(ticker, signal, priority_score), ...]
            按 priority_score 降序排列
        """
        ...
