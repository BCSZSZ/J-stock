"""Multi-dimensional moving-average based exit strategy family."""

from __future__ import annotations

from typing import Dict

import pandas as pd

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class MultiDimensionalMAExit(BaseExitStrategy):
    """
    Multi-layer exit strategy with MA regime, ATR risk, profit targets and time stop.

    Layers:
    1) R1 risk stop: ATR trailing stop from post-entry peak
    2) L2 regime break: fast MA stays below slow MA for N bars
    3) T1 hard time stop: force close after max holding days
    4) P1/P2 profit exits by R multiple (+1R partial, +2R full)
    5) O1 overheat exit: RSI overbought with pullback below fast MA
    """

    def __init__(
        self,
        fast_ma_col: str = "EMA_20",
        slow_ma_col: str = "EMA_50",
        dead_cross_confirm_days: int = 2,
        r_mult: float = 3.4,
        atr_trail_mult: float = 1.6,
        time_stop_days: int = 18,
        tp1_r: float = 1.0,
        tp2_r: float = 2.0,
        rsi_overheat: float = 75.0,
    ):
        super().__init__(strategy_name="MultiDimensionalMAExit")
        self.fast_ma_col = fast_ma_col
        self.slow_ma_col = slow_ma_col
        self.dead_cross_confirm_days = max(1, int(dead_cross_confirm_days))
        self.r_mult = float(r_mult)
        self.atr_trail_mult = float(atr_trail_mult)
        self.time_stop_days = int(time_stop_days)
        self.tp1_r = float(tp1_r)
        self.tp2_r = float(tp2_r)
        self.rsi_overheat = float(rsi_overheat)

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        df = market_data.df_features
        min_rows = max(self.dead_cross_confirm_days, 2)
        if df.empty or len(df) < min_rows:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required = ["Close", "ATR", self.fast_ma_col, self.slow_ma_col]
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

        if pd.isna(current_price) or pd.isna(current_atr) or float(current_atr) <= 0:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Invalid latest price/ATR"],
                strategy_name=self.strategy_name,
            )

        entry_atr = self._resolve_entry_atr(df, position.entry_date, float(current_atr))
        r_value = max(self.r_mult * entry_atr, 1e-6)
        pnl_abs = float(current_price) - float(position.entry_price)
        pnl_pct = position.current_pnl_pct(float(current_price))

        # R1: ATR trailing stop (full exit)
        trail_level = float(position.peak_price_since_entry) - (
            self.atr_trail_mult * float(current_atr)
        )
        if float(current_price) < trail_level:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=1.0,
                reason=f"R1 trailing stop: {current_price:.2f} < {trail_level:.2f}",
                trigger="R1_ATRTrailing",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # L2: MA dead-cross streak (full exit)
        if self._dead_cross_streak(df) >= self.dead_cross_confirm_days:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.9,
                reason=(
                    f"L2 MA dead-cross streak x{self.dead_cross_confirm_days} "
                    f"({self.fast_ma_col} < {self.slow_ma_col})"
                ),
                trigger="L2_MADeadCross",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # T1: hard time stop (full exit)
        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )
        if holding_days >= self.time_stop_days:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.85,
                reason=f"T1 time stop: {holding_days} days",
                trigger="T1_TimeStop",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # P2: +2R full exit
        if pnl_abs >= self.tp2_r * r_value:
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.8,
                reason=f"P2 target hit: +{self.tp2_r:.1f}R",
                trigger="P2_TP2",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # O1: overheat + pullback (full exit)
        rsi_value = None
        if "RSI_14" in df.columns:
            rsi_value = latest["RSI_14"]
        elif "RSI" in df.columns:
            rsi_value = latest["RSI"]
        fast_ma_value = latest[self.fast_ma_col]
        if (
            rsi_value is not None
            and pd.notna(rsi_value)
            and pd.notna(fast_ma_value)
            and float(rsi_value) >= self.rsi_overheat
            and pnl_abs > 0
            and float(current_price) < float(fast_ma_value)
        ):
            return self._sell_signal(
                sell_percentage=1.0,
                confidence=0.78,
                reason=(
                    f"O1 overheat pullback: RSI {float(rsi_value):.1f} >= "
                    f"{self.rsi_overheat:.1f}, Close < {self.fast_ma_col}"
                ),
                trigger="O1_RSIOverheatPullback",
                r_value=r_value,
                pnl_pct=pnl_pct,
            )

        # P1: +1R partial exit
        if pnl_abs >= self.tp1_r * r_value:
            return self._sell_signal(
                sell_percentage=0.5,
                confidence=0.7,
                reason=f"P1 target hit: +{self.tp1_r:.1f}R",
                trigger="P1_TP1",
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

    def _dead_cross_streak(self, df_features: pd.DataFrame) -> int:
        if len(df_features) < self.dead_cross_confirm_days:
            return 0
        tail = df_features[[self.fast_ma_col, self.slow_ma_col]].tail(
            self.dead_cross_confirm_days
        )
        if tail.isna().any().any():
            return 0
        cond = tail[self.fast_ma_col] < tail[self.slow_ma_col]
        return int(cond.sum()) if bool(cond.all()) else 0

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
            confidence=float(confidence),
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
            if pd.notna(atr) and float(atr) > 0:
                return float(atr)

        atr_series = (
            df_features["ATR"].dropna()
            if "ATR" in df_features.columns
            else pd.Series(dtype=float)
        )
        if not atr_series.empty:
            val = atr_series.iloc[-1]
            if pd.notna(val) and float(val) > 0:
                return float(val)
        return float(fallback_atr)


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


GRID_EXIT_STRATEGY_MAP: Dict[str, str] = {}

_C_VALUES = [2, 3]
_R_VALUES = [3.2, 3.4, 3.6]
_T_VALUES = [1.5, 1.6, 1.7]
_D_VALUES = [15, 18]
_O_VALUES = [72.0, 75.0]


def _build_variant_class(name: str, c: int, r: float, t: float, d: int, o: float):
    def __init__(self):
        MultiDimensionalMAExit.__init__(
            self,
            dead_cross_confirm_days=c,
            r_mult=r,
            atr_trail_mult=t,
            time_stop_days=d,
            rsi_overheat=o,
        )
        self.strategy_name = name

    return type(name, (MultiDimensionalMAExit,), {"__init__": __init__})


for _c in _C_VALUES:
    for _r in _R_VALUES:
        for _t in _T_VALUES:
            for _d in _D_VALUES:
                for _o in _O_VALUES:
                    _name = (
                        f"MDX_C{_c}_R{_float_token(_r)}_T{_float_token(_t)}_"
                        f"D{_d}_O{_float_token(_o)}"
                    )
                    _cls = _build_variant_class(_name, _c, _r, _t, _d, _o)
                    globals()[_name] = _cls
                    GRID_EXIT_STRATEGY_MAP[_name] = (
                        f"src.analysis.strategies.exit.multidim_ma_exit.{_name}"
                    )


__all__ = [
    "MultiDimensionalMAExit",
    "GRID_EXIT_STRATEGY_MAP",
    *list(GRID_EXIT_STRATEGY_MAP.keys()),
]
