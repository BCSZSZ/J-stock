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
        current_date = pd.to_datetime(latest_row['Date'])

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


# ============================================================================
# STRATEGY 1: Simple Scorer (Original Logic)
# ============================================================================

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
    
    def _check_earnings_risk(self, metadata: dict, current_date: pd.Timestamp, risk_flags: List[str]) -> float:
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


# ============================================================================
# STRATEGY 2: Enhanced Scorer (Japan-Optimized)
# ============================================================================

class EnhancedScorer(BaseScorer):
    """
    Enhanced scoring strategy optimized for Japanese stock market.
    
    KEY IMPROVEMENTS:
    1. Institutional: Smart money composite (Foreign + TrustBank + InvTrust + Insurance)
       vs Dumb money divergence detection
    2. Fundamental: EPS growth, forecast beats, cash flow quality, balance sheet health
    3. Volatility: Proper ATR historical comparison (as originally intended)
    4. Earnings Risk: Progressive penalty based on days until earnings
    5. Weights: 35% Tech, 35% Institutional (increased), 20% Fund, 10% Vol
    
    JAPANESE MARKET SPECIFICS:
    - Foreign investors are trend leaders in Japan (30% of volume)
    - Retail investors are contrarian (fade them at extremes)
    - Conservative guidance culture → forecast beats are strong signals
    - Lower volatility than US → ATR regimes matter more
    - Earnings gaps can be brutal (5-15%) → stricter risk management
    """
    
    def __init__(self):
        super().__init__(strategy_name="Enhanced_Japan_v1")
    
    def _get_weights(self) -> Dict[str, float]:
        return {
            "technical": 0.35,      # Reduced (Japan less purely technical)
            "institutional": 0.35,  # Increased (institutions drive Japan)
            "fundamental": 0.20,    # Unchanged but better utilization
            "volatility": 0.10      # Unchanged but properly calculated
        }
    
    def _check_earnings_risk(self, metadata: dict, current_date: pd.Timestamp, risk_flags: List[str]) -> float:
        """Progressive earnings penalty (Japanese stocks gap violently)."""
        if not metadata or 'earnings_calendar' not in metadata:
            return 1.0
            
        for event in metadata['earnings_calendar']:
            try:
                evt_date = pd.to_datetime(event['Date'])
                delta = (evt_date - current_date).days
                
                if delta < 0:
                    continue
                elif delta <= 1:
                    risk_flags.append("EARNINGS_IMMINENT")
                    return 0.5  # 50% penalty
                elif delta <= 3:
                    risk_flags.append("EARNINGS_APPROACHING")
                    return 0.7  # 30% penalty
                elif delta <= 7:
                    risk_flags.append("EARNINGS_NEAR")
                    return 0.85  # 15% penalty
            except:
                continue
        return 1.0
    
    def _calc_technical_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        """Enhanced: Same as simple but foundation for future MACD crossover, EMA slope."""
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
        
        # Future: Add MACD crossover detection using df_features history
        # Future: Add EMA slope analysis
        
        return np.clip(score, 0, 100)

    def _calc_institutional_score(self, df_trades: pd.DataFrame, current_date: pd.Timestamp) -> float:
        """
        Enhanced: Smart Money vs Dumb Money divergence analysis.
        Japanese market edge: Foreign + TrustBank buying while Retail selling = strong signal.
        """
        if df_trades.empty:
            return 50.0

        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
        mask = (df_trades['EnDate'] <= current_date) & (df_trades['EnDate'] >= current_date - timedelta(days=35))
        recent_trades = df_trades.loc[mask].sort_values('EnDate')

        if recent_trades.empty:
            return 50.0

        score = 50.0
        
        # Smart Money Composite (Institutional long-term players)
        smart_money = 0
        if 'FrgnBal' in recent_trades.columns:
            smart_money += recent_trades['FrgnBal'].sum()
        if 'TrstBnkBal' in recent_trades.columns:
            smart_money += recent_trades['TrstBnkBal'].sum()
        if 'InvTrBal' in recent_trades.columns:
            smart_money += recent_trades['InvTrBal'].sum()
        if 'InsCoBal' in recent_trades.columns:
            smart_money += recent_trades['InsCoBal'].sum()
        
        # Retail / Fast Money (contrarian indicators)
        retail_flow = recent_trades['IndBal'].sum() if 'IndBal' in recent_trades.columns else 0
        prop_flow = recent_trades['PropBal'].sum() if 'PropBal' in recent_trades.columns else 0
        
        # Core scoring: Smart money accumulation
        if smart_money > 0:
            score += 25  # Base bonus for institutional buying
            
            # Divergence bonus (smart buying + retail selling = strongest signal)
            if retail_flow < 0:
                score += 15  # "Smart money vs dumb money" divergence
            
            # Acceleration check (is buying speeding up?)
            recent_foreign = recent_trades['FrgnBal'].iloc[-1] if 'FrgnBal' in recent_trades.columns else 0
            avg_foreign = recent_trades['FrgnBal'].mean() if 'FrgnBal' in recent_trades.columns else 0
            if recent_foreign > avg_foreign:
                score += 10  # Accelerating inflows
                
        elif smart_money < 0:
            score -= 25  # Institutional distribution (bearish)
            
            # Double penalty if retail is buying (dumb money trap)
            if retail_flow > 0:
                score -= 10
        
        return np.clip(score, 0, 100)

    def _calc_fundamental_score(self, df_fins: pd.DataFrame) -> float:
        """
        Enhanced: EPS growth, Forecast beats, Cash flow quality, Balance sheet health.
        Japanese market edge: Conservative guidance → beats are strong signals.
        """
        if df_fins.empty or len(df_fins) < 2:
            return 50.0

        df_fins = df_fins.sort_values('DiscDate')
        latest = df_fins.iloc[-1]
        prev = df_fins.iloc[-2]

        score = 50.0

        # Convert to numeric
        latest_sales = pd.to_numeric(latest['Sales'], errors='coerce')
        prev_sales = pd.to_numeric(prev['Sales'], errors='coerce')
        latest_op = pd.to_numeric(latest['OP'], errors='coerce')
        prev_op = pd.to_numeric(prev['OP'], errors='coerce')
        
        # 1. EPS Growth (MOST IMPORTANT for Japanese stocks)
        latest_eps = pd.to_numeric(latest['EPS'], errors='coerce')
        prev_eps = pd.to_numeric(prev['EPS'], errors='coerce')
        
        if pd.notna(latest_eps) and pd.notna(prev_eps) and prev_eps != 0:
            eps_growth = (latest_eps - prev_eps) / abs(prev_eps)
            if eps_growth > 0.15:  # 15%+ QoQ EPS growth
                score += 25
            elif eps_growth > 0.05:  # 5%+ growth
                score += 15
            elif eps_growth < -0.10:  # Declining earnings
                score -= 15
        
        # 2. Revenue Growth (secondary)
        if pd.notna(latest_sales) and pd.notna(prev_sales) and latest_sales > prev_sales:
            score += 10
        
        # 3. Operating Profit Growth
        if pd.notna(latest_op) and pd.notna(prev_op) and latest_op > prev_op:
            score += 10
        
        # 4. Forecast Beat (Japanese culture: conservative guidance)
        forecast_sales = pd.to_numeric(latest['FSales'], errors='coerce')
        if pd.notna(forecast_sales) and pd.notna(latest_sales) and forecast_sales > 0:
            beat_ratio = latest_sales / forecast_sales
            if beat_ratio > 1.02:  # Beat by 2%+
                score += 15
        
        # 5. Cash Flow Quality (CFO > Net Profit = real earnings)
        cfo = pd.to_numeric(latest['CFO'], errors='coerce')
        net_profit = pd.to_numeric(latest['NP'], errors='coerce')
        if pd.notna(cfo) and pd.notna(net_profit) and net_profit > 0:
            if cfo > net_profit:
                score += 10  # Real cash backing earnings
        
        # 6. Balance Sheet Health (Equity Ratio)
        equity = pd.to_numeric(latest['Eq'], errors='coerce')
        total_assets = pd.to_numeric(latest['TA'], errors='coerce')
        if pd.notna(equity) and pd.notna(total_assets) and total_assets > 0:
            equity_ratio = equity / total_assets
            if equity_ratio > 0.5:  # Strong balance sheet
                score += 5
            elif equity_ratio < 0.3:  # Over-leveraged
                score -= 10
        
        # 7. Operating Margin Expansion
        try:
            if latest_sales > 0 and prev_sales > 0:
                latest_margin = latest_op / latest_sales
                prev_margin = prev_op / prev_sales
                if latest_margin > prev_margin:
                    score += 5
        except (ZeroDivisionError, TypeError):
            pass

        return np.clip(score, 0, 100)

    def _calc_volatility_score(self, row: pd.Series, df_features: pd.DataFrame) -> float:
        """
        Enhanced: Proper ATR historical comparison (as originally intended).
        Japanese market edge: Low volatility = predictable trends.
        """
        score = 50.0
        
        # 1. Volume Liquidity Check
        if row['Volume'] > row['Volume_SMA_20']:
            score += 10
        
        # 2. ATR Volatility Regime Analysis (PROPER IMPLEMENTATION)
        current_atr_pct = (row['ATR'] / row['Close']) * 100
        
        # Calculate 50-day historical average ATR%
        if len(df_features) >= 50:
            historical_atr = df_features['ATR'].tail(50).mean()
            historical_close = df_features['Close'].tail(50).mean()
            avg_atr_pct = (historical_atr / historical_close) * 100
            
            if current_atr_pct < avg_atr_pct * 0.8:  # Low volatility regime
                score += 20  # Safer, more predictable
            elif current_atr_pct > avg_atr_pct * 1.5:  # High volatility
                score -= 15  # Risky, unpredictable
        
        # 3. Price Extension Check (refined thresholds for Japan)
        deviation = (row['Close'] - row['EMA_20']) / row['EMA_20']
        if deviation > 0.08:  # 8%+ above EMA20 (parabolic)
            score -= 15
        elif deviation < -0.05:  # 5% below EMA20 (oversold)
            score += 5  # Potential bounce
        elif abs(deviation) < 0.02:  # Very close to EMA20
            score += 5  # Healthy trend
        
        return np.clip(score, 0, 100)


# ============================================================================
# Convenience Aliases (Backward Compatibility)
# ============================================================================

# Default to Simple strategy for backward compatibility
StockSignalScorer = SimpleScorer
