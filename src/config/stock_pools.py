from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from src.config.runtime import is_local_path


@dataclass(frozen=True)
class StockPoolEntry:
    id: str
    label: str
    monitor_list_file: str
    sector_pool_file: str | None = None
    atr_ratio_min: float | None = None
    atr_ratio_max: float | None = None
    notes: str | None = None
    enabled: bool = True
    catalog_file: str | None = None

    def to_api_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "label": self.label,
            "monitor_list_file": self.monitor_list_file,
            "sector_pool_file": self.sector_pool_file,
            "atr_ratio_min": self.atr_ratio_min,
            "atr_ratio_max": self.atr_ratio_max,
            "notes": self.notes,
            "enabled": self.enabled,
            "catalog_file": self.catalog_file,
        }


def get_stock_pool_catalog_path(
    raw_config: Mapping[str, object],
    config_file: str | Path,
) -> str | None:
    stock_pools_cfg = raw_config.get("stock_pools")
    if not isinstance(stock_pools_cfg, Mapping):
        return None

    catalog_file = stock_pools_cfg.get("catalog_file")
    if not isinstance(catalog_file, str) or not catalog_file.strip():
        return None

    resolved = _resolve_path(Path(config_file).parent, catalog_file)
    return resolved


def load_stock_pool_catalog(
    raw_config: Mapping[str, object],
    config_file: str | Path,
    *,
    strict: bool = True,
) -> list[StockPoolEntry]:
    catalog_path_str = get_stock_pool_catalog_path(raw_config, config_file)
    if not catalog_path_str:
        return []

    catalog_path = Path(catalog_path_str)
    if not catalog_path.exists():
        if strict:
            raise FileNotFoundError(f"Stock pool catalog not found: {catalog_path}")
        return []

    with open(catalog_path, "r", encoding="utf-8") as f:
        raw_catalog = json.load(f)

    raw_entries = _extract_catalog_entries(raw_catalog)
    catalog_dir = catalog_path.parent
    entries: list[StockPoolEntry] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_entries):
        if not isinstance(item, Mapping):
            if strict:
                raise ValueError(f"Stock pool catalog entry #{index} must be an object")
            continue
        entry = _parse_stock_pool_entry(item, catalog_dir, str(catalog_path))
        if entry.id in seen_ids:
            if strict:
                raise ValueError(f"Duplicate stock pool id in catalog: {entry.id}")
            continue
        seen_ids.add(entry.id)
        entries.append(entry)
    return entries


def resolve_stock_pools(
    raw_config: Mapping[str, object],
    config_file: str | Path,
    pool_ids: Sequence[str],
) -> list[StockPoolEntry]:
    requested_ids = _normalize_pool_ids(pool_ids)
    if not requested_ids:
        return []

    entries = load_stock_pool_catalog(raw_config, config_file, strict=True)
    by_id = {entry.id: entry for entry in entries}
    resolved: list[StockPoolEntry] = []
    missing: list[str] = []
    disabled: list[str] = []

    for pool_id in requested_ids:
        entry = by_id.get(pool_id)
        if entry is None:
            missing.append(pool_id)
            continue
        if not entry.enabled:
            disabled.append(pool_id)
            continue
        resolved.append(entry)

    if missing:
        raise ValueError(f"Unknown stock pool id(s): {', '.join(missing)}")
    if disabled:
        raise ValueError(f"Disabled stock pool id(s): {', '.join(disabled)}")
    return resolved


def _extract_catalog_entries(raw_catalog: object) -> list[object]:
    if isinstance(raw_catalog, list):
        return list(raw_catalog)
    if isinstance(raw_catalog, Mapping):
        pools = raw_catalog.get("pools")
        if isinstance(pools, list):
            return list(pools)
    raise ValueError("Stock pool catalog must be a list or an object with a 'pools' list")


def _parse_stock_pool_entry(
    item: Mapping[str, object],
    catalog_dir: Path,
    catalog_file: str,
) -> StockPoolEntry:
    pool_id = str(item.get("id", "") or "").strip()
    if not pool_id:
        raise ValueError("Stock pool entry is missing a non-empty 'id'")

    label = str(item.get("label", "") or pool_id).strip() or pool_id
    monitor_list_file_raw = item.get("monitor_list_file")
    if not isinstance(monitor_list_file_raw, str) or not monitor_list_file_raw.strip():
        raise ValueError(f"Stock pool '{pool_id}' is missing monitor_list_file")

    sector_pool_file_raw = item.get("sector_pool_file")
    notes_raw = item.get("notes")

    return StockPoolEntry(
        id=pool_id,
        label=label,
        monitor_list_file=_resolve_path(catalog_dir, monitor_list_file_raw),
        sector_pool_file=(
            _resolve_path(catalog_dir, sector_pool_file_raw)
            if isinstance(sector_pool_file_raw, str) and sector_pool_file_raw.strip()
            else None
        ),
        atr_ratio_min=_coerce_optional_float(item.get("atr_ratio_min")),
        atr_ratio_max=_coerce_optional_float(item.get("atr_ratio_max")),
        notes=str(notes_raw).strip() if isinstance(notes_raw, str) and notes_raw.strip() else None,
        enabled=bool(item.get("enabled", True)),
        catalog_file=catalog_file,
    )


def _coerce_optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid float value in stock pool catalog: {value}") from exc
    raise ValueError(f"Invalid numeric value in stock pool catalog: {value!r}")


def _normalize_pool_ids(pool_ids: Sequence[str]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for pool_id in pool_ids:
        normalized = str(pool_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        resolved.append(normalized)
    return resolved


def _resolve_path(base_dir: Path, raw_path: str) -> str:
    if not is_local_path(raw_path):
        return raw_path
    path = Path(raw_path)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())