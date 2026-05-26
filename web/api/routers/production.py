"""Production endpoints: daily run, status, set-cash, input trades."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path
from queue import Queue, Empty

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.api.dependencies import get_config_manager, get_production_config, get_project_root
from web.api.schemas import (
    ProductionDailyRequest,
    SetCashRequest,
    InputTradeRequest,
)

router = APIRouter(prefix="/api/production", tags=["production"])


def _append_atr_runtime_flags(args: list[str], req: ProductionDailyRequest) -> None:
    if req.position_sizing_mode:
        args.extend(["--position-sizing-mode", req.position_sizing_mode])
    if req.position_sizing_mode != "fixed":
        if req.risk_per_trade_pct is not None:
            args.extend(["--risk-per-trade-pct", str(req.risk_per_trade_pct)])
        if req.atr_stop_multiple is not None:
            args.extend(["--atr-stop-multiple", str(req.atr_stop_multiple)])
    if req.atr_ratio_min is not None:
        args.extend(["--atr-ratio-min", str(req.atr_ratio_min)])
    if req.atr_ratio_max is not None:
        args.extend(["--atr-ratio-max", str(req.atr_ratio_max)])


def _resolve_production_atr_defaults(cfg) -> dict[str, object]:
    raw_config = getattr(cfg, "raw_config", {}) or {}
    entry_filter = raw_config.get("production", {}).get("entry_filter")
    if not isinstance(entry_filter, dict):
        entry_filter = raw_config.get("evaluation", {}).get("filters", {}).get("default", {})
    if not isinstance(entry_filter, dict):
        entry_filter = {}
    return {
        "position_sizing_mode": str(getattr(cfg, "position_sizing_mode", "fixed") or "fixed"),
        "risk_per_trade_pct": float(getattr(cfg.atr_position_sizing, "risk_per_trade_pct", 0.006)),
        "atr_stop_multiple": float(getattr(cfg.atr_position_sizing, "atr_stop_multiple", 2.0)),
        "atr_ratio_min": entry_filter.get("atr_price_min"),
        "atr_ratio_max": entry_filter.get("atr_price_max"),
    }


async def _run_cli_streaming(args: list[str]) -> StreamingResponse:
    """Run a CLI command and stream stdout/stderr as SSE.

    Uses subprocess.Popen in a thread to avoid Windows asyncio subprocess limitations.
    """
    root = get_project_root()

    async def event_stream():  # type: ignore[return]
        q: Queue[str | None] = Queue()

        def _reader() -> None:
            proc = subprocess.Popen(
                ["uv", "run", "python", "main.py", *args],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(root),
            )
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                text = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                q.put(f"data: {json.dumps({'line': text})}\n\n")
            code = proc.wait()
            q.put(f"data: {json.dumps({'done': True, 'exit_code': code})}\n\n")
            q.put(None)  # sentinel

        t = threading.Thread(target=_reader, daemon=True)
        t.start()

        while True:
            # Yield control back to event loop while waiting for output
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(None, lambda: q.get(timeout=0.1))
            except Empty:
                continue
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
def production_status() -> dict[str, object]:
    cfg = get_production_config()
    state_path = Path(cfg.state_file)
    if not state_path.exists():
        raise HTTPException(status_code=404, detail="State file not found")
    state_data = json.loads(state_path.read_text(encoding="utf-8"))

    groups_summary: list[dict[str, object]] = []
    raw_groups = state_data.get("strategy_groups", [])
    items: list[tuple[str, dict]] = []
    if isinstance(raw_groups, list):
        items = [(g.get("id", f"group_{i}"), g) for i, g in enumerate(raw_groups)]
    elif isinstance(raw_groups, dict):
        items = list(raw_groups.items())
    for gid, g in items:
        positions = g.get("positions", [])
        groups_summary.append({
            "id": gid,
            "name": g.get("name", gid),
            "cash": g.get("cash", 0),
            "position_count": len(positions),
            "tickers": [p["ticker"] for p in positions],
        })

    return {
        "last_updated": state_data.get("last_updated", ""),
        "groups": groups_summary,
    }


@router.get("/options")
def production_options() -> dict[str, object]:
    cfg = get_production_config()
    cm = get_config_manager()
    stock_pools = [pool.to_api_dict() for pool in cm.list_stock_pools()]
    return {
        "production": {
            "monitor_list_file": str(getattr(cfg, "monitor_list_file", "") or ""),
            "sector_pool_file": str(getattr(cfg, "sector_pool_file", "") or ""),
            "stock_pool_catalog_file": str(getattr(cfg, "stock_pool_catalog_file", "") or ""),
        },
        "defaults": {
            "pool_id": "",
            **_resolve_production_atr_defaults(cfg),
        },
        "stock_pools": stock_pools,
    }


@router.post("/daily")
async def run_daily(req: ProductionDailyRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    args = ["production", "--daily"]
    if req.no_fetch:
        args.append("--no-fetch")
    if req.pool_id:
        args.extend(["--pool-id", req.pool_id])
    _append_atr_runtime_flags(args, req)
    return await _run_cli_streaming(args)


@router.post("/check-price-all")
async def run_check_price_all(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["production", "--check-price", "all"])


@router.post("/check-price-today")
async def run_check_price_today(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["production", "--check-price", "today"])


@router.post("/set-cash")
async def set_cash(req: SetCashRequest) -> dict[str, str]:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    root = get_project_root()
    proc = subprocess.run(
        [
            "uv", "run", "python", "main.py",
            "production", "--set-cash", str(req.amount),
            "--group-id", req.group_id,
        ],
        capture_output=True,
        cwd=str(root),
    )
    output = proc.stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        output += proc.stderr.decode("utf-8", errors="replace")
        raise HTTPException(status_code=500, detail=output)
    return {"status": "ok", "output": output}


@router.post("/input-trades")
async def input_trades(req: InputTradeRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    # Write trades to a temp CSV
    root = get_project_root()
    csv_path = root / "web" / "_temp_trades.csv"
    lines = ["ticker,action,qty,price,date"]
    for t in req.trades:
        lines.append(f"{t.ticker},{t.action},{t.quantity},{t.price},{t.date}")
    csv_path.write_text("\n".join(lines), encoding="utf-8")

    args = [
        "production", "--input", "--manual",
        "--manual-file", str(csv_path),
        "--yes",
    ]
    if req.aws_profile:
        args.extend(["--aws-profile", req.aws_profile])
    return await _run_cli_streaming(args)


class ConfirmRequest(BaseModel):
    confirm: bool = False


@router.post("/fetch")
async def run_fetch(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming(["fetch", "--all"])


@router.post("/universe")
async def run_universe(req: ConfirmRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    return await _run_cli_streaming([
        "universe-sector", "--score-model", "v2",
        "--size-balance", "--no-fetch", "--resume",
    ])
