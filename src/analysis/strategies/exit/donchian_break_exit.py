"""
Donchian Break Exit Strategy

正交思路：
- 价格行为驱动，不依赖Score体系
- 以通道破位识别趋势失效
- 配合时间止盈/止损审查，避免资金占用过久
"""

import pandas as pd

from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class DonchianBreakExit(BaseExitStrategy):
    """
    Donchian 通道破位退出策略。

    Args:
        channel_window: 通道窗口（默认20）
        hard_stop_pct: 固定止损（默认8%）
        time_stop_days: 时间止损窗口（默认35个交易日）
        min_profit_after_time_stop: 到期最低收益要求（默认1%）
    """

    def __init__(
        self,
        channel_window: int = 20,
        hard_stop_pct: float = 0.08,
        time_stop_days: int = 35,
        min_profit_after_time_stop: float = 1.0,
    ):
        super().__init__(strategy_name="DonchianBreakExit")
        self.channel_window = channel_window
        self.hard_stop_pct = hard_stop_pct
        self.time_stop_days = time_stop_days
        self.min_profit_after_time_stop = min_profit_after_time_stop

    def generate_exit_signal(
        self, position: Position, market_data: MarketData
    ) -> TradingSignal:
        self.update_position(position, market_data.latest_price)

        df = market_data.df_features
        if df.empty or len(df) < max(self.channel_window, 2):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Insufficient data"],
                strategy_name=self.strategy_name,
            )

        if "Close" not in df.columns:
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing Close column"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        current_price = latest["Close"]
        pnl_pct = position.current_pnl_pct(current_price)

        stop_price = position.entry_price * (1 - self.hard_stop_pct)
        if current_price < stop_price:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=1.0,
                reasons=[f"Hard stop: {pnl_pct:.1f}%"],
                metadata={
                    "trigger": "Donchian_HardStop",
                    "pnl_pct": float(pnl_pct),
                    "stop_price": float(stop_price),
                },
                strategy_name=self.strategy_name,
            )

        rolling_low = df["Close"].rolling(self.channel_window).min().iloc[-1]
        if pd.notna(rolling_low) and current_price < rolling_low:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.9,
                reasons=[
                    f"Channel breakdown: Close {current_price:.2f} < {self.channel_window}D low {rolling_low:.2f}"
                ],
                metadata={
                    "trigger": "Donchian_Breakdown",
                    "channel_window": int(self.channel_window),
                    "rolling_low": float(rolling_low),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        holding_days = self._count_trading_days(
            df_features=df,
            entry_date=position.entry_date,
            current_date=market_data.current_date,
        )
        if (
            holding_days >= self.time_stop_days
            and pnl_pct < self.min_profit_after_time_stop
        ):
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.75,
                reasons=[
                    f"Time stop: {holding_days}d held with low return {pnl_pct:.1f}%"
                ],
                metadata={
                    "trigger": "Donchian_TimeStop",
                    "holding_days": int(holding_days),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No Donchian exit condition"],
            metadata={
                "pnl_pct": float(pnl_pct),
                "holding_days": int(holding_days),
            },
            strategy_name=self.strategy_name,
        )

    @staticmethod
    def _count_trading_days(
        df_features: pd.DataFrame, entry_date: pd.Timestamp, current_date: pd.Timestamp
    ) -> int:
        idx = df_features.index
        mask = (idx >= entry_date) & (idx <= current_date)
        return int(mask.sum())
