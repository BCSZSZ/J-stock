from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from web.api.routers import entry_exit_validation as entry_exit_validation_router
from web.api.schemas import EntryExitValidationRunRequest


def test_build_cli_args_uses_request_values(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_exit_validation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/production_monitor_list.json",
            default_entry_strategy="DefaultEntry",
            default_exit_strategy="DefaultExit",
            strategy_groups=[{"entry_strategy": "ProdEntry", "exit_strategy": "ProdExit"}],
        ),
    )
    monkeypatch.setattr(
        entry_exit_validation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {"signal_ranking_strategy": "momentum"}}),
    )

    req = EntryExitValidationRunRequest(
        entry_strategies=["EntryA"],
        exit_strategies=["ExitA"],
        universe_files=["data/monitor_list.json"],
        start="2026-01-01",
        end="2026-01-31",
        horizons=[3, 5, 7],
        primary_horizon=5,
        execution_mode="next_open",
        signal_scope="selected",
        ranking_strategy="score_only",
        entry_filter_mode="grid",
        entry_filter_names=["f01"],
        atr_ratio_min=0.01,
        atr_ratio_max=0.08,
        tail_guard_enabled=False,
        tail_guard_max_rank=8,
        momentum_exhaustion_mode="enforce",
        momentum_exhaustion_max_score=4.0,
        max_holding_trading_days=40,
        output_dir="output/entry_exit_validation_test",
    )

    args = entry_exit_validation_router._build_cli_args(req)

    assert args[:2] == ["entry-exit-validation", "--entry-strategies"]
    assert "EntryA" in args
    assert "ExitA" in args
    assert "--signal-scope" in args
    assert args[args.index("--signal-scope") + 1] == "selected"
    assert "--entry-filter-name" in args
    assert "f01" in args
    assert "--no-tail-guard-enabled" in args
    assert args[args.index("--momentum-exhaustion-mode") + 1] == "enforce"
    assert args[args.index("--momentum-exhaustion-max-score") + 1] == "4.0"
    assert args[args.index("--momentum-exhaustion-threshold-method") + 1] == "absolute"
    assert args[args.index("--max-holding-trading-days") + 1] == "40"


def test_build_cli_args_falls_back_to_production_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_exit_validation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/production_monitor_list.json",
            default_entry_strategy="DefaultEntry",
            default_exit_strategy="DefaultExit",
            strategy_groups=[{"entry_strategy": "ProdEntry", "exit_strategy": "ProdExit"}],
        ),
    )
    monkeypatch.setattr(
        entry_exit_validation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {"signal_ranking_strategy": "momentum"}}),
    )

    args = entry_exit_validation_router._build_cli_args(EntryExitValidationRunRequest(years=[2026]))

    assert "ProdEntry" in args
    assert "ProdExit" in args
    assert "data/production_monitor_list.json" in args
    assert "momentum" in args


def test_dataset_summary_reads_manifest_and_summary(tmp_path, monkeypatch) -> None:
    root = tmp_path / "entry_exit_validation"
    dataset = root / "20260602" / "entry_exit_validation__entry_Fake__exit_Fake__120000"
    dataset.mkdir(parents=True)
    (dataset / "entry_exit_validation_summary_20260602_120000.json").write_text(
        '{"candidate_count": 3, "simulated_trade_count": 2}',
        encoding="utf-8",
    )
    (dataset / "entry_exit_validation_manifest.json").write_text(
        """
{
  "dataset_id": "entry_exit_validation__entry_Fake__exit_Fake__120000",
  "generated_at": "2026-06-02T12:00:00",
  "output_dir": "",
  "selected_trades_csv": "combo_selected_trades.csv",
  "combo_summary_csv": "combo_summary.csv",
  "combo_tail_metrics_csv": "combo_tail_metrics.csv",
  "combo_vs_fixed_horizon_csv": "combo_vs_fixed_horizon.csv",
  "combo_by_year_csv": "combo_by_year.csv",
  "combo_by_market_regime_csv": "combo_by_market_regime.csv",
  "combo_by_exit_reason_csv": "combo_by_exit_reason.csv",
  "combo_by_signal_bucket_csv": "combo_by_signal_bucket.csv",
  "combo_by_month_csv": "combo_by_month.csv",
  "combo_robustness_ranking_csv": "combo_robustness_ranking.csv",
  "combo_risk_ranking_csv": "combo_risk_ranking.csv",
  "summary_json": "entry_exit_validation_summary_20260602_120000.json",
  "report_md": "combo_report.md",
  "entry_strategies": ["FakeEntry"],
  "exit_strategies": ["FakeExit"],
  "universe_size": 3,
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "horizons": [3, 5, 7],
  "primary_horizon": 5,
  "execution_mode": "next_open",
  "signal_scope": "all",
  "ranking_strategy": "momentum",
  "entry_filter_mode": "auto",
  "entry_filter_names": [],
  "candidate_count": 3,
  "simulated_trade_count": 2,
  "combination_count": 1,
  "request": {}
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_exit_validation_router, "_entry_output_dir", lambda _output_dir=None: root)

    datasets = entry_exit_validation_router.list_datasets()
    summary = entry_exit_validation_router.get_dataset_summary(datasets[0]["id"])

    assert datasets[0]["simulated_trade_count"] == 2
    assert summary["summary"]["candidate_count"] == 3


def test_resolve_dataset_dir_blocks_path_traversal(tmp_path) -> None:
    root = tmp_path / "entry_exit_validation"
    root.mkdir()

    with pytest.raises(HTTPException):
        entry_exit_validation_router._resolve_dataset_dir(root, "../secret")


def test_run_cli_streaming_emits_frontend_contract(monkeypatch) -> None:
    class FakeProc:
        def __init__(self) -> None:
            self.stdout = iter(["first line\n", "second line\n"])

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(
        entry_exit_validation_router.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProc(),
    )
    monkeypatch.setattr(entry_exit_validation_router, "get_project_root", lambda: Path("."))

    response = asyncio.run(
        entry_exit_validation_router._run_cli_streaming(["entry-exit-validation"])
    )

    async def _collect() -> str:
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk)
        return "".join(chunks)

    body = asyncio.run(_collect())

    assert '"line": "first line"' in body
    assert '"line": "second line"' in body
    assert '"done": true' in body
    assert '"exit_code": 0' in body
