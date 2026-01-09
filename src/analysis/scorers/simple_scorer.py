"""
Simple Scorer - Original scoring strategy.

Preserves the exact original logic with:
- Technical: 40%, Institutional: 30%, Fundamental: 20%, Volatility: 10%
- Uses only Foreign investor flow
- Basic fundamental metrics (Sales, OP growth)
- Simplified volatility check
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict
from .base_scorer import BaseScorer


class SimpleScorer(BaseScorer):
    """
    Original simple scoring strategy.
    - Technical: 40%, Institutional: 30%, Fundamental: 20%, Volatility: 10%
    - Uses only Foreign investor flow
    - Basic fundamental metrics (Sales, OP growth)
    - Simplified volatility check
    """
    
    def __init__(self):
        super().__init__(strategy_name="Simple_v1")
    
    def _get_weights(self) -> Dict[str, float]:
        return {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }
    
    def _check_earnings_risk(self, metadata: dict, current_date: pd.Timestamp, risk_flags: list) -> float:
        """Original: flat 20% penalty for 7-day window."""
        if not metadata or 'earnings_calendar' not in metadata:
            return 1.0
            
        for event in metadata['earnings_calendar']:
            try:
                evt_date = pd.to_datetime(event['Date'])
                delta = (evt_date - current_date).days
                if 0 <= delta <= 7:
                    risk_flags.append("EARNINGS_APPROACHING")
                    return 0.8  # 20% penalty
            except:
                continue
        return 1.0
    
    def _calc_technical_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        score = 50.0

        # 1. Trend Alignment (The "Perfect Order")
        if row['Close'] > row['EMA_20'] > row['EMA_50'] > row['EMA_200']:
            score += 20
        elif row['Close'] > row['EMA_200']:
            score += 10
        elif row['Close'] < row['EMA_200']:
            score -= 20

        # 2. RSI Logic
        rsi = row['RSI']
        if 40 <= rsi <= 65:
            score += 10
        elif rsi > 75:
            score -= 10
        elif rsi < 30:
            score += 5

        # 3. MACD Momentum
        if row['MACD_Hist'] > 0:
            score += 10
            if row['MACD'] > 0:
                score += 5
        
        return np.clip(score, 0, 100)

    def _calc_institutional_score(self, df_trades: pd.DataFrame, current_date: pd.Timestamp) -> float:
        """Original: Only Foreign investors (FrgnBal)."""
        if df_trades.empty:
            return 50.0

        # Work with copy to avoid modifying original
        df_trades = df_trades.copy()
        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
        mask = (df_trades['EnDate'] <= current_date) & (df_trades['EnDate'] >= current_date - timedelta(days=35))
        recent_trades = df_trades.loc[mask].sort_values('EnDate')

        if recent_trades.empty:
            return 50.0

        score = 50.0
        net_foreign_flow = recent_trades['FrgnBal'].sum()
        
        if net_foreign_flow > 0:
            score += 20
            if recent_trades.iloc[-1]['FrgnBal'] > recent_trades['FrgnBal'].mean():
                score += 10
        else:
            score -= 20

        return np.clip(score, 0, 100)

    def _calc_fundamental_score(self, df_fins: pd.DataFrame) -> float:
        """Original: Sales and OP growth only."""
        if df_fins.empty or len(df_fins) < 2:
            return 50.0

        df_fins = df_fins.sort_values('DiscDate')
        latest = df_fins.iloc[-1]
        prev = df_fins.iloc[-2]

        score = 50.0

        latest_sales = pd.to_numeric(latest['Sales'], errors='coerce')
        prev_sales = pd.to_numeric(prev['Sales'], errors='coerce')
        latest_op = pd.to_numeric(latest['OP'], errors='coerce')
        prev_op = pd.to_numeric(prev['OP'], errors='coerce')

        if pd.notna(latest_sales) and pd.notna(prev_sales) and latest_sales > prev_sales:
            score += 15
        
        if pd.notna(latest_op) and pd.notna(prev_op) and latest_op > prev_op:
            score += 15
            
        try:
            if latest_sales > 0 and prev_sales > 0:
                latest_margin = latest_op / latest_sales
                prev_margin = prev_op / prev_sales
                if latest_margin > prev_margin:
                    score += 10
        except (ZeroDivisionError, TypeError):
            pass

        return np.clip(score, 0, 100)

    def _calc_volatility_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        """Original: Simplified, doesn't actually use ATR properly."""
        score = 50.0
        
        if row['Volume'] > row['Volume_SMA_20']:
            score += 10
        
        deviation = (row['Close'] - row['EMA_20']) / row['EMA_20']
        if deviation > 0.05:
            score -= 10
            
        return np.clip(score, 0, 100)
