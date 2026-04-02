"""Fine-grid variants for MultiDimensionalMAExit (MDX)."""

from __future__ import annotations

from typing import Dict

from src.analysis.strategies.exit.multidim_ma_exit import MultiDimensionalMAExit


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


_C_VALUES = [2, 3]
_R_VALUES = [3.2, 3.3, 3.4, 3.5]
_T_VALUES = [1.55, 1.60, 1.65, 1.70]
_D_VALUES = [18]
_O_VALUES = [74.0, 75.0, 76.0]


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


GRID_EXIT_FINE_STRATEGY_MAP: Dict[str, str] = {}

for _c in _C_VALUES:
    for _r in _R_VALUES:
        for _t in _T_VALUES:
            for _d in _D_VALUES:
                for _o in _O_VALUES:
                    _name = (
                        f"MDXF_C{_c}_R{_float_token(_r)}_T{_float_token(_t)}_"
                        f"D{_d}_O{_float_token(_o)}"
                    )
                    _cls = _build_variant_class(_name, _c, _r, _t, _d, _o)
                    globals()[_name] = _cls
                    GRID_EXIT_FINE_STRATEGY_MAP[_name] = (
                        f"src.analysis.strategies.exit.multidim_ma_fine_grid_exit.{_name}"
                    )


__all__ = [
    "GRID_EXIT_FINE_STRATEGY_MAP",
    *list(GRID_EXIT_FINE_STRATEGY_MAP.keys()),
]
