"""
Portfolio - 组合持仓管理
Manages multiple stock positions in a portfolio
"""
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import pandas as pd


@dataclass
class Position:
    """
    单个股票持仓
    
    与 src.analysis.signals.Position 兼容
    """
    ticker: str
    quantity: int
    entry_price: float
    entry_date: pd.Timestamp
    entry_signal: 'TradingSignal'  # Forward reference
    peak_price_since_entry: float = None
    
    def __post_init__(self):
        if self.peak_price_since_entry is None:
            self.peak_price_since_entry = self.entry_price
    
    def get_current_value(self, current_price: float) -> float:
        """计算当前市值"""
        return self.quantity * current_price
    
    def get_unrealized_pnl(self, current_price: float) -> float:
        """计算未实现盈亏"""
        return (current_price - self.entry_price) * self.quantity
    
    def get_unrealized_return_pct(self, current_price: float) -> float:
        """计算未实现收益率"""
        return ((current_price / self.entry_price) - 1) * 100
    
    def current_pnl_pct(self, current_price: float) -> float:
        """
        当前盈亏百分比（兼容 exit strategy 接口）
        
        Args:
            current_price: 当前价格
            
        Returns:
            盈亏百分比 (如 15.5 表示 +15.5%)
        """
        return ((current_price / self.entry_price) - 1) * 100
    
    def peak_pnl_pct(self) -> float:
        """
        最高盈亏百分比（兼容 exit strategy 接口）
        
        Returns:
            最高盈亏百分比
        """
        return ((self.peak_price_since_entry / self.entry_price) - 1) * 100
    
    def __repr__(self):
        return (f"Position({self.ticker}, entry=¥{self.entry_price:,.0f}, "
                f"date={self.entry_date.date()}, qty={self.quantity})")


class Portfolio:
    """
    组合投资管理器
    
    功能:
    1. 管理多个股票持仓
    2. 现金管理
    3. 仓位限制控制
    4. 总资产计算
    """
    
    def __init__(
        self,
        starting_cash: float,
        max_positions: int = 5,
        max_position_pct: float = 0.30,
        min_position_pct: float = 0.05
    ):
        """
        Args:
            starting_cash: 起始现金
            max_positions: 最大持仓数量（默认5只）
            max_position_pct: 单股最大仓位比例（默认30%）
            min_position_pct: 单股最小仓位比例（默认5%）
        """
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: Dict[str, Position] = {}
        
        self.max_positions = max_positions
        self.max_position_pct = max_position_pct
        self.min_position_pct = min_position_pct
    
    def get_total_value(self, current_prices: Dict[str, float]) -> float:
        """
        计算组合总资产
        
        Args:
            current_prices: {ticker: price} 字典
            
        Returns:
            总资产 = 现金 + 所有持仓市值
        """
        positions_value = sum(
            pos.get_current_value(current_prices[ticker])
            for ticker, pos in self.positions.items()
            if ticker in current_prices
        )
        return self.cash + positions_value
    
    def get_position_weight(
        self, 
        ticker: str, 
        current_prices: Dict[str, float]
    ) -> float:
        """
        计算某个持仓的权重
        
        Returns:
            仓位占比（0-1）
        """
        if ticker not in self.positions:
            return 0.0
        
        total_value = self.get_total_value(current_prices)
        if total_value == 0:
            return 0.0
        
        position_value = self.positions[ticker].get_current_value(
            current_prices[ticker]
        )
        return position_value / total_value
    
    def can_open_new_position(self) -> bool:
        """检查是否可以开新仓"""
        return len(self.positions) < self.max_positions
    
    def has_position(self, ticker: str) -> bool:
        """检查是否持有某只股票"""
        return ticker in self.positions
    
    def calculate_max_position_size(
        self, 
        current_prices: Dict[str, float]
    ) -> float:
        """
        计算单个新仓位的最大资金额度
        
        Returns:
            最大可投入资金
        """
        total_value = self.get_total_value(current_prices)
        max_value = total_value * self.max_position_pct
        
        # 不能超过现有现金
        return min(max_value, self.cash)
    
    def add_position(self, position: Position) -> bool:
        """
        添加新持仓
        
        Returns:
            是否成功添加
        """
        if self.has_position(position.ticker):
            return False
        
        if not self.can_open_new_position():
            return False
        
        # 扣除现金
        cost = position.quantity * position.entry_price
        if cost > self.cash:
            return False
        
        self.cash -= cost
        self.positions[position.ticker] = position
        return True
    
    def close_position(self, ticker: str, exit_price: float) -> Optional[float]:
        """
        平仓
        
        Args:
            ticker: 股票代码
            exit_price: 卖出价格
            
        Returns:
            卖出金额，如果没有持仓则返回None
        """
        if ticker not in self.positions:
            return None

        quantity = self.positions[ticker].quantity
        return self.close_partial_position(ticker=ticker, quantity=quantity, exit_price=exit_price)

    def close_partial_position(
        self,
        ticker: str,
        quantity: int,
        exit_price: float,
    ) -> Optional[float]:
        """
        部分平仓

        Args:
            ticker: 股票代码
            quantity: 卖出股数
            exit_price: 卖出价格

        Returns:
            卖出金额，如果没有持仓则返回None
        """
        if ticker not in self.positions:
            return None

        if quantity <= 0:
            return 0.0

        position = self.positions[ticker]
        sell_qty = min(quantity, position.quantity)
        proceeds = sell_qty * exit_price

        self.cash += proceeds
        position.quantity -= sell_qty

        if position.quantity <= 0:
            del self.positions[ticker]

        return proceeds
    
    def update_peak_prices(self, current_prices: Dict[str, float]):
        """更新所有持仓的峰值价格（用于trailing stop）"""
        for ticker, position in self.positions.items():
            if ticker in current_prices:
                current_price = current_prices[ticker]
                if current_price > position.peak_price_since_entry:
                    position.peak_price_since_entry = current_price
    
    def get_portfolio_summary(self, current_prices: Dict[str, float]) -> str:
        """获取组合摘要"""
        total_value = self.get_total_value(current_prices)
        
        lines = [
            f"总资产: ¥{total_value:,.0f}",
            f"现金: ¥{self.cash:,.0f} ({self.cash/total_value*100:.1f}%)",
            f"持仓数: {len(self.positions)}/{self.max_positions}"
        ]
        
        if self.positions:
            lines.append("\n持仓明细:")
            for ticker, pos in self.positions.items():
                if ticker in current_prices:
                    current_price = current_prices[ticker]
                    value = pos.get_current_value(current_price)
                    weight = value / total_value * 100
                    pnl_pct = pos.get_unrealized_return_pct(current_price)
                    
                    lines.append(
                        f"  {ticker}: {pos.quantity}股 @ ¥{current_price:,.2f} "
                        f"= ¥{value:,.0f} ({weight:.1f}%, {pnl_pct:+.2f}%)"
                    )
        
        return "\n".join(lines)
