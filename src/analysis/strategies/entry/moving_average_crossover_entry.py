"""Moving average crossover entry strategy."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


class MovingAverageCrossoverEntry(BaseEntryStrategy):
    """
    Entry when fast MA crosses above slow MA.

    Args:
        fast_ma_col: Fast MA column name.
        slow_ma_col: Slow MA column name.
        min_spread_pct: Minimum fast/slow spread percent after cross.
        require_price_above_slow: Whether close must stay above slow MA.
        confirm_with_volume: Whether to require volume expansion.
        volume_multiplier: Minimum Volume / Volume_SMA_20 ratio when volume check is on.
        min_confidence: Minimum confidence threshold for BUY.
    """

    def __init__(
        self,
        fast_ma_col: str = "EMA_20",
        slow_ma_col: str = "EMA_50",
        min_spread_pct: float = 0.1,
        require_price_above_slow: bool = True,
        confirm_with_volume: bool = False,
        volume_multiplier: float = 1.1,
        min_confidence: float = 0.6,
    ):
        super().__init__(strategy_name="MovingAverageCrossoverEntry")
        self.fast_ma_col = fast_ma_col
        self.slow_ma_col = slow_ma_col
        self.min_spread_pct = float(min_spread_pct)
        self.require_price_above_slow = bool(require_price_above_slow)
        self.confirm_with_volume = bool(confirm_with_volume)
        self.volume_multiplier = float(volume_multiplier)
        self.min_confidence = float(min_confidence)

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features
        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required = ["Close", self.fast_ma_col, self.slow_ma_col]
        if self.confirm_with_volume:
            required.extend(["Volume", "Volume_SMA_20"])

        if not all(col in df.columns for col in required):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        fast_prev = prev[self.fast_ma_col]
        slow_prev = prev[self.slow_ma_col]
        fast_now = latest[self.fast_ma_col]
        slow_now = latest[self.slow_ma_col]
        close_now = latest["Close"]

        if any(pd.isna(v) for v in [fast_prev, slow_prev, fast_now, slow_now, close_now]):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Latest indicators contain NaN"],
                strategy_name=self.strategy_name,
            )

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        spread_pct = 0.0
        if abs(float(slow_now)) > 1e-9:
            spread_pct = (float(fast_now) - float(slow_now)) / abs(float(slow_now)) * 100.0

        metadata = {
            "fast_ma_col": self.fast_ma_col,
            "slow_ma_col": self.slow_ma_col,
            "fast_prev": float(fast_prev),
            "slow_prev": float(slow_prev),
            "fast_now": float(fast_now),
            "slow_now": float(slow_now),
            "spread_pct": float(spread_pct),
            "crossed_up": bool(crossed_up),
        }

        if not crossed_up:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No moving-average golden cross"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        reasons = [f"{self.fast_ma_col} crossed above {self.slow_ma_col}"]
        confidence = 0.68

        if spread_pct >= self.min_spread_pct:
            reasons.append(f"Spread confirmed ({spread_pct:.2f}%)")
            confidence += 0.08
        else:
            reasons.append(f"Spread weak ({spread_pct:.2f}% < {self.min_spread_pct:.2f}%)")
            confidence -= 0.06

        if self.require_price_above_slow:
            if float(close_now) > float(slow_now):
                reasons.append("Price above slow MA")
                confidence += 0.08
            else:
                reasons.append("Price below slow MA")
                confidence -= 0.18

        if self.confirm_with_volume:
            vol_now = latest["Volume"]
            vol_sma = latest["Volume_SMA_20"]
            if pd.notna(vol_now) and pd.notna(vol_sma) and float(vol_sma) > 0:
                volume_ratio = float(vol_now) / float(vol_sma)
                metadata["volume_ratio"] = volume_ratio
                if volume_ratio >= self.volume_multiplier:
                    reasons.append(f"Volume confirmed ({volume_ratio:.2f}x)")
                    confidence += 0.08
                else:
                    reasons.append(
                        f"Volume weak ({volume_ratio:.2f}x < {self.volume_multiplier:.2f}x)"
                    )
                    confidence -= 0.08

        confidence = float(np.clip(confidence, 0.0, 1.0))

        if confidence >= self.min_confidence:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=confidence,
                reasons=reasons,
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=confidence,
            reasons=reasons + [f"Confidence {confidence:.2f} < threshold {self.min_confidence:.2f}"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


_FAST_MA_VALUES = ["EMA_20", "SMA_20", "SMA_25"]
_SLOW_MA_VALUES = ["EMA_50", "EMA_200"]
_SPREAD_VALUES = [0.0, 0.1, 0.2]
_PRICE_ABOVE_VALUES = [True, False]
_CONFIDENCE_VALUES = [0.58, 0.62]

_MA_COL_TOKEN_MAP = {
    "EMA_20": "E20",
    "EMA_50": "E50",
    "EMA_200": "E200",
    "SMA_20": "S20",
    "SMA_25": "S25",
}


def _build_variant_class(
    name: str,
    fast_ma_col: str,
    slow_ma_col: str,
    min_spread_pct: float,
    require_price_above_slow: bool,
    min_confidence: float,
):
    def __init__(self):
        MovingAverageCrossoverEntry.__init__(
            self,
            fast_ma_col=fast_ma_col,
            slow_ma_col=slow_ma_col,
            min_spread_pct=min_spread_pct,
            require_price_above_slow=require_price_above_slow,
            confirm_with_volume=False,
            volume_multiplier=1.1,
            min_confidence=min_confidence,
        )
        self.strategy_name = name

    return type(name, (MovingAverageCrossoverEntry,), {"__init__": __init__})


GRID_ENTRY_STRATEGY_MAP: Dict[str, str] = {}

for _fast in _FAST_MA_VALUES:
    for _slow in _SLOW_MA_VALUES:
        for _spread in _SPREAD_VALUES:
            for _price_above in _PRICE_ABOVE_VALUES:
                for _min_conf in _CONFIDENCE_VALUES:
                    _fast_token = _MA_COL_TOKEN_MAP[_fast]
                    _slow_token = _MA_COL_TOKEN_MAP[_slow]
                    _spread_token = _float_token(_spread)
                    _price_token = "A1" if _price_above else "A0"
                    _conf_token = _float_token(_min_conf)

                    _name = (
                        f"MACX_F{_fast_token}_S{_slow_token}_"
                        f"P{_spread_token}_{_price_token}_C{_conf_token}"
                    )

                    _cls = _build_variant_class(
                        _name,
                        _fast,
                        _slow,
                        _spread,
                        _price_above,
                        _min_conf,
                    )
                    globals()[_name] = _cls
                    GRID_ENTRY_STRATEGY_MAP[_name] = (
                        f"src.analysis.strategies.entry.moving_average_crossover_entry.{_name}"
                    )


__all__ = [
    "MovingAverageCrossoverEntry",
    "GRID_ENTRY_STRATEGY_MAP",
    *list(GRID_ENTRY_STRATEGY_MAP.keys()),
]
