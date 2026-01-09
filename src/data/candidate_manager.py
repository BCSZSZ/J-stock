"""
Candidate Stock Manager
Handles random stock discovery, scoring, and promotion to monitor list.
"""
import json
import random
import logging
from pathlib import Path
from typing import List, Dict, Optional, Set
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import pandas as pd

from src.client.jquants_client import JQuantsV2Client
from src.data.stock_data_manager import StockDataManager
from src.analysis.scorers import EnhancedScorer

logger = logging.getLogger(__name__)


@dataclass
class CandidateResult:
    """Result of candidate evaluation."""
    code: str
    name: str
    sector: str
    market: str
    score: float
    rank: int
    status: str  # 'promoted', 'candidate', 'rejected'
    evaluated_date: str
    promoted_date: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


class CandidateManager:
    """
    Manages candidate stock discovery and promotion.
    
    Workflow:
    1. Randomly sample 10 stocks from TSE (avoid replication)
    2. Fetch 1-year data for each
    3. Score using EnhancedScorer
    4. Promote #1 to monitor list
    5. Track history to prevent re-sampling
    """
    
    # Data paths (separate from monitor data)
    CANDIDATE_DIR = Path("data/candidates")
    CANDIDATE_FEATURES_DIR = CANDIDATE_DIR / "features"
    CANDIDATE_TRADES_DIR = CANDIDATE_DIR / "trades"
    CANDIDATE_FINANCIALS_DIR = CANDIDATE_DIR / "financials"
    CANDIDATE_METADATA_DIR = CANDIDATE_DIR / "metadata"
    
    CANDIDATE_LIST_FILE = Path("data/candidate_list.json")
    SAMPLE_HISTORY_FILE = CANDIDATE_DIR / "sample_history.json"
    MONITOR_LIST_FILE = Path("data/monitor_list.json")
    
    # Filtering criteria
    ELIGIBLE_MARKETS = ["プライム", "スタンダード"]  # Prime, Standard (exclude Growth)
    MIN_MARKET_CAP = 10_000_000_000  # ¥10B minimum (rough proxy by sector)
    
    def __init__(self, api_key: str):
        """
        Initialize CandidateManager.
        
        Args:
            api_key: J-Quants API key.
        """
        self.client = JQuantsV2Client(api_key)
        # Separate data manager for candidates (uses data/candidates/ folder)
        self.data_manager = StockDataManager(api_key, data_root=str(self.CANDIDATE_DIR))
        self.scorer = EnhancedScorer()
        
        # Create directories (StockDataManager creates subdirs automatically)
        self.CANDIDATE_DIR.mkdir(exist_ok=True)
    
    def _load_sample_history(self) -> Set[str]:
        """Load previously sampled tickers to avoid replication."""
        if not self.SAMPLE_HISTORY_FILE.exists():
            return set()
        
        with open(self.SAMPLE_HISTORY_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return set(data.get('sampled_tickers', []))
    
    def _save_sample_history(self, sampled_tickers: Set[str]) -> None:
        """Save sample history."""
        data = {
            'last_updated': datetime.now().strftime('%Y-%m-%d'),
            'total_sampled': len(sampled_tickers),
            'sampled_tickers': sorted(list(sampled_tickers))
        }
        
        with open(self.SAMPLE_HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def _load_monitor_list(self) -> Set[str]:
        """Load current monitor list tickers."""
        if not self.MONITOR_LIST_FILE.exists():
            return set()
        
        with open(self.MONITOR_LIST_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return {ticker['code'] for ticker in data.get('tickers', [])}
    
    def get_eligible_stocks(self) -> List[Dict]:
        """
        Fetch all TSE stocks and filter by eligibility criteria.
        
        Returns:
            List of eligible stock records.
        """
        logger.info("Fetching all listed stocks from J-Quants API...")
        all_stocks = self.client.get_listed_info()
        
        logger.info(f"Total stocks fetched: {len(all_stocks)}")
        
        # Filter by market (Prime/Standard only)
        eligible = [
            stock for stock in all_stocks
            if stock.get('MarketCodeName') in self.ELIGIBLE_MARKETS
        ]
        
        logger.info(f"Eligible stocks after market filter: {len(eligible)}")
        return eligible
    
    def get_random_candidates(self, n: int = 10) -> List[str]:
        """
        Randomly sample n candidate tickers (no replication).
        
        Args:
            n: Number of candidates to sample.
            
        Returns:
            List of ticker codes.
        """
        # Load exclusion lists
        sampled_history = self._load_sample_history()
        monitor_list = self._load_monitor_list()
        exclude = sampled_history.union(monitor_list)
        
        logger.info(f"Exclusion list size: {len(exclude)} (history: {len(sampled_history)}, monitor: {len(monitor_list)})")
        
        # Get eligible stocks
        eligible_stocks = self.get_eligible_stocks()
        
        # Filter out already sampled/monitored
        available = [
            stock for stock in eligible_stocks
            if stock['Code'] not in exclude
        ]
        
        logger.info(f"Available for sampling: {len(available)}")
        
        if len(available) < n:
            logger.warning(f"Only {len(available)} stocks available, resetting sample history...")
            sampled_history.clear()
            self._save_sample_history(sampled_history)
            available = [
                stock for stock in eligible_stocks
                if stock['Code'] not in monitor_list
            ]
        
        # Random sample
        sampled = random.sample(available, min(n, len(available)))
        tickers = [stock['Code'] for stock in sampled]
        
        logger.info(f"Sampled {len(tickers)} candidates: {tickers}")
        
        # Update history
        sampled_history.update(tickers)
        self._save_sample_history(sampled_history)
        
        return tickers
    
    def score_candidates(self, tickers: List[str]) -> List[CandidateResult]:
        """
        Fetch 1-year data and score each candidate.
        
        Args:
            tickers: List of candidate ticker codes.
            
        Returns:
            List of CandidateResult sorted by score (descending).
        """
        results = []
        today = datetime.now()
        one_year_ago = today - timedelta(days=365)
        
        for ticker in tickers:
            try:
                logger.info(f"Processing candidate {ticker}...")
                
                # Fetch 1-year data (stored in candidates/ folder)
                # Use run_full_etl which handles OHLC, features, trades, financials, metadata
                self.data_manager.run_full_etl(ticker)
                
                # Load data for scoring
                features_path = self.CANDIDATE_DIR / 'features' / f"{ticker}_features.parquet"
                trades_path = self.CANDIDATE_DIR / 'raw_trades' / f"{ticker}_trades.parquet"
                financials_path = self.CANDIDATE_DIR / 'raw_financials' / f"{ticker}_financials.parquet"
                
                df_features = pd.read_parquet(features_path) if features_path.exists() else pd.DataFrame()
                df_trades = pd.read_parquet(trades_path) if trades_path.exists() else pd.DataFrame()
                df_financials = pd.read_parquet(financials_path) if financials_path.exists() else pd.DataFrame()
                
                # Load metadata for name/sector
                metadata_path = self.CANDIDATE_DIR / 'metadata' / f"{ticker}_metadata.json"
                with open(metadata_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                
                # Score
                score_result = self.scorer.evaluate(df_features, df_trades, df_financials, metadata)
                
                results.append(CandidateResult(
                    code=ticker,
                    name=metadata.get('company_name', 'Unknown'),
                    sector=metadata.get('sector_name', 'Unknown'),
                    market=metadata.get('market_name', 'Unknown'),
                    score=score_result.total_score,
                    rank=0,  # Will be set after sorting
                    status='candidate',
                    evaluated_date=today.strftime('%Y-%m-%d')
                ))
                
            except Exception as e:
                logger.error(f"Failed to process candidate {ticker}: {e}")
                continue
        
        # Sort by score and assign ranks
        results.sort(key=lambda x: x.score, reverse=True)
        for i, result in enumerate(results, start=1):
            result.rank = i
        
        return results
    
    def promote_winner(self, candidates: List[CandidateResult]) -> Optional[str]:
        """
        Promote #1 candidate to monitor list.
        
        Args:
            candidates: Sorted list of candidates.
            
        Returns:
            Code of promoted ticker (or None if empty).
        """
        if not candidates:
            logger.warning("No candidates to promote")
            return None
        
        winner = candidates[0]
        winner.status = 'promoted'
        winner.promoted_date = datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"Promoting {winner.code} ({winner.name}) with score {winner.score:.2f}")
        
        # Add to monitor list
        if self.MONITOR_LIST_FILE.exists():
            with open(self.MONITOR_LIST_FILE, 'r', encoding='utf-8') as f:
                monitor_data = json.load(f)
        else:
            monitor_data = {'version': '1.0', 'tickers': []}
        
        monitor_data['tickers'].append({
            'code': winner.code,
            'name': winner.name,
            'sector': winner.sector,
            'added_date': winner.promoted_date,
            'reason': f"Promoted from candidate pool (score: {winner.score:.2f}, rank: 1/{len(candidates)})"
        })
        
        monitor_data['last_updated'] = winner.promoted_date
        
        with open(self.MONITOR_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(monitor_data, f, indent=2, ensure_ascii=False)
        
        return winner.code
    
    def save_candidate_results(self, candidates: List[CandidateResult]) -> None:
        """
        Save candidate evaluation results.
        
        Args:
            candidates: List of evaluated candidates.
        """
        data = {
            'last_updated': datetime.now().strftime('%Y-%m-%d'),
            'batch_id': datetime.now().strftime('%Y%m%d_%H%M%S'),
            'total_candidates': len(candidates),
            'promoted_count': sum(1 for c in candidates if c.status == 'promoted'),
            'candidates': [c.to_dict() for c in candidates]
        }
        
        with open(self.CANDIDATE_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved candidate results to {self.CANDIDATE_LIST_FILE}")
    
    def run_discovery_cycle(self, n_candidates: int = 10) -> Optional[str]:
        """
        Run complete discovery cycle: sample → score → promote.
        
        Args:
            n_candidates: Number of candidates to evaluate.
            
        Returns:
            Code of promoted ticker.
        """
        logger.info(f"Starting discovery cycle with {n_candidates} candidates...")
        
        # Step 1: Random sample
        tickers = self.get_random_candidates(n_candidates)
        
        # Step 2: Score
        candidates = self.score_candidates(tickers)
        
        # Step 3: Promote winner
        promoted = self.promote_winner(candidates)
        
        # Step 4: Save results
        self.save_candidate_results(candidates)
        
        logger.info(f"Discovery cycle complete. Promoted: {promoted}")
        return promoted
