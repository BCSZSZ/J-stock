"""
MACD + KDJ rule-based exit strategy.

Exit rules (first hit triggers SELL):
E1: D > 80 and K < D
E2: DIF < DEA (MACD dead cross)
E3: Price < entry_price * (1 - stop_loss_pct)
E4: Holding days > max_hold_trading_days and pnl < min_profit_pct_after_max_hold
"""

import pandas as pd

from src.analysis.signals import MarketData, Position, SignalAction, TradingSignal
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class MACDKDJRuleExit(BaseExitStrategy):
    """
    MACD + KDJ rule-based exit strategy.

    Args:
        kd_overbought_threshold: Overbought threshold for D (default 80)
        stop_loss_pct: Stop loss percent (default 0.05)
        max_hold_trading_days: Max holding days in trading bars (default 15)
        min_profit_pct_after_max_hold: Min profit threshold after max hold (default 2.0)
    """

    def __init__(
        self,
        kd_overbought_threshold: float = 80.0,
        stop_loss_pct: float = 0.05,
        max_hold_trading_days: int = 15,
        min_profit_pct_after_max_hold: float = 2.0,
        macd_dead_cross_days: int = 3,
    ):
        super().__init__(strategy_name="MACDKDJRuleExit")
        self.kd_overbought_threshold = kd_overbought_threshold
        self.stop_loss_pct = stop_loss_pct
        self.max_hold_trading_days = max_hold_trading_days
        self.min_profit_pct_after_max_hold = min_profit_pct_after_max_hold
        self.macd_dead_cross_days = macd_dead_cross_days

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        df = market_data.df_features
        if df.empty or len(df) < 2:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        required_fields = ["Close", "MACD", "MACD_Signal", "KDJ_K_9", "KDJ_D_9"]
        if not all(field in df.columns for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required indicators"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        if any(pd.isna(latest[field]) for field in required_fields):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Latest indicators contain NaN"],
                strategy_name=self.strategy_name,
            )

        current_price = latest["Close"]
        dif = latest["MACD"]
        dea = latest["MACD_Signal"]
        k_now = latest["KDJ_K_9"]
        d_now = latest["KDJ_D_9"]

        # E1: KDJ high-level death cross
        if d_now > self.kd_overbought_threshold and k_now < d_now:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=["KDJ high-level death cross"],
                metadata={
                    "trigger": "E1",
                    "kdj_k": float(k_now),
                    "kdj_d": float(d_now),
                },
                strategy_name=self.strategy_name,
            )

        # E2: MACD dead cross (consecutive days)
        if self._macd_dead_cross_streak(df) >= self.macd_dead_cross_days:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.85,
                reasons=["MACD dead cross (3 days)"]
                if self.macd_dead_cross_days == 3
                else ["MACD dead cross (streak)"],
                metadata={
                    "trigger": "E2",
                    "dif": float(dif),
                    "dea": float(dea),
                    "macd_dead_cross_days": int(self.macd_dead_cross_days),
                },
                strategy_name=self.strategy_name,
            )

        # E3: Stop loss
        stop_price = position.entry_price * (1 - self.stop_loss_pct)
        if current_price < stop_price:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=["Stop loss"],
                metadata={"trigger": "E3", "stop_price": float(stop_price)},
                strategy_name=self.strategy_name,
            )

        # E4: Time-cost filter using trading days
        holding_days = self._count_trading_days(
            df, position.entry_date, market_data.current_date
        )
        pnl_pct = position.current_pnl_pct(current_price)
        if (
            holding_days > self.max_hold_trading_days
            and pnl_pct < self.min_profit_pct_after_max_hold
        ):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.8,
                reasons=["Time-cost filter"],
                metadata={
                    "trigger": "E4",
                    "holding_days": int(holding_days),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No exit condition met"],
            metadata={"holding_days": int(holding_days), "pnl_pct": float(pnl_pct)},
            strategy_name=self.strategy_name,
        )

    @staticmethod
    def _count_trading_days(
        df_features: pd.DataFrame, entry_date: pd.Timestamp, current_date: pd.Timestamp
    ) -> int:
        if df_features.empty:
            return 0
        idx = df_features.index
        mask = (idx >= entry_date) & (idx <= current_date)
        return int(mask.sum())

    def _macd_dead_cross_streak(self, df_features: pd.DataFrame) -> int:
        if (
            df_features.empty
            or "MACD" not in df_features.columns
            or "MACD_Signal" not in df_features.columns
        ):
            return 0
        streak = 0
        for _, row in df_features.tail(self.macd_dead_cross_days).iterrows():
            if pd.isna(row["MACD"]) or pd.isna(row["MACD_Signal"]):
                return 0
            if row["MACD"] < row["MACD_Signal"]:
                streak += 1
            else:
                return 0
        return streak


class MACDKDJRuleExitA(MACDKDJRuleExit):
    def __init__(self):
        super().__init__(
            kd_overbought_threshold=80.0,
            stop_loss_pct=0.04,
            max_hold_trading_days=15,
            min_profit_pct_after_max_hold=2.0,
            macd_dead_cross_days=3,
        )
        self.strategy_name = "MACDKDJRuleExitA"


class MACDKDJRuleExitB(MACDKDJRuleExit):
    def __init__(self):
        super().__init__(
            kd_overbought_threshold=85.0,
            stop_loss_pct=0.06,
            max_hold_trading_days=15,
            min_profit_pct_after_max_hold=2.0,
            macd_dead_cross_days=3,
        )
        self.strategy_name = "MACDKDJRuleExitB"
