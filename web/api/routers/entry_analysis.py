"""Entry Analysis endpoints: all BUY signals + fixed forward returns."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.entry_analysis.aggregation import aggregate_filtered_candidates
from src.entry_analysis.models import EntryAnalysisDatasetManifest, FeatureCondition
from src.entry_analysis.paths import default_output_dir
from src.evaluation.trade_indicator_enrichment import DEFAULT_INDICATOR_COLUMNS
from web.api.dependencies import get_config_manager, get_production_config, get_project_root
from web.api.schemas import EntryAnalysisAggregateRequest, EntryAnalysisRunRequest

router = APIRouter(prefix="/api/entry-analysis", tags=["entry-analysis"])

DERIVED_FEATURE_COLUMNS = [
    "signal_close",
    "close_vs_EMA_20_pct",
    "close_vs_EMA_50_pct",
    "close_vs_EMA_200_pct",
    "close_above_EMA_20",
    "close_above_EMA_50",
    "close_above_EMA_200",
    "EMA_bull_stack",
    "MACD_Hist_norm",
    "MACD_Hist_delta_norm",
    "RSI_9_minus_RSI_22",
    "bias_pct",
    "gap_above_ema20_pct",
    "metadata_return_5d_pct",
    "volume_ratio",
    "buy_signal_streak_days",
    "stale_buy_signal",
]


def _append_multi_flag(args: list[str], flag: str, values: list[object] | None) -> None:
    if not values:
        return
    args.append(flag)
    args.extend(str(value) for value in values)


def _default_output_dir() -> str:
    raw_config = get_config_manager().raw_config
    entry_cfg = raw_config.get("entry_analysis", {}) if isinstance(raw_config, dict) else {}
    configured = str(entry_cfg["output_dir"]) if isinstance(entry_cfg, dict) and entry_cfg.get("output_dir") else None
    return default_output_dir(configured)


def _entry_output_dir(output_dir: str | None = None) -> Path:
    raw = output_dir or _default_output_dir()
    path = Path(raw)
    if not path.is_absolute():
        path = get_project_root() / path
    return path


def _build_cli_args(req: EntryAnalysisRunRequest) -> list[str]:
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    eval_cfg = raw_config.get("evaluation", {}) if isinstance(raw_config, dict) else {}

    args = ["entry-analysis"]

    entry_strategies = req.entry_strategies
    if not entry_strategies:
        entry_strategies = [str(item) for item in eval_cfg.get("default_entry_strategies", [])]
    _append_multi_flag(args, "--entry-strategies", entry_strategies)

    universe_files = req.universe_files
    if not universe_files:
        universe_files = [str(getattr(prod_cfg, "monitor_list_file", "") or "")]
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
    if req.indicator_columns:
        _append_multi_flag(args, "--indicator-columns", req.indicator_columns)

    if req.rules:
        rules_payload = {"rules": [rule.model_dump() for rule in req.rules]}
        args.extend(["--rules-json", json.dumps(rules_payload, ensure_ascii=False)])
    elif req.preset_rules and req.preset_rules != "none":
        args.extend(["--preset-rules", req.preset_rules])

    args.extend(["--label-mode", req.label_mode])
    args.extend(["--min-samples", str(req.min_samples)])
    if not req.include_joint:
        args.append("--no-joint")
    if req.limit is not None:
        args.extend(["--limit", str(req.limit)])
    args.extend(["--data-root", req.data_root])
    if req.output_dir:
        args.extend(["--output-dir", req.output_dir])
    return args


@router.get("/options")
def get_options() -> dict[str, object]:
    from src.utils.strategy_loader import get_available_strategies

    strategies = get_available_strategies()
    prod_cfg = get_production_config()
    raw_config = get_config_manager().raw_config
    eval_cfg = raw_config.get("evaluation", {}) if isinstance(raw_config, dict) else {}
    default_entries = [str(item) for item in eval_cfg.get("default_entry_strategies", [])]
    return {
        "entry_strategies": strategies.get("entry", []),
        "indicator_columns": list(DEFAULT_INDICATOR_COLUMNS),
        "derived_feature_columns": DERIVED_FEATURE_COLUMNS,
        "bucket_modes": ["manual", "sliding", "fixed", "quantile", "categorical"],
        "label_modes": ["signal_close", "next_open"],
        "preset_rules": ["default", "rsi_adx_ema", "none"],
        "defaults": {
            "entry_strategies": default_entries,
            "universe_files": [str(getattr(prod_cfg, "monitor_list_file", "") or "")],
            "horizons": [3, 5, 10],
            "primary_horizon": 5,
            "label_mode": "signal_close",
            "min_samples": 30,
            "include_joint": True,
            "save_candidates": True,
            "data_root": "data",
            "output_dir": _default_output_dir(),
        },
    }


def _manifest_files(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    files = [path for path in output_root.rglob("entry_analysis_manifest.json") if path.is_file()]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files


def _read_manifest(path: Path) -> EntryAnalysisDatasetManifest:
    return EntryAnalysisDatasetManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _resolve_dataset_dir(output_root: Path, dataset_id: str) -> Path:
    root_abs = Path(os.path.abspath(str(output_root)))
    candidate = Path(os.path.abspath(str(root_abs / dataset_id)))
    root_cmp = os.path.normcase(str(root_abs))
    candidate_cmp = os.path.normcase(str(candidate))
    if os.path.commonpath([root_cmp, candidate_cmp]) != root_cmp:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    manifest = candidate / "entry_analysis_manifest.json"
    if not candidate.exists() or not candidate.is_dir() or not manifest.exists():
        raise HTTPException(status_code=404, detail=f"Dataset not found: {dataset_id}")
    return candidate


def _manifest_summary(output_root: Path, manifest_path: Path) -> dict[str, object]:
    manifest = _read_manifest(manifest_path)
    dataset_dir = manifest_path.parent
    return {
        "id": dataset_dir.relative_to(output_root).as_posix(),
        "dataset_id": manifest.dataset_id,
        "generated_at": manifest.generated_at,
        "candidate_count": manifest.candidate_count,
        "entry_strategies": manifest.entry_strategies,
        "start_date": manifest.start_date,
        "end_date": manifest.end_date,
        "horizons": manifest.horizons,
        "label_mode": manifest.label_mode,
        "output_dir": manifest.output_dir,
    }


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


@router.get("/datasets")
def list_datasets(output_dir: str | None = Query(default=None)) -> list[dict[str, object]]:
    out_dir = _entry_output_dir(output_dir)
    return [_manifest_summary(out_dir, path) for path in _manifest_files(out_dir)]


@router.get("/datasets/{dataset_id:path}/schema")
def get_dataset_schema(dataset_id: str, output_dir: str | None = Query(default=None)) -> dict[str, object]:
    out_dir = _entry_output_dir(output_dir)
    dataset_dir = _resolve_dataset_dir(out_dir, dataset_id)
    manifest = _read_manifest(dataset_dir / "entry_analysis_manifest.json")
    candidates_path = _resolve_manifest_artifact(dataset_dir, manifest.candidates_csv)
    if not candidates_path.exists():
        raise HTTPException(status_code=404, detail="Candidates CSV not found")

    import pandas as pd

    sample = pd.read_csv(candidates_path, nrows=1000)
    numeric_features = [
        column
        for column in manifest.feature_columns
        if column in sample.columns and pd.api.types.is_numeric_dtype(sample[column])
    ]
    categorical_features = [
        column
        for column in manifest.feature_columns
        if column in sample.columns and column not in numeric_features
    ]
    return {
        "id": dataset_id,
        "manifest": manifest.model_dump(mode="json"),
        "feature_columns": manifest.feature_columns,
        "numeric_features": numeric_features,
        "categorical_features": categorical_features,
        "horizons": manifest.horizons,
        "candidate_count": manifest.candidate_count,
    }


@router.post("/datasets/{dataset_id:path}/aggregate")
def aggregate_dataset(
    dataset_id: str,
    req: EntryAnalysisAggregateRequest,
    output_dir: str | None = Query(default=None),
) -> dict[str, object]:
    out_dir = _entry_output_dir(output_dir)
    dataset_dir = _resolve_dataset_dir(out_dir, dataset_id)
    manifest = _read_manifest(dataset_dir / "entry_analysis_manifest.json")
    candidates_path = _resolve_manifest_artifact(dataset_dir, manifest.candidates_csv)
    if not candidates_path.exists():
        raise HTTPException(status_code=404, detail="Candidates CSV not found")

    import pandas as pd

    candidates = pd.read_csv(candidates_path)
    conditions = [FeatureCondition.model_validate(item.model_dump()) for item in req.conditions]
    horizons = [int(value) for value in req.horizons if int(value) > 0] or manifest.horizons
    result = aggregate_filtered_candidates(
        candidates,
        conditions,
        horizons,
        logic=req.logic,
        group_by=req.group_by,
        min_samples=req.min_samples,
    )
    return {"id": dataset_id, "manifest": manifest.model_dump(mode="json"), **result}


@router.post("/run")
async def run_entry_analysis(req: EntryAnalysisRunRequest) -> StreamingResponse:
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
            q.put(None)

        thread = threading.Thread(target=_reader, daemon=True)
        thread.start()
        while True:
            try:
                chunk = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: q.get(timeout=0.1),
                )
            except Empty:
                continue
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _iter_result_files(output_root: Path) -> list[Path]:
    if not output_root.exists():
        return []
    files = [
        path
        for path in output_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".csv", ".json", ".md"}
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
    out_dir = _entry_output_dir(output_dir)
    files: list[dict[str, str]] = []
    for path in _iter_result_files(out_dir):
        files.append({
            "name": path.relative_to(out_dir).as_posix(),
            "type": path.suffix.lstrip("."),
            "size": str(path.stat().st_size),
        })
    return files


@router.get("/results/{filename:path}")
def get_result(filename: str, output_dir: str | None = Query(default=None)) -> dict[str, object]:
    out_dir = _entry_output_dir(output_dir)
    path = _resolve_result_file(out_dir, filename)
    display_name = Path(os.path.relpath(path, start=out_dir)).as_posix()
    if path.suffix.lower() == ".csv":
        import pandas as pd

        frame = pd.read_csv(path)
        return {"type": "csv", "name": display_name, "data": frame.to_dict(orient="records")}
    if path.suffix.lower() == ".json":
        return {"type": "json", "name": display_name, "data": json.loads(path.read_text(encoding="utf-8"))}
    return {"type": "markdown", "name": display_name, "content": path.read_text(encoding="utf-8")}
