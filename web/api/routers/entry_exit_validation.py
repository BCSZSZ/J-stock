"""Entry x Exit validation endpoints."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.entry_exit_validation.models import EntryExitValidationDatasetManifest
from src.entry_exit_validation.paths import default_output_dir
from src.entry_signal_analysis.runtime import resolve_production_ranking_strategy
from web.api.dependencies import get_config_manager, get_production_config, get_project_root
from web.api.schemas import EntryExitValidationRunRequest

router = APIRouter(prefix="/api/entry-exit-validation", tags=["entry-exit-validation"])


def _default_output_dir() -> str:
    raw_config = get_config_manager().raw_config
    cfg = raw_config.get("entry_exit_validation", {}) if isinstance(raw_config, dict) else {}
    configured = str(cfg["output_dir"]) if isinstance(cfg, dict) and cfg.get("output_dir") else None
    return default_output_dir(configured)


def _entry_output_dir(output_dir: str | None = None) -> Path:
    raw = output_dir or _default_output_dir()
    path = Path(raw)
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _append_multi_flag(args: list[str], flag: str, values: list[object] | None) -> None:
    if not values:
        return
    args.append(flag)
    args.extend(str(value) for value in values)


def _production_strategy_defaults() -> tuple[list[str], list[str]]:
    prod_cfg = get_production_config()
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    entries: list[str] = []
    exits: list[str] = []
    for group in strategy_groups:
        if not isinstance(group, dict):
            continue
        entry = group.get("entry_strategy")
        if entry and str(entry) not in entries:
            entries.append(str(entry))
        exit_strategy = group.get("exit_strategy")
        if exit_strategy and str(exit_strategy) not in exits:
            exits.append(str(exit_strategy))
    default_entry = getattr(prod_cfg, "default_entry_strategy", "")
    if not entries and default_entry:
        entries.append(str(default_entry))
    default_exit = getattr(prod_cfg, "default_exit_strategy", "")
    if not exits and default_exit:
        exits.append(str(default_exit))
    return entries, exits


def _build_cli_args(req: EntryExitValidationRunRequest) -> list[str]:
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    default_entries, default_exits = _production_strategy_defaults()
    entry_strategies = req.entry_strategies or default_entries
    exit_strategies = req.exit_strategies or default_exits
    universe_files = req.universe_files or [str(getattr(prod_cfg, "monitor_list_file", "") or "")]
    ranking_strategy = req.ranking_strategy or resolve_production_ranking_strategy(raw_config)

    args = ["entry-exit-validation"]
    _append_multi_flag(args, "--entry-strategies", [value for value in entry_strategies if value])
    _append_multi_flag(args, "--exit-strategies", [value for value in exit_strategies if value])
    _append_multi_flag(args, "--universe-file", [value for value in universe_files if value])

    if req.years:
        _append_multi_flag(args, "--years", req.years)
    else:
        if req.start:
            args.extend(["--start", req.start])
        if req.end:
            args.extend(["--end", req.end])

    _append_multi_flag(args, "--horizons", req.horizons)
    args.extend(["--primary-horizon", str(req.primary_horizon)])
    args.extend(["--execution-mode", req.execution_mode])
    args.extend(["--signal-scope", req.signal_scope])
    if ranking_strategy:
        args.extend(["--ranking-strategy", ranking_strategy])
    args.extend(["--entry-filter-mode", req.entry_filter_mode])
    _append_multi_flag(args, "--entry-filter-name", req.entry_filter_names)

    fields_set = getattr(req, "model_fields_set", set())
    if req.atr_ratio_min is not None:
        args.extend(["--atr-ratio-min", str(req.atr_ratio_min)])
    elif "atr_ratio_min" in fields_set:
        args.extend(["--atr-ratio-min", "none"])
    if req.atr_ratio_max is not None:
        args.extend(["--atr-ratio-max", str(req.atr_ratio_max)])
    elif "atr_ratio_max" in fields_set:
        args.extend(["--atr-ratio-max", "none"])

    if req.tail_guard_enabled is True:
        args.append("--tail-guard-enabled")
    elif req.tail_guard_enabled is False:
        args.append("--no-tail-guard-enabled")
    if req.tail_guard_max_rank is not None:
        args.extend(["--tail-guard-max-rank", str(req.tail_guard_max_rank)])
    args.extend(["--max-holding-trading-days", str(req.max_holding_trading_days)])
    args.extend(["--partial-exit-policy", req.partial_exit_policy])
    args.extend(["--min-samples", str(req.min_samples)])
    if req.limit is not None:
        args.extend(["--limit", str(req.limit)])
    args.extend(["--data-root", req.data_root])
    if req.output_dir:
        args.extend(["--output-dir", req.output_dir])
    return args


def _manifest_files(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    files = [path for path in output_root.rglob("entry_exit_validation_manifest.json") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _read_manifest(path: Path) -> EntryExitValidationDatasetManifest:
    return EntryExitValidationDatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_dataset_dir(output_root: Path, dataset_id: str) -> Path:
    root_abs = Path(os.path.abspath(str(output_root)))
    candidate = Path(os.path.abspath(str(root_abs / dataset_id)))
    root_cmp = os.path.normcase(str(root_abs))
    candidate_cmp = os.path.normcase(str(candidate))
    if os.path.commonpath([root_cmp, candidate_cmp]) != root_cmp:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    manifest = candidate / "entry_exit_validation_manifest.json"
    if not candidate.exists() or not candidate.is_dir() or not manifest.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return candidate


def _resolve_manifest_artifact(dataset_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute() and path.exists():
        return path
    project_relative = get_project_root() / path
    if project_relative.exists():
        return project_relative
    dataset_relative = dataset_dir / path
    if dataset_relative.exists():
        return dataset_relative
    dataset_filename = dataset_dir / path.name
    if dataset_filename.exists():
        return dataset_filename
    return path if path.is_absolute() else dataset_relative


def _manifest_summary(output_root: Path, manifest_path: Path) -> dict[str, object]:
    manifest = _read_manifest(manifest_path)
    dataset_dir = manifest_path.parent
    return {
        "id": dataset_dir.relative_to(output_root).as_posix(),
        "dataset_id": manifest.dataset_id,
        "generated_at": manifest.generated_at,
        "candidate_count": manifest.candidate_count,
        "simulated_trade_count": manifest.simulated_trade_count,
        "entry_strategies": manifest.entry_strategies,
        "exit_strategies": manifest.exit_strategies,
        "start_date": manifest.start_date,
        "end_date": manifest.end_date,
        "horizons": manifest.horizons,
        "execution_mode": manifest.execution_mode,
        "signal_scope": manifest.signal_scope,
        "ranking_strategy": manifest.ranking_strategy,
        "output_dir": manifest.output_dir,
    }


async def _run_cli_streaming(args: list[str]) -> StreamingResponse:
    root = get_project_root()
    cmd = ["uv", "run", "python", "main.py", *args]
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    queue: Queue[str | None] = Queue()

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            queue.put(line.rstrip("\n"))
        queue.put(None)

    threading.Thread(target=_reader, daemon=True).start()

    async def event_stream():
        while True:
            try:
                item = queue.get_nowait()
            except Empty:
                await asyncio.sleep(0.05)
                continue
            if item is None:
                break
            yield f"data: {json.dumps({'line': item})}\n\n"
        return_code = proc.wait()
        yield f"data: {json.dumps({'done': True, 'exit_code': return_code})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/options")
def get_options() -> dict[str, object]:
    from src.utils.strategy_loader import get_available_strategies

    strategies = get_available_strategies()
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    production_cfg = raw_config.get("production", {}) if isinstance(raw_config, dict) else {}
    production_filter = production_cfg.get("entry_filter") if isinstance(production_cfg, dict) else {}
    if not isinstance(production_filter, dict):
        production_filter = {}
    tail_guard = production_cfg.get("tail_guard") if isinstance(production_cfg, dict) else {}
    if not isinstance(tail_guard, dict):
        tail_guard = {}
    default_entries, default_exits = _production_strategy_defaults()
    return {
        "entry_strategies": strategies.get("entry", []),
        "exit_strategies": strategies.get("exit", []),
        "execution_modes": ["next_open", "signal_close"],
        "signal_scopes": ["all", "selected"],
        "entry_filter_modes": ["auto", "off", "atr", "single", "grid"],
        "defaults": {
            "entry_strategies": default_entries,
            "exit_strategies": default_exits,
            "universe_files": [str(getattr(prod_cfg, "monitor_list_file", "") or "")],
            "horizons": [3, 5, 7, 9, 11],
            "primary_horizon": 5,
            "execution_mode": "next_open",
            "signal_scope": "all",
            "ranking_strategy": resolve_production_ranking_strategy(raw_config),
            "entry_filter_mode": "auto",
            "entry_filter_names": [],
            "atr_ratio_min": production_filter.get("atr_price_min"),
            "atr_ratio_max": production_filter.get("atr_price_max"),
            "tail_guard_enabled": bool(tail_guard.get("enabled", True)),
            "tail_guard_max_rank": int(tail_guard.get("max_rank", 12) or 12),
            "max_holding_trading_days": 60,
            "partial_exit_policy": "first_sell_full_exit",
            "min_samples": 30,
            "data_root": "data",
            "output_dir": _default_output_dir(),
        },
    }


@router.post("/run")
async def run_entry_exit_validation(req: EntryExitValidationRunRequest) -> StreamingResponse:
    return await _run_cli_streaming(_build_cli_args(req))


@router.get("/datasets")
def list_datasets(output_dir: str | None = Query(default=None)) -> list[dict[str, object]]:
    out_dir = _entry_output_dir(output_dir)
    return [_manifest_summary(out_dir, path) for path in _manifest_files(out_dir)]


@router.get("/datasets/{dataset_id:path}/summary")
def get_dataset_summary(dataset_id: str, output_dir: str | None = Query(default=None)) -> dict[str, object]:
    out_dir = _entry_output_dir(output_dir)
    dataset_dir = _resolve_dataset_dir(out_dir, dataset_id)
    manifest = _read_manifest(dataset_dir / "entry_exit_validation_manifest.json")
    summary_path = _resolve_manifest_artifact(dataset_dir, manifest.summary_json)
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Summary JSON not found")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "id": dataset_id,
        "manifest": manifest.model_dump(mode="json"),
        "summary": summary,
    }
