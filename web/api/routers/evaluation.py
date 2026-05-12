"""Evaluation endpoints: run evaluations, browse results."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Queue, Empty
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.config.runtime import is_local_path
from web.api.dependencies import get_production_config, get_project_root, get_config_manager
from web.api.schemas import EvaluationRunRequest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

COMMANDS = ["evaluate", "pos-evaluation", "walk-forward-evaluate"]
EVALUATION_MODES = ["annual", "quarterly", "monthly", "custom"]
ENTRY_FILTER_MODES = ["off", "single", "grid", "auto"]
RANKING_MODES = ["legacy", "target20", "risk60_profit40"]
OVERLAY_MODES = ["off", "on"]


def _resolve_local_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    if not is_local_path(path_value):
        return None

    path = Path(path_value)
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _load_entry_filter_names(raw_config: dict[str, Any]) -> list[str]:
    eval_cfg = raw_config.get("evaluation", {})
    variants = eval_cfg.get("filters", {}).get("variants", {})
    if not isinstance(variants, dict):
        return []
    return [str(name) for name in variants.keys()]


def _load_position_profiles(raw_config: dict[str, Any]) -> tuple[str, list[str], list[str]]:
    eval_cfg = raw_config.get("evaluation", {})
    default_position_file = str(eval_cfg.get("default_position_file", "") or "")
    default_profile_names = [
        str(name) for name in eval_cfg.get("default_profile_names", []) or []
    ]
    resolved_path = _resolve_local_path(default_position_file)
    if resolved_path is None or not resolved_path.exists():
        return default_position_file, default_profile_names, []

    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except Exception:
        return default_position_file, default_profile_names, []

    if isinstance(payload, list):
        profiles = payload
    elif isinstance(payload, dict):
        profiles = (
            payload.get("portfolios")
            or payload.get("profiles")
            or payload.get("positions")
            or []
        )
    else:
        profiles = []

    names: list[str] = []
    for item in profiles:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name is None:
            continue
        names.append(str(name))
    return default_position_file, default_profile_names, names


def _append_multi_flag(args: list[str], flag: str, values: list[str] | list[int] | None) -> None:
    if not values:
        return

    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return

    args.append(flag)
    args.extend(normalized)


def _resolve_production_strategy_defaults(prod_cfg) -> tuple[str, str]:
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    preferred_group = None
    for group in strategy_groups:
        if not isinstance(group, dict):
            continue
        if str(group.get("id", "")) == "group_main":
            preferred_group = group
            break
        if preferred_group is None:
            preferred_group = group

    if isinstance(preferred_group, dict):
        entry_name = str(
            preferred_group.get("entry_strategy")
            or getattr(prod_cfg, "default_entry_strategy", "")
        )
        exit_name = str(
            preferred_group.get("exit_strategy")
            or getattr(prod_cfg, "default_exit_strategy", "")
        )
        return entry_name, exit_name

    return (
        str(getattr(prod_cfg, "default_entry_strategy", "")),
        str(getattr(prod_cfg, "default_exit_strategy", "")),
    )


def _build_cli_args(req: EvaluationRunRequest) -> list[str]:
    if req.command not in COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {req.command}")

    prod_cfg = get_production_config()
    production_entry, production_exit = _resolve_production_strategy_defaults(prod_cfg)

    args = [req.command]

    if req.command in {"evaluate", "pos-evaluation"}:
        args.extend(["--mode", req.mode])

    if req.years:
        _append_multi_flag(args, "--years", req.years)

    if req.command in {"evaluate", "pos-evaluation"} and req.mode == "monthly":
        _append_multi_flag(args, "--months", req.months)

    if req.command in {"evaluate", "pos-evaluation"} and req.mode == "custom":
        if not req.custom_periods:
            raise HTTPException(
                status_code=400,
                detail="custom mode requires custom_periods JSON.",
            )
        args.extend(["--custom-periods", req.custom_periods])

    if req.command == "walk-forward-evaluate":
        if not req.years:
            raise HTTPException(
                status_code=400,
                detail="walk-forward-evaluate requires years.",
            )
        if req.min_train_years is not None:
            args.extend(["--min-train-years", str(req.min_train_years)])

    entry_strategies = (
        req.entry_strategies if req.override_strategies and req.entry_strategies else [production_entry]
    )
    exit_strategies = (
        req.exit_strategies if req.override_strategies and req.exit_strategies else [production_exit]
    )
    _append_multi_flag(args, "--entry-strategies", entry_strategies)
    _append_multi_flag(args, "--exit-strategies", exit_strategies)

    if req.exit_confirm_days is not None:
        args.extend(["--exit-confirm-days", str(req.exit_confirm_days)])

    args.extend(["--entry-filter-mode", req.entry_filter_mode])
    _append_multi_flag(args, "--entry-filter-name", req.entry_filter_names)

    if req.output_dir:
        args.extend(["--output-dir", req.output_dir])

    _append_multi_flag(args, "--universe-file", [str(prod_cfg.monitor_list_file)])

    if req.verbose:
        args.append("--verbose")

    if req.command in {"evaluate", "walk-forward-evaluate"} and req.enable_overlay:
        args.append("--enable-overlay")

    if req.ranking_mode:
        args.extend(["--ranking-mode", req.ranking_mode])

    _append_multi_flag(args, "--ranking-strategies", req.ranking_strategies)

    if req.command == "pos-evaluation":
        if req.position_file:
            args.extend(["--position-file", req.position_file])
        _append_multi_flag(args, "--profile-name", req.profile_names)
        _append_multi_flag(args, "--overlay-modes", req.overlay_modes)

    return args


@router.get("/options")
def get_options() -> dict[str, object]:
    from src.utils.strategy_loader import get_available_strategies, get_available_ranking_strategies

    strategies = get_available_strategies()
    ranking = get_available_ranking_strategies()
    cm = get_config_manager()
    raw_config = cm.raw_config
    eval_cfg = raw_config.get("evaluation", {})
    prod_cfg = get_production_config()
    prod_raw_cfg = raw_config.get("production", {})
    default_position_file, default_profile_names, position_profiles = _load_position_profiles(
        raw_config
    )

    production_entry, production_exit = _resolve_production_strategy_defaults(prod_cfg)
    default_ranking_strategy = prod_raw_cfg.get("signal_ranking_strategy")
    default_universe_file = getattr(prod_cfg, "monitor_list_file", None)
    return {
        "commands": COMMANDS,
        "entry_strategies": strategies.get("entry", []),
        "exit_strategies": strategies.get("exit", []),
        "ranking_strategies": ranking,
        "modes": EVALUATION_MODES,
        "entry_filter_modes": ENTRY_FILTER_MODES,
        "entry_filter_names": _load_entry_filter_names(raw_config),
        "overlay_modes": OVERLAY_MODES,
        "ranking_modes": RANKING_MODES,
        "position_profiles": position_profiles,
        "production": {
            "entry_strategy": production_entry,
            "exit_strategy": production_exit,
            "ranking_strategy": str(default_ranking_strategy or ""),
            "monitor_list_file": str(default_universe_file or ""),
        },
        "defaults": {
            "command": "evaluate",
            "mode": "annual",
            "override_strategies": False,
            "entry_strategies": [production_entry] if production_entry else [],
            "exit_strategies": [production_exit] if production_exit else [],
            "ranking_mode": "target20",
            "ranking_strategies": (
                [str(default_ranking_strategy)] if default_ranking_strategy else []
            ),
            "entry_filter_mode": "off",
            "entry_filter_names": [],
            "enable_overlay": False,
            "overlay_modes": ["off"],
            "exit_confirm_days": eval_cfg.get("exit_confirmation_days"),
            "output_dir": str(eval_cfg.get("output_dir", "strategy_evaluation")),
            "universe_files": (
                [str(default_universe_file)] if default_universe_file else []
            ),
            "position_file": default_position_file,
            "profile_names": default_profile_names,
            "min_train_years": 2,
        },
    }


@router.post("/run")
async def run_evaluation(req: EvaluationRunRequest) -> StreamingResponse:
    root = get_project_root()
    args = _build_cli_args(req)

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


def _eval_output_dir(output_dir: str | None = None) -> Path:
    """Resolve evaluation output directory from config."""
    if output_dir:
        resolved = _resolve_local_path(output_dir)
        if resolved is None:
            raise HTTPException(status_code=400, detail="Only local output_dir is supported.")
        return resolved

    cm = get_config_manager()
    eval_cfg = cm.raw_config.get("evaluation", {})
    out_dir = eval_cfg.get("output_dir", "strategy_evaluation")
    resolved = _resolve_local_path(str(out_dir))
    if resolved is None:
        raise HTTPException(status_code=400, detail="Configured output_dir must be local.")
    return resolved


def _iter_result_files(output_root: Path) -> list[Path]:
    files = [
        path
        for path in output_root.rglob("*")
        if path.is_file() and path.suffix in (".csv", ".md")
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _resolve_result_file(output_root: Path, filename: str) -> Path:
    root_abs = Path(os.path.abspath(str(output_root)))
    candidate = Path(os.path.abspath(str(root_abs / filename)))
    root_cmp = os.path.normcase(str(root_abs))
    candidate_cmp = os.path.normcase(str(candidate))
    if os.path.commonpath([root_cmp, candidate_cmp]) != root_cmp:
        raise HTTPException(status_code=404, detail=f"Result not found: {filename}")

    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Result not found: {filename}")
    return candidate


@router.get("/results")
def list_results(output_dir: str | None = Query(default=None)) -> list[dict[str, str]]:
    out_dir = _eval_output_dir(output_dir)
    if not out_dir.exists():
        return []
    files: list[dict[str, str]] = []
    for f in _iter_result_files(out_dir):
        files.append({
            "name": f.relative_to(out_dir).as_posix(),
            "type": f.suffix.lstrip("."),
            "size": str(f.stat().st_size),
        })
    return files


@router.get("/results/{filename:path}")
def get_result(filename: str, output_dir: str | None = Query(default=None)) -> dict[str, object]:
    out_dir = _eval_output_dir(output_dir)
    path = _resolve_result_file(out_dir, filename)
    display_name = Path(os.path.relpath(path, start=out_dir)).as_posix()

    if path.suffix == ".csv":
        import pandas as pd
        df = pd.read_csv(path)
        return {"type": "csv", "name": display_name, "data": df.to_dict(orient="records")}
    else:
        content = path.read_text(encoding="utf-8")
        return {"type": "markdown", "name": display_name, "content": content}
