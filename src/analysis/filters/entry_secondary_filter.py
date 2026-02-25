from dataclasses import dataclass
from typing import Dict

from src.analysis.signals import MarketData


@dataclass
class EntrySecondaryFilterConfig:
    enabled: bool = False
    require_ema_bull_stack: bool = True
    rsi_min: float = 55.0
    rsi_max: float = 75.0
    atr_price_max: float = 0.04
    min_price: float = 1000.0


class EntrySecondaryFilter:
    def __init__(self, config: EntrySecondaryFilterConfig):
        self.config = config

    @classmethod
    def from_dict(cls, config_dict: Dict | None):
        raw = config_dict or {}
        config = EntrySecondaryFilterConfig(
            enabled=bool(raw.get("enabled", False)),
            require_ema_bull_stack=bool(raw.get("require_ema_bull_stack", True)),
            rsi_min=float(raw.get("rsi_min", 55.0)),
            rsi_max=float(raw.get("rsi_max", 75.0)),
            atr_price_max=float(raw.get("atr_price_max", 0.04)),
            min_price=float(raw.get("min_price", 1000.0)),
        )
        return cls(config)

    def passes(self, market_data: MarketData) -> bool:
        if not self.config.enabled:
            return True

        df = market_data.df_features
        if df.empty:
            return False

        latest = df.iloc[-1]

        close_price = float(latest.get("Close", 0) or 0)
        if close_price < self.config.min_price:
            return False

        if self.config.require_ema_bull_stack:
            ema20 = float(latest.get("EMA_20", 0) or 0)
            ema50 = float(latest.get("EMA_50", 0) or 0)
            ema200 = float(latest.get("EMA_200", 0) or 0)
            if not (ema20 > ema50 > ema200):
                return False

        rsi = float(latest.get("RSI", -1) or -1)
        if not (self.config.rsi_min <= rsi <= self.config.rsi_max):
            return False

        atr = float(latest.get("ATR", 0) or 0)
        if close_price <= 0:
            return False
        atr_price = atr / close_price
        if atr_price > self.config.atr_price_max:
            return False

        return True
