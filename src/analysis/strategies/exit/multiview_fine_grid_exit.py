"""Fine-grid variants for MultiViewCompositeExit (MVX)."""

from __future__ import annotations

from typing import Dict

from src.analysis.strategies.exit.multiview_grid_exit import MultiViewCompositeExit


def _float_token(value: float) -> str:
    return str(value).replace(".", "p")


_N_VALUES = [8, 9, 10]
_R_VALUES = [3.50, 3.55, 3.60, 3.65]
_T_VALUES = [1.60, 1.65, 1.70, 1.75]
_D_VALUES = [18]
_B_VALUES = [19.75, 20.00, 20.25]


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


GRID_EXIT_FINE_STRATEGY_MAP: Dict[str, str] = {}

for _n in _N_VALUES:
    for _r in _R_VALUES:
        for _t in _T_VALUES:
            for _d in _D_VALUES:
                for _b in _B_VALUES:
                    _name = (
                        f"MVXF_N{_n}_R{_float_token(_r)}_T{_float_token(_t)}_"
                        f"D{_d}_B{_float_token(_b)}"
                    )
                    _cls = _build_variant_class(_name, _n, _r, _t, _d, _b)
                    globals()[_name] = _cls
                    GRID_EXIT_FINE_STRATEGY_MAP[_name] = (
                        f"src.analysis.strategies.exit.multiview_fine_grid_exit.{_name}"
                    )


__all__ = [
    "GRID_EXIT_FINE_STRATEGY_MAP",
    *list(GRID_EXIT_FINE_STRATEGY_MAP.keys()),
]
