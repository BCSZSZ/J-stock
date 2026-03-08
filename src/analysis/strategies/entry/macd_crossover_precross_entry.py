"""MACD crossover entry with optional pre-cross early trigger."""

from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


def _normalize_hist(hist: pd.Series, close: pd.Series) -> pd.Series:
    safe_close = close.replace(0, pd.NA).astype(float)
    return (hist.astype(float) / safe_close).fillna(0.0)


class MACDCrossoverWithPreCrossEntry(BaseEntryStrategy):
    """MACD crossover strategy with a softer pre-cross fallback trigger.

    Primary path:
    - Keep legacy MACDCrossoverStrategy behavior for confirmed cross entries.

    Fallback path:
    - If crossover path does not issue BUY, allow pre-cross entry when normalized
      MACD histogram rises inside [-eps, +eps] band.
    """

    def __init__(
        self,
        confirm_with_volume: bool = True,
        confirm_with_trend: bool = True,
        min_confidence: float = 0.6,
        eps: float = 0.0010,
        pre_rise_days: int = 3,
        pre_slope_min: float = 0.00025,
        pre_buy_size_multiplier: float = 0.8,
        precross_confidence: float = 0.64,
        allow_precross_only_above_ema200: bool = True,
    ):
        super().__init__(strategy_name="MACDCrossoverWithPreCrossEntry")
        self.confirm_volume = bool(confirm_with_volume)
        self.confirm_trend = bool(confirm_with_trend)
        self.min_confidence = float(min_confidence)
        self.eps = max(0.0, float(eps))
        self.pre_rise_days = max(2, int(pre_rise_days))
        self.pre_slope_min = max(0.0, float(pre_slope_min))
        self.pre_buy_size_multiplier = min(1.0, max(0.0, float(pre_buy_size_multiplier)))
        self.precross_confidence = float(np.clip(precross_confidence, 0.0, 1.0))
        self.allow_precross_only_above_ema200 = bool(allow_precross_only_above_ema200)

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        if len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        if "MACD_Hist" not in df.columns or "Close" not in df.columns:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        prev = df.iloc[-2]
        macd_hist_prev = prev["MACD_Hist"]
        macd_hist_now = latest["MACD_Hist"]
        golden_cross = macd_hist_prev < 0 and macd_hist_now > 0

        # Stage 1: keep original MACDCrossoverStrategy behavior as the primary path.
        if golden_cross:
            reasons = ["MACD golden cross detected"]
            confidence = 0.7

            if self.confirm_volume:
                if "Volume" in df.columns:
                    volume_now = latest["Volume"]
                    volume_avg = latest.get("Volume_SMA_20")
                    if pd.isna(volume_avg):
                        volume_avg = df["Volume"].rolling(20).mean().iloc[-1]
                    if pd.notna(volume_avg) and volume_avg > 0:
                        volume_ratio = volume_now / volume_avg
                        if volume_ratio > 1.2:
                            reasons.append(f"Volume surge (+{(volume_ratio - 1) * 100:.0f}%)")
                            confidence += 0.1
                        else:
                            reasons.append(f"Volume normal ({volume_ratio:.2f}x avg)")
                            confidence -= 0.05
                else:
                    reasons.append("Volume data unavailable")

            if self.confirm_trend:
                if "EMA_200" in df.columns:
                    price = latest["Close"]
                    ema_200 = latest["EMA_200"]
                    if pd.notna(ema_200) and price > ema_200:
                        reasons.append("Above EMA200 (uptrend)")
                        confidence += 0.1
                    else:
                        reasons.append("Below EMA200 (caution)")
                        confidence -= 0.15
                else:
                    reasons.append("EMA200 unavailable")

            confidence = float(np.clip(confidence, 0.0, 1.0))

            if confidence >= self.min_confidence:
                return TradingSignal(
                    action=SignalAction.BUY,
                    confidence=confidence,
                    reasons=reasons,
                    metadata={
                        "entry_stage": "MACD_CROSS",
                        "macd_hist": macd_hist_now,
                        "macd_hist_prev": macd_hist_prev,
                        "macd": latest.get("MACD"),
                        "macd_signal": latest.get("MACD_Signal"),
                    },
                    strategy_name=self.strategy_name,
                )

        # Stage 2: softened pre-cross fallback entry.
        if len(df) < self.pre_rise_days + 1:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No MACD cross and insufficient data for pre-cross"],
                metadata={"entry_stage": "NONE"},
                strategy_name=self.strategy_name,
            )

        hist_norm = _normalize_hist(df["MACD_Hist"], df["Close"])
        current = float(hist_norm.iloc[-1])
        recent = hist_norm.tail(self.pre_rise_days)
        in_band = (-self.eps <= current) and (current <= self.eps)
        rising = bool((recent.diff().dropna() > 0).all()) if len(recent) >= 2 else False
        slope = float(recent.iloc[-1] - recent.iloc[0]) if len(recent) >= 2 else 0.0
        slope_ok = slope >= self.pre_slope_min

        trend_ok = True
        if self.allow_precross_only_above_ema200:
            if "EMA_200" not in df.columns:
                trend_ok = False
            else:
                ema_200 = latest.get("EMA_200")
                trend_ok = bool(pd.notna(ema_200) and latest["Close"] > ema_200)

        pre_cross = in_band and rising and slope_ok and trend_ok

        metadata = {
            "entry_stage": "PRE_CROSS" if pre_cross else "NONE",
            "eps": self.eps,
            "pre_rise_days": self.pre_rise_days,
            "pre_slope_min": self.pre_slope_min,
            "hist_norm_now": current,
            "pre_cross_slope": slope,
            "buy_size_multiplier": self.pre_buy_size_multiplier,
        }

        if pre_cross:
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=self.precross_confidence,
                reasons=["Pre-cross rising momentum near MACD zero band"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No MACD cross or pre-cross setup"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


GRID_ENTRY_STRATEGY_MAP: Dict[str, str] = {}

_EPS_VALUES = [0.0005, 0.0010, 0.0015]
_PRE_RISE_VALUES = [2, 3, 4]
_PRE_SLOPE_VALUES = [0.00015, 0.00025, 0.00035]
_PRE_SIZE_VALUES = [0.7, 0.8, 0.9]


def _build_precross_variant_class(
    name: str,
    eps: float,
    rise: int,
    slope: float,
    size_mult: float,
):
    def __init__(self):
        MACDCrossoverWithPreCrossEntry.__init__(
            self,
            confirm_with_volume=True,
            confirm_with_trend=True,
            min_confidence=0.6,
            eps=eps,
            pre_rise_days=rise,
            pre_slope_min=slope,
            pre_buy_size_multiplier=size_mult,
            precross_confidence=0.64,
            allow_precross_only_above_ema200=True,
        )
        self.strategy_name = name

    return type(name, (MACDCrossoverWithPreCrossEntry,), {"__init__": __init__})


for _eps in _EPS_VALUES:
    for _rise in _PRE_RISE_VALUES:
        for _slope in _PRE_SLOPE_VALUES:
            for _size in _PRE_SIZE_VALUES:
                _name = (
                    f"MACDCP_E{_float_token(_eps)}_R{_rise}_"
                    f"S{_float_token(_slope)}_M{_float_token(_size)}"
                )
                _cls = _build_precross_variant_class(
                    _name,
                    _eps,
                    _rise,
                    _slope,
                    _size,
                )
                globals()[_name] = _cls
                GRID_ENTRY_STRATEGY_MAP[_name] = (
                    "src.analysis.strategies.entry.macd_crossover_precross_entry."
                    f"{_name}"
                )


__all__ = [
    "MACDCrossoverWithPreCrossEntry",
    "GRID_ENTRY_STRATEGY_MAP",
    *list(GRID_ENTRY_STRATEGY_MAP.keys()),
]
