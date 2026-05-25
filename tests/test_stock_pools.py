from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.config.stock_pools import (
    get_stock_pool_catalog_path,
    load_stock_pool_catalog,
    resolve_stock_pools,
)


def test_load_stock_pool_catalog_resolves_relative_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "config.json"
    catalog_file = tmp_path / "catalog" / "stock_pools.json"
    catalog_file.parent.mkdir()
    config_file.write_text(
        json.dumps({"stock_pools": {"catalog_file": "catalog/stock_pools.json"}}),
        encoding="utf-8",
    )
    catalog_file.write_text(
        json.dumps(
            {
                "pools": [
                    {
                        "id": "jp_midcap",
                        "label": "JP Midcap",
                        "monitor_list_file": "monitor.json",
                        "sector_pool_file": "sector_pool",
                        "atr_ratio_min": 0.015,
                        "atr_ratio_max": 0.05,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    raw_config = json.loads(config_file.read_text(encoding="utf-8"))
    entries = load_stock_pool_catalog(raw_config, config_file)

    assert get_stock_pool_catalog_path(raw_config, config_file) == str(catalog_file.resolve())
    assert len(entries) == 1
    assert entries[0].id == "jp_midcap"
    assert entries[0].monitor_list_file == str((catalog_file.parent / "monitor.json").resolve())
    assert entries[0].sector_pool_file == str((catalog_file.parent / "sector_pool").resolve())
    assert entries[0].to_api_dict()["atr_ratio_min"] == 0.015


def test_resolve_stock_pools_dedupes_requested_ids(tmp_path: Path) -> None:
    config_file, raw_config = _write_catalog(
        tmp_path,
        [
            {"id": "a", "monitor_list_file": "a.json"},
            {"id": "b", "monitor_list_file": "b.json"},
        ],
    )

    entries = resolve_stock_pools(raw_config, config_file, ["a", "a", "b"])

    assert [entry.id for entry in entries] == ["a", "b"]


def test_resolve_stock_pools_rejects_missing_or_disabled_ids(tmp_path: Path) -> None:
    config_file, raw_config = _write_catalog(
        tmp_path,
        [
            {"id": "enabled", "monitor_list_file": "enabled.json"},
            {"id": "disabled", "monitor_list_file": "disabled.json", "enabled": False},
        ],
    )

    with pytest.raises(ValueError, match="Unknown stock pool"):
        resolve_stock_pools(raw_config, config_file, ["missing"])

    with pytest.raises(ValueError, match="Disabled stock pool"):
        resolve_stock_pools(raw_config, config_file, ["disabled"])


def _write_catalog(
    tmp_path: Path,
    pools: list[dict[str, object]],
) -> tuple[Path, dict[str, object]]:
    config_file = tmp_path / "config.json"
    catalog_file = tmp_path / "stock_pools.json"
    raw_config = {"stock_pools": {"catalog_file": str(catalog_file)}}
    config_file.write_text(json.dumps(raw_config), encoding="utf-8")
    catalog_file.write_text(json.dumps({"pools": pools}), encoding="utf-8")
    return config_file, raw_config