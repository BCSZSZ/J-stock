from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src.production.config_manager import ConfigManager


def test_default_config_manager_uses_runtime_config_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_file = tmp_path / "runtime_config.json"
    monitor_list_file = tmp_path / "data" / "monitor_list.json"
    config_file.write_text(
        json.dumps(
            {
                "data": {
                    "monitor_list_file": str(monitor_list_file),
                    "data_dir": str(tmp_path / "data"),
                },
                "backtest": {
                    "starting_capital_jpy": 5_000_000,
                },
                "portfolio": {
                    "max_positions": 7,
                    "max_position_pct": 0.18,
                },
                "default_strategies": {
                    "entry": "RuntimeEntry",
                    "exit": "RuntimeExit",
                },
                "evaluation": {
                    "capacity_regime_mode": "off",
                },
                "production": {
                    "capacity_regime_mode": "off",
                },
                "capacity_regime": {
                    "version": "test",
                    "equity_window_days": 20,
                    "turnover_field": "Turnover_Median_20",
                    "tiers": [
                        {
                            "name": "tier0",
                            "max_equity_jpy": None,
                            "max_positions": 7,
                            "max_position_pct": 0.18,
                            "participation_cap_pct": 0.02,
                            "min_turnover_20_jpy": 500000000,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("JSA_CONFIG_FILE", str(config_file))

    manager = ConfigManager()

    assert manager.config_file == config_file
    assert manager.get_default_strategies() == ("RuntimeEntry", "RuntimeExit")


def test_get_production_config_is_safe_under_concurrent_access(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "config.json"
    state_dir = tmp_path / "state"
    signals_dir = tmp_path / "signals"
    reports_dir = tmp_path / "reports"
    sector_pool_dir = tmp_path / "sector_pool"
    monitor_list_file = tmp_path / "data" / "monitor_list.json"

    config_file.write_text(
        json.dumps(
            {
                "data": {
                    "monitor_list_file": str(monitor_list_file),
                    "data_dir": str(tmp_path / "data"),
                },
                "runtime": {
                    "mode": "local",
                    "storage_backend": "local_fs",
                    "state_backend": "json",
                },
                "backtest": {
                    "starting_capital_jpy": 5_000_000,
                },
                "portfolio": {
                    "max_positions": 7,
                    "max_position_pct": 0.18,
                },
                "default_strategies": {
                    "entry": "MACDPreCross2BarEntry",
                    "exit": "MVXW_N5_R3p35_T1p45_D21_B20p0",
                },
                "evaluation": {
                    "capacity_regime_mode": "off",
                },
                "capacity_regime": {
                    "version": "test",
                    "equity_window_days": 20,
                    "turnover_field": "Turnover_Median_20",
                    "tiers": [
                        {
                            "name": "tier0",
                            "max_equity_jpy": None,
                            "max_positions": 7,
                            "max_position_pct": 0.18,
                            "participation_cap_pct": 0.02,
                            "min_turnover_20_jpy": 500000000,
                        }
                    ],
                },
                "production": {
                    "state_file": str(state_dir / "production_state.json"),
                    "signal_file_pattern": str(signals_dir / "{date}.json"),
                    "report_file_pattern": str(reports_dir / "{date}.md"),
                    "history_file": str(state_dir / "trade_history.json"),
                    "cash_history_file": str(state_dir / "cash_history.json"),
                    "fetch_universe_file": str(state_dir / "fetch_universe.json"),
                    "sector_pool_file": str(sector_pool_dir),
                    "capacity_regime_mode": "off",
                    "buy_threshold": 65,
                },
            }
        ),
        encoding="utf-8",
    )

    manager = ConfigManager(str(config_file))

    errors: list[str] = []

    def worker(index: int) -> str:
        manager.get_production_config()
        return f"ok-{index}"

    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = [executor.submit(worker, index) for index in range(64)]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:  # pragma: no cover - asserted via errors list
                errors.append(repr(exc))

    assert errors == []
