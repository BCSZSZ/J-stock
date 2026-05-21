"""MACD pre-cross momentum entry based on rising histogram and price."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..complexity import StrategyComplexity
from ..base_entry_strategy import BaseEntryStrategy


def _rising_for_window(series: pd.Series, window: int) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce")
    if window <= 1:
        return pd.Series(True, index=numeric.index, dtype="boolean")
    diff_positive = numeric.diff().gt(0)
    return diff_positive.rolling(window - 1, min_periods=window - 1).sum().eq(window - 1)


def _true_streak_days(series: pd.Series) -> pd.Series:
    mask = series.fillna(False).astype(bool)
    segment_id = mask.ne(mask.shift(fill_value=False)).cumsum()
    streak = mask.groupby(segment_id).cumcount() + 1
    return streak.where(mask, 0).astype(int)


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


def _calc_bias_pct_and_reference(latest_row: pd.Series) -> tuple[float, str] | tuple[None, None]:
    sma_col = "SMA_25" if "SMA_25" in latest_row.index else "SMA_20"
    if sma_col not in latest_row.index:
        return None, None

    sma = pd.to_numeric(latest_row.get(sma_col), errors="coerce")
    close = pd.to_numeric(latest_row.get("Close"), errors="coerce")
    if pd.isna(sma) or sma == 0 or pd.isna(close):
        return None, None

    bias_pct = float((close - sma) / sma * 100.0)
    return bias_pct, sma_col


def build_precross_momentum_flags(
    df: pd.DataFrame,
    hist_rise_days: int = 3,
    price_rise_days: int = 3,
    require_price_rising: bool = True,
    require_hist_below_zero: bool = True,
    max_hist_abs_norm: float | None = None,
    min_hist_delta_norm: float | None = None,
    require_above_ema200: bool = False,
    require_peak_at_window_start: bool = False,
    max_gap_above_ema20_pct: float | None = None,
    max_return_5d: float | None = None,
    min_adx_14: float | None = None,
    max_bias_pct: float | None = None,
    max_buy_signal_streak_days: int | None = None,
) -> pd.DataFrame:
    close = pd.to_numeric(df["Close"], errors="coerce")
    macd_hist = pd.to_numeric(df["MACD_Hist"], errors="coerce")
    hist_abs_norm = macd_hist.abs() / close.replace(0, np.nan)
    hist_delta_norm = macd_hist.diff() / close.replace(0, np.nan)
    ema20 = pd.to_numeric(df["EMA_20"], errors="coerce") if "EMA_20" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    return_5d = pd.to_numeric(df["Return_5d"], errors="coerce") if "Return_5d" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    adx_14 = pd.to_numeric(df["ADX_14"], errors="coerce") if "ADX_14" in df.columns else pd.Series(np.nan, index=df.index, dtype=float)
    sma_col = "SMA_25" if "SMA_25" in df.columns else "SMA_20"
    sma = pd.to_numeric(df[sma_col], errors="coerce") if sma_col in df.columns else pd.Series(np.nan, index=df.index, dtype=float)

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

    if min_hist_delta_norm is None:
        hist_delta_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        hist_delta_ok = hist_delta_norm.ge(float(min_hist_delta_norm)).fillna(False)

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

    bias_pct = ((close / sma.replace(0, np.nan)) - 1.0) * 100.0
    if max_bias_pct is None:
        bias_ok = pd.Series(True, index=df.index, dtype="boolean")
    else:
        bias_ok = bias_pct.le(float(max_bias_pct)) | bias_pct.isna()

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
            "hist_delta_norm": hist_delta_norm,
            "hist_delta_ok": hist_delta_ok,
            "above_ema200": above_ema200,
            "gap_above_ema20_pct": gap_above_ema20_pct,
            "gap_above_ema20_ok": gap_above_ema20_ok,
            "return_5d": return_5d,
            "return_5d_ok": return_5d_ok,
            "adx_14": adx_14,
            "adx_ok": adx_ok,
            "bias_pct": bias_pct,
            "bias_ok": bias_ok,
            "volume_ratio": volume_ratio,
        },
        index=df.index,
    )
    if require_peak_at_window_start:
        peak_ok = flags["peak_at_window_start"]
    else:
        peak_ok = pd.Series(True, index=df.index, dtype="boolean")
    if require_price_rising:
        price_rising_ok = flags["price_rising"]
    else:
        price_rising_ok = pd.Series(True, index=df.index, dtype="boolean")
    flags["peak_ok"] = peak_ok
    flags["price_rising_ok"] = price_rising_ok
    raw_signal = flags[
        [
            "hist_rising",
            "price_rising_ok",
            "hist_below_zero",
            "near_zero_ok",
            "hist_delta_ok",
            "above_ema200",
            "peak_ok",
            "gap_above_ema20_ok",
            "return_5d_ok",
            "adx_ok",
            "bias_ok",
        ]
    ].all(axis=1)
    streak_days = _true_streak_days(raw_signal)
    flags["raw_entry_signal"] = raw_signal
    flags["buy_signal_streak_days"] = streak_days
    flags["is_fresh_buy_signal"] = raw_signal & streak_days.eq(1)
    flags["stale_buy_signal"] = raw_signal & streak_days.gt(1)
    if max_buy_signal_streak_days is None:
        fresh_gate = pd.Series(True, index=df.index, dtype="boolean")
    else:
        fresh_gate = streak_days.le(max(1, int(max_buy_signal_streak_days)))
    flags["fresh_buy_signal_ok"] = fresh_gate
    flags["signal"] = raw_signal & fresh_gate
    return flags


def _compute_latest_precross_raw_flags(
    df: pd.DataFrame,
    hist_rise_days: int = 3,
    price_rise_days: int = 3,
    require_price_rising: bool = True,
    require_hist_below_zero: bool = True,
    max_hist_abs_norm: float | None = None,
    min_hist_delta_norm: float | None = None,
    require_above_ema200: bool = False,
    require_peak_at_window_start: bool = False,
    max_gap_above_ema20_pct: float | None = None,
    max_return_5d: float | None = None,
    min_adx_14: float | None = None,
    max_bias_pct: float | None = None,
) -> dict:
    hist_window = max(2, int(hist_rise_days))
    price_window = max(2, int(price_rise_days))

    close = pd.to_numeric(df["Close"], errors="coerce")
    macd_hist = pd.to_numeric(df["MACD_Hist"], errors="coerce")
    latest_close = close.iloc[-1]
    latest_hist = macd_hist.iloc[-1]
    prev_hist = macd_hist.iloc[-2] if len(macd_hist) >= 2 else np.nan

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

    hist_delta_norm = np.nan
    if (
        pd.notna(latest_close)
        and latest_close != 0
        and pd.notna(latest_hist)
        and pd.notna(prev_hist)
    ):
        hist_delta_norm = (float(latest_hist) - float(prev_hist)) / float(latest_close)

    if min_hist_delta_norm is None:
        hist_delta_ok = True
    else:
        hist_delta_ok = bool(
            pd.notna(hist_delta_norm)
            and float(hist_delta_norm) >= float(min_hist_delta_norm)
        )

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

    bias_pct, bias_reference = _calc_bias_pct_and_reference(df.iloc[-1])
    if max_bias_pct is None:
        bias_ok = True
    else:
        bias_ok = bool(bias_pct is None or float(bias_pct) <= float(max_bias_pct))

    volume_ratio = np.nan
    if "Volume" in df.columns and "Volume_SMA_20" in df.columns:
        volume = pd.to_numeric(df["Volume"], errors="coerce").iloc[-1]
        volume_sma_20 = pd.to_numeric(df["Volume_SMA_20"], errors="coerce").iloc[-1]
        if pd.notna(volume) and pd.notna(volume_sma_20) and volume_sma_20 != 0:
            volume_ratio = float(volume) / float(volume_sma_20)

    price_rising_ok = price_rising if require_price_rising else True
    peak_ok = peak_at_window_start if require_peak_at_window_start else True
    raw_signal = all(
        [
            hist_rising,
            price_rising_ok,
            hist_below_zero,
            near_zero_ok,
            hist_delta_ok,
            above_ema200,
            peak_ok,
            gap_above_ema20_ok,
            return_5d_ok,
            adx_ok,
            bias_ok,
        ]
    )

    return {
        "hist_rising": hist_rising,
        "price_rising": price_rising,
        "peak_at_window_start": peak_at_window_start,
        "hist_below_zero": hist_below_zero,
        "hist_abs_norm": hist_abs_norm,
        "near_zero_ok": near_zero_ok,
        "hist_delta_norm": hist_delta_norm,
        "hist_delta_ok": hist_delta_ok,
        "above_ema200": above_ema200,
        "gap_above_ema20_pct": gap_above_ema20_pct,
        "gap_above_ema20_ok": gap_above_ema20_ok,
        "return_5d": return_5d,
        "return_5d_ok": return_5d_ok,
        "adx_14": adx_14,
        "adx_ok": adx_ok,
        "bias_pct": bias_pct,
        "bias_ok": bias_ok,
        "bias_reference": bias_reference,
        "volume_ratio": volume_ratio,
        "peak_ok": peak_ok,
        "price_rising_ok": price_rising_ok,
        "raw_entry_signal": raw_signal,
    }


def _latest_precross_momentum_flags(
    df: pd.DataFrame,
    hist_rise_days: int = 3,
    price_rise_days: int = 3,
    require_price_rising: bool = True,
    require_hist_below_zero: bool = True,
    max_hist_abs_norm: float | None = None,
    min_hist_delta_norm: float | None = None,
    require_above_ema200: bool = False,
    require_peak_at_window_start: bool = False,
    max_gap_above_ema20_pct: float | None = None,
    max_return_5d: float | None = None,
    min_adx_14: float | None = None,
    max_bias_pct: float | None = None,
    max_buy_signal_streak_days: int | None = None,
    previous_raw_signal: bool | None = None,
    previous_streak_days: int | None = None,
) -> dict:
    latest_flags = _compute_latest_precross_raw_flags(
        df,
        hist_rise_days=hist_rise_days,
        price_rise_days=price_rise_days,
        require_price_rising=require_price_rising,
        require_hist_below_zero=require_hist_below_zero,
        max_hist_abs_norm=max_hist_abs_norm,
        min_hist_delta_norm=min_hist_delta_norm,
        require_above_ema200=require_above_ema200,
        require_peak_at_window_start=require_peak_at_window_start,
        max_gap_above_ema20_pct=max_gap_above_ema20_pct,
        max_return_5d=max_return_5d,
        min_adx_14=min_adx_14,
        max_bias_pct=max_bias_pct,
    )

    raw_signal = bool(latest_flags["raw_entry_signal"])
    if raw_signal:
        if previous_raw_signal is not None and previous_streak_days is not None:
            buy_signal_streak_days = (
                int(previous_streak_days) + 1 if bool(previous_raw_signal) else 1
            )
        else:
            batch_flags = build_precross_momentum_flags(
                df,
                hist_rise_days=hist_rise_days,
                price_rise_days=price_rise_days,
                require_price_rising=require_price_rising,
                require_hist_below_zero=require_hist_below_zero,
                max_hist_abs_norm=max_hist_abs_norm,
                min_hist_delta_norm=min_hist_delta_norm,
                require_above_ema200=require_above_ema200,
                require_peak_at_window_start=require_peak_at_window_start,
                max_gap_above_ema20_pct=max_gap_above_ema20_pct,
                max_return_5d=max_return_5d,
                min_adx_14=min_adx_14,
                max_bias_pct=max_bias_pct,
                max_buy_signal_streak_days=max_buy_signal_streak_days,
            ).iloc[-1]
            buy_signal_streak_days = int(batch_flags.get("buy_signal_streak_days", 0))
    else:
        buy_signal_streak_days = 0

    is_fresh_buy_signal = raw_signal and buy_signal_streak_days == 1
    stale_buy_signal = raw_signal and buy_signal_streak_days > 1
    if max_buy_signal_streak_days is None:
        fresh_buy_signal_ok = True
    else:
        fresh_buy_signal_ok = buy_signal_streak_days <= max(1, int(max_buy_signal_streak_days))

    latest_flags.update(
        {
            "buy_signal_streak_days": buy_signal_streak_days,
            "is_fresh_buy_signal": is_fresh_buy_signal,
            "stale_buy_signal": stale_buy_signal,
            "fresh_buy_signal_ok": fresh_buy_signal_ok,
            "signal": bool(raw_signal and fresh_buy_signal_ok),
        }
    )
    return latest_flags


class MACDPreCrossMomentumEntry(BaseEntryStrategy):
    """Enter before MACD crosses above zero when histogram and price both strengthen."""

    complexity = StrategyComplexity(
        numeric_param_count=6,
        extra_filter_count=4,
        conditional_rule_count=3,
    )

    def __init__(
        self,
        hist_rise_days: int = 3,
        price_rise_days: int = 3,
        require_price_rising: bool = True,
        require_hist_below_zero: bool = True,
        max_hist_abs_norm: float | None = None,
        min_hist_delta_norm: float | None = None,
        require_above_ema200: bool = False,
        require_peak_at_window_start: bool = False,
        max_gap_above_ema20_pct: float | None = None,
        max_return_5d: float | None = None,
        min_adx_14: float | None = None,
        max_bias_pct: float | None = None,
        follow_exit_bias_pct: bool = False,
        fallback_bias_pct: float = 15.0,
        min_confidence: float = 0.6,
        max_buy_signal_streak_days: int | None = None,
    ):
        super().__init__(strategy_name="MACDPreCrossMomentumEntry")
        self.hist_rise_days = max(2, int(hist_rise_days))
        self.price_rise_days = max(2, int(price_rise_days))
        self.require_price_rising = bool(require_price_rising)
        self.require_hist_below_zero = bool(require_hist_below_zero)
        self.max_hist_abs_norm = (
            None if max_hist_abs_norm is None else max(0.0, float(max_hist_abs_norm))
        )
        self.min_hist_delta_norm = (
            None
            if min_hist_delta_norm is None
            else max(0.0, float(min_hist_delta_norm))
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
        self.max_bias_pct = None if max_bias_pct is None else float(max_bias_pct)
        self.follow_exit_bias_pct = bool(follow_exit_bias_pct)
        self.fallback_bias_pct = float(fallback_bias_pct)
        if self.follow_exit_bias_pct and self.max_bias_pct is None:
            self.max_bias_pct = self.fallback_bias_pct
        self.bias_threshold_source = (
            "fallback"
            if self.follow_exit_bias_pct
            else ("fixed" if self.max_bias_pct is not None else None)
        )
        self.bound_exit_strategy_name = None
        self.min_confidence = float(min_confidence)
        self.max_buy_signal_streak_days = (
            None
            if max_buy_signal_streak_days is None
            else max(1, int(max_buy_signal_streak_days))
        )
        self._latest_flag_state_by_ticker: dict[str, dict[str, object]] = {}

    def bind_exit_bias_threshold(self, exit_strategy: object | None) -> None:
        if not self.follow_exit_bias_pct:
            return

        threshold = getattr(exit_strategy, "bias_exit_threshold_pct", None)
        if threshold is None:
            self.max_bias_pct = self.fallback_bias_pct
            self.bias_threshold_source = "fallback"
        else:
            self.max_bias_pct = float(threshold)
            self.bias_threshold_source = "exit"

        if exit_strategy is None:
            self.bound_exit_strategy_name = None
        else:
            self.bound_exit_strategy_name = getattr(
                exit_strategy,
                "strategy_name",
                exit_strategy.__class__.__name__,
            )

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

        previous_state = self._latest_flag_state_by_ticker.get(market_data.ticker)
        previous_raw_signal = None
        previous_streak_days = None
        if previous_state is not None:
            previous_len = int(previous_state.get("row_count", 0))
            previous_date = previous_state.get("last_date")
            if previous_len == len(df) - 1 and len(df) >= 2 and previous_date == df.index[-2]:
                previous_raw_signal = bool(previous_state.get("raw_entry_signal", False))
                previous_streak_days = int(previous_state.get("buy_signal_streak_days", 0))
            else:
                self._latest_flag_state_by_ticker.pop(market_data.ticker, None)

        latest_flags = _latest_precross_momentum_flags(
            df,
            hist_rise_days=self.hist_rise_days,
            price_rise_days=self.price_rise_days,
            require_price_rising=self.require_price_rising,
            require_hist_below_zero=self.require_hist_below_zero,
            max_hist_abs_norm=self.max_hist_abs_norm,
            min_hist_delta_norm=self.min_hist_delta_norm,
            require_above_ema200=self.require_above_ema200,
            require_peak_at_window_start=self.require_peak_at_window_start,
            max_gap_above_ema20_pct=self.max_gap_above_ema20_pct,
            max_return_5d=self.max_return_5d,
            min_adx_14=self.min_adx_14,
            max_bias_pct=self.max_bias_pct,
            max_buy_signal_streak_days=self.max_buy_signal_streak_days,
            previous_raw_signal=previous_raw_signal,
            previous_streak_days=previous_streak_days,
        )
        self._latest_flag_state_by_ticker[market_data.ticker] = {
            "row_count": len(df),
            "last_date": df.index[-1],
            "raw_entry_signal": bool(latest_flags.get("raw_entry_signal", False)),
            "buy_signal_streak_days": int(latest_flags.get("buy_signal_streak_days", 0)),
        }
        latest = df.iloc[-1]

        entry_stage = "NONE"
        if bool(latest_flags["signal"]):
            entry_stage = "PRE_CROSS_MOMENTUM"
        elif bool(latest_flags.get("raw_entry_signal", False)):
            entry_stage = "STALE_PRE_CROSS_MOMENTUM"

        metadata = {
            "entry_stage": entry_stage,
            "hist_rise_days": self.hist_rise_days,
            "price_rise_days": self.price_rise_days,
            "require_price_rising": self.require_price_rising,
            "require_hist_below_zero": self.require_hist_below_zero,
            "require_above_ema200": self.require_above_ema200,
            "require_peak_at_window_start": self.require_peak_at_window_start,
            "max_hist_abs_norm": self.max_hist_abs_norm,
            "min_hist_delta_norm": self.min_hist_delta_norm,
            "max_gap_above_ema20_pct": self.max_gap_above_ema20_pct,
            "max_return_5d": self.max_return_5d,
            "min_adx_14": self.min_adx_14,
            "max_bias_pct": self.max_bias_pct,
            "follow_exit_bias_pct": self.follow_exit_bias_pct,
            "fallback_bias_pct": self.fallback_bias_pct,
            "bias_threshold_source": self.bias_threshold_source,
            "bound_exit_strategy_name": self.bound_exit_strategy_name,
            "max_buy_signal_streak_days": self.max_buy_signal_streak_days,
            "raw_entry_signal": bool(latest_flags.get("raw_entry_signal", False)),
            "buy_signal_streak_days": int(latest_flags.get("buy_signal_streak_days", 0)),
            "is_fresh_buy_signal": bool(latest_flags.get("is_fresh_buy_signal", False)),
            "stale_buy_signal": bool(latest_flags.get("stale_buy_signal", False)),
            "macd_hist": float(pd.to_numeric(latest.get("MACD_Hist"), errors="coerce")),
            "macd_hist_prev": float(pd.to_numeric(df.iloc[-2].get("MACD_Hist"), errors="coerce")),
            "macd": float(pd.to_numeric(latest.get("MACD"), errors="coerce")),
            "macd_signal": float(pd.to_numeric(latest.get("MACD_Signal"), errors="coerce")),
            "close": float(pd.to_numeric(latest.get("Close"), errors="coerce")),
            "close_prev": float(pd.to_numeric(df.iloc[-2].get("Close"), errors="coerce")),
            "hist_abs_norm": float(pd.to_numeric(latest_flags.get("hist_abs_norm"), errors="coerce")),
            "hist_delta_norm": float(pd.to_numeric(latest_flags.get("hist_delta_norm"), errors="coerce")),
            "above_ema200": bool(latest_flags.get("above_ema200", False)),
            "peak_at_window_start": bool(latest_flags.get("peak_at_window_start", False)),
            "gap_above_ema20_pct": float(pd.to_numeric(latest_flags.get("gap_above_ema20_pct"), errors="coerce")),
            "return_5d": float(pd.to_numeric(latest_flags.get("return_5d"), errors="coerce")),
            "adx_14": float(pd.to_numeric(latest_flags.get("adx_14"), errors="coerce")),
            "bias_pct": float(pd.to_numeric(latest_flags.get("bias_pct"), errors="coerce")),
            "bias_reference": latest_flags.get("bias_reference"),
            "volume_ratio": float(pd.to_numeric(latest_flags.get("volume_ratio"), errors="coerce")),
        }

        if not bool(latest_flags["signal"]):
            reasons = []
            if (
                self.max_buy_signal_streak_days is not None
                and bool(latest_flags.get("raw_entry_signal", False))
                and not bool(latest_flags.get("fresh_buy_signal_ok", True))
            ):
                streak_days = int(latest_flags.get("buy_signal_streak_days", 0))
                reasons.append(
                    f"BUY signal stale: streak {streak_days} days > max {self.max_buy_signal_streak_days}"
                )
            if not bool(latest_flags["hist_rising"]):
                reasons.append("MACD histogram not rising consecutively")
            if self.require_price_rising and not bool(latest_flags["price_rising"]):
                reasons.append("Price not rising consecutively")
            if self.require_hist_below_zero and not bool(latest_flags["hist_below_zero"]):
                reasons.append("Histogram is not below zero")
            if self.max_hist_abs_norm is not None and not bool(latest_flags["near_zero_ok"]):
                reasons.append("Histogram is too far below zero axis")
            if self.min_hist_delta_norm is not None and not bool(latest_flags["hist_delta_ok"]):
                reasons.append("Histogram rise is too small")
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
            if self.max_bias_pct is not None and not bool(latest_flags["bias_ok"]):
                bias_pct = pd.to_numeric(latest_flags.get("bias_pct"), errors="coerce")
                bias_reference = latest_flags.get("bias_reference") or "SMA"
                if pd.notna(bias_pct):
                    reasons.append(
                        f"Bias overheat {float(bias_pct):.2f}% > {self.max_bias_pct:.2f}% vs {bias_reference}"
                    )
                else:
                    reasons.append("Bias overheat filter blocked entry")
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
        ]
        if self.require_price_rising:
            reasons.append(f"Price rising for {self.price_rise_days} bars")

        if self.require_peak_at_window_start:
            reasons.append("Rising window starts at the negative histogram peak")
        if self.min_hist_delta_norm is not None:
            reasons.append(f"Histogram rise >= {self.min_hist_delta_norm:.4f}")
        if self.max_gap_above_ema20_pct is not None:
            reasons.append(f"Gap above EMA20 <= {self.max_gap_above_ema20_pct:.2f}%")
        if self.max_return_5d is not None:
            reasons.append(f"Return_5d <= {self.max_return_5d:.2f}")
        if self.min_adx_14 is not None:
            reasons.append(f"ADX_14 >= {self.min_adx_14:.1f}")
        if self.max_bias_pct is not None:
            reasons.append(f"Bias <= {self.max_bias_pct:.2f}%")

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

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
        )
        self.strategy_name = "MACDPreCross2BarEntry"


class MACDPreCross2BarMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """2-bar pre-cross entry with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDPreCross2BarMaxBiasPct20Entry"


