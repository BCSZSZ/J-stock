from typing import Any, Dict, Optional

import pandas as pd

from ..data.benchmark_manager import BenchmarkManager
from .base import BaseOverlay, OverlayContext, OverlayDecision


class RegimeOverlay(BaseOverlay):
    """Risk on/off overlay based on benchmark trend and volatility."""

    name = "RegimeOverlay"
    priority = 10
    requires_benchmark_data = True

    def __init__(self, config: Optional[Dict[str, Any]] = None, data_root: str = "data"):
        super().__init__(config=config)
        self.data_root = data_root

    def evaluate(self, context: OverlayContext) -> OverlayDecision:
        if not self.enabled:
            return OverlayDecision(source=self.name, metadata={"status": "disabled"})

        benchmark = self.config.get("benchmark", "TOPIX")
        ema_window = int(self.config.get("ema_window", 200))
        vol_lookback = int(self.config.get("vol_lookback", 20))
        vol_threshold = float(self.config.get("vol_threshold", 0.22))
        risk_on_target = float(self.config.get("risk_on_target_exposure", 1.0))
        risk_off_target = float(self.config.get("risk_off_target_exposure", 0.4))
        block_when_off = bool(self.config.get("block_new_entries_when_off", False))

        df = context.benchmark_data
        if df is None:
            manager = BenchmarkManager(client=None, data_root=self.data_root)
            df = manager.get_topix_data()

        if df is None or df.empty:
            return OverlayDecision(
                source=self.name,
                metadata={"status": "no_benchmark_data", "benchmark": benchmark},
            )

        df = df.copy()
        df = df[df["Date"] <= context.current_date]
        if df.empty or len(df) < max(ema_window, vol_lookback) + 1:
            return OverlayDecision(
                source=self.name,
                metadata={"status": "insufficient_history", "benchmark": benchmark},
            )

        df = df.sort_values("Date")
        close = df["Close"].iloc[-1]
        ema = df["Close"].ewm(span=ema_window, adjust=False).mean().iloc[-1]
        returns = df["Close"].pct_change().dropna()
        vol = returns.tail(vol_lookback).std() * (252**0.5)

        risk_on = close > ema and vol < vol_threshold
        target_exposure = risk_on_target if risk_on else risk_off_target

        metadata = {
            "benchmark": benchmark,
            "regime": "RISK_ON" if risk_on else "RISK_OFF",
            "close": float(close),
            "ema": float(ema),
            "vol": float(vol),
            "vol_threshold": float(vol_threshold),
        }

        return OverlayDecision(
            source=self.name,
            target_exposure=target_exposure,
            block_new_entries=block_when_off and not risk_on,
            metadata=metadata,
        )
