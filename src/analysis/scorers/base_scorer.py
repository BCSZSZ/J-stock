"""
Base abstract class for stock scoring strategies.
All scoring strategies must inherit from BaseScorer and implement the abstract methods.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ScoreResult:
    ticker: str
    total_score: float
    signal_strength: str  # "STRONG_BUY", "BUY", "NEUTRAL", "SELL"
    breakdown: Dict[str, float]
    risk_flags: List[str]
    strategy_name: str = "Unknown"


class BaseScorer(ABC):
    """
    Abstract base class for stock scoring strategies.
    Extend this to create new scoring strategies for backtesting.
    """
    
    def __init__(self, strategy_name: str = "Base"):
        self.strategy_name = strategy_name
        self.weights = self._get_weights()
    
    @abstractmethod
    def _get_weights(self) -> Dict[str, float]:
        """Return the component weights for this strategy."""
        pass
    
    @abstractmethod
    def _calc_technical_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        """Calculate technical analysis score (0-100)."""
        pass
    
    @abstractmethod
    def _calc_institutional_score(self, df_trades: pd.DataFrame, current_date: pd.Timestamp) -> float:
        """Calculate institutional flow score (0-100)."""
        pass
    
    @abstractmethod
    def _calc_fundamental_score(self, df_fins: pd.DataFrame) -> float:
        """Calculate fundamental analysis score (0-100)."""
        pass
    
    @abstractmethod
    def _calc_volatility_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        """Calculate volatility/risk score (0-100)."""
        pass
    
    def evaluate(self, 
                 ticker: str,
                 df_features: pd.DataFrame, 
                 df_trades: pd.DataFrame, 
                 df_financials: pd.DataFrame,
                 metadata: dict) -> ScoreResult:
        """
        Main entry point to calculate the score for a single ticker.
        This orchestration logic is shared across all strategies.
        """
        # 1. Sanity Check
        if df_features.empty:
            return self._empty_result(ticker, "No Price Data")

        # Get latest data points
        latest_row = df_features.iloc[-1]
        # Use index as date (engine sets Date as index)
        current_date = df_features.index[-1]
        if not isinstance(current_date, pd.Timestamp):
            current_date = pd.to_datetime(current_date)

        # --- A. Technical Scoring (0-100) ---
        tech_score = self._calc_technical_score(latest_row, df_features)

        # --- B. Institutional Flow Scoring (0-100) ---
        inst_score = self._calc_institutional_score(df_trades, current_date)

        # --- C. Fundamental Scoring (0-100) ---
        fund_score = self._calc_fundamental_score(df_financials)

        # --- D. Volatility/Risk Scoring (0-100) ---
        vol_score = self._calc_volatility_score(latest_row, df_features)

        # --- E. Risk Checks ---
        risk_flags = []
        earnings_penalty = self._check_earnings_risk(metadata, current_date, risk_flags)

        # --- Final Calculation ---
        total_score = (
            tech_score * self.weights["technical"] +
            inst_score * self.weights["institutional"] +
            fund_score * self.weights["fundamental"] +
            vol_score * self.weights["volatility"]
        )
        
        # Apply earnings penalty
        total_score *= earnings_penalty

        signal = self._interpret_score(total_score, risk_flags)

        return ScoreResult(
            ticker=ticker,
            total_score=round(total_score, 2),
            signal_strength=signal,
            breakdown={
                "Technical": round(tech_score, 1),
                "Institutional": round(inst_score, 1),
                "Fundamental": round(fund_score, 1),
                "Volatility": round(vol_score, 1)
            },
            risk_flags=risk_flags,
            strategy_name=self.strategy_name
        )
    
    def _check_earnings_risk(self, metadata: dict, current_date: pd.Timestamp, risk_flags: List[str]) -> float:
        """
        Check earnings proximity and return penalty multiplier (0.0-1.0).
        Subclasses can override for different risk handling.
        """
        if not metadata or 'earnings_calendar' not in metadata:
            return 1.0
            
        for event in metadata['earnings_calendar']:
            try:
                evt_date = pd.to_datetime(event['Date'])
                delta = (evt_date - current_date).days
                if 0 <= delta <= 7:
                    risk_flags.append("EARNINGS_APPROACHING")
                    return 0.7  # Default 30% penalty
            except:
                continue
        return 1.0
    
    def _interpret_score(self, score: float, risk_flags: List[str]) -> str:
        """Interpret numerical score into trading signal."""
        if "EARNINGS_APPROACHING" in risk_flags and score < 75:
            return "HOLD/WAIT"
            
        if score >= 80:
            return "STRONG_BUY"
        elif score >= 65:
            return "BUY"
        elif score <= 35:
            return "STRONG_SELL"
        elif score <= 45:
            return "SELL"
        else:
            return "NEUTRAL"
    
    def _empty_result(self, ticker: str, reason: str) -> ScoreResult:
        return ScoreResult(
            ticker=ticker,
            total_score=0.0,
            signal_strength="ERROR",
            breakdown={},
            risk_flags=[reason],
            strategy_name=self.strategy_name
        )
