"""Fine-grid variants for MovingAverageCrossoverEntry."""

from __future__ import annotations

from typing import Dict

from src.analysis.strategies.entry.moving_average_crossover_entry import (
    MovingAverageCrossoverEntry,
)


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


_MA_COL_TOKEN_MAP = {
    "EMA_20": "E20",
    "EMA_50": "E50",
    "EMA_200": "E200",
    "SMA_20": "S20",
    "SMA_25": "S25",
}

# Focused fine-grid families from Phase-A evidence
_FAST_SLOW_FAMILIES = [
    ("EMA_20", "EMA_50"),
    ("SMA_20", "EMA_50"),
    ("SMA_25", "EMA_200"),
]

# Smaller steps than Phase-A
_SPREAD_VALUES = [0.0, 0.05, 0.10, 0.15, 0.20]
_CONF_VALUES = [0.56, 0.58, 0.60, 0.62, 0.64]
_PRICE_ABOVE_VALUES = [False, True]


def _build_variant_class(
    name: str,
    fast_ma_col: str,
    slow_ma_col: str,
    min_spread_pct: float,
    require_price_above_slow: bool,
    min_confidence: float,
):
    def __init__(self):
        MovingAverageCrossoverEntry.__init__(
            self,
            fast_ma_col=fast_ma_col,
            slow_ma_col=slow_ma_col,
            min_spread_pct=min_spread_pct,
            require_price_above_slow=require_price_above_slow,
            confirm_with_volume=False,
            volume_multiplier=1.1,
            min_confidence=min_confidence,
        )
        self.strategy_name = name

    return type(name, (MovingAverageCrossoverEntry,), {"__init__": __init__})


GRID_ENTRY_FINE_STRATEGY_MAP: Dict[str, str] = {}

for _fast, _slow in _FAST_SLOW_FAMILIES:
    for _spread in _SPREAD_VALUES:
        for _price_above in _PRICE_ABOVE_VALUES:
            for _conf in _CONF_VALUES:
                _fast_token = _MA_COL_TOKEN_MAP[_fast]
                _slow_token = _MA_COL_TOKEN_MAP[_slow]
                _spread_token = _float_token(_spread)
                _price_token = "A1" if _price_above else "A0"
                _conf_token = _float_token(_conf)

                _name = (
                    f"MACXF_F{_fast_token}_S{_slow_token}_"
                    f"P{_spread_token}_{_price_token}_C{_conf_token}"
                )

                _cls = _build_variant_class(
                    _name,
                    _fast,
                    _slow,
                    _spread,
                    _price_above,
                    _conf,
                )
                globals()[_name] = _cls
                GRID_ENTRY_FINE_STRATEGY_MAP[_name] = (
                    f"src.analysis.strategies.entry.moving_average_crossover_fine_grid.{_name}"
                )


__all__ = [
    "GRID_ENTRY_FINE_STRATEGY_MAP",
    *list(GRID_ENTRY_FINE_STRATEGY_MAP.keys()),
]
