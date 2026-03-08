"""MACD histogram entry strategies with hysteresis and optional pre-cross mode."""

from __future__ import annotations

from typing import Dict

import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


def _normalize_hist(hist: pd.Series, close: pd.Series) -> pd.Series:
    safe_close = close.replace(0, pd.NA).astype(float)
    return (hist.astype(float) / safe_close).fillna(0.0)


class MACDHistHysteresisEntry(BaseEntryStrategy):
    """Entry on MACD histogram crossing above +eps with armed negative history."""

    def __init__(
        self,
        eps: float = 0.0010,
        arm_lookback: int = 10,
        min_confidence: float = 0.6,
    ):
        super().__init__(strategy_name="MACDHistHysteresisEntry")
        self.eps = max(0.0, float(eps))
        self.arm_lookback = max(2, int(arm_lookback))
        self.min_confidence = float(min_confidence)

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features
        min_rows = max(self.arm_lookback + 1, 3)
        if len(df) < min_rows:
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

        hist_norm = _normalize_hist(df["MACD_Hist"], df["Close"])
        current = float(hist_norm.iloc[-1])
        prev = float(hist_norm.iloc[-2])
        armed_window = hist_norm.iloc[-(self.arm_lookback + 1) : -1]
        armed = bool((armed_window <= -self.eps).any())
        crossed = prev <= self.eps and current > self.eps

        metadata = {
            "hist_norm_prev": prev,
            "hist_norm_now": current,
            "eps": self.eps,
            "arm_lookback": self.arm_lookback,
            "armed": armed,
        }

        if not armed:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Not armed by negative histogram"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        if not crossed:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No hysteresis cross above +eps"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        confidence = 0.7
        if confidence < self.min_confidence:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=confidence,
                reasons=[f"Confidence {confidence:.2f} below threshold"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        metadata["entry_stage"] = "CONFIRMED_CROSS"
        return TradingSignal(
            action=SignalAction.BUY,
            confidence=confidence,
            reasons=["Hysteresis MACD cross confirmed"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


class MACDHistHysteresisPreCrossEntry(MACDHistHysteresisEntry):
    """Hysteresis entry with optional pre-cross early trigger and size multiplier."""

    def __init__(
        self,
        eps: float = 0.0010,
        arm_lookback: int = 10,
        pre_rise_days: int = 3,
        pre_slope_min: float = 0.0003,
        pre_buy_size_multiplier: float = 0.8,
        min_confidence: float = 0.6,
    ):
        super().__init__(eps=eps, arm_lookback=arm_lookback, min_confidence=min_confidence)
        self.strategy_name = "MACDHistHysteresisPreCrossEntry"
        self.pre_rise_days = max(2, int(pre_rise_days))
        self.pre_slope_min = max(0.0, float(pre_slope_min))
        self.pre_buy_size_multiplier = min(1.0, max(0.0, float(pre_buy_size_multiplier)))

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features
        min_rows = max(self.arm_lookback + 1, self.pre_rise_days + 1, 4)
        if len(df) < min_rows:
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

        hist_norm = _normalize_hist(df["MACD_Hist"], df["Close"])
        current = float(hist_norm.iloc[-1])
        prev = float(hist_norm.iloc[-2])
        armed_window = hist_norm.iloc[-(self.arm_lookback + 1) : -1]
        armed = bool((armed_window <= -self.eps).any())
        crossed = prev <= self.eps and current > self.eps

        metadata = {
            "hist_norm_prev": prev,
            "hist_norm_now": current,
            "eps": self.eps,
            "arm_lookback": self.arm_lookback,
            "armed": armed,
            "pre_rise_days": self.pre_rise_days,
            "pre_slope_min": self.pre_slope_min,
            "pre_buy_size_multiplier": self.pre_buy_size_multiplier,
        }

        if not armed:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Not armed by negative histogram"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        if crossed:
            metadata["entry_stage"] = "CONFIRMED_CROSS"
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=0.72,
                reasons=["Hysteresis MACD cross confirmed"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        recent = hist_norm.tail(self.pre_rise_days)
        in_band = (-self.eps <= current) and (current <= self.eps)
        rising = bool((recent.diff().dropna() > 0).all()) if len(recent) >= 2 else False
        slope = float(recent.iloc[-1] - recent.iloc[0]) if len(recent) >= 2 else 0.0
        pre_cross = in_band and rising and slope >= self.pre_slope_min

        metadata["pre_cross_slope"] = slope

        if pre_cross:
            metadata["entry_stage"] = "PRE_CROSS"
            metadata["buy_size_multiplier"] = self.pre_buy_size_multiplier
            return TradingSignal(
                action=SignalAction.BUY,
                confidence=0.64,
                reasons=["Pre-cross rising momentum in hysteresis band"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No hysteresis cross or pre-cross setup"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


GRID_ENTRY_STRATEGY_MAP: Dict[str, str] = {}

_EPS_VALUES = [0.0005, 0.0010, 0.0015]
_ARM_VALUES = [8, 10]
_PRE_RISE_VALUES = [3]
_PRE_SLOPE_VALUES = [0.0002, 0.0004]
_PRE_SIZE_VALUES = [0.8]


def _build_hys_variant_class(name: str, eps: float, arm: int):
    def __init__(self):
        MACDHistHysteresisEntry.__init__(self, eps=eps, arm_lookback=arm)
        self.strategy_name = name

    return type(name, (MACDHistHysteresisEntry,), {"__init__": __init__})


def _build_hys_precross_variant_class(
    name: str,
    eps: float,
    arm: int,
    rise: int,
    slope: float,
    size_mult: float,
):
    def __init__(self):
        MACDHistHysteresisPreCrossEntry.__init__(
            self,
            eps=eps,
            arm_lookback=arm,
            pre_rise_days=rise,
            pre_slope_min=slope,
            pre_buy_size_multiplier=size_mult,
        )
        self.strategy_name = name

    return type(name, (MACDHistHysteresisPreCrossEntry,), {"__init__": __init__})


for _eps in _EPS_VALUES:
    for _arm in _ARM_VALUES:
        _hys_name = f"MGC_HYS_E{_float_token(_eps)}_L{_arm}"
        _hys_cls = _build_hys_variant_class(_hys_name, _eps, _arm)
        globals()[_hys_name] = _hys_cls
        GRID_ENTRY_STRATEGY_MAP[_hys_name] = (
            f"src.analysis.strategies.entry.macd_hysteresis_entry.{_hys_name}"
        )

        for _rise in _PRE_RISE_VALUES:
            for _slope in _PRE_SLOPE_VALUES:
                for _size in _PRE_SIZE_VALUES:
                    _pre_name = (
                        f"MGC_HYSP_E{_float_token(_eps)}_L{_arm}_R{_rise}_"
                        f"S{_float_token(_slope)}_M{_float_token(_size)}"
                    )
                    _pre_cls = _build_hys_precross_variant_class(
                        _pre_name, _eps, _arm, _rise, _slope, _size
                    )
                    globals()[_pre_name] = _pre_cls
                    GRID_ENTRY_STRATEGY_MAP[_pre_name] = (
                        f"src.analysis.strategies.entry.macd_hysteresis_entry.{_pre_name}"
                    )


__all__ = [
    "MACDHistHysteresisEntry",
    "MACDHistHysteresisPreCrossEntry",
    "GRID_ENTRY_STRATEGY_MAP",
    *list(GRID_ENTRY_STRATEGY_MAP.keys()),
]
