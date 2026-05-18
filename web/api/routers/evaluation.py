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
RANKING_MODES = ["prs_train"]
OVERLAY_MODES = ["off", "on"]
BUY_FILL_MODES = ["next_open", "next_close"]
CAPACITY_REGIME_MODES = ["off", "enforce"]


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


def _resolve_production_ranking_strategy(raw_config: dict[str, Any]) -> str:
    production_cfg = raw_config.get("production", {})
    if "signal_ranking_strategy" not in production_cfg:
        return "momentum"

    configured_value = production_cfg.get("signal_ranking_strategy")
    if configured_value is None:
        return ""
    return str(configured_value).strip()


def _resolve_requested_buy_fill_modes(req: EvaluationRunRequest) -> list[str]:
    requested_modes = req.buy_fill_modes or [req.buy_fill_mode]
    resolved: list[str] = []
    for mode in requested_modes:
        normalized = str(mode).strip()
        if normalized and normalized not in resolved:
            resolved.append(normalized)
    return resolved or [req.buy_fill_mode]


def _resolve_effective_ranking_strategies(
    req: EvaluationRunRequest,
    production_ranking_strategy: str,
) -> list[str] | None:
    if req.ranking_strategies:
        normalized = [
            str(strategy).strip()
            for strategy in req.ranking_strategies
            if str(strategy).strip()
        ]
        return normalized or None

    default_strategy = str(production_ranking_strategy or "").strip()
    if not default_strategy:
        return None
    return [default_strategy]


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


def _build_cli_args(
    req: EvaluationRunRequest,
    buy_fill_mode: str | None = None,
) -> list[str]:
    if req.command not in COMMANDS:
        raise HTTPException(status_code=400, detail=f"Unsupported command: {req.command}")

    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    production_entry, production_exit = _resolve_production_strategy_defaults(prod_cfg)
    production_ranking_strategy = _resolve_production_ranking_strategy(raw_config)

    args = [req.command]

    if req.command in {"evaluate", "pos-evaluation", "walk-forward-evaluate"}:
        if req.command == "walk-forward-evaluate" and req.mode not in {"annual", "quarterly"}:
            raise HTTPException(
                status_code=400,
                detail="walk-forward-evaluate only supports annual or quarterly mode.",
            )
        args.extend(["--mode", req.mode])

    args.extend(["--buy-fill-mode", buy_fill_mode or req.buy_fill_mode])
    if req.fill_buffer_enabled:
        args.append("--fill-buffer-enabled")
    args.extend(["--fill-buffer-pct", str(req.fill_buffer_pct)])

    if req.capacity_regime_mode:
        args.extend(["--capacity-regime-mode", req.capacity_regime_mode])

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

    _append_multi_flag(
        args,
        "--ranking-strategies",
        _resolve_effective_ranking_strategies(req, production_ranking_strategy),
    )

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
    default_position_file, default_profile_names, position_profiles = _load_position_profiles(
        raw_config
    )

    production_entry, production_exit = _resolve_production_strategy_defaults(prod_cfg)
    default_ranking_strategy = _resolve_production_ranking_strategy(raw_config)
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
        "buy_fill_modes": BUY_FILL_MODES,
        "capacity_regime_modes": CAPACITY_REGIME_MODES,
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
            "ranking_mode": "prs_train",
            "ranking_strategies": (
                [str(default_ranking_strategy)] if default_ranking_strategy else []
            ),
            "entry_filter_mode": "off",
            "entry_filter_names": [],
            "enable_overlay": False,
            "overlay_modes": ["off"],
            "buy_fill_mode": "next_open",
            "buy_fill_modes": ["next_open"],
            "fill_buffer_enabled": False,
            "fill_buffer_pct": 0.02,
            "capacity_regime_mode": str(eval_cfg.get("capacity_regime_mode", "off")),
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
    requested_buy_fill_modes = _resolve_requested_buy_fill_modes(req)

    async def event_stream():  # type: ignore[return]
        q: Queue[str | None] = Queue()

        def _emit_line(text: str) -> None:
            q.put(f"data: {json.dumps({'line': text})}\n\n")

        def _reader() -> None:
            final_code = 0
            total_modes = len(requested_buy_fill_modes)

            if total_modes > 1:
                _emit_line(
                    f"Running {total_modes} buy fill mode batches: {', '.join(requested_buy_fill_modes)}"
                )

            for index, buy_fill_mode in enumerate(requested_buy_fill_modes, start=1):
                if total_modes > 1:
                    _emit_line("=" * 80)
                    _emit_line(
                        f"[buy-fill {index}/{total_modes}] Starting full run for {buy_fill_mode}"
                    )
                    _emit_line("=" * 80)

                args = _build_cli_args(req, buy_fill_mode=buy_fill_mode)
                proc = subprocess.Popen(
                    ["uv", "run", "python", "main.py", *args],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(root),
                )
                assert proc.stdout is not None
                for raw_line in proc.stdout:
                    text = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                    _emit_line(text)

                code = proc.wait()
                if code != 0 and final_code == 0:
                    final_code = code

                if total_modes > 1:
                    status = "OK" if code == 0 else f"FAILED ({code})"
                    _emit_line(
                        f"[buy-fill {index}/{total_modes}] Completed {buy_fill_mode}: {status}"
                    )

            q.put(f"data: {json.dumps({'done': True, 'exit_code': final_code})}\n\n")
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
