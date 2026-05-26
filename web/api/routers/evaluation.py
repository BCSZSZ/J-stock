"""Evaluation endpoints: run evaluations, browse results."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import threading
from datetime import date, datetime
from pathlib import Path
from queue import Queue, Empty
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from src.backtest.entry_reference import (
    BUFFERED_FILL_ENTRY_REFERENCE,
    RAW_FILL_ENTRY_REFERENCE,
)
from src.config.runtime import is_local_path
from src.utils.atr_position_sizing import parse_portfolio_sizing_config
from web.api.dependencies import get_production_config, get_project_root, get_config_manager
from web.api.schemas import EvaluationRunRequest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

COMMANDS = [
    "evaluate",
    "pos-evaluation",
    "walk-forward-evaluate",
    "replay-evaluation",
]
EVALUATION_MODES = ["annual", "quarterly", "monthly", "custom"]
ENTRY_FILTER_MODES = ["atr", "off", "single", "grid", "auto"]
RANKING_MODES = ["prs_train"]
OVERLAY_MODES = ["off", "on"]
BUY_FILL_MODES = ["next_open", "next_close"]
ENTRY_REFERENCE_MODES = [RAW_FILL_ENTRY_REFERENCE, BUFFERED_FILL_ENTRY_REFERENCE]
CAPACITY_REGIME_MODES = ["off", "enforce"]
REPORT_ENTRY_STRATEGY_RE = re.compile(r"\*\*Entry Strategy:\*\*\s*`([^`]+)`")
REPORT_EXIT_STRATEGY_RE = re.compile(r"\*\*Exit Strategy:\*\*\s*`([^`]+)`")
REPORT_PAIR_STRATEGY_RE = re.compile(r"([A-Za-z0-9_]+)__PAIR__([A-Za-z0-9_]+)")
REPORT_BUY_STRATEGY_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|(?:[^|\n]*\|){1,5}\s*([A-Za-z][A-Za-z0-9_]*(?:Entry|Strategy))\s*\|\s*-?\d+(?:\.\d+)?\s*\|",
    re.MULTILINE,
)
REPORT_DATE_RE = re.compile(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})")
CONFIG_SNAPSHOT_NAME_RE = re.compile(r"config_(\d{8})_(\d{6})\.json$")


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


def _extract_report_strategy_context(report_content: str) -> dict[str, str]:
    context: dict[str, str] = {}

    entry_match = REPORT_ENTRY_STRATEGY_RE.search(report_content)
    if entry_match is not None:
        context["entry_strategy"] = entry_match.group(1).strip()

    exit_match = REPORT_EXIT_STRATEGY_RE.search(report_content)
    if exit_match is not None:
        context["exit_strategy"] = exit_match.group(1).strip()

    pair_match = REPORT_PAIR_STRATEGY_RE.search(report_content)
    if pair_match is not None:
        context.setdefault("entry_strategy", pair_match.group(1).strip())
        context.setdefault("exit_strategy", pair_match.group(2).strip())

    if "entry_strategy" not in context:
        buy_strategy_match = REPORT_BUY_STRATEGY_ROW_RE.search(report_content)
        if buy_strategy_match is not None:
            context["entry_strategy"] = buy_strategy_match.group(1).strip()

    return context


def _extract_report_date(report_file: Path, report_content: str) -> date | None:
    try:
        return datetime.strptime(report_file.stem, "%Y-%m-%d").date()
    except ValueError:
        pass

    date_match = REPORT_DATE_RE.search(report_content)
    if date_match is None:
        return None

    try:
        return datetime.strptime(date_match.group(1), "%Y-%m-%d").date()
    except ValueError:
        return None


def _load_strategy_context_from_config_payload(payload: dict[str, Any]) -> dict[str, str]:
    resolved: dict[str, str] = {}

    production = payload.get("production", {})
    if isinstance(production, dict):
        strategy_groups = production.get("strategy_groups")
        if isinstance(strategy_groups, list):
            preferred_group: dict[str, Any] | None = None
            for item in strategy_groups:
                if not isinstance(item, dict):
                    continue
                if str(item.get("id", "")) == "group_main":
                    preferred_group = item
                    break
                if preferred_group is None:
                    preferred_group = item
            if preferred_group is not None:
                entry_strategy = preferred_group.get("entry_strategy")
                exit_strategy = preferred_group.get("exit_strategy")
                if entry_strategy:
                    resolved["entry_strategy"] = str(entry_strategy).strip()
                if exit_strategy:
                    resolved["exit_strategy"] = str(exit_strategy).strip()

    default_strategies = payload.get("default_strategies", {})
    if isinstance(default_strategies, dict):
        entry_strategy = default_strategies.get("entry")
        exit_strategy = default_strategies.get("exit")
        if entry_strategy:
            resolved.setdefault("entry_strategy", str(entry_strategy).strip())
        if exit_strategy:
            resolved.setdefault("exit_strategy", str(exit_strategy).strip())

    return resolved


def _parse_snapshot_timestamp(path: Path) -> datetime | None:
    match = CONFIG_SNAPSHOT_NAME_RE.match(path.name)
    if match is None:
        return None
    try:
        return datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def _candidate_config_paths_for_report(report_file: Path, report_date: date | None) -> list[Path]:
    report_root = report_file.parent.parent if report_file.parent.name == "reports" else report_file.parent
    current_config = report_root / "config.json"
    old_dir = report_root / "old"

    candidates: list[Path] = []
    snapshots: list[tuple[datetime, Path]] = []
    if old_dir.exists():
        for path in old_dir.glob("config_*.json"):
            snapshot_dt = _parse_snapshot_timestamp(path)
            if snapshot_dt is not None:
                snapshots.append((snapshot_dt, path))

    if snapshots:
        snapshots.sort(key=lambda item: item[0])
        chosen_snapshot: Path | None = None
        if report_date is not None:
            report_dt = datetime.combine(report_date, datetime.min.time())
            before = [item for item in snapshots if item[0] <= report_dt]
            if before:
                chosen_snapshot = before[-1][1]
            else:
                chosen_snapshot = min(
                    snapshots,
                    key=lambda item: abs(item[0] - report_dt),
                )[1]
        else:
            chosen_snapshot = snapshots[-1][1]

        if chosen_snapshot is not None:
            candidates.append(chosen_snapshot)

    if current_config.exists():
        candidates.append(current_config)

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        normalized = os.path.normcase(str(path))
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(path)
    return deduped


def _resolve_strategy_context_from_configs(
    report_file: Path,
    report_date: date | None,
    existing: dict[str, str],
) -> dict[str, str]:
    resolved = dict(existing)
    if "entry_strategy" in resolved and "exit_strategy" in resolved:
        return resolved

    for config_path in _candidate_config_paths_for_report(report_file, report_date):
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        context = _load_strategy_context_from_config_payload(payload)
        if not context:
            continue
        if "entry_strategy" not in resolved and context.get("entry_strategy"):
            resolved["entry_strategy"] = context["entry_strategy"]
        if "exit_strategy" not in resolved and context.get("exit_strategy"):
            resolved["exit_strategy"] = context["exit_strategy"]
        if "entry_strategy" in resolved and "exit_strategy" in resolved:
            break

    return resolved


def _append_multi_flag(args: list[str], flag: str, values: list[str] | list[int] | None) -> None:
    if not values:
        return

    normalized = [str(value).strip() for value in values if str(value).strip()]
    if not normalized:
        return

    args.append(flag)
    args.extend(normalized)


def _append_atr_runtime_flags(args: list[str], req: EvaluationRunRequest) -> None:
    fields_set = getattr(req, "model_fields_set", set())
    if req.position_sizing_mode:
        args.extend(["--position-sizing-mode", req.position_sizing_mode])
    if req.position_sizing_mode != "fixed":
        if req.risk_per_trade_pct is not None:
            args.extend(["--risk-per-trade-pct", str(req.risk_per_trade_pct)])
        if req.atr_stop_multiple is not None:
            args.extend(["--atr-stop-multiple", str(req.atr_stop_multiple)])
    if req.atr_ratio_min is not None:
        args.extend(["--atr-ratio-min", str(req.atr_ratio_min)])
    elif req.entry_filter_mode == "atr" and "atr_ratio_min" in fields_set:
        args.extend(["--atr-ratio-min", "none"])
    if req.atr_ratio_max is not None:
        args.extend(["--atr-ratio-max", str(req.atr_ratio_max)])
    elif req.entry_filter_mode == "atr" and "atr_ratio_max" in fields_set:
        args.extend(["--atr-ratio-max", "none"])


def _resolve_atr_runtime_defaults(raw_config: dict[str, object]) -> dict[str, object]:
    sizing = parse_portfolio_sizing_config(raw_config.get("portfolio", {}))
    default_filter = raw_config.get("evaluation", {}).get("filters", {}).get("default", {})
    if not isinstance(default_filter, dict):
        default_filter = {}
    return {
        "position_sizing_mode": sizing.mode,
        "risk_per_trade_pct": sizing.atr.risk_per_trade_pct,
        "atr_stop_multiple": sizing.atr.atr_stop_multiple,
        "atr_ratio_min": default_filter.get("atr_price_min"),
        "atr_ratio_max": default_filter.get("atr_price_max"),
    }


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    normalized: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


def _resolve_requested_universe_files(
    req: EvaluationRunRequest,
) -> list[str]:
    requested_files = _normalize_string_list(req.universe_files)
    if requested_files:
        return requested_files

    requested_pool_ids = _normalize_string_list(req.universe_pool_ids)
    if requested_pool_ids:
        config_manager = get_config_manager()
        try:
            pools = config_manager.resolve_stock_pools(requested_pool_ids)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [pool.monitor_list_file for pool in pools]

    prod_cfg = get_production_config()
    default_file = str(getattr(prod_cfg, "monitor_list_file", "") or "").strip()
    return [default_file] if default_file else []


def _resolve_requested_launch_dates(req: EvaluationRunRequest) -> list[str]:
    requested_dates = req.launch_dates or ([req.launch_date] if req.launch_date else [])
    resolved: list[str] = []
    for value in requested_dates:
        normalized = str(value).strip()
        if normalized and normalized not in resolved:
            resolved.append(normalized)
    return resolved


def _resolve_requested_report_files(req: EvaluationRunRequest) -> list[str]:
    requested_files = req.report_files or ([req.report_file] if req.report_file else [])
    resolved: list[str] = []
    for value in requested_files:
        normalized = str(value).strip()
        if normalized and normalized not in resolved:
            resolved.append(normalized)
    return resolved


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


def _resolve_requested_entry_reference_modes(req: EvaluationRunRequest) -> list[str]:
    requested_modes = req.entry_reference_modes or [req.entry_reference_mode]
    resolved: list[str] = []
    for mode in requested_modes:
        normalized = str(mode).strip()
        if normalized and normalized not in resolved:
            resolved.append(normalized)
    return resolved or [req.entry_reference_mode]


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
    entry_reference_mode: str | None = None,
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

    if req.command == "replay-evaluation":
        report_files = [
            _resolve_local_path(path_value)
            for path_value in _resolve_requested_report_files(req)
        ]
        if not report_files or any(path is None for path in report_files):
            raise HTTPException(
                status_code=400,
                detail="replay-evaluation requires one or more local report_file values.",
            )
        _append_multi_flag(args, "--report-file", [str(path) for path in report_files if path is not None])

    args.extend(["--buy-fill-mode", buy_fill_mode or req.buy_fill_mode])
    args.extend(
        ["--entry-reference-mode", entry_reference_mode or req.entry_reference_mode]
    )
    if req.fill_buffer_enabled:
        args.append("--fill-buffer-enabled")
    args.extend(["--fill-buffer-pct", str(req.fill_buffer_pct)])

    if req.capacity_regime_mode:
        args.extend(["--capacity-regime-mode", req.capacity_regime_mode])

    if req.command in {"evaluate", "pos-evaluation", "walk-forward-evaluate"} and req.years:
        _append_multi_flag(args, "--years", req.years)

    launch_dates = _resolve_requested_launch_dates(req)
    if req.command in {"evaluate", "pos-evaluation"} and launch_dates:
        _append_multi_flag(args, "--launch-date", launch_dates)

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

    _append_multi_flag(args, "--universe-file", _resolve_requested_universe_files(req))

    if req.verbose:
        args.append("--verbose")

    if req.command in {"evaluate", "walk-forward-evaluate", "replay-evaluation"} and req.enable_overlay:
        args.append("--enable-overlay")

    if req.ranking_mode:
        args.extend(["--ranking-mode", req.ranking_mode])

    _append_atr_runtime_flags(args, req)

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


@router.get("/report-context")
def get_report_context(report_file: str = Query(...)) -> dict[str, str]:
    path = _resolve_local_path(report_file)
    if path is None:
        raise HTTPException(status_code=400, detail="report_file must be a local path.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"Report not found: {report_file}")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to read report: {exc}") from exc

    report_date = _extract_report_date(path, content)
    context = _resolve_strategy_context_from_configs(
        path,
        report_date,
        _extract_report_strategy_context(content),
    )
    if "entry_strategy" not in context or "exit_strategy" not in context:
        raise HTTPException(
            status_code=422,
            detail="Could not parse entry/exit strategy from report.",
        )

    return {
        "report_file": str(path),
        **context,
    }


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
    stock_pools = [pool.to_api_dict() for pool in cm.list_stock_pools()]
    atr_runtime_defaults = _resolve_atr_runtime_defaults(raw_config)
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
        "entry_reference_modes": ENTRY_REFERENCE_MODES,
        "capacity_regime_modes": CAPACITY_REGIME_MODES,
        "ranking_modes": RANKING_MODES,
        "position_profiles": position_profiles,
        "stock_pools": stock_pools,
        "production": {
            "entry_strategy": production_entry,
            "exit_strategy": production_exit,
            "ranking_strategy": str(default_ranking_strategy or ""),
            "monitor_list_file": str(default_universe_file or ""),
            "stock_pool_catalog_file": str(getattr(prod_cfg, "stock_pool_catalog_file", "") or ""),
            "report_file_pattern": str(getattr(prod_cfg, "report_file_pattern", "") or ""),
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
            "entry_filter_mode": "atr",
            "entry_filter_names": [],
            "enable_overlay": False,
            "overlay_modes": ["off"],
            "buy_fill_mode": "next_open",
            "buy_fill_modes": ["next_open"],
            "entry_reference_mode": RAW_FILL_ENTRY_REFERENCE,
            "entry_reference_modes": [RAW_FILL_ENTRY_REFERENCE],
            "fill_buffer_enabled": False,
            "fill_buffer_pct": 0.02,
            "capacity_regime_mode": str(eval_cfg.get("capacity_regime_mode", "off")),
            "exit_confirm_days": eval_cfg.get("exit_confirmation_days"),
            "output_dir": str(eval_cfg.get("output_dir", "strategy_evaluation")),
            "universe_files": (
                [str(default_universe_file)] if default_universe_file else []
            ),
            "universe_pool_ids": [],
            **atr_runtime_defaults,
            "position_file": default_position_file,
            "profile_names": default_profile_names,
            "report_file": "",
            "min_train_years": 2,
        },
    }


@router.post("/run")
async def run_evaluation(req: EvaluationRunRequest) -> StreamingResponse:
    root = get_project_root()
    requested_buy_fill_modes = _resolve_requested_buy_fill_modes(req)
    requested_entry_reference_modes = _resolve_requested_entry_reference_modes(req)

    async def event_stream():  # type: ignore[return]
        q: Queue[str | None] = Queue()

        def _emit_line(text: str) -> None:
            q.put(f"data: {json.dumps({'line': text})}\n\n")

        def _reader() -> None:
            final_code = 0
            batch_specs = [
                (buy_fill_mode, entry_reference_mode)
                for buy_fill_mode in requested_buy_fill_modes
                for entry_reference_mode in requested_entry_reference_modes
            ]
            total_batches = len(batch_specs)

            if total_batches > 1:
                _emit_line(
                    "Running "
                    f"{total_batches} evaluation batches: "
                    f"buy fill modes [{', '.join(requested_buy_fill_modes)}] × "
                    f"entry reference modes [{', '.join(requested_entry_reference_modes)}]"
                )

            for index, (buy_fill_mode, entry_reference_mode) in enumerate(
                batch_specs,
                start=1,
            ):
                if total_batches > 1:
                    _emit_line("=" * 80)
                    _emit_line(
                        f"[batch {index}/{total_batches}] Starting full run for buy_fill={buy_fill_mode}, entry_reference={entry_reference_mode}"
                    )
                    _emit_line("=" * 80)

                args = _build_cli_args(
                    req,
                    buy_fill_mode=buy_fill_mode,
                    entry_reference_mode=entry_reference_mode,
                )
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

                if total_batches > 1:
                    status = "OK" if code == 0 else f"FAILED ({code})"
                    _emit_line(
                        f"[batch {index}/{total_batches}] Completed buy_fill={buy_fill_mode}, entry_reference={entry_reference_mode}: {status}"
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
        if path.is_file() and path.suffix in (".csv", ".md", ".json")
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
    if path.suffix == ".json":
        content = json.loads(path.read_text(encoding="utf-8"))
        return {"type": "json", "name": display_name, "data": content}
    else:
        content = path.read_text(encoding="utf-8")
        return {"type": "markdown", "name": display_name, "content": content}
