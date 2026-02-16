"""
MACD + KDJ Three-Stage Entry Strategy

Rules:
1) MACD histogram converging: 2*(DIF-DEA) increasing
2) KDJ oversold golden cross: D < 30 and K crosses above D
3) Price support: Close > LLV9 and Close > SMA20
"""

from typing import List

import pandas as pd

from src.analysis.signals import MarketData, SignalAction, TradingSignal
from src.analysis.strategies.base_entry_strategy import BaseEntryStrategy


class MACDKDJThreeStageEntry(BaseEntryStrategy):
    """
    MACD + KDJ three-stage entry strategy.

    Args:
        kd_oversold_threshold: Oversold threshold for D (default 30)
        llv_window: Low rolling window for support check (default 9)
        ma_window: SMA window (default 20)
    """

    def __init__(
        self,
        kd_oversold_threshold: float = 30.0,
        llv_window: int = 9,
        ma_window: int = 20,
        require_above_ema200: bool = True,
        require_macd_positive: bool = False,
        max_atr_pct: float = 0.06,
    ):
        super().__init__(strategy_name="MACDKDJThreeStageEntry")
        self.kd_oversold_threshold = kd_oversold_threshold
        self.llv_window = llv_window
        self.ma_window = ma_window
        self.require_above_ema200 = require_above_ema200
        self.require_macd_positive = require_macd_positive
        self.max_atr_pct = max_atr_pct

    def generate_entry_signal(self, market_data: MarketData) -> TradingSignal:
        df = market_data.df_features

        min_bars = max(self.llv_window, self.ma_window, 2)
        if df.empty or len(df) < min_bars:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required_fields: List[str] = [
            "Close",
            "Low",
            "MACD",
            "MACD_Signal",
            "MACD_Hist",
            "KDJ_K_9",
            "KDJ_D_9",
            "SMA_20",
            "EMA_200",
            "ATR",
        ]
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        if any(
            pd.isna(latest[field])
            for field in ["MACD_Hist", "KDJ_K_9", "KDJ_D_9", "SMA_20", "EMA_200", "ATR"]
        ):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Latest indicators contain NaN"],
                strategy_name=self.strategy_name,
            )
        if (
            pd.isna(prev["MACD_Hist"])
            or pd.isna(prev["KDJ_K_9"])
            or pd.isna(prev["KDJ_D_9"])
        ):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Previous indicators contain NaN"],
                strategy_name=self.strategy_name,
            )

        macd_hist_now = 2 * latest["MACD_Hist"]
        macd_hist_prev = 2 * prev["MACD_Hist"]
        macd_converging = macd_hist_now > macd_hist_prev

        k_now = latest["KDJ_K_9"]
        d_now = latest["KDJ_D_9"]
        k_prev = prev["KDJ_K_9"]
        d_prev = prev["KDJ_D_9"]
        kdj_golden_cross = (k_prev <= d_prev) and (k_now > d_now)
        kdj_oversold = d_now < self.kd_oversold_threshold

        llv9 = df["Low"].rolling(self.llv_window).min().iloc[-1]
        sma20 = latest["SMA_20"]
        close = latest["Close"]
        price_support = (
            pd.notna(llv9) and pd.notna(sma20) and close > llv9 and close > sma20
        )

        ema200 = latest["EMA_200"]
        trend_ok = True
        if self.require_above_ema200:
            trend_ok = close > ema200
        if trend_ok and self.require_macd_positive:
            trend_ok = latest["MACD"] > 0

        atr = latest["ATR"]
        atr_pct = (atr / close) if close else None
        volatility_ok = atr_pct is not None and atr_pct <= self.max_atr_pct

        if not macd_converging:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["MACD histogram not converging"],
                metadata={
                    "macd_hist_rule": float(macd_hist_now),
                    "macd_hist_prev": float(macd_hist_prev),
                },
                strategy_name=self.strategy_name,
            )

        if not (kdj_oversold and kdj_golden_cross):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["No oversold KDJ golden cross"],
                metadata={
                    "kdj_k": float(k_now),
                    "kdj_d": float(d_now),
                    "kdj_oversold": bool(kdj_oversold),
                    "kdj_golden_cross": bool(kdj_golden_cross),
                },
                strategy_name=self.strategy_name,
            )

        if not price_support:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Price not above support/SMA20"],
                metadata={
                    "close": float(close),
                    "llv": float(llv9) if pd.notna(llv9) else 0.0,
                    "sma20": float(sma20) if pd.notna(sma20) else 0.0,
                },
                strategy_name=self.strategy_name,
            )

        if not trend_ok:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Trend filter not satisfied"],
                metadata={
                    "close": float(close),
                    "ema_200": float(ema200) if pd.notna(ema200) else 0.0,
                    "macd": float(latest["MACD"]),
                },
                strategy_name=self.strategy_name,
            )

        if not volatility_ok:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Volatility too high"],
                metadata={
                    "atr_pct": float(atr_pct) if atr_pct is not None else 0.0,
                    "max_atr_pct": float(self.max_atr_pct),
                },
                strategy_name=self.strategy_name,
            )

        macd_slope = macd_hist_now - macd_hist_prev
        kdj_strength = max(
            0.0, (self.kd_oversold_threshold - d_now) / self.kd_oversold_threshold
        )
        price_strength = max(0.0, (close - sma20) / sma20) if sma20 else 0.0
        trend_strength = max(0.0, (close - ema200) / ema200) if ema200 else 0.0
        score = 50.0
        score += min(max(macd_slope * 50.0, 0.0), 20.0)
        score += min(kdj_strength * 20.0, 20.0)
        score += min(price_strength * 20.0, 10.0)
        score += min(trend_strength * 20.0, 10.0)

        return TradingSignal(
            action=SignalAction.BUY,
            confidence=0.75,
            reasons=[
                "MACD histogram converging",
                "KDJ oversold golden cross",
                "Price above LLV9 and SMA20",
                "Trend filter passed",
                "Volatility filter passed",
            ],
            metadata={
                "score": float(score),
                "macd_hist_rule": float(macd_hist_now),
                "kdj_k": float(k_now),
                "kdj_d": float(d_now),
                "llv": float(llv9) if pd.notna(llv9) else 0.0,
                "sma20": float(sma20) if pd.notna(sma20) else 0.0,
                "close": float(close),
                "ema_200": float(ema200) if pd.notna(ema200) else 0.0,
                "atr_pct": float(atr_pct) if atr_pct is not None else 0.0,
            },
            strategy_name=self.strategy_name,
        )


class MACDKDJThreeStageEntryA(MACDKDJThreeStageEntry):
    def __init__(self):
        super().__init__(
            kd_oversold_threshold=20.0,
            require_above_ema200=True,
            require_macd_positive=True,
            max_atr_pct=0.04,
        )
        self.strategy_name = "MACDKDJThreeStageEntryA"


class MACDKDJThreeStageEntryB(MACDKDJThreeStageEntry):
    def __init__(self):
        super().__init__(
            kd_oversold_threshold=25.0,
            require_above_ema200=True,
            require_macd_positive=False,
            max_atr_pct=0.06,
        )
        self.strategy_name = "MACDKDJThreeStageEntryB"
