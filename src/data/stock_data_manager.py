"""
Stock Data Manager Module
Coordinates data fetching, storage, and analysis for Japanese stocks.
Implements a Data Lake architecture with systematic folder structure.
"""
import logging
import json
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Any
import pandas as pd
import numpy as np
from ta.trend import EMAIndicator, MACD, ADXIndicator, IchimokuIndicator
from ta.momentum import RSIIndicator, StochasticOscillator
from ta.volatility import AverageTrueRange, BollingerBands
from ta.volume import OnBalanceVolumeIndicator

from src.client.jquants_client import JQuantsV2Client

logger = logging.getLogger(__name__)


class StockDataManager:
    """
    Manages stock data ingestion, storage, and technical analysis.
    
    Data Lake Structure:
    - raw_prices/: Daily OHLCV (Incremental updates)
    - raw_financials/: Quarterly financial data
    - raw_trades/: Weekly investor trading data
    - features/: Computed technical indicators
    - metadata/: Earnings dates, sector info (JSON)
    """
    
    def __init__(self, api_key: str = None, data_root: str = './data'):
        """
        Initialize the Stock Data Manager with Data Lake structure.
        
        Args:
            api_key: J-Quants API key (optional for read-only mode).
            data_root: Root directory for data lake.
        """
        self.client = JQuantsV2Client(api_key) if api_key else None
        self.data_root = Path(data_root)
        
        # Create Data Lake structure
        self.dirs = {
            'raw_prices': self.data_root / 'raw_prices',
            'raw_financials': self.data_root / 'raw_financials',
            'raw_trades': self.data_root / 'raw_trades',
            'features': self.data_root / 'features',
            'metadata': self.data_root / 'metadata'
        }
        
        for dir_path in self.dirs.values():
            dir_path.mkdir(parents=True, exist_ok=True)
        
        if api_key:
            logger.info(f"Initialized Data Lake at: {self.data_root} (with API access)")
        else:
            logger.info(f"Initialized Data Lake at: {self.data_root} (read-only mode)")

    # ==================== OHLC DATA MANAGEMENT ====================
    
    def fetch_and_update_ohlc(self, code: str) -> tuple[pd.DataFrame, bool]:
        """
        Fetch and update OHLC data for a stock using incremental strategy.
        
        Args:
            code: Stock code (e.g., '6758').
            
        Returns:
            Tuple of (Updated DataFrame, has_new_data flag)
        """
        file_path = self.dirs['raw_prices'] / f"{code}.parquet"
        
        if not file_path.exists():
            logger.info(f"[{code}] Cold start: Fetching 5 years of history")
            result_df = self._fetch_initial_data(code, file_path)
            return result_df, True  # New data fetched
        else:
            logger.info(f"[{code}] Incremental update mode")
            return self._fetch_incremental_data(code, file_path)

    def _fetch_initial_data(self, code: str, file_path: Path) -> pd.DataFrame:
        """
        Fetch the last 5 years of daily quotes (cold start).
        
        Args:
            code: Stock code.
            file_path: Path to save the data.
            
        Returns:
            DataFrame with OHLC data.
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=1825)  # 5 years
        
        from_str = start_date.strftime('%Y-%m-%d')
        to_str = end_date.strftime('%Y-%m-%d')
        
        bars = self.client.get_daily_bars(code, from_str, to_str)
        
        if not bars:
            logger.warning(f"[{code}] No data returned from API")
            return pd.DataFrame()
        
        df = self._normalize_ohlc_data(bars)
        self._atomic_save(df, file_path)
        logger.info(f"[{code}] Saved {len(df)} rows (initial fetch)")
        
        return df

    def _fetch_incremental_data(self, code: str, file_path: Path) -> tuple[pd.DataFrame, bool]:
        """
        Fetch new data from the last available date.
        
        Args:
            code: Stock code.
            file_path: Path to existing parquet file.
            
        Returns:
            Tuple of (Updated DataFrame, has_new_data flag)
        """
        # Load existing data
        existing_df = pd.read_parquet(file_path)
        
        if existing_df.empty:
            result_df = self._fetch_initial_data(code, file_path)
            return result_df, True  # New data fetched
        
        # Find last date
        existing_df['Date'] = pd.to_datetime(existing_df['Date'])
        last_date = existing_df['Date'].max()
        today = datetime.now().date()
        
        # Check if already up-to-date
        if last_date.date() >= today:
            logger.info(f"[{code}] Already up-to-date (last: {last_date.date()})")
            return existing_df, False  # No new data
        
        # Fetch from last_date + 1 to today
        start_date = last_date + timedelta(days=1)
        end_date = datetime.now()
        
        from_str = start_date.strftime('%Y-%m-%d')
        to_str = end_date.strftime('%Y-%m-%d')
        
        logger.info(f"[{code}] Fetching updates: {from_str} to {to_str}")
        bars = self.client.get_daily_bars(code, from_str, to_str)
        
        if not bars:
            logger.info(f"[{code}] No new data available")
            return existing_df, False  # No new data
        
        # Normalize and merge
        new_df = self._normalize_ohlc_data(bars)
        merged_df = pd.concat([existing_df, new_df], ignore_index=True)
        merged_df = merged_df.drop_duplicates(subset=['Date'], keep='last')
        merged_df = merged_df.sort_values('Date').reset_index(drop=True)
        
        # Atomic save
        self._atomic_save(merged_df, file_path)
        logger.info(f"[{code}] Added {len(new_df)} new rows. Total: {len(merged_df)}")
        
        return merged_df, True  # New data added
    
    def _atomic_save(self, df: pd.DataFrame, target_path: Path) -> None:
        """
        Save DataFrame using atomic write (temp file + rename).
        Prevents corruption if process is interrupted.
        
        Args:
            df: DataFrame to save.
            target_path: Final destination path.
        """
        # Write to temp file first
        temp_dir = target_path.parent
        with tempfile.NamedTemporaryFile(
            mode='wb',
            suffix='.parquet',
            dir=temp_dir,
            delete=False
        ) as tmp:
            temp_path = Path(tmp.name)
        
        try:
            df.to_parquet(temp_path, index=False)
            # Atomic rename (POSIX guarantees atomicity)
            shutil.move(str(temp_path), str(target_path))
        except Exception as e:
            # Cleanup on failure
            if temp_path.exists():
                temp_path.unlink()
            raise e

    def _normalize_ohlc_data(self, bars: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Convert API response to normalized DataFrame with human-readable columns.
        
        Args:
            bars: Raw bar data from API (abbreviated column names).
            
        Returns:
            DataFrame with standard column names.
        """
        df = pd.DataFrame(bars)
        
        # Rename abbreviated columns to human-readable
        column_mapping = {
            'Date': 'Date',
            'O': 'Open',
            'H': 'High',
            'L': 'Low',
            'C': 'Close',
            'Vo': 'Volume',
            'AdjustmentFactor': 'AdjustmentFactor'
        }
        
        # Only rename columns that exist
        existing_mappings = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=existing_mappings)
        
        # Ensure Date is datetime
        df['Date'] = pd.to_datetime(df['Date'])
        
        # Select core columns
        core_columns = ['Date', 'Open', 'High', 'Low', 'Close', 'Volume']
        available_columns = [col for col in core_columns if col in df.columns]
        
        return df[available_columns]

    # ==================== TECHNICAL INDICATORS (TRANSFORM) ====================
    
    def compute_features(self, code: str, force_recompute: bool = False) -> pd.DataFrame:
        """
        Compute technical indicators and save to features layer.
        Uses the `ta` library for indicator calculations.
        
        Args:
            code: Stock code.
            force_recompute: If True, always recompute. If False, check if needed.
            
        Returns:
            DataFrame with computed features.
        """
        # Load raw price data
        raw_path = self.dirs['raw_prices'] / f"{code}.parquet"
        features_path = self.dirs['features'] / f"{code}_features.parquet"
        
        if not raw_path.exists():
            logger.warning(f"[{code}] No raw price data found. Run fetch_and_update_ohlc first.")
            return pd.DataFrame()
        
        # Check if we need to recompute
        if not force_recompute and features_path.exists():
            # Compare raw vs features file timestamps
            raw_mtime = raw_path.stat().st_mtime
            features_mtime = features_path.stat().st_mtime
            
            if features_mtime >= raw_mtime:
                logger.info(f"[{code}] Features up-to-date, skip recompute")
                return pd.read_parquet(features_path)
        
        df = pd.read_parquet(raw_path)
        
        if df.empty or len(df) < 200:
            logger.warning(f"[{code}] Insufficient data for indicators (need 200+ rows)")
            return df
        
        # Add indicators using ta library
        logger.info(f"[{code}] Computing technical indicators...")
        
        # ==================== TREND INDICATORS ====================
        # EMAs
        ema_20 = EMAIndicator(close=df['Close'], window=20)
        ema_50 = EMAIndicator(close=df['Close'], window=50)
        ema_200 = EMAIndicator(close=df['Close'], window=200)
        
        df['EMA_20'] = ema_20.ema_indicator()
        df['EMA_50'] = ema_50.ema_indicator()
        df['EMA_200'] = ema_200.ema_indicator()
        
        # ADX (趋势强度)
        adx = ADXIndicator(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        df['ADX_14'] = adx.adx()
        
        # Ichimoku (一目均衡表)
        ichimoku = IchimokuIndicator(
            high=df['High'], 
            low=df['Low'], 
            window1=9,  # Tenkan-sen
            window2=26, # Kijun-sen
            window3=52  # Senkou Span B
        )
        df['Ichi_Tenkan'] = ichimoku.ichimoku_conversion_line()
        df['Ichi_Kijun'] = ichimoku.ichimoku_base_line()
        df['Ichi_SpanA'] = ichimoku.ichimoku_a()
        df['Ichi_SpanB'] = ichimoku.ichimoku_b()
        
        # ==================== MOMENTUM INDICATORS ====================
        # RSI
        rsi = RSIIndicator(close=df['Close'], window=14)
        df['RSI'] = rsi.rsi()
        
        # MACD
        macd = MACD(close=df['Close'], window_fast=12, window_slow=26, window_sign=9)
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Hist'] = macd.macd_diff()
        
        # Stochastic (KDJ)
        stoch = StochasticOscillator(
            high=df['High'], 
            low=df['Low'], 
            close=df['Close'],
            window=14,
            smooth_window=3
        )
        df['Stoch_K'] = stoch.stoch()
        df['Stoch_D'] = stoch.stoch_signal()
        
        # ==================== VOLATILITY INDICATORS ====================
        # ATR
        atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        df['ATR'] = atr.average_true_range()
        
        # Bollinger Bands
        bb = BollingerBands(close=df['Close'], window=20, window_dev=2)
        df['BB_Upper'] = bb.bollinger_hband()
        df['BB_Lower'] = bb.bollinger_lband()
        df['BB_Middle'] = bb.bollinger_mavg()
        df['BB_Width'] = bb.bollinger_wband()  # (Upper - Lower) / Middle
        df['BB_PctB'] = bb.bollinger_pband()   # (Close - Lower) / (Upper - Lower)
        
        # ==================== VOLUME INDICATORS ====================
        # Volume SMA
        df['Volume_SMA_20'] = df['Volume'].rolling(window=20).mean()
        
        # OBV (On-Balance Volume, 能量潮)
        obv = OnBalanceVolumeIndicator(close=df['Close'], volume=df['Volume'])
        df['OBV'] = obv.on_balance_volume()
        
        # Save to features layer
        self._atomic_save(df, features_path)
        logger.info(f"[{code}] Features saved: {len(df)} rows with {len(df.columns)} columns")
        
        return df

    # ==================== AUXILIARY DATA (CONTEXT) ====================
    
    def fetch_and_save_financials(self, code: str) -> Optional[pd.DataFrame]:
        """
        Fetch latest financial summary and save to raw_financials (增量追加).
        
        Args:
            code: Stock code.
            
        Returns:
            DataFrame with financial data or None.
        """
        output_path = self.dirs['raw_financials'] / f"{code}_financials.parquet"
        
        # 获取新数据
        financials = self.client.get_financial_summary(code)
        
        if not financials:
            logger.warning(f"[{code}] No financial data available")
            return None
        
        new_df = pd.DataFrame(financials)
        
        # 检查是否有历史数据
        if output_path.exists():
            existing_df = pd.read_parquet(output_path)
            
            # 确保DiscDate是datetime
            if 'DiscDate' in existing_df.columns:
                existing_df['DiscDate'] = pd.to_datetime(existing_df['DiscDate'])
            if 'DiscDate' in new_df.columns:
                new_df['DiscDate'] = pd.to_datetime(new_df['DiscDate'])
            
            # 合并：保留旧数据 + 追加新数据
            merged_df = pd.concat([existing_df, new_df], ignore_index=True)
            
            # 去重（根据DiscDate和Quarter去重，保留最新的）
            if 'DiscDate' in merged_df.columns and 'Quarter' in merged_df.columns:
                merged_df = merged_df.drop_duplicates(subset=['DiscDate', 'Quarter'], keep='last')
            
            # 排序
            if 'DiscDate' in merged_df.columns:
                merged_df = merged_df.sort_values('DiscDate').reset_index(drop=True)
            
            # 检查是否有新增
            if len(merged_df) > len(existing_df):
                logger.info(f"[{code}] Added {len(merged_df) - len(existing_df)} new financial records. Total: {len(merged_df)}")
                self._atomic_save(merged_df, output_path)
            else:
                logger.info(f"[{code}] Financials up-to-date, no new records ({len(existing_df)} records)")
                return existing_df
            
            return merged_df
        else:
            # 首次保存
            self._atomic_save(new_df, output_path)
            logger.info(f"[{code}] Saved {len(new_df)} financial records (initial)")
            return new_df
    
    def fetch_and_save_investor_trades(self, code: str) -> Optional[pd.DataFrame]:
        """
        Fetch investor type trading data and save to raw_trades (incremental append).
        
        Args:
            code: Stock code.
            
        Returns:
            DataFrame with trading data or None.
        """
        output_path = self.dirs['raw_trades'] / f"{code}_trades.parquet"
        
        # Check for existing data
        if output_path.exists():
            existing_df = pd.read_parquet(output_path)
            existing_df['EnDate'] = pd.to_datetime(existing_df['EnDate'])
            
            # Find last date
            last_date = existing_df['EnDate'].max()
            
            # Only fetch after last date (+1 day to today)
            start_date = last_date + timedelta(days=1)
            end_date = datetime.now()
            
            # If already up-to-date, skip
            if start_date.date() >= end_date.date():
                logger.info(f"[{code}] Investor trades up-to-date (last: {last_date.date()})")
                return existing_df
        else:
            # First fetch: get 90 days
            end_date = datetime.now()
            start_date = end_date - timedelta(days=90)
            existing_df = pd.DataFrame()
        
        # Fetch new data
        new_records = self.client.get_investor_types(
            code,
            start_date.strftime('%Y-%m-%d'),
            end_date.strftime('%Y-%m-%d')
        )
        
        if not new_records:
            if existing_df.empty:
                logger.warning(f"[{code}] No investor trading data available")
                return None
            else:
                logger.info(f"[{code}] No new investor trades")
                return existing_df
        
        # Convert to DataFrame
        new_df = pd.DataFrame(new_records)
        
        if 'EnDate' in new_df.columns:
            new_df['EnDate'] = pd.to_datetime(new_df['EnDate'])
        
        # Merge with existing
        if not existing_df.empty:
            merged_df = pd.concat([existing_df, new_df], ignore_index=True)
            
            # Deduplicate by (EnDate, Section, InvestorCode)
            available_cols = [col for col in ['EnDate', 'Section', 'InvestorCode'] 
                            if col in merged_df.columns]
            if available_cols:
                merged_df = merged_df.drop_duplicates(subset=available_cols, keep='last')
            
            # Sort
            merged_df = merged_df.sort_values('EnDate').reset_index(drop=True)
            
            if len(merged_df) > len(existing_df):
                logger.info(f"[{code}] Added {len(new_df)} new trade records. Total: {len(merged_df)} (was {len(existing_df)})")
            else:
                logger.info(f"[{code}] No new records after dedup. Total: {len(merged_df)}")
        else:
            merged_df = new_df.sort_values('EnDate').reset_index(drop=True)
            logger.info(f"[{code}] Saved {len(merged_df)} trading records (initial)")
        
        # Save
        self._atomic_save(merged_df, output_path)
        
        return merged_df
    
    def fetch_and_save_metadata(self, code: str) -> None:
        """
        Fetch and save metadata (earnings calendar) as JSON (智能更新).
        
        Args:
            code: Stock code.
        """
        output_path = self.dirs['metadata'] / f"{code}_metadata.json"
        
        # 获取新的元数据
        new_metadata = {}
        
        # Earnings calendar
        today = datetime.now()
        future = today + timedelta(days=180)
        
        earnings = self.client.get_earnings_calendar(
            code,
            today.strftime('%Y-%m-%d'),
            future.strftime('%Y-%m-%d')
        )
        
        if earnings:
            new_metadata['earnings_calendar'] = earnings
        
        # 如果没有新数据，跳过
        if not new_metadata:
            logger.info(f"[{code}] No metadata to update")
            return
        
        # 检查是否有历史数据
        if output_path.exists():
            with open(output_path, 'r', encoding='utf-8') as f:
                existing_metadata = json.load(f)
            
            # 比较是否有变化
            if existing_metadata == new_metadata:
                logger.info(f"[{code}] Metadata unchanged, skip save")
                return
            else:
                logger.info(f"[{code}] Metadata updated ({len(earnings)} events)")
        else:
            logger.info(f"[{code}] Saved {len(earnings)} earnings events (initial)")
        
        # 保存
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(new_metadata, f, indent=2, ensure_ascii=False)

    # ==================== COMPLETE ETL WORKFLOW ====================
    
    def run_full_etl(self, code: str) -> Dict[str, Any]:
        """
        Run complete ETL pipeline for a single stock.
        
        Args:
            code: Stock code.
            
        Returns:
            Dictionary with status and metrics.
        """
        result = {
            'code': code,
            'success': False,
            'errors': [],
            'has_new_data': False
        }
        
        try:
            # Step 1: Fetch/Update OHLC (增量)
            df_prices, has_new_data = self.fetch_and_update_ohlc(code)
            result['price_rows'] = len(df_prices)
            result['has_new_data'] = has_new_data
            
            if df_prices.empty:
                result['errors'].append('No price data fetched')
                return result
            
            # Step 2: Compute Features (只有新数据才重算)
            # force_recompute=False 会检查文件时间戳，只有raw_prices更新了才重算
            df_features = self.compute_features(code, force_recompute=False)
            result['feature_cols'] = len(df_features.columns)
            
            # Step 3: Fetch Auxiliary Data (optional - don't fail on these)
            try:
                self.fetch_and_save_financials(code)
            except Exception as e:
                logger.warning(f"[{code}] Financials fetch failed: {e}")
            
            try:
                self.fetch_and_save_investor_trades(code)
            except Exception as e:
                logger.warning(f"[{code}] Investor trades fetch failed: {e}")
            
            try:
                self.fetch_and_save_metadata(code)
            except Exception as e:
                logger.warning(f"[{code}] Metadata fetch failed: {e}")
            
            result['success'] = True
            
        except Exception as e:
            logger.error(f"[{code}] ETL failed: {e}", exc_info=True)
            result['errors'].append(str(e))
        
        return result

    # ==================== DATA LOADING METHODS ====================
    
    def load_stock_features(self, ticker: str) -> pd.DataFrame:
        """
        Load feature data for a stock (read-only operation).
        
        Args:
            ticker: Stock code (e.g., '7974')
            
        Returns:
            DataFrame with features, or empty DataFrame if not found
        """
        features_path = self.dirs['features'] / f"{ticker}_features.parquet"
        
        if not features_path.exists():
            logger.warning(f"Features file not found for {ticker}: {features_path}")
            return pd.DataFrame()
        
        try:
            df = pd.read_parquet(features_path)
            logger.debug(f"Loaded {len(df)} rows for {ticker}")
            return df
        except Exception as e:
            logger.error(f"Failed to load features for {ticker}: {e}")
            return pd.DataFrame()
    
    def load_raw_prices(self, ticker: str) -> pd.DataFrame:
        """Load raw price data for a stock."""
        prices_path = self.dirs['raw_prices'] / f"{ticker}.parquet"
        
        if not prices_path.exists():
            logger.warning(f"Price file not found for {ticker}")
            return pd.DataFrame()
        
        return pd.read_parquet(prices_path)
    
    def load_trades(self, ticker: str) -> pd.DataFrame:
        """Load investor trades data for a stock."""
        trades_path = self.dirs['raw_trades'] / f"{ticker}_trades.parquet"
        
        if not trades_path.exists():
            return pd.DataFrame()
        
        return pd.read_parquet(trades_path)
    
    def load_financials(self, ticker: str) -> pd.DataFrame:
        """Load financial data for a stock."""
        financials_path = self.dirs['raw_financials'] / f"{ticker}_financials.parquet"
        
        if not financials_path.exists():
            return pd.DataFrame()
        
        return pd.read_parquet(financials_path)
    
    def load_metadata(self, ticker: str) -> dict:
        """Load metadata for a stock."""
        metadata_path = self.dirs['metadata'] / f"{ticker}_metadata.json"
        
        if not metadata_path.exists():
            return {}
        
        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load metadata for {ticker}: {e}")
            return {}
