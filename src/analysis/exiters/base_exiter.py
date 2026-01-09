"""
Base abstract class for exit strategies.
All exit strategies must inherit from BaseExiter and implement the abstract methods.
"""
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class Position:
    """
    Represents a current holding that needs exit evaluation.
    """
    ticker: str
    entry_price: float
    entry_date: pd.Timestamp
    entry_score: float
    quantity: int
    peak_price_since_entry: Optional[float] = None  # Track highest price since entry


@dataclass
class ExitSignal:
    """
    Result of exit evaluation - what action to take.
    """
    ticker: str
    action: str  # "HOLD", "SELL_25%", "SELL_50%", "SELL_75%", "SELL_100%"
    urgency: str  # "LOW", "MEDIUM", "HIGH", "EMERGENCY"
    reason: str
    triggered_by: str  # Which layer/rule triggered
    current_price: float
    current_score: float
    entry_price: float
    entry_score: float
    profit_loss_pct: float
    holding_days: int
    
    def __str__(self):
        return (f"{self.ticker}: {self.action} ({self.urgency}) - {self.reason}\n"
                f"  P&L: {self.profit_loss_pct:+.1f}% | Days: {self.holding_days} | "
                f"Score: {self.entry_score:.0f}→{self.current_score:.0f}")


class BaseExiter(ABC):
    """
    Abstract base class for exit strategies.
    Each strategy implements different logic for when to exit positions.
    """
    
    def __init__(self, strategy_name: str = "Base"):
        self.strategy_name = strategy_name
    
    @abstractmethod
    def evaluate_exit(self,
                     position: Position,
                     df_features: pd.DataFrame,
                     df_trades: pd.DataFrame,
                     df_financials: pd.DataFrame,
                     metadata: dict,
                     current_score: float) -> ExitSignal:
        """
        Main entry point to evaluate whether to exit a position.
        
        Args:
            position: Current position details (entry price, date, score, etc.)
            df_features: Technical indicators dataframe
            df_trades: Institutional flows dataframe
            df_financials: Fundamental data dataframe
            metadata: Earnings calendar and other metadata
            current_score: Latest score from scorer (for strategies that use it)
        
        Returns:
            ExitSignal with action and reasoning
        """
        pass
    
    def _get_latest_data(self, df_features: pd.DataFrame) -> pd.Series:
        """Helper: Get latest row from features dataframe."""
        if df_features.empty:
            raise ValueError("Features dataframe is empty")
        return df_features.iloc[-1]
    
    def _calculate_pnl(self, entry_price: float, current_price: float) -> float:
        """Helper: Calculate profit/loss percentage."""
        return ((current_price - entry_price) / entry_price) * 100
    
    def _get_holding_days(self, entry_date: pd.Timestamp, current_date: pd.Timestamp) -> int:
        """Helper: Calculate number of days held."""
        return (current_date - entry_date).days
    
    def _create_signal(self,
                      position: Position,
                      current_price: float,
                      current_score: float,
                      current_date: pd.Timestamp,
                      action: str,
                      urgency: str,
                      reason: str,
                      triggered_by: str) -> ExitSignal:
        """Helper: Create ExitSignal with common calculations."""
        pnl = self._calculate_pnl(position.entry_price, current_price)
        holding_days = self._get_holding_days(position.entry_date, current_date)
        
        return ExitSignal(
            ticker=position.ticker,
            action=action,
            urgency=urgency,
            reason=reason,
            triggered_by=triggered_by,
            current_price=current_price,
            current_score=current_score,
            entry_price=position.entry_price,
            entry_score=position.entry_score,
            profit_loss_pct=pnl,
            holding_days=holding_days
        )
