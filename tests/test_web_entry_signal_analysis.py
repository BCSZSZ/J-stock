import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException

from web.api.routers import entry_signal_analysis as entry_signal_analysis_router
from web.api.schemas import EntrySignalAnalysisRunRequest


def test_build_cli_args_uses_request_values(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_signal_analysis_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/production_monitor_list.json",
            default_entry_strategy="DefaultEntry",
            strategy_groups=[{"entry_strategy": "ProdEntry"}],
        ),
    )
    monkeypatch.setattr(
        entry_signal_analysis_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {"signal_ranking_strategy": "momentum"}}),
    )

    req = EntrySignalAnalysisRunRequest(
        entry_strategies=["EntryA"],
        universe_files=["data/monitor_list.json"],
        start="2026-01-01",
        end="2026-01-31",
        horizons=[1, 3, 5],
        primary_horizon=5,
        primary_horizons=[3, 5],
        label_mode="next_open",
        ranking_strategy="score_only",
        entry_filter_mode="grid",
        entry_filter_names=["f01"],
        risk_per_trade_pct=0.0078,
        atr_stop_multiple=1.0,
        tail_guard_enabled=False,
        tail_guard_max_rank=8,
        momentum_exhaustion_mode="enforce",
        momentum_exhaustion_max_score=4.0,
        industry_filter_mode="enforce",
        max_buy_per_industry_per_day=1,
        max_total_positions_per_industry=3,
        industry_reference_file="data/jpx_final_list.csv",
        output_dir="output/entry_signal_analysis_test",
    )

    args = entry_signal_analysis_router._build_cli_args(req)

    assert args[:2] == ["entry-signal-analysis", "--entry-strategies"]
    assert "EntryA" in args
    assert "--ranking-strategy" in args
    assert "score_only" in args
    assert "--entry-filter-name" in args
    assert "f01" in args
    assert args[args.index("--primary-horizons") + 1 : args.index("--label-mode")] == ["3", "5", "--primary-horizon", "3"]
    assert "--no-tail-guard-enabled" in args
    assert args[args.index("--tail-guard-max-rank") + 1] == "8"
    assert args[args.index("--momentum-exhaustion-mode") + 1] == "enforce"
    assert args[args.index("--momentum-exhaustion-max-score") + 1] == "4.0"
    assert args[args.index("--momentum-exhaustion-threshold-method") + 1] == "absolute"
    assert args[args.index("--industry-filter-mode") + 1] == "enforce"
    assert args[args.index("--max-buy-per-industry-per-day") + 1] == "1"
    assert args[args.index("--max-total-positions-per-industry") + 1] == "3"
    assert args[args.index("--industry-reference-file") + 1] == "data/jpx_final_list.csv"


def test_build_cli_args_falls_back_to_production_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_signal_analysis_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/production_monitor_list.json",
            default_entry_strategy="DefaultEntry",
            strategy_groups=[{"entry_strategy": "ProdEntry"}],
        ),
    )
    monkeypatch.setattr(
        entry_signal_analysis_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {"signal_ranking_strategy": "momentum"}}),
    )

    args = entry_signal_analysis_router._build_cli_args(EntrySignalAnalysisRunRequest(years=[2026]))

    assert "ProdEntry" in args
    assert "data/production_monitor_list.json" in args
    assert "momentum" in args


def test_dataset_summary_reads_manifest_and_summary(tmp_path, monkeypatch) -> None:
    root = tmp_path / "entry_signal_analysis"
    dataset = root / "20260602" / "entry_signal_analysis__entry_Fake__h1_3_5__120000"
    dataset.mkdir(parents=True)
    (dataset / "entry_signal_analysis_summary_20260602_120000.json").write_text(
        '{"candidate_count": 3, "selected_count": 2}',
        encoding="utf-8",
    )
    (dataset / "entry_signal_analysis_manifest.json").write_text(
        """
{
  "dataset_id": "entry_signal_analysis__entry_Fake__h1_3_5__120000",
  "generated_at": "2026-06-02T12:00:00",
  "output_dir": "",
  "candidates_csv": "candidates.csv",
  "selected_csv": "selected.csv",
  "daily_summary_csv": "daily.csv",
  "strategy_summary_csv": "strategy.csv",
  "summary_json": "entry_signal_analysis_summary_20260602_120000.json",
  "report_md": "report.md",
  "entry_strategies": ["Fake"],
  "universe_size": 3,
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "horizons": [1, 3, 5],
  "primary_horizon": 5,
    "primary_horizons": [5],
  "label_mode": "next_open",
  "ranking_strategy": "momentum",
  "entry_filter_mode": "auto",
  "entry_filter_names": [],
  "candidate_count": 3,
  "selected_count": 2,
  "request": {}
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_signal_analysis_router, "_entry_output_dir", lambda _output_dir=None: root)

    datasets = entry_signal_analysis_router.list_datasets()
    summary = entry_signal_analysis_router.get_dataset_summary(datasets[0]["id"])

    assert datasets[0]["selected_count"] == 2
    assert summary["summary"]["candidate_count"] == 3


def test_resolve_dataset_dir_blocks_path_traversal(tmp_path) -> None:
    root = tmp_path / "entry_signal_analysis"
    root.mkdir()

    with pytest.raises(HTTPException):
        entry_signal_analysis_router._resolve_dataset_dir(root, "../secret")


def test_run_cli_streaming_emits_frontend_contract(monkeypatch) -> None:
    class FakeProc:
        def __init__(self) -> None:
            self.stdout = iter(["first line\n", "second line\n"])

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(
        entry_signal_analysis_router.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProc(),
    )
    monkeypatch.setattr(entry_signal_analysis_router, "get_project_root", lambda: Path("."))

    response = asyncio.run(
        entry_signal_analysis_router._run_cli_streaming(["entry-signal-analysis"])
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
