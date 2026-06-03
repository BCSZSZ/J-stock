from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from src.config.runtime import get_config_file_path
from src.config.service import load_config as load_config_service
from src.entry_analysis.aggregation import build_preset_rules
from src.entry_analysis.models import EntryAnalysisRequest, FeatureBucketRule
from src.entry_analysis.paths import default_output_dir
from src.entry_analysis.runner import run_entry_analysis
from src.utils.universe_loader import load_tickers_from_file


def _load_runtime_config() -> dict[str, Any]:
    config_path = get_config_file_path()
    if not config_path.exists():
        return {}
    return load_config_service(str(config_path))


def _coerce_date(value: str | None, fallback: date | None = None) -> date:
    if value:
        return date.fromisoformat(value)
    if fallback is not None:
        return fallback
    raise ValueError("date value is required")


def _resolve_date_range(args: Any, config: dict[str, Any]) -> tuple[date, date]:
    if args.years:
        years = sorted({int(year) for year in args.years})
        return date(years[0], 1, 1), date(years[-1], 12, 31)

    backtest_cfg = config.get("backtest", {}) if isinstance(config, dict) else {}
    start_fallback = None
    end_fallback = None
    if backtest_cfg.get("start_date"):
        start_fallback = date.fromisoformat(str(backtest_cfg["start_date"]))
    if backtest_cfg.get("end_date"):
        end_fallback = date.fromisoformat(str(backtest_cfg["end_date"]))

    return _coerce_date(args.start, start_fallback), _coerce_date(args.end, end_fallback)


def _resolve_entry_strategies(args: Any, config: dict[str, Any]) -> list[str]:
    if args.entry_strategies:
        return list(args.entry_strategies)

    eval_cfg = config.get("evaluation", {}) if isinstance(config, dict) else {}
    default_entries = eval_cfg.get("default_entry_strategies") or []
    if default_entries:
        return [str(value) for value in default_entries]

    default_strategies = config.get("default_strategies", {}) if isinstance(config, dict) else {}
    default_entry = default_strategies.get("entry")
    if default_entry:
        return [str(default_entry)]

    raise ValueError("entry-analysis requires --entry-strategies or configured evaluation.default_entry_strategies")


def _resolve_universe_files(args: Any, config: dict[str, Any]) -> list[str]:
    if args.universe_file:
        return [str(value) for value in args.universe_file]

    data_cfg = config.get("data", {}) if isinstance(config, dict) else {}
    monitor_file = data_cfg.get("monitor_list_file")
    if monitor_file:
        return [str(monitor_file)]

    raise ValueError("entry-analysis requires --universe-file or configured data.monitor_list_file")


def _load_tickers(universe_files: list[str], limit: int | None = None) -> list[str]:
    tickers: list[str] = []
    seen: set[str] = set()
    for universe_file in universe_files:
        for ticker in load_tickers_from_file(universe_file):
            if ticker in seen:
                continue
            seen.add(ticker)
            tickers.append(ticker)
            if limit is not None and len(tickers) >= limit:
                return tickers
    return tickers


def _load_rules(args: Any) -> list[FeatureBucketRule]:
    if not args.rules_json:
        if not args.preset_rules or str(args.preset_rules).strip().lower() == "none":
            return []
        return build_preset_rules(args.preset_rules)

    raw = str(args.rules_json)
    path = Path(raw)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = raw

    payload = json.loads(text)
    raw_rules = payload.get("rules") if isinstance(payload, dict) else payload
    if not isinstance(raw_rules, list):
        raise ValueError("--rules-json must be a JSON list or an object with a 'rules' list")
    return [FeatureBucketRule.model_validate(item) for item in raw_rules]


def _resolve_output_dir(args: Any, config: dict[str, Any]) -> str:
    if args.output_dir:
        return str(args.output_dir)
    entry_cfg = config.get("entry_analysis", {}) if isinstance(config, dict) else {}
    configured = str(entry_cfg["output_dir"]) if entry_cfg.get("output_dir") else None
    return default_output_dir(configured)


def cmd_entry_analysis(args: Any) -> None:
    config = _load_runtime_config()
    start_date, end_date = _resolve_date_range(args, config)
    entry_strategies = _resolve_entry_strategies(args, config)
    universe_files = _resolve_universe_files(args, config)
    tickers = _load_tickers(universe_files, limit=args.limit)
    if not tickers:
        raise ValueError("entry-analysis resolved an empty ticker universe")

    horizons = args.horizons or [3, 5, 10]
    primary_horizon = args.primary_horizon or (5 if 5 in horizons else horizons[0])
    rules = _load_rules(args)
    request = EntryAnalysisRequest(
        entry_strategies=entry_strategies,
        tickers=tickers,
        start_date=start_date,
        end_date=end_date,
        horizons=[int(value) for value in horizons],
        indicator_columns=args.indicator_columns or [],
        rules=rules,
        label_mode=args.label_mode,
        primary_horizon=int(primary_horizon),
        min_samples=int(args.min_samples),
        include_joint=not args.no_joint,
        data_root=str(args.data_root),
        output_dir=_resolve_output_dir(args, config),
        save_candidates=True,
    )

    print("Entry Analysis")
    print(f"  strategies: {', '.join(request.entry_strategies)}")
    print(f"  universe files: {', '.join(universe_files)}")
    print(f"  tickers: {len(request.tickers)}")
    print(f"  range: {request.start_date} -> {request.end_date}")
    print(f"  horizons: {', '.join(map(str, request.normalized_horizons))}")
    print(f"  label_mode: {request.label_mode}")
    print(f"  rules: {len(request.rules)}")
    run_entry_analysis(request)
