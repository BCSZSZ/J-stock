"""
一目均衡表 + KDJ震荡入场策略 (Ichimoku-Stochastic Oscillator)

核心逻辑:
1. 一目均衡表判断趋势方向（价格在云上方 = 多头）
2. KDJ震荡指标捕捉超卖反弹（K < 20且金叉）
3. 机构数据确认外资买入
4. 布林带位置确认（价格接近下轨，有反弹空间）

适用场景: 趋势中的震荡回调买点
"""

import pandas as pd
import numpy as np
from ..base_entry_strategy import BaseEntryStrategy
from ...signals import TradingSignal, SignalAction, MarketData


class IchimokuStochStrategy(BaseEntryStrategy):
    """
    一目均衡表 + KDJ震荡入场策略
    
    多层过滤:
    1. 趋势判断: Close > Ichi_SpanA 且 Close > Ichi_SpanB（价格在云上方）
    2. KDJ超卖: Stoch_K < 20 且 Stoch_K上穿Stoch_D（金叉）
    3. 机构确认: 最近3周外资净流入 > 0（可选）
    4. 布林带位置: BB_PctB < 0.3（价格接近下轨，有反弹空间）
    5. 成交量: Volume > 0.8x Volume_SMA_20（避免无量下跌）
    
    Args:
        stoch_oversold: KDJ超卖阈值（默认20）
        require_institutional: 是否需要机构确认（默认True）
        bb_lower_threshold: 布林带位置阈值（默认0.3）
    """
    
    def __init__(
        self,
        stoch_oversold: float = 20.0,
        require_institutional: bool = True,
        bb_lower_threshold: float = 0.3
    ):
        super().__init__(strategy_name="IchimokuStoch")
        self.stoch_oversold = stoch_oversold
        self.require_institutional = require_institutional
        self.bb_lower_threshold = bb_lower_threshold
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """生成一目均衡表+KDJ震荡信号"""
        
        df = market_data.df_features
        df_trades = market_data.df_trades
        
        if df.empty or len(df) < 52:  # 一目均衡表需要52根K线
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                metadata={"reason": "Insufficient data"}
            )
        
        # 确保所有需要的列存在
        required_cols = ['Close', 'Ichi_SpanA', 'Ichi_SpanB', 'Ichi_Tenkan', 'Ichi_Kijun',
                        'Stoch_K', 'Stoch_D', 'BB_PctB', 'Volume', 'Volume_SMA_20']
        if not all(col in df.columns for col in required_cols):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                metadata={"reason": "Missing required indicators"}
            )
        
        # 获取最近数据
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        
        close_price = latest['Close']
        
        # ========== STAGE 1: 一目均衡表趋势判断 ==========
        span_a = latest['Ichi_SpanA']
        span_b = latest['Ichi_SpanB']
        tenkan = latest['Ichi_Tenkan']  # 转换线
        kijun = latest['Ichi_Kijun']    # 基准线
        
        # 价格在云上方（多头趋势）
        is_above_cloud = close_price > span_a and close_price > span_b
        
        # 转换线在基准线上方（短期强势）
        tenkan_above_kijun = tenkan > kijun
        
        # ========== STAGE 2: KDJ超卖金叉 ==========
        stoch_k = latest['Stoch_K']
        stoch_d = latest['Stoch_D']
        prev_stoch_k = prev['Stoch_K']
        prev_stoch_d = prev['Stoch_D']
        
        # KDJ超卖（K < 20）
        is_oversold = stoch_k < self.stoch_oversold
        
        # KDJ金叉（K上穿D）
        is_golden_cross = (prev_stoch_k <= prev_stoch_d) and (stoch_k > stoch_d)
        
        # ========== STAGE 3: 布林带位置（价格接近下轨）==========
        bb_pctb = latest['BB_PctB']
        is_near_lower = bb_pctb < self.bb_lower_threshold
        
        # ========== STAGE 4: 成交量（避免无量）==========
        volume = latest['Volume']
        volume_sma = latest['Volume_SMA_20']
        has_volume = volume > (volume_sma * 0.8) if volume_sma > 0 else False
        
        # ========== STAGE 5: 机构确认（可选）==========
        institutional_support = True  # 默认通过
        institutional_info = {}
        
        if self.require_institutional and df_trades is not None and not df_trades.empty:
            # 检查最近3周外资净流入
            recent_trades = df_trades.tail(3)
            if 'FrgnBal' in recent_trades.columns:
                frgn_net = recent_trades['FrgnBal'].sum()
                institutional_support = frgn_net > 0
                institutional_info = {
                    "frgn_net_3w": round(frgn_net, 0)
                }
        
        # ========== 综合判断 ==========
        signals = {
            "above_cloud": is_above_cloud,
            "tenkan_above_kijun": tenkan_above_kijun,
            "stoch_oversold": is_oversold,
            "stoch_golden_cross": is_golden_cross,
            "near_bb_lower": is_near_lower,
            "has_volume": has_volume,
            "institutional_support": institutional_support
        }
        
        # 计算置信度
        confidence = 0.0
        confidence += 0.20 if is_above_cloud else 0.0
        confidence += 0.10 if tenkan_above_kijun else 0.0
        confidence += 0.15 if is_oversold else 0.0
        confidence += 0.25 if is_golden_cross else 0.0
        confidence += 0.15 if is_near_lower else 0.0
        confidence += 0.10 if has_volume else 0.0
        confidence += 0.05 if institutional_support else -0.10  # 不满足会扣分
        
        # 核心条件：趋势向上 + KDJ金叉
        core_conditions = is_above_cloud and is_golden_cross
        
        if core_conditions and confidence >= 0.6:
            action = SignalAction.BUY
        else:
            action = SignalAction.HOLD
        
        metadata = {
            "close": round(close_price, 2),
            "cloud_top": round(max(span_a, span_b), 2),
            "cloud_bottom": round(min(span_a, span_b), 2),
            "stoch_k": round(stoch_k, 2),
            "stoch_d": round(stoch_d, 2),
            "bb_pctb": round(bb_pctb, 4),
            "volume_ratio": round(volume / volume_sma, 2) if volume_sma > 0 else 0,
            "signals": signals,
            **institutional_info
        }
        
        return TradingSignal(
            action=action,
            confidence=confidence,
            metadata=metadata
        )
