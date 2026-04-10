"""
Multi-view composite exit strategy with a single default parameter set.

Design layers:
1) L2 Signal inversion: MACD histogram shrinking for N consecutive bars
2) R1 Risk: ATR trailing stop
3) Profit: +1R -> SELL 50%, +2R -> SELL 100%, optional SMA20 bias overheat full exit
4) Time hard exit: force close after max holding trading days

The historical 243-grid variants are deprecated. This module now exposes a
single default MVX parameter set for evaluation and production use.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict

import pandas as pd

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class MultiViewCompositeExit(BaseExitStrategy):
    """Composite exit strategy with configurable parameters."""

    def __init__(
        self,
        hist_shrink_n: int = 9,
        r_mult: float = 3.4,
        trail_mult: float = 1.6,
        time_stop_days: int = 18,
        bias_exit_threshold_pct: float = 20.0,
        tp1_r: float = 1.0,
        tp2_r: float = 2.0,
    ):
        super().__init__(strategy_name="MultiViewCompositeExit")
        self.hist_shrink_n = int(hist_shrink_n)
        self.r_mult = float(r_mult)
        self.trail_mult = float(trail_mult)
        self.time_stop_days = int(time_stop_days)
        self.bias_exit_threshold_pct = float(bias_exit_threshold_pct)
        self.tp1_r = float(tp1_r)
        self.tp2_r = float(tp2_r)

    def _l2_is_triggered(self, df_features: pd.DataFrame) -> bool:
        return self._hist_shrinking(df_features, self.hist_shrink_n)

    def _l2_trigger_name(self) -> str:
        return "L2_HistShrink"

    def _l2_reason(self) -> str:
        return f"L2 histogram shrink x{self.hist_shrink_n}"

    def _l2_threshold(self) -> str:
        return "consecutive decline"

    def get_evaluation_details(
        self, position: Position, market_data: MarketData
    ) -> Dict:
        """
        Get detailed evaluation for each exit layer (for reporting).

        Returns dict with:
        - layers: list of {name, status, value, threshold, triggered}
        - summary: overall assessment
        """
        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return {"layers": [], "summary": "Insufficient data"}

        required = ["Close", "ATR", "MACD_Hist"]
        if not all(col in df.columns for col in required):
            return {"layers": [], "summary": "Missing indicators"}

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]

        if pd.isna(current_atr) or current_atr <= 0:
            return {"layers": [], "summary": "Invalid ATR"}

        entry_atr = self._resolve_entry_atr(df, position.entry_date, current_atr)
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_r = pnl_abs / r_value
        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )

        layers = []

        # R1: ATR trailing stop
        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        layers.append(
            {
                "name": "R1_TrailingStop",
                "status": "SAFE" if current_price >= trail_level else "TRIGGER",
                "value": f"¥{current_price:.2f}",
                "threshold": f"¥{trail_level:.2f}",
                "triggered": current_price < trail_level,
            }
        )

        # L2: Histogram shrinking
        hist_shrinking = self._l2_is_triggered(df)
        layers.append(
            {
                "name": self._l2_trigger_name(),
                "status": "TRIGGER" if hist_shrinking else "PASS",
                "value": f"{self.hist_shrink_n} bars",
                "threshold": self._l2_threshold(),
                "triggered": hist_shrinking,
            }
        )

        # T1: Time stop
        layers.append(
            {
                "name": "T1_TimeStop",
                "status": "TRIGGER" if holding_days >= self.time_stop_days else "SAFE",
                "value": f"{holding_days} days",
                "threshold": f"{self.time_stop_days} days",
                "triggered": holding_days >= self.time_stop_days,
            }
        )

        # P: Profit takes
        tp2_triggered = pnl_abs >= self.tp2_r * r_value
        tp1_triggered = pnl_abs >= self.tp1_r * r_value

        bias_pct = self._calc_bias_pct(latest)
        bias_triggered = (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        )

        layers.append(
            {
                "name": "P_TP2",
                "status": "TRIGGER" if tp2_triggered else "PENDING",
                "value": f"+{pnl_r:.2f}R",
                "threshold": f"+{self.tp2_r:.1f}R",
                "triggered": tp2_triggered,
            }
        )

        layers.append(
            {
                "name": "P_TP1",
                "status": "TRIGGER" if tp1_triggered else "PENDING",
                "value": f"+{pnl_r:.2f}R",
                "threshold": f"+{self.tp1_r:.1f}R",
                "triggered": tp1_triggered,
            }
        )

        if bias_pct is not None:
            layers.append(
                {
                    "name": "P_BiasOverheat",
                    "status": "TRIGGER" if bias_triggered else "PASS",
                    "value": f"{bias_pct:.1f}%",
                    "threshold": f"{self.bias_exit_threshold_pct:.1f}%",
                    "triggered": bias_triggered,
                }
            )

        triggered_count = sum(1 for layer in layers if layer["triggered"])
        summary = f"{triggered_count}/{len(layers)} conditions triggered"

        return {
            "layers": layers,
            "summary": summary,
            "r_value": float(r_value),
            "pnl_r": float(pnl_r),
            "holding_days": int(holding_days),
        }

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required = ["Close", "ATR", "MACD_Hist"]
        if not all(col in df.columns for col in required):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]
        if pd.isna(current_atr) or current_atr <= 0:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Invalid ATR"],
                strategy_name=self.strategy_name,
            )

        entry_atr = self._resolve_entry_atr(df, position.entry_date, current_atr)
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_pct = position.current_pnl_pct(current_price)

        # R1: ATR trailing risk stop (full exit)
        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        if current_price < trail_level:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=1.0,
                reason=f"R1 trailing stop: {current_price:.2f} < {trail_level:.2f}",
                trigger="R1_ATRTrailing",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # L2: signal inversion by momentum decay (full exit)
        if self._l2_is_triggered(df):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.9,
                reason=self._l2_reason(),
                trigger=self._l2_trigger_name(),
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # Time hard exit (full exit)
        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )
        if holding_days >= self.time_stop_days:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.85,
                reason=f"Time stop: {holding_days} days",
                trigger="T1_TimeStop",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # Profit exits
        if pnl_abs >= self.tp2_r * r_value:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.8,
                reason=f"TP2 hit: +{self.tp2_r:.1f}R",
                trigger="P_TP2",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        bias_pct = self._calc_bias_pct(latest)
        if (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        ):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.75,
                reason=f"Bias overheat: {bias_pct:.2f}% >= {self.bias_exit_threshold_pct:.2f}%",
                trigger="P_BiasOverheat",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        if pnl_abs >= self.tp1_r * r_value:
            return self._sell_signal(
                sell_percentage=0.5,
                confidence=0.7,
                reason=f"TP1 hit: +{self.tp1_r:.1f}R",
                trigger="P_TP1",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No exit condition met"],
            metadata={
                "r_value": float(r_value),
                "pnl_pct": float(pnl_pct),
                "holding_days": int(holding_days),
            },
            strategy_name=self.strategy_name,
        )

    def _sell_signal(
        self,
        sell_percentage: float,
        confidence: float,
        reason: str,
        trigger: str,
        r_value: float,
        pnl_pct: float,
    ) -> TradingSignal:
        return TradingSignal(
            action=SignalAction.SELL,
            confidence=confidence,
            reasons=[reason],
            metadata={
                "trigger": trigger,
                "sell_percentage": float(sell_percentage),
                "r_value": float(r_value),
                "pnl_pct": float(pnl_pct),
            },
            strategy_name=self.strategy_name,
        )

    @staticmethod
    def _calc_bias_pct(latest_row: pd.Series):
        # Use SMA_25 for bias calculation (Japanese market standard for mean reversion)
        # SMA_25 is the statistical reference for 乖離率 (deviation rate) in JP market
        sma_col = "SMA_25" if "SMA_25" in latest_row.index else "SMA_20"

        if sma_col not in latest_row.index:
            return None
        sma = latest_row[sma_col]
        close = latest_row["Close"]
        if pd.isna(sma) or sma == 0 or pd.isna(close):
            return None
        return float((close - sma) / sma * 100.0)

    @staticmethod
    def _count_trading_days(
        df_features: pd.DataFrame,
        entry_date: pd.Timestamp,
        current_date: pd.Timestamp,
    ) -> int:
        idx = df_features.index
        mask = (idx >= entry_date) & (idx <= current_date)
        return int(mask.sum())

    @staticmethod
    def _resolve_entry_atr(
        df_features: pd.DataFrame,
        entry_date: pd.Timestamp,
        fallback_atr: float,
    ) -> float:
        eligible = df_features[df_features.index <= entry_date]
        if not eligible.empty and "ATR" in eligible.columns:
            atr = eligible.iloc[-1]["ATR"]
            if pd.notna(atr) and atr > 0:
                return float(atr)

        atr_series = (
            df_features["ATR"].dropna()
            if "ATR" in df_features.columns
            else pd.Series(dtype=float)
        )
        if not atr_series.empty:
            val = atr_series.iloc[-1]
            if pd.notna(val) and val > 0:
                return float(val)

        return float(fallback_atr)

    @staticmethod
    def _hist_shrinking(df_features: pd.DataFrame, n: int) -> bool:
        hist = df_features["MACD_Hist"].tail(n + 1)
        if len(hist) < n + 1 or hist.isna().any():
            return False
        diffs = hist.diff().tail(n)
        return bool((diffs < 0).all())

    @staticmethod
    def _hist_window_decay(df_features: pd.DataFrame, n: int) -> bool:
        hist = df_features["MACD_Hist"].tail(n + 1)
        if len(hist) < n + 1 or hist.isna().any():
            return False

        diffs = hist.diff().tail(n)
        if len(diffs) < n or diffs.isna().any():
            return False

        negative_changes = int((diffs < 0).sum())
        if negative_changes < max(n - 1, 0):
            return False

        if not bool(diffs.iloc[-1] < 0):
            return False

        y_values = [float(value) for value in hist.tolist()]
        x_values = list(range(len(y_values)))
        x_mean = sum(x_values) / len(x_values)
        y_mean = sum(y_values) / len(y_values)
        numerator = sum(
            (x_value - x_mean) * (y_value - y_mean)
            for x_value, y_value in zip(x_values, y_values)
        )
        denominator = sum((x_value - x_mean) ** 2 for x_value in x_values)
        if denominator == 0:
            return False

        slope = numerator / denominator
        return slope < 0.0

    @staticmethod
    def _macd_dead_cross(df_features: pd.DataFrame) -> bool:
        if (
            df_features.empty
            or len(df_features) < 2
            or "MACD" not in df_features.columns
            or "MACD_Signal" not in df_features.columns
        ):
            return False

        tail = df_features[["MACD", "MACD_Signal"]].tail(2)
        if tail.isna().any().any():
            return False

        prev = tail.iloc[-2]
        curr = tail.iloc[-1]
        return bool(
            prev["MACD"] >= prev["MACD_Signal"]
            and curr["MACD"] < curr["MACD_Signal"]
        )


class MVXNew_N3_R3p25_T1p6_D21_B20p0(MultiViewCompositeExit):
    """Production MVX parameters plus an extra MACD dead-cross full exit."""

    def __init__(self):
        super().__init__(
            hist_shrink_n=3,
            r_mult=3.25,
            trail_mult=1.6,
            time_stop_days=21,
            bias_exit_threshold_pct=20.0,
        )
        self.strategy_name = "MVXNew_N3_R3p25_T1p6_D21_B20p0"

    def get_evaluation_details(
        self, position: Position, market_data: MarketData
    ) -> Dict:
        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return {"layers": [], "summary": "Insufficient data"}

        required = ["Close", "ATR", "MACD_Hist", "MACD", "MACD_Signal"]
        if not all(col in df.columns for col in required):
            return {"layers": [], "summary": "Missing indicators"}

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]

        if pd.isna(current_atr) or current_atr <= 0:
            return {"layers": [], "summary": "Invalid ATR"}

        entry_atr = self._resolve_entry_atr(df, position.entry_date, current_atr)
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_r = pnl_abs / r_value
        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )

        layers = []

        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        layers.append(
            {
                "name": "R1_TrailingStop",
                "status": "SAFE" if current_price >= trail_level else "TRIGGER",
                "value": f"¥{current_price:.2f}",
                "threshold": f"¥{trail_level:.2f}",
                "triggered": current_price < trail_level,
            }
        )

        hist_shrinking = self._hist_shrinking(df, self.hist_shrink_n)
        layers.append(
            {
                "name": "L2_HistShrink",
                "status": "TRIGGER" if hist_shrinking else "PASS",
                "value": f"{self.hist_shrink_n} bars",
                "threshold": "consecutive decline",
                "triggered": hist_shrinking,
            }
        )

        macd_dead_cross = self._macd_dead_cross(df)
        layers.append(
            {
                "name": "L3_MACD_DeadCross",
                "status": "TRIGGER" if macd_dead_cross else "PASS",
                "value": (
                    f"DIF {latest['MACD']:.2f} vs DEA {latest['MACD_Signal']:.2f}"
                ),
                "threshold": "cross below signal",
                "triggered": macd_dead_cross,
            }
        )

        layers.append(
            {
                "name": "T1_TimeStop",
                "status": "TRIGGER" if holding_days >= self.time_stop_days else "SAFE",
                "value": f"{holding_days} days",
                "threshold": f"{self.time_stop_days} days",
                "triggered": holding_days >= self.time_stop_days,
            }
        )

        tp2_triggered = pnl_abs >= self.tp2_r * r_value
        tp1_triggered = pnl_abs >= self.tp1_r * r_value

        bias_pct = self._calc_bias_pct(latest)
        bias_triggered = (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        )

        layers.append(
            {
                "name": "P_TP2",
                "status": "TRIGGER" if tp2_triggered else "PENDING",
                "value": f"+{pnl_r:.2f}R",
                "threshold": f"+{self.tp2_r:.1f}R",
                "triggered": tp2_triggered,
            }
        )

        layers.append(
            {
                "name": "P_TP1",
                "status": "TRIGGER" if tp1_triggered else "PENDING",
                "value": f"+{pnl_r:.2f}R",
                "threshold": f"+{self.tp1_r:.1f}R",
                "triggered": tp1_triggered,
            }
        )

        if bias_pct is not None:
            layers.append(
                {
                    "name": "P_BiasOverheat",
                    "status": "TRIGGER" if bias_triggered else "PASS",
                    "value": f"{bias_pct:.1f}%",
                    "threshold": f"{self.bias_exit_threshold_pct:.1f}%",
                    "triggered": bias_triggered,
                }
            )

        triggered_count = sum(1 for layer in layers if layer["triggered"])
        summary = f"{triggered_count}/{len(layers)} conditions triggered"

        return {
            "layers": layers,
            "summary": summary,
            "r_value": float(r_value),
            "pnl_r": float(pnl_r),
            "holding_days": int(holding_days),
        }

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required = ["Close", "ATR", "MACD_Hist", "MACD", "MACD_Signal"]
        if not all(col in df.columns for col in required):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]
        if pd.isna(current_atr) or current_atr <= 0:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Invalid ATR"],
                strategy_name=self.strategy_name,
            )

        entry_atr = self._resolve_entry_atr(df, position.entry_date, current_atr)
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_pct = position.current_pnl_pct(current_price)

        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        if current_price < trail_level:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=1.0,
                reason="R1 trailing stop",
                trigger="R1_ATRTrailing",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        if self._hist_shrinking(df, self.hist_shrink_n):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.9,
                reason=f"L2 histogram shrink x{self.hist_shrink_n}",
                trigger="L2_HistShrink",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        if self._macd_dead_cross(df):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.88,
                reason="L3 MACD dead cross",
                trigger="L3_MACDDeadCross",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )
        if holding_days >= self.time_stop_days:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.85,
                reason=f"Time stop: {holding_days} days",
                trigger="T1_TimeStop",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        if pnl_abs >= self.tp2_r * r_value:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.8,
                reason=f"TP2 hit: +{self.tp2_r:.1f}R",
                trigger="P_TP2",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        bias_pct = self._calc_bias_pct(latest)
        if (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        ):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.75,
                reason="Bias overheat",
                trigger="P_BiasOverheat",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        if pnl_abs >= self.tp1_r * r_value:
            return self._sell_signal(
                sell_percentage=0.5,
                confidence=0.7,
                reason=f"TP1 hit: +{self.tp1_r:.1f}R",
                trigger="P_TP1",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No exit condition met"],
            metadata={
                "r_value": float(r_value),
                "pnl_pct": float(pnl_pct),
                "holding_days": int(holding_days),
            },
            strategy_name=self.strategy_name,
        )


class MultiViewWindowDecayExit(MultiViewCompositeExit):
    """MVX variant that replaces strict histogram shrinking with window decay."""

    def _l2_is_triggered(self, df_features: pd.DataFrame) -> bool:
        return self._hist_window_decay(df_features, self.hist_shrink_n)

    def _l2_trigger_name(self) -> str:
        return "L2_HistWindowDecay"

    def _l2_reason(self) -> str:
        return f"L2 histogram window decay x{self.hist_shrink_n}"

    def _l2_threshold(self) -> str:
        return "n-1 of n down, latest down, negative slope"


class MultiViewUnifiedTakeProfitExit(BaseExitStrategy):
    """MVX variant with a single full-exit take-profit threshold."""

    def __init__(
        self,
        hist_shrink_n: int = 9,
        r_mult: float = 3.4,
        trail_mult: float = 1.6,
        time_stop_days: int = 18,
        bias_exit_threshold_pct: float = 20.0,
        take_profit_r: float = 1.5,
    ):
        super().__init__(strategy_name="MultiViewUnifiedTakeProfitExit")
        self.hist_shrink_n = int(hist_shrink_n)
        self.r_mult = float(r_mult)
        self.trail_mult = float(trail_mult)
        self.time_stop_days = int(time_stop_days)
        self.bias_exit_threshold_pct = float(bias_exit_threshold_pct)
        self.take_profit_r = float(take_profit_r)

    def _take_profit_trigger(self) -> str:
        return f"P_TP{_float_token(self.take_profit_r)}"

    def _take_profit_reason(self) -> str:
        return f"TP{self.take_profit_r:.1f} hit: +{self.take_profit_r:.1f}R"

    def get_evaluation_details(
        self, position: Position, market_data: MarketData
    ) -> Dict:
        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return {"layers": [], "summary": "Insufficient data"}

        required = ["Close", "ATR", "MACD_Hist"]
        if not all(col in df.columns for col in required):
            return {"layers": [], "summary": "Missing indicators"}

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]

        if pd.isna(current_atr) or current_atr <= 0:
            return {"layers": [], "summary": "Invalid ATR"}

        entry_atr = MultiViewCompositeExit._resolve_entry_atr(
            df,
            position.entry_date,
            current_atr,
        )
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_r = pnl_abs / r_value
        holding_days = MultiViewCompositeExit._count_trading_days(
            df,
            position.entry_date,
            market_data.current_date,
        )

        layers = []

        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        layers.append(
            {
                "name": "R1_TrailingStop",
                "status": "SAFE" if current_price >= trail_level else "TRIGGER",
                "value": f"JPY{current_price:.2f}",
                "threshold": f"JPY{trail_level:.2f}",
                "triggered": current_price < trail_level,
            }
        )

        hist_shrinking = MultiViewCompositeExit._hist_shrinking(df, self.hist_shrink_n)
        layers.append(
            {
                "name": "L2_HistShrink",
                "status": "TRIGGER" if hist_shrinking else "PASS",
                "value": f"{self.hist_shrink_n} bars",
                "threshold": "consecutive decline",
                "triggered": hist_shrinking,
            }
        )

        layers.append(
            {
                "name": "T1_TimeStop",
                "status": "TRIGGER" if holding_days >= self.time_stop_days else "SAFE",
                "value": f"{holding_days} days",
                "threshold": f"{self.time_stop_days} days",
                "triggered": holding_days >= self.time_stop_days,
            }
        )

        tp_triggered = pnl_abs >= self.take_profit_r * r_value
        layers.append(
            {
                "name": self._take_profit_trigger(),
                "status": "TRIGGER" if tp_triggered else "PENDING",
                "value": f"+{pnl_r:.2f}R",
                "threshold": f"+{self.take_profit_r:.1f}R",
                "triggered": tp_triggered,
            }
        )

        bias_pct = MultiViewCompositeExit._calc_bias_pct(latest)
        bias_triggered = (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        )
        if bias_pct is not None:
            layers.append(
                {
                    "name": "P_BiasOverheat",
                    "status": "TRIGGER" if bias_triggered else "PASS",
                    "value": f"{bias_pct:.1f}%",
                    "threshold": f"{self.bias_exit_threshold_pct:.1f}%",
                    "triggered": bias_triggered,
                }
            )

        triggered_count = sum(1 for layer in layers if layer["triggered"])
        summary = f"{triggered_count}/{len(layers)} conditions triggered"

        return {
            "layers": layers,
            "summary": summary,
            "r_value": float(r_value),
            "pnl_r": float(pnl_r),
            "holding_days": int(holding_days),
        }

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        position.peak_price_since_entry = max(
            position.peak_price_since_entry,
            market_data.latest_price,
        )

        df = market_data.df_features
        if df.empty or len(df) < max(self.hist_shrink_n + 1, 2):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required = ["Close", "ATR", "MACD_Hist"]
        if not all(col in df.columns for col in required):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        current_price = latest["Close"]
        current_atr = latest["ATR"]
        if pd.isna(current_atr) or current_atr <= 0:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Invalid ATR"],
                strategy_name=self.strategy_name,
            )

        entry_atr = MultiViewCompositeExit._resolve_entry_atr(
            df,
            position.entry_date,
            current_atr,
        )
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = current_price - position.entry_price
        pnl_pct = position.current_pnl_pct(current_price)

        trail_level = position.peak_price_since_entry - (self.trail_mult * current_atr)
        if current_price < trail_level:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=[f"R1 trailing stop: {current_price:.2f} < {trail_level:.2f}"],
                metadata={
                    "trigger": "R1_ATRTrailing",
                    "sell_percentage": 1.0,
                    "r_value": float(r_value),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        if MultiViewCompositeExit._hist_shrinking(df, self.hist_shrink_n):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[f"L2 histogram shrink x{self.hist_shrink_n}"],
                metadata={
                    "trigger": "L2_HistShrink",
                    "sell_percentage": 1.0,
                    "r_value": float(r_value),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        holding_days = MultiViewCompositeExit._count_trading_days(
            df,
            position.entry_date,
            market_data.current_date,
        )
        if holding_days >= self.time_stop_days:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.85,
                reasons=[f"Time stop: {holding_days} days"],
                metadata={
                    "trigger": "T1_TimeStop",
                    "sell_percentage": 1.0,
                    "r_value": float(r_value),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        if pnl_abs >= self.take_profit_r * r_value:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.8,
                reasons=[self._take_profit_reason()],
                metadata={
                    "trigger": self._take_profit_trigger(),
                    "sell_percentage": 1.0,
                    "r_value": float(r_value),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        bias_pct = MultiViewCompositeExit._calc_bias_pct(latest)
        if (
            bias_pct is not None
            and pnl_abs > 0
            and bias_pct >= self.bias_exit_threshold_pct
        ):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.75,
                reasons=[
                    f"Bias overheat: {bias_pct:.2f}% >= {self.bias_exit_threshold_pct:.2f}%"
                ],
                metadata={
                    "trigger": "P_BiasOverheat",
                    "sell_percentage": 1.0,
                    "r_value": float(r_value),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No exit condition met"],
            metadata={
                "r_value": float(r_value),
                "pnl_pct": float(pnl_pct),
                "holding_days": int(holding_days),
            },
            strategy_name=self.strategy_name,
        )


def _float_token(value: float) -> str:
    normalized = f"{float(value):.2f}"
    if normalized.endswith("00"):
        normalized = normalized[:-1]
    elif normalized.endswith("0"):
        normalized = normalized[:-1]
    return normalized.replace(".", "p")


GRID_EXIT_STRATEGY_MAP: Dict[str, str] = {}

# 固定参数 (来自最优参数D18_B20)
_D_VALUES = [18]  # 固定D=18
# 参数微调网格 (3^4 = 81个组合)
_N_VALUES = [8, 9, 10]  # MACD直方图收缩周期: ±1步长
_R_VALUES = [3.4, 3.5, 3.6]  # 回报倍数: ±0.1步长
_T_VALUES = [1.5, 1.6, 1.7]  # 尾随倍数: ±0.1步长
_B_VALUES = [19.5, 20.0, 20.5]  # 偏离度百分比: ±0.5步长


def _build_variant_class(name: str, n: int, r: float, t: float, d: int, b: float):
    def __init__(self):
        MultiViewCompositeExit.__init__(
            self,
            hist_shrink_n=n,
            r_mult=r,
            trail_mult=t,
            time_stop_days=d,
            bias_exit_threshold_pct=b,
        )
        self.strategy_name = name

    return type(name, (MultiViewCompositeExit,), {"__init__": __init__})


def _build_window_decay_variant_class(
    name: str,
    n: int,
    r: float,
    t: float,
    d: int,
    b: float,
):
    def __init__(self):
        MultiViewWindowDecayExit.__init__(
            self,
            hist_shrink_n=n,
            r_mult=r,
            trail_mult=t,
            time_stop_days=d,
            bias_exit_threshold_pct=b,
        )
        self.strategy_name = name

    return type(name, (MultiViewWindowDecayExit,), {"__init__": __init__})


def _build_unified_tp_variant_class(
    name: str,
    n: int,
    r: float,
    t: float,
    d: int,
    b: float,
    take_profit_r: float,
):
    def __init__(self):
        MultiViewUnifiedTakeProfitExit.__init__(
            self,
            hist_shrink_n=n,
            r_mult=r,
            trail_mult=t,
            time_stop_days=d,
            bias_exit_threshold_pct=b,
            take_profit_r=take_profit_r,
        )
        self.strategy_name = name

    return type(name, (MultiViewUnifiedTakeProfitExit,), {"__init__": __init__})


def _register_grid_exit_variant(name: str, cls) -> None:
    globals()[name] = cls
    GRID_EXIT_STRATEGY_MAP[name] = (
        f"src.analysis.strategies.exit.multiview_grid_exit.{name}"
    )


def _register_standard_variant(n: int, r: float, t: float, d: int, b: float) -> None:
    name = f"MVX_N{n}_R{_float_token(r)}_T{_float_token(t)}_D{d}_B{_float_token(b)}"
    if name in GRID_EXIT_STRATEGY_MAP:
        return
    _register_grid_exit_variant(name, _build_variant_class(name, n, r, t, d, b))


def _register_window_decay_variant(n: int, r: float, t: float, d: int, b: float) -> None:
    name = f"MVXW_N{n}_R{_float_token(r)}_T{_float_token(t)}_D{d}_B{_float_token(b)}"
    if name in GRID_EXIT_STRATEGY_MAP:
        return
    _register_grid_exit_variant(
        name,
        _build_window_decay_variant_class(name, n, r, t, d, b),
    )


def _expand_refinement_values(base_values, step: float, rounds: int):
    step_decimal = Decimal(str(step))
    expanded = set()
    for base_value in base_values:
        base_decimal = Decimal(str(base_value))
        for offset in range(-rounds, rounds + 1):
            expanded.add(float(base_decimal + (step_decimal * offset)))
    return sorted(expanded)


for _n in _N_VALUES:
    for _r in _R_VALUES:
        for _t in _T_VALUES:
            for _d in _D_VALUES:
                for _b in _B_VALUES:
                    _register_standard_variant(_n, _r, _t, _d, _b)


_EXTRA_VARIANTS = [
    (1, 3.4, 1.6, 18, 20.0),
    (2, 3.4, 1.6, 18, 20.0),
    (3, 3.2, 1.6, 15, 20.0),
    (3, 3.2, 1.6, 16, 20.0),
    (3, 3.2, 1.6, 17, 20.0),
    (3, 3.2, 1.5, 18, 20.0),
    (3, 3.2, 1.55, 18, 20.0),
    (3, 3.2, 1.6, 18, 20.0),
    (3, 3.2, 1.65, 18, 20.0),
    (3, 3.2, 1.7, 18, 20.0),
    (3, 3.2, 1.6, 19, 20.0),
    (3, 3.2, 1.6, 20, 20.0),
    (3, 3.2, 1.6, 21, 20.0),
    (3, 3.2, 1.6, 22, 20.0),
    (3, 3.2, 1.65, 21, 20.0),
    (3, 3.2, 1.65, 22, 20.0),
    (3, 3.2, 1.6, 23, 20.0),
    (3, 3.2, 1.6, 24, 20.0),
    (3, 3.2, 1.6, 25, 20.0),
    (3, 3.2, 1.6, 26, 20.0),
    (3, 3.2, 1.6, 27, 20.0),
    (3, 3.25, 1.5, 18, 20.0),
    (3, 3.25, 1.55, 18, 20.0),
    (3, 3.25, 1.6, 18, 20.0),
    (3, 3.25, 1.65, 18, 20.0),
    (3, 3.25, 1.6, 21, 20.0),
    (3, 3.25, 1.6, 22, 20.0),
    (3, 3.25, 1.65, 21, 20.0),
    (3, 3.25, 1.65, 22, 20.0),
    (3, 3.3, 1.5, 18, 20.0),
    (3, 3.3, 1.55, 18, 20.0),
    (3, 3.3, 1.6, 18, 20.0),
    (3, 3.3, 1.65, 18, 20.0),
    (3, 3.3, 1.7, 18, 20.0),
    (3, 3.35, 1.5, 18, 20.0),
    (3, 3.35, 1.55, 18, 20.0),
    (3, 3.35, 1.6, 18, 20.0),
    (3, 3.35, 1.65, 18, 20.0),
    (3, 3.4, 1.2, 18, 20.0),
    (3, 3.4, 1.3, 18, 20.0),
    (3, 3.4, 1.4, 18, 20.0),
    (3, 3.4, 1.5, 18, 20.0),
    (3, 3.4, 1.6, 18, 20.0),
    (3, 3.4, 1.7, 18, 20.0),
    (3, 3.4, 1.8, 18, 20.0),
    (3, 3.5, 1.5, 18, 20.0),
    (3, 3.5, 1.6, 18, 20.0),
    (3, 3.5, 1.7, 18, 20.0),
    (3, 3.6, 1.5, 18, 20.0),
    (3, 3.6, 1.6, 18, 20.0),
    (3, 3.6, 1.7, 18, 20.0),
]


for _n, _r, _t, _d, _b in _EXTRA_VARIANTS:
    _register_standard_variant(_n, _r, _t, _d, _b)


# D21/B20 parameter family for the dedicated MACD/2bar MVX study.
# The refinement lists cover the initial sweep and two later 0.1-step grid rounds.
_D21_B20_SWEEP_N_VALUES = [2, 3, 4, 5, 6, 7]
_D21_B20_SWEEP_R_BASE_VALUES = [3.0, 3.25, 3.5, 3.75, 4.0]
_D21_B20_SWEEP_T_BASE_VALUES = [1.2, 1.4, 1.6, 1.8, 2.0]
_D21_B20_REFINED_R_VALUES = _expand_refinement_values(
    _D21_B20_SWEEP_R_BASE_VALUES,
    step=0.1,
    rounds=2,
)
_D21_B20_REFINED_T_VALUES = _expand_refinement_values(
    _D21_B20_SWEEP_T_BASE_VALUES,
    step=0.1,
    rounds=2,
)

for _n in _D21_B20_SWEEP_N_VALUES:
    for _r in _D21_B20_REFINED_R_VALUES:
        for _t in _D21_B20_REFINED_T_VALUES:
            _register_standard_variant(_n, _r, _t, 21, 20.0)


_MVXW_VARIANTS = [
    (2, 3.85, 2.0, 21, 20.0),
    (3, 3.85, 2.0, 21, 20.0),
    (4, 3.85, 2.0, 21, 20.0),
    (5, 3.85, 2.0, 21, 20.0),
    (6, 3.85, 2.0, 21, 20.0),
    (7, 3.85, 2.0, 21, 20.0),
    (8, 3.85, 2.0, 21, 20.0),
    (2, 3.35, 1.6, 21, 20.0),
    (3, 3.35, 1.6, 21, 20.0),
    (4, 3.35, 1.6, 21, 20.0),
    (5, 3.35, 1.6, 21, 20.0),
    (6, 3.35, 1.6, 21, 20.0),
    (7, 3.35, 1.6, 21, 20.0),
    (8, 3.35, 1.6, 21, 20.0),
    (2, 3.25, 1.8, 21, 20.0),
    (3, 3.25, 1.8, 21, 20.0),
    (4, 3.25, 1.8, 21, 20.0),
    (5, 3.25, 1.8, 21, 20.0),
    (6, 3.25, 1.8, 21, 20.0),
    (7, 3.25, 1.8, 21, 20.0),
    (8, 3.25, 1.8, 21, 20.0),
]


_MVXW_N5_RT_TUNING_R_VALUES = [3.2, 3.25, 3.3, 3.35, 3.4, 3.45, 3.5]
_MVXW_N5_RT_TUNING_T_VALUES = [1.45, 1.5, 1.55, 1.6, 1.65, 1.7, 1.75]


for _n, _r, _t, _d, _b in _MVXW_VARIANTS:
    _register_window_decay_variant(_n, _r, _t, _d, _b)

for _r in _MVXW_N5_RT_TUNING_R_VALUES:
    for _t in _MVXW_N5_RT_TUNING_T_VALUES:
        _register_window_decay_variant(5, _r, _t, 21, 20.0)


_UNIFIED_TP_VARIANTS = [
    (1, 3.4, 1.6, 18, 20.0),
    (2, 3.4, 1.6, 18, 20.0),
    (3, 3.4, 1.6, 18, 20.0),
]

_UNIFIED_TP_FAMILIES = [
    (1.2, "MVU12"),
    (1.4, "MVU14"),
    (1.5, "MVU"),
]


for _take_profit_r, _family_prefix in _UNIFIED_TP_FAMILIES:
    for _n, _r, _t, _d, _b in _UNIFIED_TP_VARIANTS:
        _name = (
            f"{_family_prefix}_N{_n}_R{_float_token(_r)}_T{_float_token(_t)}"
            f"_D{_d}_B{_float_token(_b)}"
        )
        if _name in GRID_EXIT_STRATEGY_MAP:
            continue
        _register_grid_exit_variant(
            _name,
            _build_unified_tp_variant_class(
                _name,
                _n,
                _r,
                _t,
                _d,
                _b,
                _take_profit_r,
            ),
        )


GRID_EXIT_STRATEGY_MAP["MVXNew_N3_R3p25_T1p6_D21_B20p0"] = (
    "src.analysis.strategies.exit.multiview_grid_exit.MVXNew_N3_R3p25_T1p6_D21_B20p0"
)


__all__ = [
    "MultiViewCompositeExit",
    "MultiViewWindowDecayExit",
    "MultiViewUnifiedTakeProfitExit",
    "MVXNew_N3_R3p25_T1p6_D21_B20p0",
    "GRID_EXIT_STRATEGY_MAP",
    *list(GRID_EXIT_STRATEGY_MAP.keys()),
]