class MACDPreCross2BarRet5d008Entry(MACDPreCrossMomentumEntry):
    """CLI-friendly fixed variant for 2-bar pre-cross plus Return_5d filter."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            max_return_5d=0.08,
        )
        self.strategy_name = "MACDPreCross2BarRet5d008Entry"


class MACDPreCross2BarMinHistDeltaNorm0005Entry(MACDPreCrossMomentumEntry):
    """2-bar pre-cross that rejects tiny one-day histogram improvements."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            min_hist_delta_norm=0.0005,
        )
        self.strategy_name = "MACDPreCross2BarMinHistDeltaNorm0005Entry"


class MACDPreCross2BarMinHistDeltaNorm001Entry(MACDPreCrossMomentumEntry):
    """2-bar pre-cross with a 0.001 normalized histogram-rise floor."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            min_hist_delta_norm=0.001,
        )
        self.strategy_name = "MACDPreCross2BarMinHistDeltaNorm001Entry"


class MACDPreCross2BarMinHistDeltaNorm0015Entry(MACDPreCrossMomentumEntry):
    """2-bar pre-cross with a 0.0015 normalized histogram-rise floor."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            min_hist_delta_norm=0.0015,
        )
        self.strategy_name = "MACDPreCross2BarMinHistDeltaNorm0015Entry"


