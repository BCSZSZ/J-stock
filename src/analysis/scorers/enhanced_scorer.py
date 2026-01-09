"""
Enhanced Scorer - Japan market optimized strategy.

Key improvements:
1. Institutional: Smart money composite (Foreign + TrustBank + InvTrust + Insurance)
   vs Dumb money divergence detection
2. Fundamental: EPS growth, forecast beats, cash flow quality, balance sheet health
3. Volatility: Proper ATR historical comparison (as originally intended)
4. Earnings Risk: Progressive penalty based on days until earnings
5. Weights: 35% Tech, 35% Institutional (increased), 20% Fund, 10% Vol

Japanese market specifics:
- Foreign investors are trend leaders in Japan (30% of volume)
- Retail investors are contrarian (fade them at extremes)
- Conservative guidance culture → forecast beats are strong signals
- Lower volatility than US → ATR regimes matter more
- Earnings gaps can be brutal (5-15%) → stricter risk management
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict
from .base_scorer import BaseScorer


class EnhancedScorer(BaseScorer):
    """
    Enhanced scoring strategy optimized for Japanese stock market.
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
    
    def _check_earnings_risk(self, metadata: dict, current_date: pd.Timestamp, risk_flags: list) -> float:
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

        # Work with copy to avoid modifying original
        df_trades = df_trades.copy()
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
