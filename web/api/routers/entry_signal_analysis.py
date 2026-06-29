"""Entry Signal Analysis endpoints: production-style daily signal quality datasets."""

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

from src.entry_signal_analysis.models import EntrySignalAnalysisDatasetManifest
from src.entry_signal_analysis.paths import default_output_dir
from src.entry_signal_analysis.runtime import resolve_production_ranking_strategy
from src.utils.momentum_exhaustion import (
    DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    resolve_momentum_exhaustion_config,
)
from src.utils.industry_filter import (
    DEFAULT_INDUSTRY_FILTER_MODE,
    resolve_industry_filter_config,
)
from web.api.dependencies import get_config_manager, get_production_config, get_project_root
from web.api.schemas import EntrySignalAnalysisRunRequest

router = APIRouter(prefix="/api/entry-signal-analysis", tags=["entry-signal-analysis"])


def _default_output_dir() -> str:
    raw_config = get_config_manager().raw_config
    entry_cfg = raw_config.get("entry_signal_analysis", {}) if isinstance(raw_config, dict) else {}
    configured = str(entry_cfg["output_dir"]) if isinstance(entry_cfg, dict) and entry_cfg.get("output_dir") else None
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


def _append_momentum_exhaustion_flags(
    args: list[str],
    req: EntrySignalAnalysisRunRequest,
) -> None:
    if req.momentum_exhaustion_mode:
        args.extend(["--momentum-exhaustion-mode", req.momentum_exhaustion_mode])
    if req.momentum_exhaustion_max_score is not None:
        args.extend(["--momentum-exhaustion-max-score", str(req.momentum_exhaustion_max_score)])
    if req.momentum_exhaustion_threshold_method:
        args.extend(
            [
                "--momentum-exhaustion-threshold-method",
                req.momentum_exhaustion_threshold_method,
            ]
        )


def _append_industry_filter_flags(
    args: list[str],
    req: EntrySignalAnalysisRunRequest,
) -> None:
    if req.industry_filter_mode:
        args.extend(["--industry-filter-mode", req.industry_filter_mode])
    if req.max_buy_per_industry_per_day is not None:
        args.extend([
            "--max-buy-per-industry-per-day",
            str(req.max_buy_per_industry_per_day),
        ])
    if req.max_total_positions_per_industry is not None:
        args.extend([
            "--max-total-positions-per-industry",
            str(req.max_total_positions_per_industry),
        ])
    if req.industry_reference_file:
        args.extend(["--industry-reference-file", req.industry_reference_file])


def _resolve_momentum_exhaustion_defaults(raw_config: dict[str, object]) -> dict[str, object]:
    cfg = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
        use_configured_mode=False,
    )
    return {
        "momentum_exhaustion_mode": cfg.mode,
        "momentum_exhaustion_max_score": cfg.max_score,
        "momentum_exhaustion_threshold_method": cfg.threshold_method,
    }


def _resolve_industry_filter_defaults(raw_config: dict[str, object]) -> dict[str, object]:
    cfg = resolve_industry_filter_config(
        raw_config,
        default_mode=DEFAULT_INDUSTRY_FILTER_MODE,
    )
    return {
        "industry_filter_mode": cfg.mode,
        "max_buy_per_industry_per_day": cfg.max_buy_per_industry_per_day,
        "max_total_positions_per_industry": cfg.max_total_positions_per_industry,
        "industry_reference_file": cfg.reference_file,
    }


