from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.analysis.strategies.exit import multiview_grid_exit as mvx_module
from src.analysis.strategies.exit.multiview_grid_exit import (
    make_mvx_exit_strategy_name,
    parse_mvx_exit_strategy_name,
)
from src.utils.strategy_loader import (
    EXIT_STRATEGIES,
    STRATEGY_CLASS_CACHE,
    load_exit_strategy,
)
from web.api.routers import strategies as strategies_router
from web.api.schemas import MvxExitStrategyResolveRequest


def _remove_dynamic_exit_strategy(name: str) -> None:
    mvx_module.GRID_EXIT_STRATEGY_MAP.pop(name, None)
    if hasattr(mvx_module, name):
        delattr(mvx_module, name)
    EXIT_STRATEGIES.pop(name, None)
    STRATEGY_CLASS_CACHE.pop(("exit", name), None)


def test_mvxwl_name_generation_and_parsing() -> None:
    name = make_mvx_exit_strategy_name("MVXWL", 3, 0.54, 1.3, 10, 20.0, 2.0)

    assert name == "MVXWL_N3_R0p54_T1p3_D10_B20p0_I2p0"

    spec = parse_mvx_exit_strategy_name(name)

    assert spec is not None
    assert spec.family == "MVXWL"
    assert spec.n == 3
    assert spec.r == 0.54
    assert spec.t == 1.3
    assert spec.d == 10
    assert spec.b == 20.0
    assert spec.i == 2.0


def test_loader_registers_valid_mvxwl_name_on_demand() -> None:
    name = "MVXWL_N13_R0p93_T2p07_D29_B21p35_I2p45"
    _remove_dynamic_exit_strategy(name)

    strategy = load_exit_strategy(name)

    assert strategy.strategy_name == name
    assert name in EXIT_STRATEGIES
    assert name in mvx_module.GRID_EXIT_STRATEGY_MAP


def test_resolve_mvx_family_generates_and_registers_cartesian_product() -> None:
    req = MvxExitStrategyResolveRequest(
        family="MVXW",
        n_values="12",
        r_values="0.91,0.92",
        t_values="2.03",
        d_values="28",
        b_values="21.3",
    )

    response = strategies_router.resolve_mvx_exit_strategies(req)

    assert response.generated_names == [
        "MVXW_N12_R0p91_T2p03_D28_B21p3",
        "MVXW_N12_R0p92_T2p03_D28_B21p3",
    ]
    assert response.combination_count == 2
    assert all(name in EXIT_STRATEGIES for name in response.generated_names)


def test_resolve_mvxwl_defaults_initial_stop_multiple() -> None:
    req = MvxExitStrategyResolveRequest(
        family="MVXWL",
        n_values="14",
        r_values="0.94",
        t_values="2.04",
        d_values="30",
        b_values="21.4",
    )

    response = strategies_router.resolve_mvx_exit_strategies(req)

    assert response.generated_names == ["MVXWL_N14_R0p94_T2p04_D30_B21p4_I2p0"]
    assert response.parameters["I"] == ["2.0"]


def test_resolve_rejects_full_width_commas() -> None:
    req = MvxExitStrategyResolveRequest(
        family="MVX",
        n_values="3，5",
        r_values="0.54",
        t_values="1.3",
        d_values="10",
        b_values="20.0",
    )

    with pytest.raises(HTTPException) as exc_info:
        strategies_router.resolve_mvx_exit_strategies(req)

    assert exc_info.value.status_code == 422


def test_resolve_rejects_excessive_combinations() -> None:
    req = MvxExitStrategyResolveRequest(
        family="MVX",
        n_values="3,5",
        r_values="0.54,0.55",
        t_values="1.3",
        d_values="10",
        b_values="20.0",
        max_combinations=3,
    )

    with pytest.raises(HTTPException) as exc_info:
        strategies_router.resolve_mvx_exit_strategies(req)

    assert exc_info.value.status_code == 422
