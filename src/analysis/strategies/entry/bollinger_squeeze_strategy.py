"""
Bollinger Squeeze Entry Strategy
布林带挤压突破入场策略

核心逻辑：
1. 检测布林带宽度收窄（BB_Width < 历史20分位 - 波动率挤压）
2. 等待突破信号：价格突破上轨 + 成交量放大
3. ADX > 20确认趋势强度
4. 适合捕捉震荡后的爆发行情
"""

from typing import Optional
import pandas as pd
import numpy as np

from src.analysis.signals import TradingSignal, SignalAction, MarketData
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy


class BollingerSqueezeStrategy(BaseEntryStrategy):
    """
    布林带挤压突破策略
    
    Parameters:
        squeeze_percentile: 挤压判断的百分位阈值（默认20，即BB_Width < 历史20%分位）
        adx_threshold: ADX最低阈值（默认20）
        volume_multiplier: 成交量放大倍数（默认1.5）
        min_confidence: 最低置信度（默认0.6）
    """
    
    def __init__(
        self,
        squeeze_percentile: float = 20.0,
        adx_threshold: float = 20.0,
        volume_multiplier: float = 1.5,
        min_confidence: float = 0.6
    ):
        super().__init__()
        self.squeeze_percentile = squeeze_percentile
        self.adx_threshold = adx_threshold
        self.volume_multiplier = volume_multiplier
        self.min_confidence = min_confidence

    def precompute_entry_signals(
        self,
        *,
        ticker: str,
        features: pd.DataFrame,
        **_unused: object,
    ) -> dict[int, TradingSignal]:
        if len(features) < 50:
            return {}
        required_fields = [
            'BB_Width',
            'BB_PctB',
            'ADX_14',
            'Volume',
            'Volume_SMA_20',
            'Close',
        ]
        if not all(field in features.columns for field in required_fields):
            return {}

        bb_width = pd.to_numeric(features['BB_Width'], errors='coerce')
        bb_pctb = pd.to_numeric(features['BB_PctB'], errors='coerce')
        adx = pd.to_numeric(features['ADX_14'], errors='coerce')
        volume = pd.to_numeric(features['Volume'], errors='coerce')
        volume_sma20 = pd.to_numeric(features['Volume_SMA_20'], errors='coerce')
        fallback_threshold, history_count = _rolling_non_null_percentile(
            bb_width,
            percentile=self.squeeze_percentile,
            window=100,
        )
        if 'BB_Width_Q20_100' in features.columns:
            squeeze_threshold = pd.to_numeric(
                features['BB_Width_Q20_100'],
                errors='coerce',
            )
            squeeze_threshold = squeeze_threshold.where(
                squeeze_threshold.notna(),
                fallback_threshold,
            )
        else:
            squeeze_threshold = fallback_threshold

        is_squeezed = bb_width < squeeze_threshold
        breakout_upper = (bb_pctb > 1.0) & (bb_pctb.shift(1) <= 1.0)
        near_upper = bb_pctb > 0.8
        volume_surge = volume > (self.volume_multiplier * volume_sma20)
        adx_confirmed = adx > self.adx_threshold

        confidence = pd.Series(0.0, index=features.index, dtype='float64')
        confidence += is_squeezed.fillna(False).astype(float) * 0.2
        confidence += breakout_upper.fillna(False).astype(float) * 0.4
        confidence += (
            (~breakout_upper.fillna(False)) & near_upper.fillna(False)
        ).astype(float) * 0.2
        confidence += volume_surge.fillna(False).astype(float) * 0.2
        confidence += adx_confirmed.fillna(False).astype(float) * 0.2
        confidence -= (~adx_confirmed.fillna(False)).astype(float) * 0.1

        row_numbers = pd.Series(np.arange(len(features)), index=features.index)
        buy_mask = (
            (row_numbers >= 49)
            & (history_count >= 20)
            & (confidence >= self.min_confidence)
        ).fillna(False)

        signals: dict[int, TradingSignal] = {}
        empty = pd.DataFrame()
        for row_pos in np.flatnonzero(buy_mask.to_numpy(dtype=bool)):
            row_pos_int = int(row_pos)
            signal = self.generate_entry_signal(
                MarketData(
                    ticker=ticker,
                    current_date=pd.Timestamp(features.index[row_pos_int]),
                    df_features=features.iloc[: row_pos_int + 1],
                    df_trades=empty,
                    df_financials=empty,
                    metadata={},
                )
            )
            if signal.action == SignalAction.BUY:
                signals[row_pos_int] = signal
        return signals
    
    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        """
        生成入场信号
        
        检测逻辑：
        1. BB_Width处于挤压状态（低于历史20分位）
        2. 价格突破上轨（BB_PctB > 1.0）
        3. 成交量放大（Volume > 1.5 * Volume_SMA_20）
        4. ADX > 20（趋势形成）
        """
        df = market_data.df_features
        
        if df.empty or len(df) < 50:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["数据不足"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 检查必要字段
        required_fields = ['BB_Width', 'BB_PctB', 'ADX_14', 'Volume', 'Volume_SMA_20', 'Close']
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["缺少必要技术指标"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        reasons = []
        confidence = 0.0
        
        # 1. 布林带宽度挤压检测
        bb_width_series = df['BB_Width'].dropna()
        if len(bb_width_series) < 20:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["历史数据不足"],
                strategy_name="BollingerSqueezeStrategy"
            )
        
        squeeze_threshold = latest.get('BB_Width_Q20_100')
        if pd.isna(squeeze_threshold):
            squeeze_threshold = np.percentile(bb_width_series.tail(100), self.squeeze_percentile)
        is_squeezed = latest['BB_Width'] < squeeze_threshold
        
        # 2. 突破上轨检测
        breakout_upper = latest['BB_PctB'] > 1.0 and prev['BB_PctB'] <= 1.0
        
        # 3. 成交量放大
        volume_surge = (
            pd.notna(latest['Volume']) and 
            pd.notna(latest['Volume_SMA_20']) and 
            latest['Volume'] > self.volume_multiplier * latest['Volume_SMA_20']
        )
        
        # 4. ADX趋势确认
        adx_confirmed = pd.notna(latest['ADX_14']) and latest['ADX_14'] > self.adx_threshold
        
        # 综合判断
        if is_squeezed:
            reasons.append(f"布林带挤压（宽度{latest['BB_Width']:.4f} < {squeeze_threshold:.4f}）")
            confidence += 0.2
        
        if breakout_upper:
            reasons.append(f"突破上轨（PctB={latest['BB_PctB']:.2f}）")
            confidence += 0.4
        else:
            # 即使没突破，但接近上轨也加分
            if latest['BB_PctB'] > 0.8:
                reasons.append(f"接近上轨（PctB={latest['BB_PctB']:.2f}）")
                confidence += 0.2
        
        if volume_surge:
            reasons.append(f"成交量放大（{latest['Volume']/latest['Volume_SMA_20']:.2f}x）")
            confidence += 0.2
        
        if adx_confirmed:
            reasons.append(f"ADX确认趋势（{latest['ADX_14']:.1f}）")
            confidence += 0.2
        else:
            reasons.append(f"ADX偏弱（{latest['ADX_14']:.1f}）")
            confidence -= 0.1
        
        # 判定买入
        action = SignalAction.BUY if confidence >= self.min_confidence else SignalAction.HOLD
        
        if action == SignalAction.HOLD and len(reasons) == 0:
            reasons = ["无突破信号"]
        
        return TradingSignal(
            action=action,
            confidence=min(confidence, 1.0),
            reasons=reasons,
            metadata={
                "bb_width": float(latest['BB_Width']),
                "bb_pctb": float(latest['BB_PctB']),
                "adx": float(latest['ADX_14']) if pd.notna(latest['ADX_14']) else 0.0,
                "volume_ratio": float(latest['Volume'] / latest['Volume_SMA_20']) if pd.notna(latest['Volume_SMA_20']) else 0.0,
                "is_squeezed": is_squeezed,
                "breakout": breakout_upper
            },
            strategy_name="BollingerSqueezeStrategy"
        )


def _rolling_non_null_percentile(
    series: pd.Series,
    *,
    percentile: float,
    window: int,
) -> tuple[pd.Series, pd.Series]:
    history: list[float] = []
    thresholds: list[float] = []
    counts: list[int] = []
    for value in pd.to_numeric(series, errors='coerce'):
        if pd.notna(value):
            history.append(float(value))
        counts.append(len(history))
        if len(history) >= 20:
            thresholds.append(float(np.percentile(history[-window:], percentile)))
        else:
            thresholds.append(np.nan)
    return (
        pd.Series(thresholds, index=series.index, dtype='float64'),
        pd.Series(counts, index=series.index, dtype='int64'),
    )
