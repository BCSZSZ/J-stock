"""Evaluation endpoints: run evaluations, browse results."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from web.api.dependencies import get_production_config, get_project_root, get_config_manager
from web.api.schemas import EvaluationRunRequest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("/options")
def get_options() -> dict[str, object]:
    from src.utils.strategy_loader import get_available_strategies, get_available_ranking_strategies

    strategies = get_available_strategies()
    ranking = get_available_ranking_strategies()
    return {
        "entry_strategies": strategies.get("entry", []),
        "exit_strategies": strategies.get("exit", []),
        "ranking_strategies": ranking,
        "modes": ["annual", "quarterly", "monthly", "custom", "walk-forward"],
        "ranking_modes": ["legacy", "target20", "risk60_profit40"],
    }


@router.post("/run")
async def run_evaluation(req: EvaluationRunRequest) -> StreamingResponse:
    root = get_project_root()

    args = ["evaluate", "--mode", req.mode]

    if req.years:
        args.append("--years")
        args.extend(str(y) for y in req.years)

    args.append("--entry-strategies")
    args.extend(req.entry_strategies)

    args.append("--exit-strategies")
    args.extend(req.exit_strategies)

    if req.enable_overlay:
        args.append("--enable-overlay")

    if req.entry_filter_mode != "off":
        args.extend(["--entry-filter-mode", req.entry_filter_mode])

    async def event_stream():  # type: ignore[return]
        proc = await asyncio.create_subprocess_exec(
            "uv", "run", "python", "main.py", *args,
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


def _eval_output_dir() -> Path:
    """Resolve evaluation output directory from config."""
    cm = get_config_manager()
    eval_cfg = cm.raw_config.get("evaluation", {})
    out_dir = eval_cfg.get("output_dir", "strategy_evaluation")
    path = Path(out_dir)
    if not path.is_absolute():
        path = get_project_root() / path
    return path


@router.get("/results")
def list_results() -> list[dict[str, str]]:
    out_dir = _eval_output_dir()
    if not out_dir.exists():
        return []
    files: list[dict[str, str]] = []
    for f in sorted(out_dir.iterdir(), reverse=True):
        if f.suffix in (".csv", ".md"):
            files.append({
                "name": f.name,
                "type": f.suffix.lstrip("."),
                "size": str(f.stat().st_size),
            })
    return files


@router.get("/results/{filename}")
def get_result(filename: str) -> dict[str, object]:
    out_dir = _eval_output_dir()
    # Prevent path traversal
    safe_name = Path(filename).name
    path = out_dir / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Result not found: {safe_name}")

    if path.suffix == ".csv":
        import pandas as pd
        df = pd.read_csv(path)
        return {"type": "csv", "name": safe_name, "data": df.to_dict(orient="records")}
    else:
        content = path.read_text(encoding="utf-8")
        return {"type": "markdown", "name": safe_name, "content": content}
