"""
Batch Processing Pipeline for J-Stock-Analyzer
Handles concurrent processing of multiple stock tickers with progress tracking.
"""
import logging
from typing import List, Dict, Any
from tqdm import tqdm
from pathlib import Path
import json
from datetime import datetime

from src.data.stock_data_manager import StockDataManager

logger = logging.getLogger(__name__)


class StockETLPipeline:
    """
    Batch processor for running ETL on multiple stocks.
    Features: Progress bar, error handling, summary reports.
    """
    
    def __init__(self, api_key: str, data_root: str = './data'):
        """
        Initialize the pipeline.
        
        Args:
            api_key: J-Quants API key.
            data_root: Root directory for data lake.
        """
        self.manager = StockDataManager(api_key, data_root)
        self.results: List[Dict[str, Any]] = []
        logger.info("ETL Pipeline initialized")
    
    def run_batch(self, tickers: List[str], fetch_aux_data: bool = True) -> Dict[str, Any]:
        """
        Run ETL pipeline for a batch of tickers.
        
        Args:
            tickers: List of stock codes (e.g., ['6758', '7203']).
            fetch_aux_data: Whether to fetch financial/trading data.
            
        Returns:
            Summary dictionary with success/failure counts.
        """
        logger.info(f"Starting batch ETL for {len(tickers)} tickers")
        
        self.results = []
        successful = 0
        failed = 0
        
        # Process with progress bar
        for code in tqdm(tickers, desc="Processing stocks", unit="stock"):
            try:
                if fetch_aux_data:
                    result = self.manager.run_full_etl(code)
                else:
                    # Just OHLC and features
                    result = self._run_basic_etl(code)
                
                self.results.append(result)
                
                if result['success']:
                    successful += 1
                else:
                    failed += 1
                    logger.error(f"[{code}] ETL failed: {result.get('errors', [])}")
                    
            except Exception as e:
                failed += 1
                error_result = {
                    'code': code,
                    'success': False,
                    'errors': [f"Pipeline exception: {str(e)}"]
                }
                self.results.append(error_result)
                logger.error(f"[{code}] Unexpected error: {e}", exc_info=True)
        
        # Generate summary
        summary = {
            'total': len(tickers),
            'successful': successful,
            'failed': failed,
            'success_rate': (successful / len(tickers) * 100) if tickers else 0,
            'timestamp': datetime.now().isoformat(),
            'results': self.results
        }
        
        # Save summary report
        self._save_summary(summary)
        
        logger.info(f"Batch complete: {successful}/{len(tickers)} successful")
        return summary
    
    def _run_basic_etl(self, code: str) -> Dict[str, Any]:
        """
        Run basic ETL (OHLC + Features only).
        
        Args:
            code: Stock code.
            
        Returns:
            Result dictionary.
        """
        result = {
            'code': code,
            'success': False,
            'errors': []
        }
        
        try:
            df_prices = self.manager.fetch_and_update_ohlc(code)
            result['price_rows'] = len(df_prices)
            
            if df_prices.empty:
                result['errors'].append('No price data fetched')
                return result
            
            df_features = self.manager.compute_features(code)
            result['feature_cols'] = len(df_features.columns)
            result['success'] = True
            
        except Exception as e:
            logger.error(f"[{code}] Basic ETL failed: {e}")
            result['errors'].append(str(e))
        
        return result
    
    def _save_summary(self, summary: Dict[str, Any]) -> None:
        """
        Save pipeline summary to metadata folder.
        
        Args:
            summary: Summary dictionary.
        """
        reports_dir = self.manager.data_root / 'metadata' / 'reports'
        reports_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_path = reports_dir / f"etl_summary_{timestamp}.json"
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Summary saved to: {report_path}")
    
    def get_failed_tickers(self) -> List[str]:
        """
        Get list of tickers that failed processing.
        
        Returns:
            List of failed ticker codes.
        """
        return [r['code'] for r in self.results if not r['success']]
    
    def retry_failed(self) -> Dict[str, Any]:
        """
        Retry processing for failed tickers.
        
        Returns:
            Summary of retry attempt.
        """
        failed_tickers = self.get_failed_tickers()
        
        if not failed_tickers:
            logger.info("No failed tickers to retry")
            return {'total': 0, 'successful': 0, 'failed': 0}
        
        logger.info(f"Retrying {len(failed_tickers)} failed tickers")
        return self.run_batch(failed_tickers, fetch_aux_data=True)
    
    def print_summary(self) -> None:
        """Print a formatted summary to console."""
        if not self.results:
            print("No results available")
            return
        
        total = len(self.results)
        successful = sum(1 for r in self.results if r['success'])
        failed = total - successful
        
        print("\n" + "="*60)
        print("ETL Pipeline Summary")
        print("="*60)
        print(f"Total:      {total}")
        print(f"Successful: {successful} ({successful/total*100:.1f}%)")
        print(f"Failed:     {failed} ({failed/total*100:.1f}%)")
        
        if failed > 0:
            print("\nFailed Tickers:")
            for result in self.results:
                if not result['success']:
                    errors = ', '.join(result.get('errors', ['Unknown error']))
                    print(f"  - {result['code']}: {errors}")
        
        print("="*60 + "\n")


# ==================== CONVENIENCE FUNCTIONS ====================

def run_daily_update(api_key: str, tickers: List[str]) -> None:
    """
    Convenience function for daily batch updates (OHLC + Features only).
    
    Args:
        api_key: J-Quants API key.
        tickers: List of stock codes.
    """
    pipeline = StockETLPipeline(api_key)
    summary = pipeline.run_batch(tickers, fetch_aux_data=False)
    pipeline.print_summary()


def run_weekly_full_sync(api_key: str, tickers: List[str]) -> None:
    """
    Convenience function for weekly full sync (including financials/metadata).
    
    Args:
        api_key: J-Quants API key.
        tickers: List of stock codes.
    """
    pipeline = StockETLPipeline(api_key)
    summary = pipeline.run_batch(tickers, fetch_aux_data=True)
    pipeline.print_summary()
    
    # Retry failed ones
    if pipeline.get_failed_tickers():
        print("\nRetrying failed tickers...")
        pipeline.retry_failed()
        pipeline.print_summary()
