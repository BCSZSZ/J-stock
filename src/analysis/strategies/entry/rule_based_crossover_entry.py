"""Rule-based crossover entry strategies with built-in entry filters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from ...signals import MarketData, SignalAction, TradingSignal
from ..base_entry_strategy import BaseEntryStrategy
from ..complexity import StrategyComplexity
from .crossover_utils import (
    crossed_up,
    gt_latest,
    macd_position_ok,
    rsi_not_overheated,
    safe_float,
    volume_ratio,
    volume_ratio_ok,
)


@dataclass(frozen=True)
class RuleResult:
    name: str
    passed: bool
    reason: str
    values: Mapping[str, object]


class RuleBasedCrossoverEntry(BaseEntryStrategy):
    """Base class for fixed, auditable crossover entry combinations."""

    complexity = StrategyComplexity(
        numeric_param_count=3,
        extra_filter_count=3,
        conditional_rule_count=5,
    )

    def __init__(
        self,
        *,
        strategy_name: str,
        rule_profile: str,
        buy_confidence: float = 0.78,
    ) -> None:
        super().__init__(strategy_name=strategy_name)
        self.rule_profile = rule_profile
        self.buy_confidence = float(buy_confidence)

    def _evaluate_rule_results(self, df: pd.DataFrame) -> list[RuleResult]:
        raise NotImplementedError

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features
        if df.empty or len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                metadata={"rule_profile": self.rule_profile, "score": 0.0},
                strategy_name=self.strategy_name,
            )

        results = self._evaluate_rule_results(df)
        passed_count = sum(1 for result in results if result.passed)
        score = (passed_count / len(results) * 100.0) if results else 0.0
        failed = next((result for result in results if not result.passed), None)
        metadata = self._build_metadata(results, score, failed)

        if failed is not None:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=min(score / 100.0, max(0.0, self.buy_confidence - 0.01)),
                reasons=[f"{failed.name} failed: {failed.reason}"],
                metadata=metadata,
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.BUY,
            confidence=self.buy_confidence,
            reasons=[f"{self.rule_profile} rules passed"],
            metadata=metadata,
            strategy_name=self.strategy_name,
        )

    def _build_metadata(
        self,
        results: list[RuleResult],
        score: float,
        failed: RuleResult | None,
    ) -> dict[str, object]:
        return {
            "rule_profile": self.rule_profile,
            "score": float(score),
            "failed_rule": failed.name if failed is not None else None,
            "rules": {
                result.name: {
                    "passed": bool(result.passed),
                    "reason": result.reason,
                    **dict(result.values),
                }
                for result in results
            },
        }


class CrossTrendMACDVolumeEntry(RuleBasedCrossoverEntry):
    """Trend up, MACD golden cross, positive MACD position, and volume confirm."""

    def __init__(
        self,
        *,
        macd_position_mode: str = "above_zero",
        near_zero_abs: float = 0.02,
        volume_multiplier: float = 1.2,
    ) -> None:
        super().__init__(
            strategy_name="CrossTrendMACDVolumeEntry",
            rule_profile="trend_macd_volume",
            buy_confidence=0.80,
        )
        self.macd_position_mode = str(macd_position_mode)
        self.near_zero_abs = float(near_zero_abs)
        self.volume_multiplier = float(volume_multiplier)

    def _evaluate_rule_results(self, df: pd.DataFrame) -> list[RuleResult]:
        latest_close = _latest_value(df, "Close")
        latest_sma20 = _latest_indicator(df, "SMA_20", rolling_window=20)
        latest_sma60 = _latest_indicator(df, "SMA_60", rolling_window=60)
        macd_prev, macd_now = _previous_and_latest_value(df, "MACD")
        signal_prev, signal_now = _previous_and_latest_value(df, "MACD_Signal")
        volume_now = _latest_value(df, "Volume")
        volume_avg = _latest_indicator(df, "Volume_SMA_20", rolling_window=20)
        ratio = volume_ratio(volume_now, volume_avg)

        return [
            RuleResult(
                name="close_above_sma60",
                passed=gt_latest(latest_close, latest_sma60),
                reason="Close > SMA60" if gt_latest(latest_close, latest_sma60) else "Close <= SMA60 or SMA60 missing",
                values={"close": latest_close, "sma60": latest_sma60},
            ),
            RuleResult(
                name="sma20_above_sma60",
                passed=gt_latest(latest_sma20, latest_sma60),
                reason="SMA20 > SMA60" if gt_latest(latest_sma20, latest_sma60) else "SMA20 <= SMA60 or SMA missing",
                values={"sma20": latest_sma20, "sma60": latest_sma60},
            ),
            RuleResult(
                name="macd_golden_cross",
                passed=crossed_up(macd_prev, signal_prev, macd_now, signal_now),
                reason=(
                    "MACD crossed above signal"
                    if crossed_up(macd_prev, signal_prev, macd_now, signal_now)
                    else "MACD did not cross above signal"
                ),
                values={
                    "macd_prev": macd_prev,
                    "macd": macd_now,
                    "macd_signal_prev": signal_prev,
                    "macd_signal": signal_now,
                },
            ),
            RuleResult(
                name="macd_position",
                passed=macd_position_ok(
                    macd_now,
                    signal_now,
                    mode=self.macd_position_mode,
                    near_zero_abs=self.near_zero_abs,
                ),
                reason=(
                    f"MACD position ok ({self.macd_position_mode})"
                    if macd_position_ok(
                        macd_now,
                        signal_now,
                        mode=self.macd_position_mode,
                        near_zero_abs=self.near_zero_abs,
                    )
                    else f"MACD position failed ({self.macd_position_mode})"
                ),
                values={
                    "macd": macd_now,
                    "macd_signal": signal_now,
                    "macd_position_mode": self.macd_position_mode,
                    "near_zero_abs": self.near_zero_abs,
                },
            ),
            RuleResult(
                name="volume_confirmation",
                passed=volume_ratio_ok(
                    volume_now,
                    volume_avg,
                    self.volume_multiplier,
                ),
                reason=(
                    f"Volume >= {self.volume_multiplier:.2f}x average"
                    if volume_ratio_ok(volume_now, volume_avg, self.volume_multiplier)
                    else f"Volume < {self.volume_multiplier:.2f}x average or missing"
                ),
                values={
                    "volume": volume_now,
                    "volume_sma20": volume_avg,
                    "volume_ratio": ratio,
                    "volume_multiplier": self.volume_multiplier,
                },
            ),
        ]


class CrossTrendMACDVolumeLooseEntry(CrossTrendMACDVolumeEntry):
    """Trend + MACD + volume combo without zero-axis MACD position gating."""

    def __init__(self) -> None:
        super().__init__(macd_position_mode="any")
        self.strategy_name = "CrossTrendMACDVolumeLooseEntry"
        self.rule_profile = "trend_macd_volume_loose"
        self.buy_confidence = 0.76


class CrossReboundKDJRSIEntry(RuleBasedCrossoverEntry):
    """Short rebound combo using MA5/MA10, low KDJ cross, and RSI cap."""

    def __init__(
        self,
        *,
        kdj_k_max: float = 50.0,
        rsi_max: float = 70.0,
    ) -> None:
        super().__init__(
            strategy_name="CrossReboundKDJRSIEntry",
            rule_profile="rebound_kdj_rsi",
            buy_confidence=0.74,
        )
        self.kdj_k_max = float(kdj_k_max)
        self.rsi_max = float(rsi_max)

    def _evaluate_rule_results(self, df: pd.DataFrame) -> list[RuleResult]:
        latest_close = _latest_value(df, "Close")
        latest_sma10 = _latest_indicator(df, "SMA_10", rolling_window=10)
        sma5_prev, sma5_now = _previous_and_latest_indicator(
            df,
            "SMA_5",
            rolling_window=5,
        )
        sma10_prev, sma10_now = _previous_and_latest_indicator(
            df,
            "SMA_10",
            rolling_window=10,
        )
        k_prev, k_now = _previous_and_latest_value(df, "KDJ_K_9")
        d_prev, d_now = _previous_and_latest_value(df, "KDJ_D_9")
        rsi_now = _latest_value(df, "RSI_9")
        if rsi_now is None:
            rsi_now = _latest_value(df, "RSI")
        kdj_cross = crossed_up(k_prev, d_prev, k_now, d_now)
        kdj_low = k_now is not None and k_now < self.kdj_k_max

        return [
            RuleResult(
                name="close_above_sma10",
                passed=gt_latest(latest_close, latest_sma10),
                reason="Close > SMA10" if gt_latest(latest_close, latest_sma10) else "Close <= SMA10 or SMA10 missing",
                values={"close": latest_close, "sma10": latest_sma10},
            ),
            RuleResult(
                name="sma5_cross_sma10",
                passed=crossed_up(sma5_prev, sma10_prev, sma5_now, sma10_now),
                reason=(
                    "SMA5 crossed above SMA10"
                    if crossed_up(sma5_prev, sma10_prev, sma5_now, sma10_now)
                    else "SMA5 did not cross above SMA10"
                ),
                values={
                    "sma5_prev": sma5_prev,
                    "sma5": sma5_now,
                    "sma10_prev": sma10_prev,
                    "sma10": sma10_now,
                },
            ),
            RuleResult(
                name="kdj_low_golden_cross",
                passed=kdj_cross and kdj_low,
                reason=(
                    f"KDJ crossed low with K < {self.kdj_k_max:.1f}"
                    if kdj_cross and kdj_low
                    else f"KDJ low golden cross missing or K >= {self.kdj_k_max:.1f}"
                ),
                values={
                    "kdj_k_prev": k_prev,
                    "kdj_k": k_now,
                    "kdj_d_prev": d_prev,
                    "kdj_d": d_now,
                    "kdj_k_max": self.kdj_k_max,
                },
            ),
            RuleResult(
                name="rsi_not_overheated",
                passed=rsi_not_overheated(rsi_now, self.rsi_max),
                reason=(
                    f"RSI < {self.rsi_max:.1f}"
                    if rsi_not_overheated(rsi_now, self.rsi_max)
                    else f"RSI >= {self.rsi_max:.1f} or missing"
                ),
                values={"rsi": rsi_now, "rsi_max": self.rsi_max},
            ),
        ]


def _latest_value(df: pd.DataFrame, column: str) -> float | None:
    if column not in df.columns or df.empty:
        return None
    return safe_float(pd.to_numeric(df[column], errors="coerce").iloc[-1])


def _previous_and_latest_value(
    df: pd.DataFrame,
    column: str,
) -> tuple[float | None, float | None]:
    if column not in df.columns or len(df) < 2:
        return None, None
    numeric = pd.to_numeric(df[column], errors="coerce")
    return safe_float(numeric.iloc[-2]), safe_float(numeric.iloc[-1])


def _indicator_series(
    df: pd.DataFrame,
    column: str,
    *,
    rolling_window: int,
) -> pd.Series | None:
    if column in df.columns:
        return pd.to_numeric(df[column], errors="coerce")
    if "Close" not in df.columns:
        return None
    close = pd.to_numeric(df["Close"], errors="coerce")
    return close.rolling(window=rolling_window).mean()


def _latest_indicator(
    df: pd.DataFrame,
    column: str,
    *,
    rolling_window: int,
) -> float | None:
    series = _indicator_series(df, column, rolling_window=rolling_window)
    if series is None or series.empty:
        return None
    return safe_float(series.iloc[-1])


def _previous_and_latest_indicator(
    df: pd.DataFrame,
    column: str,
    *,
    rolling_window: int,
) -> tuple[float | None, float | None]:
    series = _indicator_series(df, column, rolling_window=rolling_window)
    if series is None or len(series) < 2:
        return None, None
    return safe_float(series.iloc[-2]), safe_float(series.iloc[-1])


__all__ = [
    "CrossReboundKDJRSIEntry",
    "CrossTrendMACDVolumeEntry",
    "CrossTrendMACDVolumeLooseEntry",
    "RuleBasedCrossoverEntry",
]