class MACDPreCross2BarMinHistDeltaNorm002Entry(MACDPreCrossMomentumEntry):
    """2-bar pre-cross with a 0.002 normalized histogram-rise floor."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            min_hist_delta_norm=0.002,
        )
        self.strategy_name = "MACDPreCross2BarMinHistDeltaNorm002Entry"


class MACDPreCross2BarLiteComboEntry(MACDPreCrossMomentumEntry):
    """CLI-friendly fixed variant for the current best LiteCombo entry."""

    complexity = StrategyComplexity(
        numeric_param_count=4,
        extra_filter_count=3,
        conditional_rule_count=3,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            max_hist_abs_norm=0.01,
            min_adx_14=10.0,
            max_return_5d=0.08,
        )
        self.strategy_name = "MACDPreCross2BarLiteComboEntry"


class MACDPreCrossHist2BarEntry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only (no price rising requirement)."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
        )
        self.strategy_name = "MACDPreCrossHist2BarEntry"


class MACDPreCrossHist2BarMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """2-bar histogram-only pre-cross entry with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDPreCrossHist2BarMaxBiasPct20Entry"


class MACDHist2BarAnySignEntry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, without requiring the latest bar below zero."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
        )
        self.strategy_name = "MACDHist2BarAnySignEntry"


