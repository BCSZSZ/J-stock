"""
ADX趋势衰竭退出策略 (ADX Trend Exhaustion Exit)

核心逻辑:
1. ADX监控趋势强度变化（ADX下降 = 趋势减弱）
2. 一目均衡表破位（价格跌破云层）
3. 成交量萎缩（Volume < 0.7x SMA_20，无量下跌风险）
4. 多周期EMA交叉确认（EMA20下穿EMA50）

适用场景: 趋势交易的精准退出
"""

from ..base_exit_strategy import BaseExitStrategy
from ...signals import TradingSignal, SignalAction, MarketData, Position
import pandas as pd
import numpy as np


class ADXTrendExhaustionExit(BaseExitStrategy):
    """
    ADX趋势衰竭退出策略
    
    4层退出逻辑:
    - P0: ADX趋势衰竭（ADX从峰值下降50%以上）
    - P1: 一目均衡表云层破位（Close < min(SpanA, SpanB)）
    - P2: 成交量萎缩 + 价格破位（Volume < 0.7x SMA且Close < EMA20）
    - P3: 多周期EMA死叉（EMA20下穿EMA50）
    
    Args:
        adx_decline_threshold: ADX衰竭阈值（默认50%）
        volume_threshold: 成交量萎缩阈值（默认0.7）
        min_adx_peak: ADX峰值最低要求（默认25，避免误判弱趋势）
    """
    
    def __init__(
        self,
        adx_decline_threshold: float = 50.0,
        volume_threshold: float = 0.7,
        min_adx_peak: float = 25.0
    ):
        super().__init__(strategy_name="ADXTrendExhaustionExit")
        self.adx_decline_threshold = adx_decline_threshold
        self.volume_threshold = volume_threshold
        self.min_adx_peak = min_adx_peak
        self._adx_peak = None
    
    def generate_exit_signal(
        self,
        position: Position,
        market_data: MarketData
    ) -> TradingSignal:
        """生成退出信号"""
        
        self.update_position(position, market_data.latest_price)
        
        df = market_data.df_features
        if df.empty or len(df) < 52:  # 一目均衡表需要52根K线
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name
            )
        
        # 确保所有需要的列存在
        required_cols = ['Close', 'ADX_14', 'Ichi_SpanA', 'Ichi_SpanB',
                        'EMA_20', 'EMA_50', 'Volume', 'Volume_SMA_20']
        if not all(col in df.columns for col in required_cols):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name
            )
        
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) >= 2 else latest
        recent_20 = df.tail(20)
        
        current_price = latest['Close']
        entry_price = position.entry_price
        peak_price = position.peak_price_since_entry
        
        # ========== P0: ADX趋势衰竭 ==========
        adx_current = latest['ADX_14']
        
        # 更新ADX峰值
        if self._adx_peak is None or adx_current > self._adx_peak:
            self._adx_peak = adx_current
        
        # 检查ADX是否从峰值大幅下降
        if self._adx_peak is not None and self._adx_peak >= self.min_adx_peak:
            adx_decline_pct = (1 - adx_current / self._adx_peak) * 100
            
            if adx_decline_pct >= self.adx_decline_threshold:
                return TradingSignal(
                    action=SignalAction.SELL,
                    confidence=0.90,
                    reasons=[f"P0: ADX趋势衰竭 (从{self._adx_peak:.1f}下降至{adx_current:.1f}, -{adx_decline_pct:.1f}%)"],
                    metadata={
                        "layer": "P0_ADXExhaustion",
                        "adx_current": round(adx_current, 2),
                        "adx_peak": round(self._adx_peak, 2),
                        "adx_decline_pct": round(adx_decline_pct, 2)
                    },
                    strategy_name=self.strategy_name
                )
        
        # ========== P1: 一目均衡表云层破位 ==========
        span_a = latest['Ichi_SpanA']
        span_b = latest['Ichi_SpanB']
        cloud_bottom = min(span_a, span_b)
        cloud_top = max(span_a, span_b)
        
        # 价格从云上方跌破云层
        prev_close = prev['Close']
        prev_cloud_bottom = min(prev['Ichi_SpanA'], prev['Ichi_SpanB'])
        
        was_above_cloud = prev_close > prev_cloud_bottom
        now_below_cloud = current_price < cloud_bottom
        
        if was_above_cloud and now_below_cloud:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.88,
                reasons=[f"P1: 一目均衡表云层破位 (价格{current_price:.2f} < 云底{cloud_bottom:.2f})"],
                metadata={
                    "layer": "P1_IchimokuCloudBreak",
                    "current_price": round(current_price, 2),
                    "cloud_bottom": round(cloud_bottom, 2),
                    "cloud_top": round(cloud_top, 2)
                },
                strategy_name=self.strategy_name
            )
        
        # ========== P2: 成交量萎缩 + 价格破位 ==========
        volume = latest['Volume']
        volume_sma = latest['Volume_SMA_20']
        ema_20 = latest['EMA_20']
        
        volume_ratio = volume / volume_sma if volume_sma > 0 else 1.0
        is_volume_dry = volume_ratio < self.volume_threshold
        is_price_break = current_price < ema_20
        
        # 成交量萎缩且价格跌破EMA20
        if is_volume_dry and is_price_break:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.75,
                reasons=[f"P2: 成交量萎缩+破位 (量比{volume_ratio:.2f}, 价格{current_price:.2f} < EMA20 {ema_20:.2f})"],
                metadata={
                    "layer": "P2_VolumeExhaustion",
                    "volume_ratio": round(volume_ratio, 2),
                    "ema_20": round(ema_20, 2)
                },
                strategy_name=self.strategy_name
            )
        
        # ========== P3: 多周期EMA死叉 ==========
        ema_20_current = latest['EMA_20']
        ema_50_current = latest['EMA_50']
        ema_20_prev = prev['EMA_20']
        ema_50_prev = prev['EMA_50']
        
        # EMA20从上方下穿EMA50（死叉）
        was_ema20_above = ema_20_prev > ema_50_prev
        now_ema20_below = ema_20_current < ema_50_current
        
        is_death_cross = was_ema20_above and now_ema20_below
        
        if is_death_cross:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.82,
                reasons=[f"P3: EMA死叉 (EMA20 {ema_20_current:.2f} < EMA50 {ema_50_current:.2f})"],
                metadata={
                    "layer": "P3_EMADeathCross",
                    "ema_20": round(ema_20_current, 2),
                    "ema_50": round(ema_50_current, 2)
                },
                strategy_name=self.strategy_name
            )
        
        # ========== 次级风险预警（不立即退出，但置信度提醒）==========
        warnings = []
        warning_confidence = 0.0
        
        # ADX下降但未达阈值
        if self._adx_peak is not None and self._adx_peak >= self.min_adx_peak:
            adx_decline_pct = (1 - adx_current / self._adx_peak) * 100
            if 30 <= adx_decline_pct < self.adx_decline_threshold:
                warnings.append(f"ADX下降{adx_decline_pct:.1f}%（警告）")
                warning_confidence += 0.15
        
        # 价格在云层内部（犹豫区）
        if cloud_bottom < current_price < cloud_top:
            warnings.append("价格在一目云层内（犹豫区）")
            warning_confidence += 0.10
        
        # 成交量轻度萎缩
        if 0.7 <= volume_ratio < 1.0:
            warnings.append(f"成交量偏低（{volume_ratio:.2f}x）")
            warning_confidence += 0.10
        
        # 没有触发退出，但有警告信号
        metadata = {
            "current_price": round(current_price, 2),
            "adx_current": round(adx_current, 2),
            "cloud_bottom": round(cloud_bottom, 2),
            "cloud_top": round(cloud_top, 2),
            "volume_ratio": round(volume_ratio, 2),
            "ema_20": round(ema_20_current, 2),
            "ema_50": round(ema_50_current, 2),
            "warnings": warnings
        }
        
        if warnings:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=warning_confidence,
                reasons=warnings,
                metadata=metadata,
                strategy_name=self.strategy_name
            )
        
        # 没有退出信号
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No exit condition met"],
            metadata=metadata,
            strategy_name=self.strategy_name
        )
