"""
打分工具函数集

定位：
- 纯工具函数，无状态
- 任何策略都可以选择性调用
- Entry策略可以用（生成买入信号）
- Exit策略也可以用（生成卖出信号）
- 也可以完全不用

使用示例：
    # Entry策略使用
    from src.analysis.scoring_utils import calculate_composite_score
    
    score, breakdown = calculate_composite_score(
        df_features, df_trades, df_financials, metadata
    )
    if score >= 65:
        return TradingSignal(action=BUY, metadata={'score': score, ...})
    
    # Exit策略使用
    current_score, _ = calculate_composite_score(...)
    entry_score = position.entry_signal.metadata.get('score', 0)
    if current_score < entry_score - 15:
        return TradingSignal(action=SELL, ...)
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional
from datetime import timedelta


# =====================================================================
# 核心打分函数
# =====================================================================

def calculate_technical_score(df_features: pd.DataFrame) -> float:
    """
    计算技术面分数 (0-100)
    
    评估指标:
    - EMA Perfect Order（趋势对齐）
    - RSI动量
    - MACD动量
    
    Args:
        df_features: 技术指标DataFrame
        
    Returns:
        技术面分数 (0-100)
    """
    if df_features.empty:
        return 50.0
    
    latest = df_features.iloc[-1]
    score = 50.0
    
    # 1. EMA Perfect Order (The "Perfect Order")
    if latest['Close'] > latest['EMA_20'] > latest['EMA_50'] > latest['EMA_200']:
        score += 20  # 完美趋势
    elif latest['Close'] > latest['EMA_200']:
        score += 10  # 基本趋势向上
    elif latest['Close'] < latest['EMA_200']:
        score -= 20  # 趋势向下
    
    # 2. RSI Logic
    rsi = latest['RSI']
    if 40 <= rsi <= 65:
        score += 10  # 健康区间
    elif rsi > 75:
        score -= 10  # 超买
    elif rsi < 30:
        score += 5   # 超卖反弹机会
    
    # 3. MACD Momentum
    if latest['MACD_Hist'] > 0:
        score += 10  # 正动量
        if latest['MACD'] > 0:
            score += 5  # 强动量
    
    return np.clip(score, 0, 100)


def calculate_institutional_score(
    df_trades: pd.DataFrame,
    current_date: pd.Timestamp,
    lookback_days: int = 35,
    use_smart_money: bool = False
) -> float:
    """
    计算机构流向分数 (0-100)
    
    Args:
        df_trades: 机构交易数据
        current_date: 当前日期
        lookback_days: 回看天数
        use_smart_money: True=增强版(Smart Money), False=简单版(仅外资)
        
    Returns:
        机构流向分数 (0-100)
    """
    if df_trades.empty:
        return 50.0
    
    df_trades = df_trades.copy()
    df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
    
    # 过滤日期范围
    start_date = current_date - timedelta(days=lookback_days)
    mask = (df_trades['EnDate'] <= current_date) & (df_trades['EnDate'] >= start_date)
    recent = df_trades.loc[mask].sort_values('EnDate')
    
    if recent.empty:
        return 50.0
    
    score = 50.0
    
    if use_smart_money:
        # 增强版：Smart Money vs Dumb Money
        smart_cols = ['FrgnBal', 'TrustBal', 'InvTrustBal', 'InsuranceBal']
        dumb_cols = ['IndividualBal', 'SecuritiesBal']
        
        smart_flow = sum(recent[col].sum() for col in smart_cols if col in recent.columns)
        dumb_flow = sum(recent[col].sum() for col in dumb_cols if col in recent.columns)
        
        if smart_flow > 0:
            score += 25
            if dumb_flow < 0:  # Smart买入 + Dumb卖出 = 完美
                score += 15
        elif smart_flow < 0:
            score -= 15
        
        # 加速度检测
        if len(recent) >= 14:
            recent_week = recent.tail(7)
            prev_week = recent.iloc[-14:-7]
            
            if not recent_week.empty and not prev_week.empty:
                recent_smart = sum(recent_week[col].sum() for col in smart_cols if col in recent_week.columns)
                prev_smart = sum(prev_week[col].sum() for col in smart_cols if col in prev_week.columns)
                
                if recent_smart > prev_smart:
                    score += 10  # 加速买入
    else:
        # 简单版：仅看外资
        net_foreign_flow = recent['FrgnBal'].sum()
        
        if net_foreign_flow > 0:
            score += 20
            # 最近更强
            if recent.iloc[-1]['FrgnBal'] > recent['FrgnBal'].mean():
                score += 10
        elif net_foreign_flow < 0:
            score -= 15
    
    return np.clip(score, 0, 100)


def calculate_fundamental_score(df_financials: pd.DataFrame) -> float:
    """
    计算基本面分数 (0-100)
    
    评估指标:
    - 营收增长
    - 利润增长
    - 财报超预期
    
    Args:
        df_financials: 财务数据DataFrame
        
    Returns:
        基本面分数 (0-100)
    """
    if df_financials.empty or len(df_financials) < 2:
        return 50.0
    
    df_fins = df_financials.sort_values('DiscDate')
    latest = df_fins.iloc[-1]
    prev = df_fins.iloc[-2]
    
    score = 50.0
    
    # 1. 营收增长
    sales = pd.to_numeric(latest.get('Sales', 0), errors='coerce')
    prev_sales = pd.to_numeric(prev.get('Sales', 0), errors='coerce')
    
    if pd.notna(sales) and pd.notna(prev_sales) and prev_sales > 0:
        sales_growth = (sales / prev_sales - 1) * 100
        if sales_growth > 10:
            score += 15
        elif sales_growth > 5:
            score += 10
        elif sales_growth < -5:
            score -= 15
    
    # 2. 营业利润增长
    op = pd.to_numeric(latest.get('OperatingProfit', 0), errors='coerce')
    prev_op = pd.to_numeric(prev.get('OperatingProfit', 0), errors='coerce')
    
    if pd.notna(op) and pd.notna(prev_op) and prev_op > 0:
        op_growth = (op / prev_op - 1) * 100
        if op_growth > 15:
            score += 20
        elif op_growth > 8:
            score += 12
        elif op_growth < -10:
            score -= 20
    
    # 3. Forecast beat (财报超预期)
    forecast_sales = pd.to_numeric(latest.get('FSales', 0), errors='coerce')
    if pd.notna(forecast_sales) and pd.notna(sales) and forecast_sales > 0:
        if sales > forecast_sales * 1.03:  # 超预期3%
            score += 15
    
    return np.clip(score, 0, 100)


def calculate_volatility_score(df_features: pd.DataFrame) -> float:
    """
    计算波动性/风险分数 (0-100)
    
    低风险时期 = 高分
    高风险时期 = 低分
    
    Args:
        df_features: 技术指标DataFrame
        
    Returns:
        波动性分数 (0-100，低波动=高分)
    """
    if df_features.empty or len(df_features) < 20:
        return 50.0
    
    latest = df_features.iloc[-1]
    score = 50.0
    
    # ATR相对历史水平
    atr_current = latest['ATR']
    atr_avg = df_features['ATR'].tail(60).mean()
    atr_std = df_features['ATR'].tail(60).std()
    
    if pd.notna(atr_avg) and pd.notna(atr_std) and atr_std > 0:
        atr_zscore = (atr_current - atr_avg) / atr_std
        
        if atr_zscore < -0.5:  # 低于平均（低波动）
            score += 20
        elif atr_zscore > 1.0:  # 高于平均（高波动）
            score -= 20
    
    return np.clip(score, 0, 100)


def calculate_composite_score(
    df_features: pd.DataFrame,
    df_trades: pd.DataFrame,
    df_financials: pd.DataFrame,
    metadata: dict,
    weights: Dict[str, float] = None,
    current_date: pd.Timestamp = None
) -> Tuple[float, Dict[str, float]]:
    """
    计算综合分数
    
    Args:
        df_features: 技术指标数据
        df_trades: 机构交易数据
        df_financials: 财务数据
        metadata: 元数据
        weights: 权重配置，默认为Simple权重 (40/30/20/10)
        current_date: 当前日期（用于机构流向计算）
        
    Returns:
        (total_score, breakdown)
        - total_score: 0-100 综合分数
        - breakdown: 各组件分数字典
    """
    # 默认权重（Simple策略）
    if weights is None:
        weights = {
            "technical": 0.4,
            "institutional": 0.3,
            "fundamental": 0.2,
            "volatility": 0.1
        }
    
    # 当前日期
    if current_date is None:
        if not df_features.empty:
            current_date = df_features.index[-1]
        else:
            current_date = pd.Timestamp.now()
    
    # 计算各组件分数
    tech_score = calculate_technical_score(df_features)
    inst_score = calculate_institutional_score(df_trades, current_date)
    fund_score = calculate_fundamental_score(df_financials)
    vol_score = calculate_volatility_score(df_features)
    
    # 加权组合
    total_score = (
        tech_score * weights["technical"] +
        inst_score * weights["institutional"] +
        fund_score * weights["fundamental"] +
        vol_score * weights["volatility"]
    )
    
    breakdown = {
        "technical": tech_score,
        "institutional": inst_score,
        "fundamental": fund_score,
        "volatility": vol_score
    }
    
    return total_score, breakdown


# =====================================================================
# 辅助检测函数
# =====================================================================

def check_earnings_risk(
    metadata: dict,
    current_date: pd.Timestamp
) -> Tuple[bool, int]:
    """
    检查财报风险
    
    Args:
        metadata: 元数据（含earnings_calendar）
        current_date: 当前日期
        
    Returns:
        (has_risk, days_until_earnings)
        - has_risk: True if 7天内有财报
        - days_until_earnings: 距离财报天数（999表示无近期财报）
    """
    if not metadata or 'earnings_calendar' not in metadata:
        return False, 999
    
    for event in metadata['earnings_calendar']:
        try:
            evt_date = pd.to_datetime(event['Date'])
            delta = (evt_date - current_date).days
            if 0 <= delta <= 7:
                return True, delta
        except:
            continue
    
    return False, 999


def detect_institutional_exodus(
    df_trades: pd.DataFrame,
    current_date: pd.Timestamp,
    threshold: float = -50_000_000,
    window_days: int = 14
) -> bool:
    """
    检测机构大举撤离
    
    Args:
        df_trades: 交易数据
        current_date: 当前日期
        threshold: 净卖出阈值（日元，默认-5000万）
        window_days: 检测窗口（天）
        
    Returns:
        True if 检测到机构大举卖出
    """
    if df_trades.empty:
        return False
    
    df_trades = df_trades.copy()
    df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
    
    start_date = current_date - timedelta(days=window_days)
    recent = df_trades[(df_trades['EnDate'] > start_date) & 
                       (df_trades['EnDate'] <= current_date)]
    
    if recent.empty or 'FrgnBal' not in recent.columns:
        return False
    
    net_foreign = recent['FrgnBal'].sum()
    return net_foreign < threshold


def detect_trend_breakdown(df_features: pd.DataFrame) -> Optional[str]:
    """
    检测趋势破坏（多信号确认）
    
    检测指标:
    - 跌破EMA200（2/3天确认）
    - MACD死叉
    - RSI持续弱势（4/5天 <45）
    - 成交量萎缩+价格下跌
    
    Args:
        df_features: 技术指标DataFrame
        
    Returns:
        破坏信号描述字符串，None表示无破坏
        需要至少2个信号才确认破坏
    """
    if len(df_features) < 5:
        return None
    
    latest = df_features.iloc[-1]
    signals = []
    
    # 1. 跌破EMA200（确认不是假突破）
    if latest['Close'] < latest['EMA_200']:
        closes_below = (df_features['Close'].tail(3) < df_features['EMA_200'].tail(3)).sum()
        if closes_below >= 2:
            signals.append("Below EMA200")
    
    # 2. MACD死叉
    if len(df_features) >= 2:
        macd_hist_prev = df_features.iloc[-2]['MACD_Hist']
        macd_hist_now = latest['MACD_Hist']
        if macd_hist_prev > 0 and macd_hist_now < 0:
            signals.append("MACD death cross")
    
    # 3. RSI持续弱势
    if latest['RSI'] < 40:
        rsi_weak = (df_features['RSI'].tail(5) < 45).sum()
        if rsi_weak >= 4:
            signals.append("Persistent RSI weakness")
    
    # 4. 成交量萎缩 + 价格下跌
    if len(df_features) >= 20:
        volume_avg = df_features['Volume'].tail(20).mean()
        if latest['Volume'] < volume_avg * 0.7:
            price_change_5d = (latest['Close'] / df_features.iloc[-6]['Close'] - 1) * 100
            if price_change_5d < -3:
                signals.append("Volume dry-up")
    
    # 需要至少2个信号
    if len(signals) >= 2:
        return " AND ".join(signals)
    
    return None


def detect_market_deterioration(
    entry_data: pd.Series,
    current_data: pd.Series,
    df_trades: pd.DataFrame,
    entry_date: pd.Timestamp,
    current_date: pd.Timestamp
) -> Optional[str]:
    """
    检测市场恶化（对比入场时的状态）
    
    检测维度:
    - 趋势反转（EMA200上方→下方）
    - 动量丧失（MACD正→负）
    - 机构流向反转（买入→卖出）
    
    Args:
        entry_data: 入场时的技术指标
        current_data: 当前技术指标
        df_trades: 交易数据
        entry_date: 入场日期
        current_date: 当前日期
        
    Returns:
        恶化信号描述，None表示无明显恶化
        需要至少2个维度恶化才确认
    """
    issues = []
    
    # 1. 趋势反转
    if entry_data['Close'] > entry_data['EMA_200'] and current_data['Close'] < current_data['EMA_200']:
        issues.append("Trend reversed")
    
    # 2. 动量丧失
    if entry_data['MACD_Hist'] > 0 and current_data['MACD_Hist'] < 0:
        issues.append("Momentum lost")
    
    # 3. 机构流向恶化
    if not df_trades.empty:
        df_trades = df_trades.copy()
        df_trades['EnDate'] = pd.to_datetime(df_trades['EnDate'])
        
        # 入场前一个月
        entry_month = df_trades[
            (df_trades['EnDate'] > entry_date - timedelta(days=30)) &
            (df_trades['EnDate'] <= entry_date)
        ]
        # 当前一个月
        current_month = df_trades[
            (df_trades['EnDate'] > current_date - timedelta(days=30)) &
            (df_trades['EnDate'] <= current_date)
        ]
        
        if not entry_month.empty and not current_month.empty:
            entry_foreign = entry_month['FrgnBal'].sum()
            current_foreign = current_month['FrgnBal'].sum()
            
            # 从买入转为大举卖出
            if entry_foreign > 0 and current_foreign < -30_000_000:
                issues.append("Foreign reversal")
    
    # 需要至少2个维度恶化
    if len(issues) >= 2:
        return "Market deterioration: " + " + ".join(issues)
    
    return None