class MACDHist2BarAnySignStrictFreshEntry(MACDPreCrossMomentumEntry):
    """2-bar any-sign histogram entry that only accepts the first raw BUY day."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_buy_signal_streak_days=1,
        )
        self.strategy_name = "MACDHist2BarAnySignStrictFreshEntry"


class MACDHist2BarAnySignMaxBiasPct15Entry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, but block buys when price is too extended above SMA."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=15.0,
        )
        self.strategy_name = "MACDHist2BarAnySignMaxBiasPct15Entry"


class MACDHist2BarAnySignMaxBiasPct10Entry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, with a 10% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=10.0,
        )
        self.strategy_name = "MACDHist2BarAnySignMaxBiasPct10Entry"


class MACDHist2BarAnySignMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDHist2BarAnySignMaxBiasPct20Entry"


class MACDHist2BarAnySignMaxBiasPct25Entry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, with a 25% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=25.0,
        )
        self.strategy_name = "MACDHist2BarAnySignMaxBiasPct25Entry"


class MACDHist2BarAnySignMaxBiasPct30Entry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, with a 30% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=30.0,
        )
        self.strategy_name = "MACDHist2BarAnySignMaxBiasPct30Entry"


class MACDHist2BarAnySignFollowExitBiasEntry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram rising only, using paired exit bias when available and 15% otherwise."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_price_rising=False,
            require_hist_below_zero=False,
            follow_exit_bias_pct=True,
            fallback_bias_pct=15.0,
        )
        self.strategy_name = "MACDHist2BarAnySignFollowExitBiasEntry"


class MACD2BarAnySignEntry(MACDPreCrossMomentumEntry):
    """2-bar MACD histogram + price rising, without requiring the latest bar below zero."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_hist_below_zero=False,
        )
        self.strategy_name = "MACD2BarAnySignEntry"


