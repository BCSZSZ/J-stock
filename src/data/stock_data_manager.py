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
from ta.trend import EMAIndicator, MACD
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

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
    
    def __init__(self, api_key: str, data_root: str = './data'):
        """
        Initialize the Stock Data Manager with Data Lake structure.
        
        Args:
            api_key: J-Quants API key.
            data_root: Root directory for data lake.
        """
        self.client = JQuantsV2Client(api_key)
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
        
        logger.info(f"Initialized Data Lake at: {self.data_root}")

    # ==================== OHLC DATA MANAGEMENT ====================
    
    def fetch_and_update_ohlc(self, code: str) -> pd.DataFrame:
        """
        Fetch and update OHLC data for a stock using incremental strategy.
        
        Args:
            code: Stock code (e.g., '6758').
            
        Returns:
            Updated DataFrame with OHLC data.
        """
        file_path = self.dirs['raw_prices'] / f"{code}.parquet"
        
        if not file_path.exists():
            logger.info(f"[{code}] Cold start: Fetching 5 years of history")
            return self._fetch_initial_data(code, file_path)
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

    def _fetch_incremental_data(self, code: str, file_path: Path) -> pd.DataFrame:
        """
        Fetch new data from the last available date.
        
        Args:
            code: Stock code.
            file_path: Path to existing parquet file.
            
        Returns:
            Updated DataFrame with merged data.
        """
        # Load existing data
        existing_df = pd.read_parquet(file_path)
        
        if existing_df.empty:
            return self._fetch_initial_data(code, file_path)
        
        # Find last date
        existing_df['Date'] = pd.to_datetime(existing_df['Date'])
        last_date = existing_df['Date'].max()
        today = datetime.now().date()
        
        # Check if already up-to-date
        if last_date.date() >= today:
            logger.info(f"[{code}] Already up-to-date (last: {last_date.date()})")
            return existing_df
        
        # Fetch from last_date + 1 to today
        start_date = last_date + timedelta(days=1)
        end_date = datetime.now()
        
        from_str = start_date.strftime('%Y-%m-%d')
        to_str = end_date.strftime('%Y-%m-%d')
        
        logger.info(f"[{code}] Fetching updates: {from_str} to {to_str}")
        bars = self.client.get_daily_bars(code, from_str, to_str)
        
        if not bars:
            logger.info(f"[{code}] No new data available")
            return existing_df
        
        # Normalize and merge
        new_df = self._normalize_ohlc_data(bars)
        merged_df = pd.concat([existing_df, new_df], ignore_index=True)
        merged_df = merged_df.drop_duplicates(subset=['Date'], keep='last')
        merged_df = merged_df.sort_values('Date').reset_index(drop=True)
        
        # Atomic save
        self._atomic_save(merged_df, file_path)
        logger.info(f"[{code}] Added {len(new_df)} new rows. Total: {len(merged_df)}")
        
        return merged_df
    
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
    
    def compute_features(self, code: str) -> pd.DataFrame:
        """
        Compute technical indicators and save to features layer.
        Uses the `ta` library for indicator calculations.
        
        Args:
            code: Stock code.
            
        Returns:
            DataFrame with computed features.
        """
        # Load raw price data
        raw_path = self.dirs['raw_prices'] / f"{code}.parquet"
        
        if not raw_path.exists():
            logger.warning(f"[{code}] No raw price data found. Run fetch_and_update_ohlc first.")
            return pd.DataFrame()
        
        df = pd.read_parquet(raw_path)
        
        if df.empty or len(df) < 200:
            logger.warning(f"[{code}] Insufficient data for indicators (need 200+ rows)")
            return df
        
        # Add indicators using ta library
        logger.info(f"[{code}] Computing technical indicators...")
        
        # Trend: EMAs
        ema_20 = EMAIndicator(close=df['Close'], window=20)
        ema_50 = EMAIndicator(close=df['Close'], window=50)
        ema_200 = EMAIndicator(close=df['Close'], window=200)
        
        df['EMA_20'] = ema_20.ema_indicator()
        df['EMA_50'] = ema_50.ema_indicator()
        df['EMA_200'] = ema_200.ema_indicator()
        
        # Momentum: RSI
        rsi = RSIIndicator(close=df['Close'], window=14)
        df['RSI'] = rsi.rsi()
        
        # MACD
        macd = MACD(close=df['Close'], window_fast=12, window_slow=26, window_sign=9)
        df['MACD'] = macd.macd()
        df['MACD_Signal'] = macd.macd_signal()
        df['MACD_Hist'] = macd.macd_diff()
        
        # Volatility: ATR
        atr = AverageTrueRange(high=df['High'], low=df['Low'], close=df['Close'], window=14)
        df['ATR'] = atr.average_true_range()
        
        # Volume: SMA
        df['Volume_SMA_20'] = df['Volume'].rolling(window=20).mean()
        
        # Save to features layer
        features_path = self.dirs['features'] / f"{code}_features.parquet"
        self._atomic_save(df, features_path)
        logger.info(f"[{code}] Features saved: {len(df)} rows with {len(df.columns)} columns")
        
        return df

    # ==================== AUXILIARY DATA (CONTEXT) ====================
    
    def fetch_and_save_financials(self, code: str) -> Optional[pd.DataFrame]:
        """
        Fetch latest financial summary and save to raw_financials.
        
        Args:
            code: Stock code.
            
        Returns:
            DataFrame with financial data or None.
        """
        financials = self.client.get_financial_summary(code)
        
        if not financials:
            logger.warning(f"[{code}] No financial data available")
            return None
        
        df = pd.DataFrame(financials)
        output_path = self.dirs['raw_financials'] / f"{code}_financials.parquet"
        self._atomic_save(df, output_path)
        logger.info(f"[{code}] Saved {len(df)} financial records")
        
        return df
    
    def fetch_and_save_investor_trades(self, code: str) -> Optional[pd.DataFrame]:
        """
        Fetch investor type trading data and save to raw_trades.
        
        Args:
            code: Stock code.
            
        Returns:
            DataFrame with trading data or None.
        """
        # Fetch last 90 days to capture weekly data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=90)
        
        from_str = start_date.strftime('%Y-%m-%d')
        to_str = end_date.strftime('%Y-%m-%d')
        
        trades = self.client.get_investor_types(code, from_str, to_str)
        
        if not trades:
            logger.warning(f"[{code}] No investor trading data available")
            return None
        
        df = pd.DataFrame(trades)
        output_path = self.dirs['raw_trades'] / f"{code}_trades.parquet"
        self._atomic_save(df, output_path)
        logger.info(f"[{code}] Saved {len(df)} trading records")
        
        return df
    
    def fetch_and_save_metadata(self, code: str) -> None:
        """
        Fetch and save metadata (earnings calendar, etc.) as JSON.
        
        Args:
            code: Stock code.
        """
        metadata = {}
        
        # Earnings calendar
        today = datetime.now()
        future = today + timedelta(days=180)
        
        earnings = self.client.get_earnings_calendar(
            code,
            today.strftime('%Y-%m-%d'),
            future.strftime('%Y-%m-%d')
        )
        
        if earnings:
            metadata['earnings_calendar'] = earnings
            logger.info(f"[{code}] Found {len(earnings)} upcoming earnings events")
        
        # Save as JSON
        if metadata:
            output_path = self.dirs['metadata'] / f"{code}_metadata.json"
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            logger.info(f"[{code}] Metadata saved")

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
            'errors': []
        }
        
        try:
            # Step 1: Fetch/Update OHLC
            df_prices = self.fetch_and_update_ohlc(code)
            result['price_rows'] = len(df_prices)
            
            if df_prices.empty:
                result['errors'].append('No price data fetched')
                return result
            
            # Step 2: Compute Features
            df_features = self.compute_features(code)
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
