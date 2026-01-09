"""
最小购买单位管理器
Manages minimum lot sizes for different stocks
"""
from typing import Dict


class LotSizeManager:
    """
    处理不同股票的最小购买单位
    
    日本股票市场规则:
    - 普通股票: 100股为1单位（1 lot）
    - REIT (如1321): 1股为1单位
    """
    
    # 特殊股票的lot size配置
    SPECIAL_LOT_SIZES: Dict[str, int] = {
        "1321": 1,     # REIT: 1股起
        "1343": 1,     # REIT
        # 可以继续添加其他特殊股票
    }
    
    DEFAULT_LOT_SIZE = 100  # 日本股票默认100股
    
    @classmethod
    def get_lot_size(cls, ticker: str) -> int:
        """
        获取股票的最小购买单位
        
        Args:
            ticker: 股票代码
            
        Returns:
            该股票的最小购买单位
        """
        return cls.SPECIAL_LOT_SIZES.get(ticker, cls.DEFAULT_LOT_SIZE)
    
    @classmethod
    def calculate_buyable_shares(
        cls, 
        ticker: str, 
        available_cash: float, 
        price: float
    ) -> int:
        """
        计算可购买的股数（考虑最小单位限制）
        
        Args:
            ticker: 股票代码
            available_cash: 可用资金
            price: 股票价格
            
        Returns:
            可购买的股数（已向下取整到lot_size的倍数）
            
        Examples:
            >>> # 普通股票（100股起）
            >>> LotSizeManager.calculate_buyable_shares("7203", 250000, 2500)
            100  # 只能买100股，不能买101-199股
            
            >>> # REIT（1股起）
            >>> LotSizeManager.calculate_buyable_shares("1321", 10000, 3500)
            2  # 可以买2股
        """
        if price <= 0:
            return 0
        
        lot_size = cls.get_lot_size(ticker)
        
        # 计算最大可买股数
        max_shares = int(available_cash / price)
        
        # 向下取整到lot_size的倍数
        shares = (max_shares // lot_size) * lot_size
        
        return shares
    
    @classmethod
    def set_custom_lot_size(cls, ticker: str, lot_size: int):
        """
        设置自定义lot size（用于配置文件加载）
        
        Args:
            ticker: 股票代码
            lot_size: 最小购买单位
        """
        cls.SPECIAL_LOT_SIZES[ticker] = lot_size
    
    @classmethod
    def load_from_config(cls, lot_sizes_config: Dict[str, int]):
        """
        从配置文件加载lot size设置
        
        Args:
            lot_sizes_config: {"ticker": lot_size} 字典
        """
        for ticker, lot_size in lot_sizes_config.items():
            if ticker != "default":
                cls.set_custom_lot_size(ticker, lot_size)
