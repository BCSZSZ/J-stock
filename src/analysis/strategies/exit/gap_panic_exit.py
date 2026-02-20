"""
Gap Panic Exit Strategy

正交思路：
- 事件冲击与流动性风险驱动
- 识别“向下跳空 + 放量 + 趋势破坏”的恐慌日
"""

import pandas as pd

from src.analysis.signals import TradingSignal, SignalAction, MarketData, Position
from src.analysis.strategies.base_exit_strategy import BaseExitStrategy


class GapPanicExit(BaseExitStrategy):
    """
    跳空恐慌退出策略。

    Args:
        gap_down_pct: 向下跳空阈值（默认2.5%）
        volume_spike_ratio: 成交量放大量比阈值（默认1.8x）
        emergency_intraday_drop_pct: 当日收盘跌幅紧急阈值（默认5%）
    """

    def __init__(
        self,
        gap_down_pct: float = 2.5,
        volume_spike_ratio: float = 1.8,
        emergency_intraday_drop_pct: float = 5.0,
    ):
        super().__init__(strategy_name="GapPanicExit")
        self.gap_down_pct = gap_down_pct
        self.volume_spike_ratio = volume_spike_ratio
        self.emergency_intraday_drop_pct = emergency_intraday_drop_pct

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

        required_cols = ["Close", "Volume"]
        if not all(col in df.columns for col in required_cols):
            return TradingSignal(
                action=SignalAction.HOLD,
                confidence=0.0,
                reasons=["Missing required columns"],
                strategy_name=self.strategy_name,
            )

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        current_close = latest["Close"]
        prev_close = prev["Close"]

        # 回退逻辑：若无Open，使用Close估算（降低触发概率）
        current_open = latest["Open"] if "Open" in df.columns else current_close

        gap_down = (current_open / prev_close - 1.0) * 100 if prev_close > 0 else 0.0
        intraday_drop = (current_close / prev_close - 1.0) * 100 if prev_close > 0 else 0.0

        volume_avg = latest.get("Volume_SMA_20")
        if pd.isna(volume_avg):
            volume_avg = df["Volume"].rolling(20).mean().iloc[-1]
        volume_ratio = latest["Volume"] / volume_avg if pd.notna(volume_avg) and volume_avg > 0 else 1.0

        ema20 = latest["EMA_20"] if "EMA_20" in df.columns else None
        below_ema20 = pd.notna(ema20) and current_close < ema20

        panic_combo = (
            gap_down <= -self.gap_down_pct
            and volume_ratio >= self.volume_spike_ratio
            and below_ema20
        )
        emergency_drop = intraday_drop <= -self.emergency_intraday_drop_pct

        pnl_pct = position.current_pnl_pct(current_close)

        if panic_combo:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.92,
                reasons=[
                    f"Gap panic: gap {gap_down:.2f}%, volume {volume_ratio:.2f}x, below EMA20"
                ],
                metadata={
                    "trigger": "GapPanic_Combo",
                    "gap_down_pct": float(gap_down),
                    "volume_ratio": float(volume_ratio),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        if emergency_drop:
            return TradingSignal(
                action=SignalAction.SELL,
                confidence=0.86,
                reasons=[f"Emergency drop: daily return {intraday_drop:.2f}%"],
                metadata={
                    "trigger": "GapPanic_EmergencyDrop",
                    "intraday_drop_pct": float(intraday_drop),
                    "pnl_pct": float(pnl_pct),
                },
                strategy_name=self.strategy_name,
            )

        return TradingSignal(
            action=SignalAction.HOLD,
            confidence=0.0,
            reasons=["No panic condition"],
            metadata={
                "gap_down_pct": float(gap_down),
                "intraday_drop_pct": float(intraday_drop),
                "volume_ratio": float(volume_ratio),
            },
            strategy_name=self.strategy_name,
        )
