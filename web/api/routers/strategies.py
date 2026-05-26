"""Strategy endpoints: list, details, metadata."""

from __future__ import annotations

import inspect
import math
import re
from itertools import product

from fastapi import APIRouter, HTTPException

from web.api.schemas import (
    MvxExitStrategyResolveRequest,
    MvxExitStrategyResolveResponse,
    MvxParameterInput,
)

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

_PARAM_SPLIT_RE = re.compile(r"[\s,;]+")


def _get_strategy_metadata(name: str, strategy_type: str) -> dict[str, object]:
    """Extract metadata from a strategy class via inspection."""
    from src.utils.strategy_loader import load_strategy_class

    try:
        cls = load_strategy_class(name, strategy_type=strategy_type)
    except (KeyError, ImportError, AttributeError) as exc:
        raise HTTPException(status_code=404, detail=f"Strategy not found: {name}") from exc

    # Extract __init__ parameters
    sig = inspect.signature(cls.__init__)
    params: list[dict[str, str]] = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        info: dict[str, str] = {"name": pname}
        if param.annotation != inspect.Parameter.empty:
            info["type"] = str(param.annotation)
        if param.default != inspect.Parameter.empty:
            info["default"] = str(param.default)
        params.append(info)

    # Extract docstring
    doc = inspect.getdoc(cls) or ""

    # Class-level metadata (optional, added in Phase 3)
    category = getattr(cls, "category", "uncategorized")
    description = getattr(cls, "description", doc.split("\n")[0] if doc else name)

    return {
        "name": name,
        "type": strategy_type,
        "category": category,
        "description": description,
        "docstring": doc,
        "parameters": params,
        "module": cls.__module__,
    }


@router.get("")
def list_strategies() -> dict[str, list[dict[str, object]]]:
    from src.utils.strategy_loader import get_available_strategies

    available = get_available_strategies()
    result: dict[str, list[dict[str, object]]] = {"entry": [], "exit": []}

    for stype in ("entry", "exit"):
        for name in available.get(stype, []):
            try:
                meta = _get_strategy_metadata(name, stype)
                result[stype].append(meta)
            except Exception:
                result[stype].append({
                    "name": name,
                    "type": stype,
                    "category": "uncategorized",
                    "description": name,
                    "parameters": [],
                })
    return result


def _split_parameter_values(raw: MvxParameterInput | None, field_name: str) -> list[str]:
    if raw is None:
        return []

    raw_values = raw if isinstance(raw, list) else [raw]
    tokens: list[str] = []
    for value in raw_values:
        text = str(value).strip()
        if not text:
            continue
        if "，" in text:
            raise HTTPException(
                status_code=422,
                detail=f"{field_name} must use half-width commas.",
            )
        tokens.extend(
            token.strip()
            for token in _PARAM_SPLIT_RE.split(text)
            if token.strip()
        )
    return tokens


def _parse_positive_float_tokens(tokens: list[str], field_name: str) -> list[float]:
    values: list[float] = []
    errors: list[str] = []
    for token in tokens:
        try:
            value = float(token.replace("p", "."))
        except ValueError:
            errors.append(f"{field_name}: invalid number '{token}'")
            continue
        if not math.isfinite(value) or value <= 0:
            errors.append(f"{field_name}: value must be positive ({token})")
            continue
        values.append(value)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return values


def _parse_positive_int_tokens(tokens: list[str], field_name: str) -> list[int]:
    float_values = _parse_positive_float_tokens(tokens, field_name)
    values: list[int] = []
    errors: list[str] = []
    for token, value in zip(tokens, float_values):
        if not value.is_integer():
            errors.append(f"{field_name}: value must be an integer ({token})")
            continue
        values.append(int(value))
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return values


def _require_values(values: list[int] | list[float], field_name: str) -> None:
    if not values:
        raise HTTPException(status_code=422, detail=f"{field_name} requires at least one value.")


@router.post("/exit/mvx-family/resolve", response_model=MvxExitStrategyResolveResponse)
def resolve_mvx_exit_strategies(
    req: MvxExitStrategyResolveRequest,
) -> MvxExitStrategyResolveResponse:
    from src.analysis.strategies.exit.multiview_grid_exit import make_mvx_exit_strategy_name
    from src.utils.strategy_loader import EXIT_STRATEGIES, ensure_exit_strategy_registered

    n_values = _parse_positive_int_tokens(_split_parameter_values(req.n_values, "N"), "N")
    r_values = _parse_positive_float_tokens(_split_parameter_values(req.r_values, "R"), "R")
    t_values = _parse_positive_float_tokens(_split_parameter_values(req.t_values, "T"), "T")
    d_values = _parse_positive_int_tokens(_split_parameter_values(req.d_values, "D"), "D")
    b_values = _parse_positive_float_tokens(_split_parameter_values(req.b_values, "B"), "B")

    _require_values(n_values, "N")
    _require_values(r_values, "R")
    _require_values(t_values, "T")
    _require_values(d_values, "D")
    _require_values(b_values, "B")

    i_tokens = _split_parameter_values(req.i_values, "I")
    if req.family == "MVXWL":
        i_values = _parse_positive_float_tokens(i_tokens or ["2.0"], "I")
    elif i_tokens:
        raise HTTPException(status_code=422, detail="I is only supported for MVXWL.")
    else:
        i_values = [None]

    combination_count = (
        len(n_values)
        * len(r_values)
        * len(t_values)
        * len(d_values)
        * len(b_values)
        * len(i_values)
    )
    if combination_count > req.max_combinations:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Generated combination count {combination_count} exceeds "
                f"limit {req.max_combinations}."
            ),
        )

    generated_names: list[str] = []
    already_registered: list[str] = []
    newly_registered: list[str] = []
    seen_names: set[str] = set()
    duplicate_count = 0

    for n, r, t, d, b, i in product(
        n_values,
        r_values,
        t_values,
        d_values,
        b_values,
        i_values,
    ):
        name = make_mvx_exit_strategy_name(req.family, n, r, t, d, b, i)
        if name in seen_names:
            duplicate_count += 1
            continue
        seen_names.add(name)
        was_registered = name in EXIT_STRATEGIES
        if not ensure_exit_strategy_registered(name):
            raise HTTPException(status_code=422, detail=f"Could not register {name}.")
        generated_names.append(name)
        if was_registered:
            already_registered.append(name)
        else:
            newly_registered.append(name)

    parameters = {
        "N": [str(value) for value in n_values],
        "R": [str(value) for value in r_values],
        "T": [str(value) for value in t_values],
        "D": [str(value) for value in d_values],
        "B": [str(value) for value in b_values],
    }
    if req.family == "MVXWL":
        parameters["I"] = [str(value) for value in i_values if value is not None]

    return MvxExitStrategyResolveResponse(
        family=req.family,
        parameters=parameters,
        generated_names=generated_names,
        already_registered=already_registered,
        newly_registered=newly_registered,
        duplicate_count=duplicate_count,
        combination_count=combination_count,
    )


@router.get("/{name}")
def get_strategy(name: str, type: str = "entry") -> dict[str, object]:
    return _get_strategy_metadata(name, type)
