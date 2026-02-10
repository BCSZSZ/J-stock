"""
MarketDataBuilder - 统一数据准备工具

用于将原始数据（features/trades/financials）转换为 MarketData 对象
消除重复的数据准备代码（之前在5个地方都有相同的逻辑）
"""

from pathlib import Path
from typing import Optional, Dict, Tuple
import json
import pandas as pd

from src.analysis.signals import MarketData


class MarketDataBuilder:
    """构建 MarketData 对象的统一工具类"""
    
    @staticmethod
    def build_from_manager(
        data_manager,
        ticker: str,
        current_date: pd.Timestamp
    ) -> Optional[MarketData]:
        """
        从 StockDataManager 加载数据并构建 MarketData 对象
        
        Args:
            data_manager: StockDataManager 实例
            ticker: 股票代码
            current_date: 当前日期
            
        Returns:
            MarketData 对象，或 None（如果数据加载失败）
        """
        try:
            # 加载所有数据
            df_features = data_manager.load_stock_features(ticker)
            df_trades = data_manager.load_trades(ticker)
            df_financials = data_manager.load_financials(ticker)
            metadata = data_manager.load_metadata(ticker)
            
            if df_features is None or df_features.empty:
                return None
            
            # 标准化特征数据
            df_features = MarketDataBuilder._prepare_features(df_features, current_date)
            
            # 标准化交易数据
            df_trades = MarketDataBuilder._prepare_trades(df_trades, current_date)
            
            # 标准化财务数据
            df_financials = MarketDataBuilder._prepare_financials(df_financials, current_date)
            
            # 创建 MarketData 对象
            return MarketData(
                ticker=ticker,
                current_date=current_date,
                df_features=df_features,
                df_trades=df_trades,
                df_financials=df_financials,
                metadata=metadata or {}
            )
            
        except Exception as e:
            print(f"❌ Error building MarketData for {ticker}: {e}")
            return None
    
    @staticmethod
    def build_from_parquet(
        ticker: str,
        current_date: pd.Timestamp,
        data_root: str = "data"
    ) -> Optional[MarketData]:
        """
        从 Parquet 文件直接加载数据并构建 MarketData 对象
        
        Args:
            ticker: 股票代码
            current_date: 当前日期
            data_root: 数据根目录
            
        Returns:
            MarketData 对象，或 None（如果数据加载失败）
        """
        try:
            data_root = Path(data_root)
            
            # 加载特征数据
            features_path = data_root / 'features' / f'{ticker}_features.parquet'
            if not features_path.exists():
                return None
            
            df_features = pd.read_parquet(features_path)
            df_features = MarketDataBuilder._prepare_features(df_features, current_date)
            
            # 加载交易数据
            trades_path = data_root / 'raw_trades' / f'{ticker}_trades.parquet'
            df_trades = pd.DataFrame()
            if trades_path.exists():
                df_trades = pd.read_parquet(trades_path)
                df_trades = MarketDataBuilder._prepare_trades(df_trades, current_date)
            
            # 加载财务数据
            financials_path = data_root / 'raw_financials' / f'{ticker}_financials.parquet'
            df_financials = pd.DataFrame()
            if financials_path.exists():
                df_financials = pd.read_parquet(financials_path)
                df_financials = MarketDataBuilder._prepare_financials(df_financials, current_date)
            
            # 加载元数据
            metadata = {}
            metadata_path = data_root / 'metadata' / f'{ticker}_metadata.json'
            if metadata_path.exists():
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            
            # 创建 MarketData 对象
            return MarketData(
                ticker=ticker,
                current_date=current_date,
                df_features=df_features,
                df_trades=df_trades,
                df_financials=df_financials,
                metadata=metadata
            )
            
        except Exception as e:
            print(f"❌ Error building MarketData for {ticker}: {e}")
            return None
    
    @staticmethod
    def build_from_dataframes(
        ticker: str,
        current_date: pd.Timestamp,
        df_features: pd.DataFrame,
        df_trades: Optional[pd.DataFrame] = None,
        df_financials: Optional[pd.DataFrame] = None,
        metadata: Optional[Dict] = None
    ) -> MarketData:
        """
        从已加载的 DataFrame 构建 MarketData 对象
        
        Args:
            ticker: 股票代码
            current_date: 当前日期
            df_features: 特征数据
            df_trades: 交易数据（可选）
            df_financials: 财务数据（可选）
            metadata: 元数据（可选）
            
        Returns:
            MarketData 对象
        """
        # 标准化所有数据
        df_features = MarketDataBuilder._prepare_features(df_features, current_date)
        df_trades = MarketDataBuilder._prepare_trades(df_trades if df_trades is not None else pd.DataFrame(), current_date)
        df_financials = MarketDataBuilder._prepare_financials(df_financials if df_financials is not None else pd.DataFrame(), current_date)
        
        return MarketData(
            ticker=ticker,
            current_date=current_date,
            df_features=df_features,
            df_trades=df_trades,
            df_financials=df_financials,
            metadata=metadata or {}
        )
    
    # ================================================================
    # 内部辅助方法 - 数据标准化
    # ================================================================
    
    @staticmethod
    def _prepare_features(
        df_features: pd.DataFrame,
        current_date: pd.Timestamp
    ) -> pd.DataFrame:
        """
        标准化特征数据
        
        要求：
        1. Date 列转为 datetime64
        2. 设置 Date 为索引
        3. 按日期过滤 <= current_date
        4. 按日期排序（升序）
        
        Args:
            df_features: 原始特征数据
            current_date: 截止日期
            
        Returns:
            标准化的特征数据（Date 作为索引）
        """
        if df_features.empty:
            return df_features
        
        df = df_features.copy()
        
        # 确保 Date 列是 datetime64
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date'])
            # 如果还不是索引，设置为索引
            if df.index.name != 'Date':
                df = df.set_index('Date')
        elif df.index.name != 'Date':
            # 如果 Date 不在列中但在索引中，确保它是 datetime64
            df.index = pd.to_datetime(df.index)
        
        # 按日期过滤
        current_ts = pd.Timestamp(current_date)
        df = df[df.index <= current_ts]
        
        # 按日期排序
        df = df.sort_index()
        
        return df
    
    @staticmethod
    def _prepare_trades(
        df_trades: pd.DataFrame,
        current_date: pd.Timestamp
    ) -> pd.DataFrame:
        """
        标准化交易数据
        
        要求：
        1. EnDate 列转为 datetime64（保持为列，不转为索引）
        2. 按 EnDate 过滤 <= current_date
        3. 过滤到 TSEPrime 部分（如果有 Section 列）
        
        Args:
            df_trades: 原始交易数据
            current_date: 截止日期
            
        Returns:
            标准化的交易数据（EnDate 作为列）
        """
        if df_trades.empty:
            return df_trades
        
        df = df_trades.copy()
        
        # 过滤到 TSEPrime
        if 'Section' in df.columns:
            df = df[df['Section'] == 'TSEPrime']
        
        # 转换 EnDate 为 datetime64
        if 'EnDate' in df.columns:
            df['EnDate'] = pd.to_datetime(df['EnDate'])
            
            # 按日期过滤
            current_ts = pd.Timestamp(current_date)
            df = df[df['EnDate'] <= current_ts]
        
        return df
    
    @staticmethod
    def _prepare_financials(
        df_financials: pd.DataFrame,
        current_date: pd.Timestamp
    ) -> pd.DataFrame:
        """
        标准化财务数据
        
        要求：
        1. DiscDate 列转为 datetime64（保持为列，不转为索引）
        2. 按 DiscDate 过滤 <= current_date
        
        Args:
            df_financials: 原始财务数据
            current_date: 截止日期
            
        Returns:
            标准化的财务数据（DiscDate 作为列）
        """
        if df_financials.empty:
            return df_financials
        
        df = df_financials.copy()
        
        # 转换 DiscDate 为 datetime64
        if 'DiscDate' in df.columns:
            df['DiscDate'] = pd.to_datetime(df['DiscDate'])
            
            # 按日期过滤
            current_ts = pd.Timestamp(current_date)
            df = df[df['DiscDate'] <= current_ts]
        
        return df
