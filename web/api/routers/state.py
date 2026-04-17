"""State endpoints: portfolio, trade history, signals, reports."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from web.api.dependencies import get_production_config
from web.api.schemas import PortfolioResponse, StrategyGroupOut, PositionOut

router = APIRouter(prefix="/api/state", tags=["state"])


def _load_json(path: str | Path) -> object:
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p.name}")
    return json.loads(p.read_text(encoding="utf-8"))


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio() -> PortfolioResponse:
    cfg = get_production_config()
    state_data = _load_json(cfg.state_file)

    groups: list[StrategyGroupOut] = []
    raw_groups = state_data.get("strategy_groups", [])
    # Handle both list and dict formats
    items: list[tuple[str, dict]] = []
    if isinstance(raw_groups, list):
        items = [(g.get("id", f"group_{i}"), g) for i, g in enumerate(raw_groups)]
    elif isinstance(raw_groups, dict):
        items = list(raw_groups.items())
    for gid, g in items:
        positions = [
            PositionOut(
                ticker=p["ticker"],
                quantity=p["quantity"],
                entry_price=p["entry_price"],
                entry_date=p["entry_date"],
                entry_score=p.get("entry_score", 0.0),
                peak_price=p.get("peak_price", p["entry_price"]),
                lot_id=p.get("lot_id", ""),
            )
            for p in g.get("positions", [])
        ]
        groups.append(
            StrategyGroupOut(
                id=gid,
                name=g.get("name", gid),
                initial_capital=g.get("initial_capital", 0),
                cash=g.get("cash", 0),
                positions=positions,
            )
        )

    return PortfolioResponse(
        groups=groups,
        last_updated=state_data.get("last_updated", ""),
    )


@router.get("/trade-history")
def get_trade_history() -> dict[str, object]:
    cfg = get_production_config()
    data = _load_json(cfg.history_file)
    return data


@router.get("/cash-history")
def get_cash_history() -> dict[str, object]:
    cfg = get_production_config()
    data = _load_json(cfg.cash_history_file)
    return data


@router.get("/signals")
def list_signals() -> list[str]:
    """List available signal dates."""
    cfg = get_production_config()
    pattern = cfg.signal_file_pattern
    signal_dir = Path(pattern).parent
    if not signal_dir.exists():
        return []
    dates = sorted(
        [f.stem for f in signal_dir.glob("*.json")],
        reverse=True,
    )
    return dates


@router.get("/signals/{date}")
def get_signals(date: str) -> list[dict[str, object]]:
    cfg = get_production_config()
    path = cfg.signal_file_pattern.replace("{date}", date)
    data = _load_json(path)
    if isinstance(data, list):
        return data
    return data.get("signals", [])


@router.get("/reports")
def list_reports() -> list[str]:
    """List available report dates."""
    cfg = get_production_config()
    pattern = cfg.report_file_pattern
    report_dir = Path(pattern).parent
    if not report_dir.exists():
        return []
    dates = sorted(
        [f.stem for f in report_dir.glob("*.md")],
        reverse=True,
    )
    return dates


@router.get("/reports/{date}")
def get_report(date: str) -> dict[str, str]:
    cfg = get_production_config()
    path = Path(cfg.report_file_pattern.replace("{date}", date))
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {date}")
    content = path.read_text(encoding="utf-8")
    return {"date": date, "content": content}
