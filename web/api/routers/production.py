"""Production endpoints: daily run, status, set-cash, input trades."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from web.api.dependencies import get_production_config, get_project_root
from web.api.schemas import (
    ProductionDailyRequest,
    SetCashRequest,
    InputTradeRequest,
)

router = APIRouter(prefix="/api/production", tags=["production"])


async def _run_cli_streaming(args: list[str]) -> StreamingResponse:
    """Run a CLI command and stream stdout/stderr as SSE."""
    root = get_project_root()
    uv = "uv"

    async def event_stream():  # type: ignore[return]
        proc = await asyncio.create_subprocess_exec(
            uv, "run", "python", "main.py", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(root),
        )
        assert proc.stdout is not None
        async for line in proc.stdout:
            text = line.decode("utf-8", errors="replace").rstrip("\n")
            yield f"data: {json.dumps({'line': text})}\n\n"
        code = await proc.wait()
        yield f"data: {json.dumps({'done': True, 'exit_code': code})}\n\n"

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


@router.post("/daily")
async def run_daily(req: ProductionDailyRequest) -> StreamingResponse:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    args = ["production", "--daily"]
    if req.no_fetch:
        args.append("--no-fetch")
    return await _run_cli_streaming(args)


@router.post("/set-cash")
async def set_cash(req: SetCashRequest) -> dict[str, str]:
    if not req.confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")
    root = get_project_root()
    proc = await asyncio.create_subprocess_exec(
        "uv", "run", "python", "main.py",
        "production", "--set-cash", str(req.amount),
        "--group-id", req.group_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(root),
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode("utf-8", errors="replace")
    if proc.returncode != 0:
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
