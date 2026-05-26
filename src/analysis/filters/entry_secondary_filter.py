from dataclasses import dataclass
import math
from typing import Dict

from src.analysis.signals import MarketData


@dataclass
class EntrySecondaryFilterConfig:
    enabled: bool = False
    require_ema_bull_stack: bool = True
    rsi_min: float | None = 55.0
    rsi_max: float | None = 75.0
    atr_price_min: float | None = None
    atr_price_max: float | None = 0.04
    min_price: float | None = 1000.0


class EntrySecondaryFilter:
    def __init__(self, config: EntrySecondaryFilterConfig):
        self.config = config

    @classmethod
    def from_dict(cls, config_dict: Dict | None):
        raw = config_dict or {}
        config = EntrySecondaryFilterConfig(
            enabled=bool(raw.get("enabled", False)),
            require_ema_bull_stack=bool(raw.get("require_ema_bull_stack", True)),
            rsi_min=_optional_float(raw.get("rsi_min", 55.0)),
            rsi_max=_optional_float(raw.get("rsi_max", 75.0)),
            atr_price_min=_optional_float(raw.get("atr_price_min")),
            atr_price_max=_optional_float(raw.get("atr_price_max", 0.04)),
            min_price=_optional_float(raw.get("min_price", 1000.0)),
        )
        return cls(config)

    def passes(self, market_data: MarketData) -> bool:
        if not self.config.enabled:
            return True

        df = market_data.df_features
        if df.empty:
            return False

        return self.passes_latest(df.iloc[-1])

    def passes_latest(self, latest) -> bool:
        if not self.config.enabled:
            return True

        close_price = float(latest.get("Close", 0) or 0)
        if self.config.min_price is not None and close_price < self.config.min_price:
            return False

        if self.config.require_ema_bull_stack:
            ema20 = float(latest.get("EMA_20", 0) or 0)
            ema50 = float(latest.get("EMA_50", 0) or 0)
            ema200 = float(latest.get("EMA_200", 0) or 0)
            if not (ema20 > ema50 > ema200):
                return False

        if self.config.rsi_min is not None or self.config.rsi_max is not None:
            rsi = float(latest.get("RSI", -1) or -1)
            if self.config.rsi_min is not None and rsi < self.config.rsi_min:
                return False
            if self.config.rsi_max is not None and rsi > self.config.rsi_max:
                return False

        atr_price = _resolve_atr_price(latest, close_price)
        if atr_price is None:
            return False
        if self.config.atr_price_min is not None and atr_price < self.config.atr_price_min:
            return False
        if self.config.atr_price_max is not None and atr_price > self.config.atr_price_max:
            return False

        return True


def _optional_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return float(value)


def _resolve_atr_price(latest, close_price: float) -> float | None:
    atr_ratio = latest.get("ATR_Ratio")
    if atr_ratio is not None:
        try:
            value = float(atr_ratio)
            if math.isfinite(value) and value > 0:
                return value
        except (TypeError, ValueError):
            pass

    atr = float(latest.get("ATR", 0) or 0)
    if close_price <= 0 or atr <= 0:
        return None
    return atr / close_price
