from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


REPORT_ENTRY_STRATEGY_RE = re.compile(r"\*\*Entry Strategy:\*\*\s*`([^`]+)`")
REPORT_EXIT_STRATEGY_RE = re.compile(r"\*\*Exit Strategy:\*\*\s*`([^`]+)`")
REPORT_PAIR_STRATEGY_RE = re.compile(r"([A-Za-z0-9_]+)__PAIR__([A-Za-z0-9_]+)")
REPORT_BUY_STRATEGY_ROW_RE = re.compile(
    r"^\|\s*\d+\s*\|(?:[^|\n]*\|){1,5}\s*([A-Za-z][A-Za-z0-9_]*(?:Entry|Strategy))\s*\|\s*-?\d+(?:\.\d+)?\s*\|",
    re.MULTILINE,
)
REPORT_DATE_RE = re.compile(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})")
CONFIG_SNAPSHOT_NAME_RE = re.compile(r"config_(\d{8})_(\d{6})\.json$")


def extract_report_strategy_context(report_content: str) -> dict[str, str]:
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


def extract_report_context_date(report_file: Path, report_content: str) -> date | None:
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


def resolve_report_strategy_context(report_file: Path) -> dict[str, str]:
    content = report_file.read_text(encoding="utf-8")
    report_date = extract_report_context_date(report_file, content)
    resolved = extract_report_strategy_context(content)
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
