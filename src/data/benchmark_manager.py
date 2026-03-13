"""
Benchmark Data Manager
Manage benchmark indices (TOPIX, Nikkei225, etc.) for strategy comparison.
"""
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import pandas as pd

from src.client.jquants_client import JQuantsV2Client

logger = logging.getLogger(__name__)


class BenchmarkManager:
    """
    Manage benchmark index data (TOPIX, etc.)
    
    Features:
    - Incremental updates (only fetch new data)
    - Local caching in data/benchmarks/
    - Consistent with stock data pipeline
    """
    
    def __init__(self, client: JQuantsV2Client, data_root: str = './data'):
        """
        Initialize benchmark manager.
        
        Args:
            client: J-Quants API client
            data_root: Root directory for data storage
        """
        self.client = client
        self.data_root = Path(data_root)
        self.benchmark_dir = self.data_root / 'benchmarks'
        self.benchmark_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Benchmark data directory: {self.benchmark_dir}")
    
    def fetch_and_update_topix(
        self,
        lookback_days: int = 1800,
        force_full_refresh: bool = False
    ) -> pd.DataFrame:
        """
        Fetch and update TOPIX daily data (incremental).
        
        Args:
            lookback_days: Days to fetch on first load (default ~5 years for Light Plan)
            force_full_refresh: If True, re-fetch all data
            
        Returns:
            DataFrame with TOPIX OHLC data
        """
        output_path = self.benchmark_dir / 'topix_daily.parquet'
        
        # Determine date range
        if output_path.exists() and not force_full_refresh:
            # Incremental mode: Load existing data
            existing_df = pd.read_parquet(output_path)
            existing_df['Date'] = pd.to_datetime(existing_df['Date'])
            
            last_date = existing_df['Date'].max()
            start_date = last_date + timedelta(days=1)
            end_date = datetime.now()
            
            logger.info(f"TOPIX incremental update: last={last_date.date()}, fetching from {start_date.date()}")
            
            # Check if already up-to-date
            if start_date.date() > end_date.date():
                logger.info(f"TOPIX up-to-date (last: {last_date.date()})")
                return existing_df
        else:
            # First fetch: Get historical data
            end_date = datetime.now()
            start_date = end_date - timedelta(days=lookback_days)
            existing_df = pd.DataFrame()
            
            logger.info(f"TOPIX initial fetch: {lookback_days} days ({start_date.date()} to {end_date.date()})")
        
        # Fetch new data from API
        try:
            new_records = self.client.get_topix_bars(
                start_date.strftime('%Y-%m-%d'),
                end_date.strftime('%Y-%m-%d')
            )
            
            if not new_records:
                if existing_df.empty:
                    logger.warning("No TOPIX data available")
                    return pd.DataFrame()
                else:
                    logger.info("No new TOPIX data")
                    return existing_df
            
            # Convert to DataFrame
            new_df = pd.DataFrame(new_records)
            
            # Standardize column names (API returns uppercase O, H, L, C)
            column_mapping = {
                'Date': 'Date',  # Already correct
                'O': 'Open',
                'H': 'High',
                'L': 'Low',
                'C': 'Close'
            }
            new_df = new_df.rename(columns=column_mapping)
            new_df['Date'] = pd.to_datetime(new_df['Date'])
            
            # Merge with existing
            if not existing_df.empty:
                merged_df = pd.concat([existing_df, new_df], ignore_index=True)
                merged_df = merged_df.drop_duplicates(subset=['Date'], keep='last')
                merged_df = merged_df.sort_values('Date').reset_index(drop=True)
                
                new_count = len(merged_df) - len(existing_df)
                logger.info(f"TOPIX: Added {new_count} new records. Total: {len(merged_df)} (was {len(existing_df)})")
            else:
                merged_df = new_df.sort_values('Date').reset_index(drop=True)
                logger.info(f"TOPIX: Saved {len(merged_df)} records (initial)")
            
            # Save to parquet
            merged_df.to_parquet(output_path, index=False)
            logger.info(f"TOPIX data saved to {output_path}")
            
            return merged_df
            
        except Exception as e:
            logger.error(f"Failed to fetch TOPIX data: {e}")
            if not existing_df.empty:
                logger.info("Returning existing TOPIX data")
                return existing_df
            return pd.DataFrame()
    
    def get_topix_data(self) -> Optional[pd.DataFrame]:
        """
        Load TOPIX data from local storage.
        
        Returns:
            DataFrame with TOPIX OHLC data, or None if not available
        """
        output_path = self.benchmark_dir / 'topix_daily.parquet'
        
        if not output_path.exists():
            logger.warning("TOPIX data not found. Run fetch_and_update_topix() first.")
            return None
        
        df = pd.read_parquet(output_path)
        df['Date'] = pd.to_datetime(df['Date'])
        
        logger.info(f"Loaded TOPIX data: {len(df)} records ({df['Date'].min().date()} to {df['Date'].max().date()})")
        
        return df
    
    def calculate_benchmark_return(
        self,
        start_date: str,
        end_date: str,
        use_cached: bool = True
    ) -> Optional[float]:
        """
        Calculate TOPIX buy-and-hold return for a date range.
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            use_cached: Use local data (True) or fetch from API (False)
            
        Returns:
            Total return percentage, or None if data unavailable
        """
        if use_cached:
            df = self.get_topix_data()
            if df is None or df.empty:
                logger.warning("No cached TOPIX data, please run fetch_and_update_topix() first")
                return None
        else:
            # Fetch directly from API (for one-off comparisons)
            try:
                records = self.client.get_topix_bars(start_date, end_date)
                if not records or len(records) < 2:
                    logger.warning("Insufficient TOPIX data from API")
                    return None
                df = pd.DataFrame(records)
                df['Date'] = pd.to_datetime(df['Date'])
                df = df.rename(columns={'C': 'Close'})
            except Exception as e:
                logger.error(f"Failed to fetch TOPIX from API: {e}")
                return None
        
        # Filter to date range
        start = pd.to_datetime(start_date)
        end = pd.to_datetime(end_date)
        df_range = df[(df['Date'] >= start) & (df['Date'] <= end)]
        
        if len(df_range) < 2:
            logger.warning(f"Insufficient TOPIX data for range {start_date} to {end_date}")
            return None
        
        start_price = df_range.iloc[0]['Close']
        end_price = df_range.iloc[-1]['Close']
        
        benchmark_return = ((end_price / start_price) - 1) * 100
        
        logger.info(f"TOPIX return ({start_date} to {end_date}): {benchmark_return:+.2f}%")
        
        return benchmark_return


def update_benchmarks(client: JQuantsV2Client, data_root: str = './data') -> dict:
    """
    Convenience function to update all benchmark indices.
    
    Args:
        client: J-Quants API client
        data_root: Data root directory
        
    Returns:
        Dictionary with update status
    """
    manager = BenchmarkManager(client, data_root)
    
    result = {
        'success': False,
        'topix_records': 0,
        'error': None
    }
    
    try:
        df_topix = manager.fetch_and_update_topix()
        result['success'] = not df_topix.empty
        result['topix_records'] = len(df_topix)
        
        if df_topix.empty:
            result['error'] = "No TOPIX data fetched"
        
    except Exception as e:
        logger.error(f"Benchmark update failed: {e}")
        result['error'] = str(e)
    
    return result
