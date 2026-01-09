"""
Backtest Metrics Calculation
Functions for computing performance metrics.
"""
import numpy as np
import pandas as pd
from typing import List
from src.backtest.models import Trade


def calculate_sharpe_ratio(
    returns: List[float], 
    risk_free_rate: float = 0.001,  # Japan 10Y bond ~0.1%
    periods_per_year: int = 252
) -> float:
    """
    Calculate Sharpe ratio from list of trade returns.
    
    Args:
        returns: List of return percentages (e.g., [5.2, -3.1, 8.7])
        risk_free_rate: Annual risk-free rate (default 0.1% for Japan)
        periods_per_year: Trading days per year
        
    Returns:
        Sharpe ratio (higher is better, >1.0 is good)
    """
    if not returns or len(returns) < 2:
        return 0.0
    
    returns_array = np.array(returns) / 100  # Convert to decimal
    excess_returns = returns_array - (risk_free_rate / periods_per_year)
    
    if np.std(excess_returns) == 0:
        return 0.0
    
    sharpe = np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(periods_per_year)
    return float(sharpe)


def calculate_max_drawdown(equity_curve: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity_curve: Series of portfolio values over time
        
    Returns:
        Maximum drawdown as percentage (negative value)
    """
    if equity_curve.empty or len(equity_curve) < 2:
        return 0.0
    
    # Calculate running maximum
    running_max = equity_curve.expanding().max()
    
    # Calculate drawdown at each point
    drawdown = (equity_curve - running_max) / running_max * 100
    
    # Return the worst drawdown
    return float(drawdown.min())


def calculate_equity_curve(
    trades: List[Trade], 
    starting_capital: float
) -> pd.Series:
    """
    Build equity curve from trade list.
    
    Args:
        trades: List of completed trades
        starting_capital: Starting capital in JPY
        
    Returns:
        Series with equity values indexed by date
    """
    if not trades:
        return pd.Series([starting_capital])
    
    equity_points = [(trades[0].entry_date, starting_capital)]
    current_capital = starting_capital
    
    for trade in trades:
        # After each trade, update capital
        current_capital += trade.return_jpy
        equity_points.append((trade.exit_date, current_capital))
    
    dates = [point[0] for point in equity_points]
    values = [point[1] for point in equity_points]
    
    return pd.Series(values, index=pd.to_datetime(dates))


def calculate_profit_factor(trades: List[Trade]) -> float:
    """
    Calculate profit factor (gross profit / gross loss).
    
    Args:
        trades: List of completed trades
        
    Returns:
        Profit factor (>1.0 means profitable system)
    """
    if not trades:
        return 0.0
    
    gross_profit = sum(t.return_jpy for t in trades if t.return_jpy > 0)
    gross_loss = abs(sum(t.return_jpy for t in trades if t.return_jpy < 0))
    
    if gross_loss == 0:
        return float('inf') if gross_profit > 0 else 0.0
    
    return gross_profit / gross_loss


def calculate_annualized_return(
    total_return_pct: float,
    start_date: str,
    end_date: str
) -> float:
    """
    Calculate annualized return from total return.
    
    Args:
        total_return_pct: Total return percentage
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        
    Returns:
        Annualized return percentage
    """
    start = pd.to_datetime(start_date)
    end = pd.to_datetime(end_date)
    years = (end - start).days / 365.25
    
    if years <= 0:
        return 0.0
    
    # Compound annual growth rate
    cagr = (((total_return_pct / 100 + 1) ** (1 / years)) - 1) * 100
    return float(cagr)


def calculate_trade_statistics(trades: List[Trade]) -> dict:
    """
    Calculate comprehensive trade statistics.
    
    Args:
        trades: List of completed trades
        
    Returns:
        Dictionary with trade statistics
    """
    if not trades:
        return {
            'num_trades': 0,
            'win_rate_pct': 0.0,
            'avg_gain_pct': 0.0,
            'avg_loss_pct': 0.0,
            'avg_holding_days': 0.0,
            'profit_factor': 0.0
        }
    
    winners = [t for t in trades if t.return_pct > 0]
    losers = [t for t in trades if t.return_pct <= 0]
    
    return {
        'num_trades': len(trades),
        'win_rate_pct': (len(winners) / len(trades)) * 100,
        'avg_gain_pct': np.mean([t.return_pct for t in winners]) if winners else 0.0,
        'avg_loss_pct': np.mean([t.return_pct for t in losers]) if losers else 0.0,
        'avg_holding_days': np.mean([t.holding_days for t in trades]),
        'profit_factor': calculate_profit_factor(trades)
    }