class MACD2BarAnySignMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """2-bar synchronized momentum entry, with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=2,
            price_rise_days=2,
            require_hist_below_zero=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACD2BarAnySignMaxBiasPct20Entry"


class MACDPreCrossHist3BarEntry(MACDPreCrossMomentumEntry):
    """3-bar MACD histogram rising only (no price rising requirement)."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_price_rising=False,
        )
        self.strategy_name = "MACDPreCrossHist3BarEntry"


class MACDPreCrossHist3BarMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """3-bar histogram-only pre-cross entry with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_price_rising=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDPreCrossHist3BarMaxBiasPct20Entry"


class MACDHist3BarAnySignEntry(MACDPreCrossMomentumEntry):
    """3-bar MACD histogram rising only, without requiring the latest bar below zero."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_price_rising=False,
            require_hist_below_zero=False,
        )
        self.strategy_name = "MACDHist3BarAnySignEntry"


class MACDHist3BarAnySignMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """3-bar MACD histogram rising only, with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_price_rising=False,
            require_hist_below_zero=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDHist3BarAnySignMaxBiasPct20Entry"


class MACDPreCross3BarEntry(MACDPreCrossMomentumEntry):
    """3-bar MACD histogram + price rising (synchronized momentum)."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
        )
        self.strategy_name = "MACDPreCross3BarEntry"


