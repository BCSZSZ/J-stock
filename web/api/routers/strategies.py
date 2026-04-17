"""Strategy endpoints: list, details, metadata."""

from __future__ import annotations

import inspect

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


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


@router.get("/{name}")
def get_strategy(name: str, type: str = "entry") -> dict[str, object]:
    return _get_strategy_metadata(name, type)