def _build_cli_args(req: EntrySignalAnalysisRunRequest) -> list[str]:
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    production_entry = None
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    if strategy_groups and isinstance(strategy_groups[0], dict):
        production_entry = strategy_groups[0].get("entry_strategy")
    if not production_entry:
        production_entry = getattr(prod_cfg, "default_entry_strategy", "")

    entry_strategies = req.entry_strategies or ([str(production_entry)] if production_entry else [])
    universe_files = req.universe_files or [str(getattr(prod_cfg, "monitor_list_file", "") or "")]
    ranking_strategy = req.ranking_strategy or resolve_production_ranking_strategy(raw_config)
    args = ["entry-signal-analysis"]
    _append_multi_flag(args, "--entry-strategies", [value for value in entry_strategies if value])
    _append_multi_flag(args, "--universe-file", [value for value in universe_files if value])
    args.extend(["--analysis-profile", req.analysis_profile])
    args.extend(["--large-artifact-format", req.large_artifact_format])

    if req.years:
        _append_multi_flag(args, "--years", req.years)
    else:
        if req.start:
            args.extend(["--start", req.start])
        if req.end:
            args.extend(["--end", req.end])

    _append_multi_flag(args, "--horizons", req.horizons)
    primary_horizons = [int(value) for value in (req.primary_horizons or []) if int(value) > 0]
    if primary_horizons:
        _append_multi_flag(args, "--primary-horizons", primary_horizons)
        args.extend(["--primary-horizon", str(primary_horizons[0])])
    else:
        args.extend(["--primary-horizon", str(req.primary_horizon)])
    args.extend(["--label-mode", req.label_mode])
    if ranking_strategy:
        args.extend(["--ranking-strategy", ranking_strategy])
    args.extend(["--entry-filter-mode", req.entry_filter_mode])
    _append_multi_flag(args, "--entry-filter-name", req.entry_filter_names)

    fields_set = getattr(req, "model_fields_set", set())
    if req.position_sizing_mode:
        args.extend(["--position-sizing-mode", req.position_sizing_mode])
    if req.risk_per_trade_pct is not None:
        args.extend(["--risk-per-trade-pct", str(req.risk_per_trade_pct)])
    if req.atr_stop_multiple is not None:
        args.extend(["--atr-stop-multiple", str(req.atr_stop_multiple)])
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
    _append_momentum_exhaustion_flags(args, req)
    _append_industry_filter_flags(args, req)
    _append_multi_flag(args, "--target-pcts", req.target_pcts)
    _append_multi_flag(args, "--stop-pcts", req.stop_pcts)
    _append_multi_flag(args, "--target-stop-horizons", req.target_stop_horizons)
    _append_multi_flag(args, "--checkpoint-days", req.checkpoint_days)
    _append_multi_flag(args, "--cooldown-days", req.cooldown_days)
    _append_multi_flag(args, "--late-entry-days", req.late_entry_days)
    _append_multi_flag(args, "--cost-bps", req.cost_bps)
    if req.limit is not None:
        args.extend(["--limit", str(req.limit)])
    args.extend(["--data-root", req.data_root])
    if req.output_dir:
        args.extend(["--output-dir", req.output_dir])
    return args