class MACDPreCross3BarMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """3-bar synchronized momentum entry with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACDPreCross3BarMaxBiasPct20Entry"


class MACD3BarAnySignEntry(MACDPreCrossMomentumEntry):
    """3-bar MACD histogram + price rising, without requiring the latest bar below zero."""

    complexity = StrategyComplexity(
        numeric_param_count=1,
        extra_filter_count=0,
        conditional_rule_count=1,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_hist_below_zero=False,
        )
        self.strategy_name = "MACD3BarAnySignEntry"


class MACD3BarAnySignMaxBiasPct20Entry(MACDPreCrossMomentumEntry):
    """3-bar synchronized momentum entry without sign constraint, with a 20% bias-overheat cap."""

    complexity = StrategyComplexity(
        numeric_param_count=2,
        extra_filter_count=1,
        conditional_rule_count=2,
    )

    def __init__(self):
        super().__init__(
            hist_rise_days=3,
            price_rise_days=3,
            require_hist_below_zero=False,
            max_bias_pct=20.0,
        )
        self.strategy_name = "MACD3BarAnySignMaxBiasPct20Entry"


_STRICT_FRESH_PARAM_NAMES = (
    "hist_rise_days",
    "price_rise_days",
    "require_price_rising",
    "require_hist_below_zero",
    "max_hist_abs_norm",
    "min_hist_delta_norm",
    "require_above_ema200",
    "require_peak_at_window_start",
    "max_gap_above_ema20_pct",
    "max_return_5d",
    "min_adx_14",
    "max_bias_pct",
    "follow_exit_bias_pct",
    "fallback_bias_pct",
    "min_confidence",
)


def _strict_fresh_strategy_name(base_cls: type[MACDPreCrossMomentumEntry]) -> str:
    base_name = base_cls.__name__
    if not base_name.endswith("Entry"):
        raise ValueError(f"Strict fresh variant requires an Entry class name: {base_name}")
    return f"{base_name.removesuffix('Entry')}StrictFreshEntry"


def _strict_fresh_complexity(base_cls: type[MACDPreCrossMomentumEntry]) -> StrategyComplexity:
    base_complexity = getattr(base_cls, "complexity", StrategyComplexity())
    return StrategyComplexity(
        numeric_param_count=base_complexity.numeric_param_count + 1,
        extra_filter_count=base_complexity.extra_filter_count + 1,
        conditional_rule_count=base_complexity.conditional_rule_count + 1,
    )


def _create_strict_fresh_variant(
    base_cls: type[MACDPreCrossMomentumEntry],
) -> type[MACDPreCrossMomentumEntry]:
    strategy_name = _strict_fresh_strategy_name(base_cls)
    base_instance = base_cls()
    base_params = {
        name: getattr(base_instance, name)
        for name in _STRICT_FRESH_PARAM_NAMES
    }

    def __init__(self) -> None:
        MACDPreCrossMomentumEntry.__init__(
            self,
            **base_params,
            max_buy_signal_streak_days=1,
        )
        self.strategy_name = strategy_name

    strict_doc = (
        ((base_cls.__doc__ or base_cls.__name__).rstrip("."))
        + " with strict fresh gating that only accepts the first raw BUY day."
    )
    strict_cls = type(
        strategy_name,
        (MACDPreCrossMomentumEntry,),
        {
            "__doc__": strict_doc,
            "__init__": __init__,
            "complexity": _strict_fresh_complexity(base_cls),
        },
    )
    strict_cls.__module__ = __name__
    return strict_cls


_STRICT_FRESH_VARIANT_BASE_CLASSES = (
    MACDHist2BarAnySignMaxBiasPct10Entry,
    MACDHist2BarAnySignMaxBiasPct15Entry,
    MACDHist2BarAnySignMaxBiasPct20Entry,
    MACDHist2BarAnySignMaxBiasPct25Entry,
    MACDHist2BarAnySignMaxBiasPct30Entry,
    MACDHist2BarAnySignFollowExitBiasEntry,
    MACD2BarAnySignEntry,
    MACD2BarAnySignMaxBiasPct20Entry,
    MACDPreCrossHist3BarEntry,
    MACDPreCrossHist3BarMaxBiasPct20Entry,
    MACDHist3BarAnySignEntry,
    MACDHist3BarAnySignMaxBiasPct20Entry,
    MACDPreCross3BarEntry,
    MACDPreCross3BarMaxBiasPct20Entry,
    MACD3BarAnySignEntry,
    MACD3BarAnySignMaxBiasPct20Entry,
)

GENERATED_STRICT_FRESH_VARIANT_NAMES: tuple[str, ...] = ()
for _base_cls in _STRICT_FRESH_VARIANT_BASE_CLASSES:
    _strict_cls = _create_strict_fresh_variant(_base_cls)
    globals()[_strict_cls.__name__] = _strict_cls
    GENERATED_STRICT_FRESH_VARIANT_NAMES += (_strict_cls.__name__,)


__all__ = [
    "MACDPreCrossMomentumEntry",
    "MACDPreCross2BarEntry",
    "MACDPreCross2BarMaxBiasPct20Entry",
    "MACDPreCross2BarRet5d008Entry",
    "MACDPreCross2BarMinHistDeltaNorm0005Entry",
    "MACDPreCross2BarMinHistDeltaNorm001Entry",
    "MACDPreCross2BarMinHistDeltaNorm0015Entry",
    "MACDPreCross2BarMinHistDeltaNorm002Entry",
    "MACDPreCross2BarLiteComboEntry",
    "MACDPreCrossHist2BarEntry",
    "MACDPreCrossHist2BarMaxBiasPct20Entry",
    "MACDHist2BarAnySignEntry",
    "MACDHist2BarAnySignStrictFreshEntry",
    "MACDHist2BarAnySignMaxBiasPct10Entry",
    "MACDHist2BarAnySignMaxBiasPct15Entry",
    "MACDHist2BarAnySignMaxBiasPct20Entry",
    "MACDHist2BarAnySignMaxBiasPct25Entry",
    "MACDHist2BarAnySignMaxBiasPct30Entry",
    "MACDHist2BarAnySignFollowExitBiasEntry",
    "MACD2BarAnySignEntry",
    "MACD2BarAnySignMaxBiasPct20Entry",
    "MACDPreCrossHist3BarEntry",
    "MACDPreCrossHist3BarMaxBiasPct20Entry",
    "MACDHist3BarAnySignEntry",
    "MACDHist3BarAnySignMaxBiasPct20Entry",
    "MACDPreCross3BarEntry",
    "MACDPreCross3BarMaxBiasPct20Entry",
    "MACD3BarAnySignEntry",
    "MACD3BarAnySignMaxBiasPct20Entry",
    *GENERATED_STRICT_FRESH_VARIANT_NAMES,
    "build_precross_momentum_flags",
]