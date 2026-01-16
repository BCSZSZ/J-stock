"""
J-Stock Universe Selector
Screens the entire Japanese stock market to identify top trading candidates.

Design Philosophy:
1. Hard Filters: Remove unsuitable stocks (penny stocks, illiquid, extreme volatility)
2. Normalization: Convert metrics to comparable 0-1 scales via percentile ranking
3. Weighted Scoring: Combine normalized features with domain weights
4. Top N Selection: Extract highest-scoring candidates

Data Flow:
    JQuants API -> StockDataManager -> Feature Calculation -> Filtering -> Ranking -> Top 50
"""
import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from src.client.jquants_client import JQuantsV2Client
from src.data.stock_data_manager import StockDataManager

logger = logging.getLogger(__name__)


class UniverseSelector:
    """
    Universe selection engine for Japanese stocks.
    
    Selection Criteria:
        - Hard Filters: Price > 100 JPY, Liquidity > 500M JPY, 1.5% < ATR Ratio < 5%
        - Scoring Weights: Volatility 40%, Liquidity 30%, Trend 30%
        - Output: Top 50 stocks with highest composite scores
    """
    
    # ==================== CONFIGURATION ====================
    
    # Hard Filter Thresholds
    MIN_PRICE = 100  # JPY
    MIN_LIQUIDITY = 500_000_000  # 500M JPY (median turnover over 20 days)
    MIN_ATR_RATIO = 0.015  # 1.5%
    MAX_ATR_RATIO = 0.050  # 5.0%
    
    # Scoring Weights
    WEIGHT_VOLATILITY = 0.4
    WEIGHT_LIQUIDITY = 0.3
    WEIGHT_TREND = 0.3
    
    # Data Requirements
    MIN_HISTORY_DAYS = 250  # Need at least 250 days for MA200
    LOOKBACK_DAYS = 250
    
    def __init__(self, data_manager: StockDataManager):
        """
        Initialize the Universe Selector.
        
        Args:
            data_manager: StockDataManager instance with API access.
        """
        self.data_manager = data_manager
        self.client = data_manager.client
        
        if not self.client:
            raise ValueError("StockDataManager must have API access (api_key required)")
        
        logger.info("UniverseSelector initialized")
    
    # ==================== MAIN PIPELINE ====================
    
    def run_selection(
        self, 
        top_n: int = 50,
        test_mode: bool = False,
        test_limit: int = 10,
        ticker_list: Optional[List[str]] = None,
        apply_filters: bool = True,
        return_full: bool = False,
        no_fetch: bool = False
    ) -> pd.DataFrame:
        """
        Execute the full selection pipeline.
        
        Args:
            top_n: Number of top stocks to select.
            test_mode: If True, only process first N stocks for testing.
            test_limit: Number of stocks to process in test mode.
            ticker_list: Optional list of ticker codes (bypasses API fetch).
            no_fetch: If True, skip data fetching and use local data only.
            
        Returns:
            DataFrame with raw metrics (normalization done globally in main.py).
            If return_full=True, returns a tuple (df_top, df_scored).
        """
        logger.info("="*60)
        logger.info("J-Stock Universe Selection - Starting Pipeline")
        logger.info("="*60)
        
        # Step 1: Fetch universe data
        df_universe = self.fetch_universe_data(
            test_mode=test_mode, 
            test_limit=test_limit,
            ticker_list=ticker_list,
            no_fetch=no_fetch
        )
        
        if df_universe.empty:
            logger.error("No data fetched from universe. Aborting.")
            return pd.DataFrame()
        
        logger.info(f"Universe size: {len(df_universe)} stocks")
        
        # Step 2: Apply hard filters (optional)
        if apply_filters:
            df_filtered = self.apply_hard_filters(df_universe)
            logger.info(f"After hard filters: {len(df_filtered)} stocks remain")
        else:
            df_filtered = df_universe.copy()
            logger.info(f"Filters disabled. Using all {len(df_filtered)} stocks for scoring")
        
        # Note: Normalization and scoring moved to main.py for global ranking
        # This function now returns raw metrics only
        df_scored = df_filtered.copy()
        
        logger.info("="*60)
        logger.info(f"Feature extraction complete: {len(df_scored)} stocks processed")
        logger.info("="*60)
        
        # Return all scored data for global normalization in main.py
        if return_full:
            return pd.DataFrame(), df_scored  # Empty df_top, full df_scored
        return df_scored
    
    # ==================== DATA FETCHING ====================
    
    def fetch_universe_data(
        self, 
        test_mode: bool = False,
        test_limit: int = 10,
        ticker_list: Optional[List[str]] = None,
        no_fetch: bool = False
    ) -> pd.DataFrame:
        """
        Fetch all listed stocks and their required features.
        
        Args:
            test_mode: If True, only process first N stocks.
            test_limit: Number of stocks in test mode.
            ticker_list: Optional list of ticker codes to process (bypasses API fetch).
            no_fetch: If True, skip API calls and use local data only.
            
        Returns:
            DataFrame with columns: Code, CompanyName, Close, MedianTurnover,
                                   ATR_Ratio, TrendStrength
        """
        logger.info("Step 1: Fetching universe data from J-Quants API...")
        
        # Option 1: Use provided ticker list (for testing or manual universe)
        if ticker_list:
            logger.info(f"Using provided ticker list: {len(ticker_list)} stocks")
            df_listed = pd.DataFrame([
                {'Code': code.zfill(4), 'CompanyName': f'Stock_{code}'}
                for code in ticker_list
            ])
        else:
            # Option 2: Fetch from API
            listed_stocks = self.client.get_listed_info()
            
            if not listed_stocks:
                logger.error("Failed to fetch listed stocks info")
                logger.warning("TIP: For testing, you can provide ticker_list parameter")
                return pd.DataFrame()
            
            logger.info(f"Total listed issues: {len(listed_stocks)}")
            
            # Filter out ETFs, REITs, and preferred shares
            df_listed = pd.DataFrame(listed_stocks)
            df_listed = self._filter_equity_only(df_listed)
            
            logger.info(f"After filtering ETFs/REITs: {len(df_listed)} stocks")
        
        # Test mode: limit stocks
        if test_mode:
            logger.warning(f"⚠️  TEST MODE: Processing only first {test_limit} stocks")
            df_listed = df_listed.head(test_limit)
        
        # Extract features for each stock
        results = []
        total = len(df_listed)
        
        for idx, row in df_listed.iterrows():
            code = str(row.get('Code', '')).zfill(4)
            name = row.get('CompanyName', 'Unknown')
            
            logger.info(f"[{idx+1}/{total}] Processing {code} - {name}")
            
            try:
                features = self._extract_stock_features(code, name, no_fetch=no_fetch)
                if features:
                    results.append(features)
            except Exception as e:
                logger.error(f"Failed to process {code}: {e}")
                continue
        
        df_universe = pd.DataFrame(results)
        logger.info(f"Successfully extracted features for {len(df_universe)} stocks")
        
        # Save snapshot
        self._save_universe_snapshot(df_universe)
        
        return df_universe
    
    def _filter_equity_only(self, df_listed: pd.DataFrame) -> pd.DataFrame:
        """
        Filter to keep only common stocks (exclude ETFs, REITs, preferred shares).
        
        Args:
            df_listed: DataFrame from get_listed_info().
            
        Returns:
            Filtered DataFrame with only equity stocks.
        """
        # Remove ETFs (usually have specific market codes)
        # Remove REITs (ScaleCategory might indicate)
        # Remove preferred shares (Code usually ends in specific patterns)
        
        df_filtered = df_listed.copy()
        
        # Filter by ScaleCategory if available
        if 'ScaleCategory' in df_filtered.columns:
            # Keep only standard categories (exclude REITs/ETFs)
            valid_categories = ['TOPIX Core30', 'TOPIX Large70', 'TOPIX Mid400', 
                               'TOPIX Small1', 'TOPIX Small2', 'Others']
            df_filtered = df_filtered[
                df_filtered['ScaleCategory'].fillna('Others').isin(valid_categories)
            ]
        
        # Filter by MarketCode if available (exclude specific market segments)
        if 'MarketCode' in df_filtered.columns:
            # Typically exclude market codes for ETFs/REITs
            # Keep Prime, Standard, Growth
            valid_markets = ['0111', '0113', '0114']  # Common equity market codes
            # If market codes are different, this needs adjustment
            # For now, we'll be permissive
            pass
        
        return df_filtered
    
    def _extract_stock_features(self, code: str, name: str, no_fetch: bool = False) -> Optional[Dict]:
        """
        Extract required features for a single stock.
        
        Args:
            code: Stock code (4 digits).
            name: Company name.
            no_fetch: If True, skip API fetch and only use local data.
            
        Returns:
            Dict with extracted features, or None if insufficient data.
        """
        # Fetch/update OHLC data (skip if no_fetch mode)
        if no_fetch:
            # Load existing features only
            df_features = self.data_manager.load_stock_features(code)
            if df_features.empty or len(df_features) < self.MIN_HISTORY_DAYS:
                logger.warning(f"[{code}] No local data available (use without --no-fetch first)")
                return None
        else:
            df_prices, updated = self.data_manager.fetch_and_update_ohlc(code)
            
            if df_prices.empty or len(df_prices) < self.MIN_HISTORY_DAYS:
                logger.warning(f"[{code}] Insufficient price data ({len(df_prices)} days)")
                return None
            
            # Compute features (ATR, EMA, etc.)
            df_features = self.data_manager.compute_features(code)
        
        if df_features.empty:
            logger.warning(f"[{code}] Failed to compute features")
            return None
        
        # Get latest row
        latest = df_features.iloc[-1]
        
        # Calculate custom metrics
        # 1. MedianTurnover (Trading Value over last 20 days)
        df_recent = df_features.tail(20).copy()  # .copy() to avoid SettingWithCopyWarning
        df_recent['TradingValue'] = df_recent['Close'] * df_recent['Volume']
        median_turnover = df_recent['TradingValue'].median()
        
        # 2. ATR Ratio
        atr = latest.get('ATR', np.nan)
        close = latest.get('Close', np.nan)
        atr_ratio = atr / close if (close > 0 and not np.isnan(atr)) else np.nan
        
        # 3. Trend Strength (relative to MA200)
        # Use EMA_200 as proxy for MA200
        ema_200 = latest.get('EMA_200', np.nan)
        trend_strength = (close - ema_200) / ema_200 if (ema_200 > 0 and not np.isnan(ema_200)) else np.nan
        
        # 4. Momentum_20d (20-day return)
        if len(df_features) >= 21:
            price_20d_ago = df_features.iloc[-21]['Close']
            momentum_20d = (close - price_20d_ago) / price_20d_ago if price_20d_ago > 0 else np.nan
        else:
            momentum_20d = np.nan
        
        # 5. Volume_Surge (recent 20d vs baseline 100d volume ratio)
        if len(df_features) >= 120:
            vol_recent = df_features.tail(20)['Volume'].mean()
            vol_baseline = df_features.iloc[-120:-20]['Volume'].mean()
            volume_surge = vol_recent / vol_baseline if vol_baseline > 0 else np.nan
        else:
            volume_surge = np.nan
        
        # Validate all required fields
        if any(np.isnan([close, median_turnover, atr_ratio, trend_strength, momentum_20d, volume_surge])):
            logger.warning(f"[{code}] Missing required metrics")
            return None
        
        return {
            'Code': code,
            'CompanyName': name,
            'Close': close,
            'MedianTurnover': median_turnover,
            'ATR': atr,
            'ATR_Ratio': atr_ratio,
            'EMA_200': ema_200,
            'TrendStrength': trend_strength,
            'Momentum_20d': momentum_20d,
            'Volume_Surge': volume_surge,
            'DataDate': latest.get('Date')
        }
    
    # ==================== FILTERING & SCORING ====================
    
    def apply_hard_filters(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Phase 1: Apply hard filters to remove unsuitable stocks.
        
        Filters:
            1. Minimum Price > 100 JPY
            2. Median Turnover > 500M JPY
            3. ATR Ratio within 1.5% - 5.0%
            
        Args:
            df: Universe DataFrame.
            
        Returns:
            Filtered DataFrame.
        """
        logger.info("Phase 1: Applying hard filters...")
        
        initial_count = len(df)
        
        # Filter 1: Minimum Price
        mask_price = df['Close'] > self.MIN_PRICE
        filtered_price = df[mask_price].copy()
        logger.info(f"  - Price filter (>{self.MIN_PRICE} JPY): "
                   f"{len(filtered_price)}/{initial_count} remain")
        
        # Filter 2: Liquidity
        mask_liquidity = filtered_price['MedianTurnover'] > self.MIN_LIQUIDITY
        filtered_liq = filtered_price[mask_liquidity].copy()
        logger.info(f"  - Liquidity filter (>{self.MIN_LIQUIDITY/1e6:.0f}M JPY): "
                   f"{len(filtered_liq)}/{len(filtered_price)} remain")
        
        # Filter 3: Volatility Range
        mask_vol_low = filtered_liq['ATR_Ratio'] > self.MIN_ATR_RATIO
        mask_vol_high = filtered_liq['ATR_Ratio'] < self.MAX_ATR_RATIO
        filtered_vol = filtered_liq[mask_vol_low & mask_vol_high].copy()
        logger.info(f"  - Volatility filter ({self.MIN_ATR_RATIO*100:.1f}% - {self.MAX_ATR_RATIO*100:.1f}%): "
                   f"{len(filtered_vol)}/{len(filtered_liq)} remain")
        
        return filtered_vol
    
    def normalize_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Phase 2: Normalize features using percentile ranking.
        
        Converts raw metrics to 0-1 scale via rank(pct=True).
        
        Args:
            df: Filtered DataFrame.
            
        Returns:
            DataFrame with Rank_Vol, Rank_Liq, Rank_Trend columns.
        """
        logger.info("Phase 2: Normalizing features via percentile ranking...")
        
        df_norm = df.copy()
        
        # Rank_Vol: Higher ATR Ratio = Higher Score (within safe range)
        df_norm['Rank_Vol'] = df_norm['ATR_Ratio'].rank(pct=True, ascending=True)
        
        # Rank_Liq: Higher Liquidity = Higher Score
        df_norm['Rank_Liq'] = df_norm['MedianTurnover'].rank(pct=True, ascending=True)
        
        # Rank_Trend: Higher Trend Strength = Higher Score
        df_norm['Rank_Trend'] = df_norm['TrendStrength'].rank(pct=True, ascending=True)
        
        logger.info(f"  - Normalized {len(df_norm)} stocks")
        
        return df_norm
    
    def calculate_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Phase 3: Calculate weighted composite scores.
        
        Formula:
            TotalScore = 0.4 × Rank_Vol + 0.3 × Rank_Liq + 0.3 × Rank_Trend
            
        Args:
            df: Normalized DataFrame.
            
        Returns:
            DataFrame with TotalScore column.
        """
        logger.info("Phase 3: Calculating weighted scores...")
        
        df_scored = df.copy()
        
        df_scored['TotalScore'] = (
            self.WEIGHT_VOLATILITY * df_scored['Rank_Vol'] +
            self.WEIGHT_LIQUIDITY * df_scored['Rank_Liq'] +
            self.WEIGHT_TREND * df_scored['Rank_Trend']
        )
        
        logger.info(f"  - Score range: {df_scored['TotalScore'].min():.3f} - {df_scored['TotalScore'].max():.3f}")
        
        return df_scored
    
    def select_top_n(self, df: pd.DataFrame, n: int = 50) -> pd.DataFrame:
        """
        Phase 4: Select top N stocks by TotalScore.
        
        Args:
            df: Scored DataFrame.
            n: Number of top stocks to select.
            
        Returns:
            DataFrame with top N stocks, sorted by TotalScore descending.
        """
        logger.info(f"Phase 4: Selecting top {n} stocks...")
        
        df_top = df.nlargest(n, 'TotalScore').copy()
        
        # Add rank column
        df_top['Rank'] = range(1, len(df_top) + 1)
        
        return df_top
    
    # ==================== OUTPUT & PERSISTENCE ====================
    
    def _save_universe_snapshot(self, df: pd.DataFrame) -> None:
        """Save full universe snapshot for analysis."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        snapshot_path = Path('data/universe') / f'universe_snapshot_{timestamp}.parquet'
        
        df.to_parquet(snapshot_path, index=False)
        logger.info(f"Universe snapshot saved: {snapshot_path}")
    
    def save_selection_results(
        self, 
        df_top: pd.DataFrame,
        format: str = 'both'
    ) -> Tuple[Optional[Path], Optional[Path]]:
        """
        Save selection results in multiple formats.
        
        Args:
            df_top: Top N selected stocks.
            format: 'json', 'csv', or 'both'.
            
        Returns:
            Tuple of (json_path, csv_path).
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_path = Path('data/universe')
        
        json_path = None
        csv_path = None
        
        # JSON format (monitor_list compatible)
        if format in ['json', 'both']:
            json_path = base_path / f'top50_selection_{timestamp}.json'
            
            # Convert to monitor_list.json format
            tickers_list = []
            for _, row in df_top.iterrows():
                ticker_data = {
                    'code': row['Code'],
                    'name': row['CompanyName'],
                    'rank': int(row['Rank']),
                    'total_score': float(row['TotalScore']),
                    'rank_vol': float(row['Rank_Vol']),
                    'rank_liq': float(row['Rank_Liq']),
                    'rank_trend': float(row['Rank_Trend']),
                    'atr_ratio': float(row['ATR_Ratio']),
                    'median_turnover': float(row['MedianTurnover']),
                    'trend_strength': float(row['TrendStrength']),
                    'close_price': float(row['Close']),
                    'selected_date': datetime.now().strftime('%Y-%m-%d')
                }
                
                # Add new metrics if available
                if 'Rank_Momentum' in row:
                    ticker_data['rank_momentum'] = float(row['Rank_Momentum'])
                    ticker_data['momentum_20d'] = float(row['Momentum_20d'])
                if 'Rank_VolSurge' in row:
                    ticker_data['rank_volsurge'] = float(row['Rank_VolSurge'])
                    ticker_data['volume_surge'] = float(row['Volume_Surge'])
                    
                tickers_list.append(ticker_data)
            
            output = {
                'version': '2.0',
                'selection_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'description': 'Top 50 stocks selected by Universe Selector (5-dimension scoring)',
                'selection_criteria': {
                    'min_price': self.MIN_PRICE,
                    'min_liquidity': self.MIN_LIQUIDITY,
                    'atr_ratio_range': [self.MIN_ATR_RATIO, self.MAX_ATR_RATIO],
                    'weights': {
                        'volatility': 0.25,
                        'liquidity': 0.25,
                        'trend': 0.20,
                        'momentum': 0.20,
                        'volume_surge': 0.10
                    }
                },
                'tickers': tickers_list
            }
            
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
            
            logger.info(f"JSON results saved: {json_path}")
        
        # CSV format (for analysis)
        if format in ['csv', 'both']:
            csv_path = base_path / f'top50_selection_{timestamp}.csv'
            
            # Select key columns (include new metrics if available)
            output_columns = [
                'Rank', 'Code', 'CompanyName', 'TotalScore',
                'Rank_Vol', 'Rank_Liq', 'Rank_Trend',
                'Close', 'ATR_Ratio', 'MedianTurnover', 'TrendStrength'
            ]
            
            # Add new columns if they exist
            if 'Rank_Momentum' in df_top.columns:
                output_columns.extend(['Rank_Momentum', 'Momentum_20d'])
            if 'Rank_VolSurge' in df_top.columns:
                output_columns.extend(['Rank_VolSurge', 'Volume_Surge'])
            
            df_top[output_columns].to_csv(csv_path, index=False, encoding='utf-8-sig')
            logger.info(f"CSV results saved: {csv_path}")
        
        return json_path, csv_path

    def save_scores_txt(
        self,
        df_scored: pd.DataFrame,
        df_top: pd.DataFrame,
        top_n: int = 50
    ) -> Path:
        """
        Save a comprehensive TXT summary with all stock scores and TOP N.

        Args:
            df_scored: Scored DataFrame for all processed stocks.
            df_top: Top N selection DataFrame.
            top_n: Number of top stocks to include in summary.

        Returns:
            Path to the saved TXT file.
        """
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        txt_path = Path('data/universe') / f'universe_summary_{timestamp}.txt'

        # Ensure sort by TotalScore desc for full list
        df_all_sorted = df_scored.sort_values('TotalScore', ascending=False).copy()

        lines = []
        lines.append("="*80)
        lines.append("J-Stock Universe Selection - Full Score Summary")
        lines.append("="*80)
        lines.append("")
        lines.append(f"Processed stocks: {len(df_scored)}")
        lines.append(f"Selected top {top_n} stocks")
        lines.append("")
        lines.append("All stocks (sorted by TotalScore):")
        lines.append("Rank,Code,CompanyName,TotalScore,Rank_Vol,Rank_Liq,Rank_Trend,Close,ATR_Ratio,MedianTurnover,TrendStrength")
        for i, row in enumerate(df_all_sorted.itertuples(index=False), 1):
            lines.append(
                f"{i},{row.Code},{row.CompanyName},{row.TotalScore:.4f},{getattr(row,'Rank_Vol',float('nan')):.4f},{getattr(row,'Rank_Liq',float('nan')):.4f},{getattr(row,'Rank_Trend',float('nan')):.4f},{row.Close:.2f},{row.ATR_Ratio:.6f},{row.MedianTurnover:.0f},{row.TrendStrength:.6f}"
            )

        lines.append("")
        lines.append("-"*80)
        lines.append(f"TOP {min(top_n, len(df_top))}:")
        lines.append("Rank,Code,CompanyName,TotalScore")
        for row in df_top.sort_values('Rank').itertuples(index=False):
            lines.append(f"{int(row.Rank)},{row.Code},{row.CompanyName},{row.TotalScore:.4f}")

        txt_path.parent.mkdir(parents=True, exist_ok=True)
        txt_path.write_text("\n".join(lines), encoding='utf-8')
        logger.info(f"TXT summary saved: {txt_path}")
        return txt_path
    
    def print_summary(self, df_top: pd.DataFrame, n: int = 10) -> None:
        """
        Print summary of top selections.
        
        Args:
            df_top: Top N selected stocks.
            n: Number of rows to display.
        """
        print("\n" + "="*80)
        print(f"TOP {len(df_top)} UNIVERSE SELECTION RESULTS")
        print("="*80)
        
        display_cols = [
            'Rank', 'Code', 'CompanyName', 'TotalScore',
            'Rank_Vol', 'Rank_Liq', 'Rank_Trend'
        ]
        
        print("\nTop {} stocks:".format(min(n, len(df_top))))
        print(df_top[display_cols].head(n).to_string(index=False))
        
        print("\n" + "-"*80)
        print("Score Statistics:")
        print(f"  Mean Score: {df_top['TotalScore'].mean():.4f}")
        print(f"  Std Dev:    {df_top['TotalScore'].std():.4f}")
        print(f"  Min Score:  {df_top['TotalScore'].min():.4f}")
        print(f"  Max Score:  {df_top['TotalScore'].max():.4f}")
        print("="*80 + "\n")
