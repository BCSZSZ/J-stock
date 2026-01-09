"""
交易信号定义

定义统一的信号格式，供Entry和Exit策略使用
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any
from enum import Enum
import pandas as pd


class SignalAction(Enum):
    """交易信号动作"""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradingSignal:
    """
    统一的交易信号
    
    Entry和Exit策略都返回此格式
    
    Attributes:
        action: BUY/SELL/HOLD
        confidence: 0.0-1.0 信号强度/置信度
        reasons: 触发原因列表
        metadata: 额外数据（如score、技术指标值等）
        strategy_name: 策略名称
    """
    action: SignalAction
    confidence: float
    reasons: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)
    strategy_name: str = "Unknown"
    
    def __str__(self):
        return (f"[{self.strategy_name}] {self.action.value} "
                f"(confidence={self.confidence:.2f}): "
                f"{', '.join(self.reasons)}")
    
    def __repr__(self):
        return self.__str__()


@dataclass
class MarketData:
    """
    封装所有市场数据
    
    传递给Entry和Exit策略的统一数据接口
    
    Attributes:
        ticker: 股票代码
        current_date: 当前日期
        df_features: 技术指标DataFrame
        df_trades: 机构交易DataFrame
        df_financials: 财务数据DataFrame
        metadata: 元数据字典（财报日历等）
    """
    ticker: str
    current_date: pd.Timestamp
    df_features: pd.DataFrame
    df_trades: pd.DataFrame
    df_financials: pd.DataFrame
    metadata: dict
    
    @property
    def latest_price(self) -> float:
        """当前价格"""
        if self.df_features.empty:
            return 0.0
        return self.df_features.iloc[-1]['Close']
    
    @property
    def latest_features(self) -> pd.Series:
        """最新技术指标"""
        if self.df_features.empty:
            return pd.Series()
        return self.df_features.iloc[-1]
    
    def __repr__(self):
        return (f"MarketData({self.ticker}, {self.current_date.date()}, "
                f"price=¥{self.latest_price:,.0f})")


@dataclass
class Position:
    """
    持仓信息
    
    传递给Exit策略，包含入场信息和动态更新的数据
    
    Attributes:
        ticker: 股票代码
        entry_price: 入场价格
        entry_date: 入场日期
        quantity: 持仓数量
        entry_signal: 入场时的TradingSignal（含metadata如score等）
        peak_price_since_entry: 入场后的最高价格
    """
    ticker: str
    entry_price: float
    entry_date: pd.Timestamp
    quantity: int
    entry_signal: TradingSignal
    peak_price_since_entry: float = None
    
    def __post_init__(self):
        if self.peak_price_since_entry is None:
            self.peak_price_since_entry = self.entry_price
    
    def current_pnl_pct(self, current_price: float) -> float:
        """
        当前盈亏百分比
        
        Args:
            current_price: 当前价格
            
        Returns:
            盈亏百分比 (如 15.5 表示 +15.5%)
        """
        return ((current_price / self.entry_price) - 1) * 100
    
    def peak_pnl_pct(self) -> float:
        """
        最高盈亏百分比
        
        Returns:
            最高盈亏百分比
        """
        return ((self.peak_price_since_entry / self.entry_price) - 1) * 100
    
    def __repr__(self):
        return (f"Position({self.ticker}, entry=¥{self.entry_price:,.0f}, "
                f"date={self.entry_date.date()}, qty={self.quantity})")