def _manifest_files(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    files = [path for path in output_root.rglob("entry_signal_analysis_manifest.json") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _read_manifest(path: Path) -> EntrySignalAnalysisDatasetManifest:
    return EntrySignalAnalysisDatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_dataset_dir(output_root: Path, dataset_id: str) -> Path:
    root_abs = Path(os.path.abspath(str(output_root)))
    candidate = Path(os.path.abspath(str(root_abs / dataset_id)))
    root_cmp = os.path.normcase(str(root_abs))
    candidate_cmp = os.path.normcase(str(candidate))
    if os.path.commonpath([root_cmp, candidate_cmp]) != root_cmp:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    manifest = candidate / "entry_signal_analysis_manifest.json"
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
        "selected_count": manifest.selected_count,
        "entry_strategies": manifest.entry_strategies,
        "start_date": manifest.start_date,
        "end_date": manifest.end_date,
        "horizons": manifest.horizons,
        "analysis_profile": manifest.analysis_profile,
        "label_mode": manifest.label_mode,
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
            payload = json.dumps({"line": item})
            yield f"data: {payload}\n\n"

        return_code = proc.wait()
        payload = json.dumps({"done": True, "exit_code": return_code})
        yield f"data: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/options")
def get_options() -> dict[str, object]:
    from src.utils.strategy_loader import get_available_strategies

    strategies = get_available_strategies()
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    production_cfg = raw_config.get("production", {}) if isinstance(raw_config, dict) else {}
    strategy_groups = getattr(prod_cfg, "strategy_groups", None) or []
    production_entry = getattr(prod_cfg, "default_entry_strategy", "")
    if strategy_groups and isinstance(strategy_groups[0], dict):
        production_entry = str(strategy_groups[0].get("entry_strategy") or production_entry)
    production_filter = production_cfg.get("entry_filter") if isinstance(production_cfg, dict) else {}
    if not isinstance(production_filter, dict):
        production_filter = {}
    tail_guard = production_cfg.get("tail_guard") if isinstance(production_cfg, dict) else {}
    if not isinstance(tail_guard, dict):
        tail_guard = {}
    return {
        "entry_strategies": strategies.get("entry", []),
        "label_modes": ["signal_close", "next_open"],
        "analysis_profiles": ["legacy", "priority15"],
        "entry_filter_modes": ["auto", "off", "atr", "single", "grid"],
        "defaults": {
            "entry_strategies": [production_entry] if production_entry else [],
            "universe_files": [str(getattr(prod_cfg, "monitor_list_file", "") or "")],
            "analysis_profile": "priority15",
            "large_artifact_format": "parquet",
            "horizons": [1, 2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 80],
            "primary_horizon": 5,
            "primary_horizons": [5],
            "label_mode": "next_open",
            "ranking_strategy": resolve_production_ranking_strategy(raw_config),
            "entry_filter_mode": "auto",
            "entry_filter_names": [],
            "position_sizing_mode": str(getattr(prod_cfg, "position_sizing_mode", "atr") or "atr"),
            "risk_per_trade_pct": float(getattr(prod_cfg.atr_position_sizing, "risk_per_trade_pct", 0.0) or 0.0),
            "atr_stop_multiple": float(getattr(prod_cfg.atr_position_sizing, "atr_stop_multiple", 0.0) or 0.0),
            "atr_ratio_min": production_filter.get("atr_price_min"),
            "atr_ratio_max": production_filter.get("atr_price_max"),
            "tail_guard_enabled": bool(tail_guard.get("enabled", True)),
            "tail_guard_max_rank": int(tail_guard.get("max_rank", 12) or 12),
            **_resolve_momentum_exhaustion_defaults(raw_config),
            **_resolve_industry_filter_defaults(raw_config),
            "target_pcts": [5, 8, 10, 15, 20],
            "stop_pcts": [3, 5, 8, 10, 12],
            "target_stop_horizons": [10, 20, 40, 60, 80],
            "checkpoint_days": [10, 20, 40],
            "cooldown_days": [5, 10, 20, 40],
            "late_entry_days": [1, 2, 3, 5],
            "cost_bps": [10, 20, 50, 100],
            "data_root": "data",
            "output_dir": _default_output_dir(),
        },
    }


@router.post("/run")
async def run_entry_signal_analysis(req: EntrySignalAnalysisRunRequest) -> StreamingResponse:
    return await _run_cli_streaming(_build_cli_args(req))


@router.get("/datasets")
def list_datasets(output_dir: str | None = Query(default=None)) -> list[dict[str, object]]:
    out_dir = _entry_output_dir(output_dir)
    return [_manifest_summary(out_dir, path) for path in _manifest_files(out_dir)]


@router.get("/datasets/{dataset_id:path}/summary")
def get_dataset_summary(dataset_id: str, output_dir: str | None = Query(default=None)) -> dict[str, object]:
    out_dir = _entry_output_dir(output_dir)
    dataset_dir = _resolve_dataset_dir(out_dir, dataset_id)
    manifest = _read_manifest(dataset_dir / "entry_signal_analysis_manifest.json")
    summary_path = _resolve_manifest_artifact(dataset_dir, manifest.summary_json)
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail="Summary JSON not found")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "id": dataset_id,
        "manifest": manifest.model_dump(mode="json"),
        "summary": summary,
    }
