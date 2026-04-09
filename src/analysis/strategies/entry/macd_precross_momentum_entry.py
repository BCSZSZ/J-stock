"""MACD pre-cross momentum entry based on rising histogram and price."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy


def _rising_for_window(series: pd.Series, window: int) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if window <= 1:
        return pd.Series(True, index=numeric.index, dtype="boolean")
    diff_positive = numeric.diff().gt(0)
    return diff_positive.rolling(window - 1, min_periods=window - 1).sum().eq(window - 1)


def _peak_at_window_start(macd_hist: pd.Series, window: int) -> pd.Series:
    numeric = pd.to_numeric(macd_hist, errors="coerce")
    window = max(2, int(window))
    negative_mask = numeric.lt(0).fillna(False)
    segment_id = (~negative_mask).cumsum()
    segment_cummin = numeric.where(negative_mask).groupby(segment_id).cummin()
    start_value = numeric.shift(window - 1)
    start_segment_id = segment_id.shift(window - 1)
    same_negative_segment = negative_mask & start_segment_id.eq(segment_id)
    return same_negative_segment & start_value.eq(segment_cummin)


def build_precross_momentum_flags(
    df: pd.DataFrame,
    hist_rise_days: int = 3,
    price_rise_days: int = 3,
    require_hist_below_zero: bool = True,
    max_hist_abs_norm: float | None = None,
    require_above_ema200: bool = False,
    require_peak_at_window_start: bool = False,
    max_gap_above_ema20_pct: float | None = None,
    max_return_5d: float | None = None,
    min_adx_14: float | None = None,
) -> pd.DataFrame:
    close = pd.to_numeric(df["Close"], errors="coerce")
    macd_hist = pd.to_numeric(df["MACD_Hist"], errors="coerce")
    hist_abs_norm = macd_hist.abs() / close.replace(0, np.nan)
    ema20 = pd.to_numeric(df["EMA_20"], errors="coerce") if "EMA_20" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    return_5d = pd.to_numeric(df["Return_5d"], errors="coerce") if "Return_5d" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    adx_14 = pd.to_numeric(df["ADX_14"], errors="coerce") if "ADX_14" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)

    hist_rising = _rising_for_window(macd_hist, max(2, int(hist_rise_days))).fillna(False)
    price_rising = _rising_for_window(close, max(2, int(price_rise_days))).fillna(False)
    peak_at_window_start = _peak_at_window_start(macd_hist, max(2, int(hist_rise_days))).fillna(False)

    if require_hist_below_zero:
        hist_below_zero = macd_hist.lt(0).fillna(False)
    else:
        hist_below_zero = pd.Series(True, index=df.index, dtype="boolean")

    if max_hist_abs_norm is None:
        near_zero_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        near_zero_ok = hist_abs_norm.le(float(max_hist_abs_norm)).fillna(False)

    if require_above_ema200:
        if "EMA_200" in df.columns:
            ema_200 = pd.to_numeric(df["EMA_200"], errors="coerce")
            above_ema200 = close.gt(ema_200).fillna(False)
        else:
            above_ema200 = pd.Series(False, index=df.index, dtype="boolean")
    else:
        above_ema200 = pd.Series(True, index=df.index, dtype="boolean")

    gap_above_ema20_pct = ((close / ema20) - 1.0) * 100.0
    if max_gap_above_ema20_pct is None:
        gap_above_ema20_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        gap_above_ema20_ok = gap_above_ema20_pct.le(float(max_gap_above_ema20_pct)).fillna(False)

    if max_return_5d is None:
        return_5d_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        return_5d_ok = return_5d.le(float(max_return_5d)).fillna(False)

    if min_adx_14 is None:
        adx_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        adx_ok = adx_14.ge(float(min_adx_14)).fillna(False)

    volume_ratio = pd.Series(np.nan, index=df.index, dtype=float)
    if "Volume" in df.columns and "Volume_SMA_20" in df.columns:
        volume = pd.to_numeric(df["Volume"], errors="coerce")
        volume_sma_20 = pd.to_numeric(df["Volume_SMA_20"], errors="coerce")
        volume_ratio = volume / volume_sma_20.replace(0, np.nan)

    flags = pd.DataFrame(
        {
            "hist_rising": hist_rising,
            "price_rising": price_rising,
            "peak_at_window_start": peak_at_window_start,
            "hist_below_zero": hist_below_zero,
            "hist_abs_norm": hist_abs_norm,
            "near_zero_ok": near_zero_ok,
            "above_ema200": above_ema200,
            "gap_above_ema20_pct": gap_above_ema20_pct,
            "gap_above_ema20_ok": gap_above_ema20_ok,
            "return_5d": return_5d,
            "return_5d_ok": return_5d_ok,
            "adx_14": adx_14,
            "adx_ok": adx_ok,
            "volume_ratio": volume_ratio,
        },
        index=df.index,
    )
    if require_peak_at_window_start:
        peak_ok = flags["peak_at_window_start"]
    else:
        peak_ok = pd.Series(True, index=df.index, dtype="boolean")
    flags["peak_ok"] = peak_ok
    flags["signal"] = flags[
        [
            "hist_rising",
            "price_rising",
            "hist_below_zero",
            "near_zero_ok",
            "above_ema200",
            "peak_ok",
            "gap_above_ema20_ok",
            "return_5d_ok",
            "adx_ok",
        ]
    ].all(axis=1)
    return flags


def _latest_precross_momentum_flags(
    df: pd.DataFrame,
    hist_rise_days: int = 3,
    price_rise_days: int = 3,
    require_hist_below_zero: bool = True,
    max_hist_abs_norm: float | None = None,
    require_above_ema200: bool = False,
    require_peak_at_window_start: bool = False,
    max_gap_above_ema20_pct: float | None = None,
    max_return_5d: float | None = None,
    min_adx_14: float | None = None,
) -> dict:
    hist_window = max(2, int(hist_rise_days))
    price_window = max(2, int(price_rise_days))

    close = pd.to_numeric(df["Close"], errors="coerce")
    macd_hist = pd.to_numeric(df["MACD_Hist"], errors="coerce")
    latest_close = close.iloc[-1]
    latest_hist = macd_hist.iloc[-1]

    hist_window_values = macd_hist.tail(hist_window)
    price_window_values = close.tail(price_window)

    hist_rising = bool(
        len(hist_window_values) == hist_window
        and hist_window_values.notna().all()
        and hist_window_values.diff().iloc[1:].gt(0).all()
    )
    price_rising = bool(
        len(price_window_values) == price_window
        and price_window_values.notna().all()
        and price_window_values.diff().iloc[1:].gt(0).all()
    )

    latest_hist_negative = bool(pd.notna(latest_hist) and latest_hist < 0)
    trailing_negative_segment = []
    for value in reversed(macd_hist.tolist()):
        if pd.isna(value) or value >= 0:
            break
        trailing_negative_segment.append(float(value))
    trailing_negative_segment.reverse()

    peak_at_window_start = False
    if len(hist_window_values) == hist_window and hist_window_values.notna().all():
        start_value = float(hist_window_values.iloc[0])
        same_negative_segment = latest_hist_negative and hist_window_values.lt(0).all()
        if same_negative_segment and trailing_negative_segment:
            peak_at_window_start = bool(start_value == min(trailing_negative_segment))

    if require_hist_below_zero:
        hist_below_zero = latest_hist_negative
    else:
        hist_below_zero = True

    hist_abs_norm = np.nan
    if pd.notna(latest_close) and latest_close != 0 and pd.notna(latest_hist):
        hist_abs_norm = abs(float(latest_hist)) / float(latest_close)

    if max_hist_abs_norm is None:
        near_zero_ok = True
    else:
        near_zero_ok = bool(pd.notna(hist_abs_norm) and hist_abs_norm <= float(max_hist_abs_norm))

    if require_above_ema200:
        if "EMA_200" in df.columns:
            ema_200 = pd.to_numeric(df["EMA_200"], errors="coerce").iloc[-1]
            above_ema200 = bool(pd.notna(latest_close) and pd.notna(ema_200) and latest_close > ema_200)
        else:
            above_ema200 = False
    else:
        above_ema200 = True

    ema20 = pd.to_numeric(df["EMA_20"], errors="coerce").iloc[-1] if "EMA_20" in df.columns else np.nan
    gap_above_ema20_pct = np.nan
    if pd.notna(latest_close) and pd.notna(ema20) and ema20 != 0:
        gap_above_ema20_pct = ((float(latest_close) / float(ema20)) - 1.0) * 100.0
    if max_gap_above_ema20_pct is None:
        gap_above_ema20_ok = True
    else:
        gap_above_ema20_ok = bool(pd.notna(gap_above_ema20_pct) and gap_above_ema20_pct <= float(max_gap_above_ema20_pct))

    return_5d = pd.to_numeric(df["Return_5d"], errors="coerce").iloc[-1] if "Return_5d" in df.columns else np.nan
    if max_return_5d is None:
        return_5d_ok = True
    else:
        return_5d_ok = bool(pd.notna(return_5d) and float(return_5d) <= float(max_return_5d))

    adx_14 = pd.to_numeric(df["ADX_14"], errors="coerce").iloc[-1] if "ADX_14" in df.columns else np.nan
    if min_adx_14 is None:
        adx_ok = True
    else:
        adx_ok = bool(pd.notna(adx_14) and float(adx_14) >= float(min_adx_14))

    volume_ratio = np.nan
    if "Volume" in df.columns and "Volume_SMA_20" in df.columns:
        volume = pd.to_numeric(df["Volume"], errors="coerce").iloc[-1]
        volume_sma_20 = pd.to_numeric(df["Volume_SMA_20"], errors="coerce").iloc[-1]
        if pd.notna(volume) and pd.notna(volume_sma_20) and volume_sma_20 != 0:
            volume_ratio = float(volume) / float(volume_sma_20)

    peak_ok = peak_at_window_start if require_peak_at_window_start else True
    signal = all(
        [
            hist_rising,
            price_rising,
            hist_below_zero,
            near_zero_ok,
            above_ema200,
            peak_ok,
            gap_above_ema20_ok,
            return_5d_ok,
            adx_ok,
        ]
    )

    return {
        "hist_rising": hist_rising,
        "price_rising": price_rising,
        "peak_at_window_start": peak_at_window_start,
        "hist_below_zero": hist_below_zero,
        "hist_abs_norm": hist_abs_norm,
        "near_zero_ok": near_zero_ok,
        "above_ema200": above_ema200,
        "gap_above_ema20_pct": gap_above_ema20_pct,
        "gap_above_ema20_ok": gap_above_ema20_ok,
        "return_5d": return_5d,
        "return_5d_ok": return_5d_ok,
        "adx_14": adx_14,
        "adx_ok": adx_ok,
        "volume_ratio": volume_ratio,
        "peak_ok": peak_ok,
        "signal": signal,
    }


class MACDPreCrossMomentumEntry(BaseEntryStrategy):
    """Enter before MACD crosses above zero when histogram and price both strengthen."""

    def __init__(
        self,
        hist_rise_days: int = 3,
        price_rise_days: int = 3,
        require_hist_below_zero: bool = True,
        max_hist_abs_norm: float | None = None,
        require_above_ema200: bool = False,
        require_peak_at_window_start: bool = False,
        max_gap_above_ema20_pct: float | None = None,
        max_return_5d: float | None = None,
        min_adx_14: float | None = None,
        min_confidence: float = 0.6,
    ):
        super().__init__(strategy_name="MACDPreCrossMomentumEntry")
        self.hist_rise_days = max(2, int(hist_rise_days))
        self.price_rise_days = max(2, int(price_rise_days))
        self.require_hist_below_zero = bool(require_hist_below_zero)
        self.max_hist_abs_norm = (
            None if max_hist_abs_norm is None else max(0.0, float(max_hist_abs_norm))
        )
        self.require_above_ema200 = bool(require_above_ema200)
        self.require_peak_at_window_start = bool(require_peak_at_window_start)
        self.max_gap_above_ema20_pct = (
            None
            if max_gap_above_ema20_pct is None
            else float(max_gap_above_ema20_pct)
        )
        self.max_return_5d = None if max_return_5d is None else float(max_return_5d)
        self.min_adx_14 = None if min_adx_14 is None else float(min_adx_14)
        self.min_confidence = float(min_confidence)

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features
        min_rows = max(self.hist_rise_days, self.price_rise_days)

        if len(df) < min_rows:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        if "Close" not in df.columns or "MACD_Hist" not in df.columns:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest_flags = _latest_precross_momentum_flags(
            df,
            hist_rise_days=self.hist_rise_days,
            price_rise_days=self.price_rise_days,
            require_hist_below_zero=self.require_hist_below_zero,
            max_hist_abs_norm=self.max_hist_abs_norm,
            require_above_ema200=self.require_above_ema200,
            require_peak_at_window_start=self.require_peak_at_window_start,
            max_gap_above_ema20_pct=self.max_gap_above_ema20_pct,
            max_return_5d=self.max_return_5d,
            min_adx_14=self.min_adx_14,
        )
        latest = df.iloc[-1]

        metadata = {
            "entry_stage": "PRE_CROSS_MOMENTUM" if bool(latest_flags["signal"]) else "NONE",
            "hist_rise_days": self.hist_rise_days,
            "price_rise_days": self.price_rise_days,
            "require_hist_below_zero": self.require_hist_below_zero,
            "require_above_ema200": self.require_above_ema200,
            "require_peak_at_window_start": self.require_peak_at_window_start,
            "max_hist_abs_norm": self.max_hist_abs_norm,
            "max_gap_above_ema20_pct": self.max_gap_above_ema20_pct,
            "max_return_5d": self.max_return_5d,
            "min_adx_14": self.min_adx_14,
            "macd_hist": float(pd.to_numeric(latest.get("MACD_Hist"), errors="coerce")),
            "macd_hist_prev": float(pd.to_numeric(df.iloc[-2].get("MACD_Hist"), errors="coerce")),
            "macd": float(pd.to_numeric(latest.get("MACD"), errors="coerce")),
            "macd_signal": float(pd.to_numeric(latest.get("MACD_Signal"), errors="coerce")),
            "close": float(pd.to_numeric(latest.get("Close"), errors="coerce")),
            "close_prev": float(pd.to_numeric(df.iloc[-2].get("Close"), errors="coerce")),
            "hist_abs_norm": float(pd.to_numeric(latest_flags.get("hist_abs_norm"), errors="coerce")),
            "above_ema200": bool(latest_flags.get("above_ema200", False)),
            "peak_at_window_start": bool(latest_flags.get("peak_at_window_start", False)),
            "gap_above_ema20_pct": float(pd.to_numeric(latest_flags.get("gap_above_ema20_pct"), errors="coerce")),
            "return_5d": float(pd.to_numeric(latest_flags.get("return_5d"), errors="coerce")),
            "adx_14": float(pd.to_numeric(latest_flags.get("adx_14"), errors="coerce")),
            "volume_ratio": float(pd.to_numeric(latest_flags.get("volume_ratio"), errors="coerce")),
        }

        if not bool(latest_flags["signal"]):
            reasons = []
            if not bool(latest_flags["hist_rising"]):
                reasons.append("MACD histogram not rising consecutively")
            if not bool(latest_flags["price_rising"]):
                reasons.append("Price not rising consecutively")
            if self.require_hist_below_zero and not bool(latest_flags["hist_below_zero"]):
                reasons.append("Histogram is not below zero")
            if self.max_hist_abs_norm is not None and not bool(latest_flags["near_zero_ok"]):
                reasons.append("Histogram is too far below zero axis")
            if self.require_above_ema200 and not bool(latest_flags["above_ema200"]):
                reasons.append("Price is below EMA200")
            if self.require_peak_at_window_start and not bool(latest_flags["peak_at_window_start"]):
                reasons.append("Rising window does not start at the negative histogram peak")
            if self.max_gap_above_ema20_pct is not None and not bool(latest_flags["gap_above_ema20_ok"]):
                reasons.append("Price is too far above EMA20")
            if self.max_return_5d is not None and not bool(latest_flags["return_5d_ok"]):
                reasons.append("Return_5d is too high")
            if self.min_adx_14 is not None and not bool(latest_flags["adx_ok"]):
                reasons.append("ADX_14 is too low")
            if not reasons:
                reasons.append("No pre-cross momentum setup")
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=reasons,
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        confidence = 0.62
        reasons = [
            f"MACD histogram rising for {self.hist_rise_days} bars below zero",
            f"Price rising for {self.price_rise_days} bars",
        ]

        if self.require_peak_at_window_start:
            reasons.append("Rising window starts at the negative histogram peak")
        if self.max_gap_above_ema20_pct is not None:
            reasons.append(f"Gap above EMA20 <= {self.max_gap_above_ema20_pct:.2f}%")
        if self.max_return_5d is not None:
            reasons.append(f"Return_5d <= {self.max_return_5d:.2f}")
        if self.min_adx_14 is not None:
            reasons.append(f"ADX_14 >= {self.min_adx_14:.1f}")

        hist_abs_norm = pd.to_numeric(latest_flags.get("hist_abs_norm"), errors="coerce")
        if pd.notna(hist_abs_norm) and hist_abs_norm <= 0.010:
            confidence += 0.04
            reasons.append("Histogram is close to zero axis")

        if self.require_above_ema200 and bool(latest_flags["above_ema200"]):
            confidence += 0.04
            reasons.append("Price is above EMA200")

        confidence = float(np.clip(confidence, 0.0, 1.0))
        if confidence < self.min_confidence:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=confidence,
                reasons=reasons + [f"Confidence {confidence:.2f} < threshold {self.min_confidence:.2f}"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.BUY,
            confidence=confidence,
            reasons=reasons,
            metadata=metadata,
            strategy_name=self.strategy_name,
        )


class MACDPreCross2BarEntry(MACDPreCrossMomentumEntry):
    """CLI-friendly fixed variant for the plain 2-bar pre-cross entry."""

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
        )
        self.strategy_name = "MACDPreCross2BarEntry"


class MACDPreCross2BarRet5d008Entry(MACDPreCrossMomentumEntry):
    """CLI-friendly fixed variant for 2-bar pre-cross plus Return_5d filter."""

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            max_return_5d=0.08,
        )
        self.strategy_name = "MACDPreCross2BarRet5d008Entry"


class MACDPreCross2BarLiteComboEntry(MACDPreCrossMomentumEntry):
    """CLI-friendly fixed variant for the current best LiteCombo entry."""

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            max_hist_abs_norm=0.01,
            min_adx_14=10.0,
            max_return_5d=0.08,
        )
        self.strategy_name = "MACDPreCross2BarLiteComboEntry"


__all__ = [
    "MACDPreCrossMomentumEntry",
    "MACDPreCross2BarEntry",
    "MACDPreCross2BarRet5d008Entry",
    "MACDPreCross2BarLiteComboEntry",
    "build_precross_momentum_flags",
]