"""Immediate-rebound entries for next-open buys after controlled pullbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy
from ..complexity import StrategyComplexity


@dataclass(frozen=True)
class ImmediateReboundFeatureCache:
    frame: pd.DataFrame
    close: pd.Series
    open: pd.Series
    high: pd.Series
    low: pd.Series
    volume: pd.Series
    volume_ratio: pd.Series
    ema20: pd.Series
    ema50: pd.Series
    ema200: pd.Series
    macd_hist: pd.Series
    rsi9: pd.Series
    rsi14: pd.Series
    bb_pctb: pd.Series
    adx14: pd.Series
    close_return_1d_pct: pd.Series
    close_return_2d_pct: pd.Series
    close_return_3d_pct: pd.Series
    close_return_5d_pct: pd.Series
    body_return_pct: pd.Series
    close_location: pd.Series
    low_vs_ema20_pct: pd.Series
    close_vs_ema20_pct: pd.Series
    close_vs_ema50_pct: pd.Series
    intraday_range_pct: pd.Series
    uptrend: pd.Series


def build_immediate_rebound_feature_cache(
    features: pd.DataFrame,
) -> ImmediateReboundFeatureCache:
    close = _numeric_series(features, "Close")
    open_ = _numeric_series(features, "Open")
    high = _numeric_series(features, "High")
    low = _numeric_series(features, "Low")
    volume = _numeric_series(features, "Volume")
    volume_sma20 = _numeric_series(features, "Volume_SMA_20")
    ema20 = _numeric_series(features, "EMA_20")
    ema50 = _numeric_series(features, "EMA_50")
    ema200 = _numeric_series(features, "EMA_200")
    rsi9 = _numeric_series(features, "RSI_9")
    rsi14 = _numeric_series(features, "RSI_14")
    if rsi14.isna().all():
        rsi14 = _numeric_series(features, "RSI")
    high_low_range = (high - low).replace(0.0, np.nan)
    return ImmediateReboundFeatureCache(
        frame=features,
        close=close,
        open=open_,
        high=high,
        low=low,
        volume=volume,
        volume_ratio=volume / volume_sma20.where(volume_sma20 > 0.0),
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        macd_hist=_numeric_series(features, "MACD_Hist"),
        rsi9=rsi9,
        rsi14=rsi14,
        bb_pctb=_numeric_series(features, "BB_PctB"),
        adx14=_numeric_series(features, "ADX_14"),
        close_return_1d_pct=close.pct_change() * 100.0,
        close_return_2d_pct=(close / close.shift(2).where(close.shift(2) > 0.0) - 1.0) * 100.0,
        close_return_3d_pct=(close / close.shift(3).where(close.shift(3) > 0.0) - 1.0) * 100.0,
        close_return_5d_pct=(close / close.shift(5).where(close.shift(5) > 0.0) - 1.0) * 100.0,
        body_return_pct=(close / open_.where(open_ > 0.0) - 1.0) * 100.0,
        close_location=(close - low) / high_low_range,
        low_vs_ema20_pct=(low / ema20.where(ema20 > 0.0) - 1.0) * 100.0,
        close_vs_ema20_pct=(close / ema20.where(ema20 > 0.0) - 1.0) * 100.0,
        close_vs_ema50_pct=(close / ema50.where(ema50 > 0.0) - 1.0) * 100.0,
        intraday_range_pct=(high / low.where(low > 0.0) - 1.0) * 100.0,
        uptrend=(close.gt(ema50) & ema20.gt(ema50)).fillna(False),
    )


class ImmediateReboundEntry(BaseEntryStrategy):
    """Base class for same-day pullback setups that target next-day rebound."""

    precompute_family_key = "immediate_rebound_entry"
    complexity = StrategyComplexity(
        numeric_param_count=6,
        extra_filter_count=3,
        conditional_rule_count=5,
    )

    def __init__(
        self,
        *,
        strategy_name: str,
        rule_name: str,
        rule_fn: Callable[[ImmediateReboundFeatureCache], pd.Series],
        buy_confidence: float = 0.76,
    ) -> None:
        super().__init__(strategy_name=strategy_name)
        self.rule_name = str(rule_name)
        self._rule_fn = rule_fn
        self.buy_confidence = float(buy_confidence)

    def build_precompute_feature_cache(
        self,
        *,
        features: pd.DataFrame,
        **_unused: object,
    ) -> ImmediateReboundFeatureCache:
        return build_immediate_rebound_feature_cache(features)

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        features = market_data.df_features
        if len(features) < 3:
            return self._hold_signal("Insufficient data")
        cache = build_immediate_rebound_feature_cache(features)
        row_pos = len(features) - 1
        mask = self._buy_mask(cache)
        if bool(mask.iloc[row_pos]):
            return self._buy_signal(cache, row_pos)
        return self._hold_signal("Immediate rebound rule not met")

    def precompute_entry_signals(
        self,
        *,
        ticker: str,
        features: pd.DataFrame,
        feature_cache: object | None = None,
        **_unused: object,
    ) -> dict[int, TradingSignal]:
        cache = (
            feature_cache
            if isinstance(feature_cache, ImmediateReboundFeatureCache)
            else build_immediate_rebound_feature_cache(features)
        )
        mask = self._buy_mask(cache)
        signals: dict[int, TradingSignal] = {}
        for row_pos in np.flatnonzero(mask.to_numpy(dtype=bool)):
            if int(row_pos) < 2:
                continue
            signals[int(row_pos)] = self._buy_signal(cache, int(row_pos))
        return signals

    def _buy_mask(self, cache: ImmediateReboundFeatureCache) -> pd.Series:
        required = (
            cache.close.notna()
            & cache.open.notna()
            & cache.high.notna()
            & cache.low.notna()
            & cache.ema20.notna()
            & cache.ema50.notna()
        )
        return (required & self._rule_fn(cache)).fillna(False).astype(bool)

    def _buy_signal(
        self,
        cache: ImmediateReboundFeatureCache,
        row_pos: int,
    ) -> TradingSignal:
        metadata = self._metadata_at(cache, row_pos)
        score = self._score(metadata)
        metadata["score"] = score
        confidence = float(np.clip(self.buy_confidence + (score - 60.0) / 600.0, 0.0, 0.98))
        return TradingSignal(
            action=SignalAction.BUY,
            confidence=confidence,
            reasons=[f"{self.rule_name} immediate rebound rule passed"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )

    def _hold_signal(self, reason: str) -> TradingSignal:
        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=[reason],
            metadata={"rule_name": self.rule_name, "score": 0.0},
            strategy_name=self.strategy_name,
        )

    def _metadata_at(
        self,
        cache: ImmediateReboundFeatureCache,
        row_pos: int,
    ) -> dict[str, object]:
        return {
            "rule_name": self.rule_name,
            "close_return_1d_pct": _value_at(cache.close_return_1d_pct, row_pos),
            "close_return_2d_pct": _value_at(cache.close_return_2d_pct, row_pos),
            "close_return_3d_pct": _value_at(cache.close_return_3d_pct, row_pos),
            "close_return_5d_pct": _value_at(cache.close_return_5d_pct, row_pos),
            "body_return_pct": _value_at(cache.body_return_pct, row_pos),
            "close_location": _value_at(cache.close_location, row_pos),
            "low_vs_ema20_pct": _value_at(cache.low_vs_ema20_pct, row_pos),
            "close_vs_ema20_pct": _value_at(cache.close_vs_ema20_pct, row_pos),
            "close_vs_ema50_pct": _value_at(cache.close_vs_ema50_pct, row_pos),
            "intraday_range_pct": _value_at(cache.intraday_range_pct, row_pos),
            "volume_ratio": _value_at(cache.volume_ratio, row_pos),
            "macd_hist": _value_at(cache.macd_hist, row_pos),
            "rsi_9": _value_at(cache.rsi9, row_pos),
            "rsi_14": _value_at(cache.rsi14, row_pos),
            "bb_pctb": _value_at(cache.bb_pctb, row_pos),
            "adx_14": _value_at(cache.adx14, row_pos),
        }

    @staticmethod
    def _score(metadata: dict[str, object]) -> float:
        rsi = _safe_float(metadata.get("rsi_14")) or 50.0
        low_vs_ema20 = _safe_float(metadata.get("low_vs_ema20_pct")) or 0.0
        close_location = _safe_float(metadata.get("close_location")) or 0.0
        volume_ratio = _safe_float(metadata.get("volume_ratio")) or 1.0
        close_return = _safe_float(metadata.get("close_return_1d_pct")) or 0.0
        support_bonus = max(0.0, 3.0 - abs(low_vs_ema20)) * 4.0
        rsi_bonus = max(0.0, 58.0 - abs(rsi - 48.0)) / 3.0
        return float(
            np.clip(
                35.0
                + support_bonus
                + rsi_bonus
                + close_location * 18.0
                + min(volume_ratio, 2.0) * 4.0
                - max(close_return, 0.0) * 2.0,
                0.0,
                100.0,
            )
        )


class ImmediateReboundOversoldUptrendEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundOversoldUptrendEntry",
            rule_name="oversold_in_uptrend",
            rule_fn=lambda c: (
                c.close.gt(c.ema50)
                & c.rsi14.between(35.0, 45.0)
                & c.close_return_1d_pct.lt(0.0)
                & c.low_vs_ema20_pct.between(-5.0, 2.0)
            ),
            buy_confidence=0.79,
        )


class ImmediateReboundEMA50SupportEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundEMA50SupportEntry",
            rule_name="ema50_support_pullback",
            rule_fn=lambda c: (
                c.close.gt(c.ema200)
                & c.low.le(c.ema50 * 1.02)
                & c.close.gt(c.ema50)
                & c.close_return_1d_pct.between(-2.5, 1.0)
                & c.rsi14.between(38.0, 62.0)
            ),
            buy_confidence=0.77,
        )


class ImmediateReboundTwoDownEMA20Entry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundTwoDownEMA20Entry",
            rule_name="two_down_uptrend_ema20",
            rule_fn=lambda c: (
                c.uptrend
                & c.close_return_1d_pct.lt(0.0)
                & c.close_return_1d_pct.shift(1).lt(0.0)
                & c.low_vs_ema20_pct.between(-4.0, 3.0)
                & c.rsi14.between(38.0, 66.0)
            ),
            buy_confidence=0.77,
        )


class ImmediateReboundNarrowRedUptrendEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundNarrowRedUptrendEntry",
            rule_name="narrow_red_uptrend",
            rule_fn=lambda c: (
                c.uptrend
                & c.close_return_1d_pct.between(-1.2, 0.0)
                & c.intraday_range_pct.lt(4.0)
                & c.low_vs_ema20_pct.between(-3.0, 3.0)
            ),
            buy_confidence=0.76,
        )


class ImmediateReboundADXTrendPullbackEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundADXTrendPullbackEntry",
            rule_name="adx_trend_pullback",
            rule_fn=lambda c: (
                c.uptrend
                & c.adx14.ge(18.0)
                & c.close_return_1d_pct.lt(0.3)
                & c.low_vs_ema20_pct.between(-3.0, 3.0)
                & c.rsi14.between(40.0, 65.0)
            ),
            buy_confidence=0.77,
        )


class ImmediateReboundMACDPositivePullbackEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundMACDPositivePullbackEntry",
            rule_name="macd_positive_pullback",
            rule_fn=lambda c: (
                c.uptrend
                & c.macd_hist.gt(0.0)
                & c.close_return_1d_pct.lt(0.5)
                & c.low_vs_ema20_pct.between(-3.0, 3.0)
                & c.rsi14.between(42.0, 68.0)
            ),
            buy_confidence=0.77,
        )


class ImmediateReboundLowerShadowUptrendEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundLowerShadowUptrendEntry",
            rule_name="lower_shadow_uptrend",
            rule_fn=lambda c: (
                c.uptrend
                & c.close_return_1d_pct.lt(0.5)
                & c.close_location.ge(0.65)
                & c.low_vs_ema20_pct.lt(1.5)
                & c.rsi14.between(38.0, 66.0)
            ),
            buy_confidence=0.76,
        )


class ImmediateReboundRSI4555PullbackEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundRSI4555PullbackEntry",
            rule_name="rsi45_55_uptrend_pullback",
            rule_fn=lambda c: (
                c.uptrend
                & c.rsi14.between(45.0, 55.0)
                & c.low_vs_ema20_pct.between(-4.0, 2.0)
                & c.close_return_2d_pct.lt(1.0)
            ),
            buy_confidence=0.76,
        )


class ImmediateReboundRedCloseNearHighEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundRedCloseNearHighEntry",
            rule_name="red_close_near_high_uptrend",
            rule_fn=lambda c: (
                c.uptrend
                & c.close_return_1d_pct.lt(0.0)
                & c.close_location.ge(0.55)
                & c.low_vs_ema20_pct.between(-3.0, 3.0)
                & c.rsi14.between(40.0, 70.0)
            ),
            buy_confidence=0.76,
        )


class ImmediateReboundBBMidPullbackEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundBBMidPullbackEntry",
            rule_name="bb_mid_pullback_uptrend",
            rule_fn=lambda c: (
                c.uptrend
                & c.bb_pctb.between(0.25, 0.65)
                & c.low_vs_ema20_pct.between(-4.0, 3.0)
                & c.rsi14.between(40.0, 65.0)
            ),
            buy_confidence=0.76,
        )


class ImmediateReboundEMA20TouchEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundEMA20TouchEntry",
            rule_name="ema20_touch_greenish_uptrend",
            rule_fn=lambda c: (
                c.uptrend
                & c.low.le(c.ema20 * 1.01)
                & c.close.gt(c.ema20)
                & c.close_return_1d_pct.between(-1.5, 1.0)
                & c.close_location.ge(0.50)
            ),
            buy_confidence=0.75,
        )


class ImmediateReboundThreeDaySnapbackEntry(ImmediateReboundEntry):
    def __init__(self) -> None:
        super().__init__(
            strategy_name="ImmediateReboundThreeDaySnapbackEntry",
            rule_name="three_day_snapback_bb_mid_reclaim",
            rule_fn=lambda c: (
                c.close_return_3d_pct.ge(5.0)
                & c.close_return_5d_pct.le(1.0)
                & c.rsi9.le(50.0)
                & c.bb_pctb.ge(0.30)
            ),
            buy_confidence=0.82,
        )


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype="float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _safe_float(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    return result


def _value_at(series: pd.Series, row_pos: int) -> float | None:
    return _safe_float(series.iloc[row_pos])


IMMEDIATE_REBOUND_ENTRY_NAMES: tuple[str, ...] = (
    "ImmediateReboundOversoldUptrendEntry",
    "ImmediateReboundEMA50SupportEntry",
    "ImmediateReboundTwoDownEMA20Entry",
    "ImmediateReboundNarrowRedUptrendEntry",
    "ImmediateReboundADXTrendPullbackEntry",
    "ImmediateReboundMACDPositivePullbackEntry",
    "ImmediateReboundLowerShadowUptrendEntry",
    "ImmediateReboundRSI4555PullbackEntry",
    "ImmediateReboundRedCloseNearHighEntry",
    "ImmediateReboundBBMidPullbackEntry",
    "ImmediateReboundEMA20TouchEntry",
    "ImmediateReboundThreeDaySnapbackEntry",
)


__all__ = [
    "ImmediateReboundEntry",
    "ImmediateReboundFeatureCache",
    "build_immediate_rebound_feature_cache",
    *IMMEDIATE_REBOUND_ENTRY_NAMES,
]
