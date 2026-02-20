"""
Multi-view composite exit strategy with parameter grid variants.

Design layers:
1) L2 Signal inversion: MACD histogram shrinking for N consecutive bars
2) R1 Risk: ATR trailing stop
3) Profit: +1R -> SELL 50%, +2R -> SELL 100%, optional SMA20 bias overheat full exit
4) Time hard exit: force close after max holding trading days

This module dynamically generates 243 strategy classes for grid evaluation,
so existing evaluation flow can consume strategy names directly.
"""

from __future__ import annotations

from typing import Dict
import pandas as pd

from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class MultiViewCompositeExit(BaseExitStrategy):
    """Composite exit strategy with configurable parameters."""

    def __init__(
        self,
        hist_shrink_n: int = 3,
        r_mult: float = 1.5,
        trail_mult: float = 2.0,
        time_stop_days: int = 15,
        bias_exit_threshold_pct: float = 15.0,
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
        if self._hist_shrinking(df, self.hist_shrink_n):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.9,
                reason=f"L2 histogram shrink x{self.hist_shrink_n}",
                trigger="L2_HistShrink",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # Time hard exit (full exit)
        holding_days = self._count_trading_days(df, position.entry_date, market_data.current_date)
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
        if bias_pct is not None and pnl_abs > 0 and bias_pct >= self.bias_exit_threshold_pct:
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
        if "SMA_20" not in latest_row.index:
            return None
        sma = latest_row["SMA_20"]
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

        atr_series = df_features["ATR"].dropna() if "ATR" in df_features.columns else pd.Series(dtype=float)
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


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


GRID_EXIT_STRATEGY_MAP: Dict[str, str] = {}

_N_VALUES = [2, 3, 4]
_R_VALUES = [1.2, 1.5, 1.8]
_T_VALUES = [1.8, 2.0, 2.2]
_D_VALUES = [10, 15, 20]
_B_VALUES = [12, 15, 18]


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


for _n in _N_VALUES:
    for _r in _R_VALUES:
        for _t in _T_VALUES:
            for _d in _D_VALUES:
                for _b in _B_VALUES:
                    _name = f"MVX_N{_n}_R{_float_token(_r)}_T{_float_token(_t)}_D{_d}_B{int(_b)}"
                    _cls = _build_variant_class(_name, _n, _r, _t, _d, _b)
                    globals()[_name] = _cls
                    GRID_EXIT_STRATEGY_MAP[_name] = (
                        f"src.analysis.strategies.exit.multiview_grid_exit.{_name}"
                    )


__all__ = ["MultiViewCompositeExit", "GRID_EXIT_STRATEGY_MAP", *list(GRID_EXIT_STRATEGY_MAP.keys())]
