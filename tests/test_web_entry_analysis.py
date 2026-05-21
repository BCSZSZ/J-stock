from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException

from web.api.routers import entry_analysis as entry_analysis_router
from web.api.schemas import EntryAnalysisAggregateRequest, EntryAnalysisFeatureCondition, EntryAnalysisRule, EntryAnalysisRunRequest


def test_build_cli_args_uses_request_rules_json(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_analysis_router,
        "get_production_config",
        lambda: SimpleNamespace(monitor_list_file="data/monitor_list.json"),
    )
    monkeypatch.setattr(
        entry_analysis_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"evaluation": {"default_entry_strategies": ["DefaultEntry"]}}),
    )

    req = EntryAnalysisRunRequest(
        entry_strategies=["EntryA"],
        universe_files=["data/monitor_list.json"],
        start="2026-01-01",
        end="2026-01-31",
        horizons=[3, 5],
        rules=[EntryAnalysisRule(feature="RSI", mode="sliding", min=0, max=100, window=10, step=5)],
        include_joint=False,
        save_candidates=False,
        output_dir="output/entry_analysis_test",
    )

    args = entry_analysis_router._build_cli_args(req)

    assert args[:2] == ["entry-analysis", "--entry-strategies"]
    assert "EntryA" in args
    assert "--rules-json" in args
    assert "--preset-rules" not in args
    assert "--no-joint" in args
    assert "--no-save-candidates" not in args
    assert args[args.index("--output-dir") + 1] == "output/entry_analysis_test"


def test_build_cli_args_falls_back_to_defaults(monkeypatch) -> None:
    monkeypatch.setattr(
        entry_analysis_router,
        "get_production_config",
        lambda: SimpleNamespace(monitor_list_file="data/production_monitor_list.json"),
    )
    monkeypatch.setattr(
        entry_analysis_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"evaluation": {"default_entry_strategies": ["DefaultEntry"]}}),
    )

    args = entry_analysis_router._build_cli_args(EntryAnalysisRunRequest(years=[2026]))

    assert "DefaultEntry" in args
    assert "data/production_monitor_list.json" in args
    assert "--years" in args
    assert "--preset-rules" not in args


def test_resolve_result_file_blocks_path_traversal(tmp_path) -> None:
    root = tmp_path / "entry_analysis"
    root.mkdir()
    outside = tmp_path / "secret.json"
    outside.write_text("{}", encoding="utf-8")

    with pytest.raises(HTTPException):
        entry_analysis_router._resolve_result_file(root, "../secret.json")


def test_get_result_reads_json_inside_root(tmp_path, monkeypatch) -> None:
    root = tmp_path / "entry_analysis"
    root.mkdir()
    payload = root / "summary.json"
    payload.write_text('{"ok": true}', encoding="utf-8")
    monkeypatch.setattr(entry_analysis_router, "_entry_output_dir", lambda _output_dir=None: root)

    result = entry_analysis_router.get_result("summary.json")

    assert result == {"type": "json", "name": "summary.json", "data": {"ok": True}}


def test_dataset_schema_and_aggregate_read_manifest_dataset(tmp_path, monkeypatch) -> None:
    root = tmp_path / "entry_analysis"
    dataset = root / "20260521" / "entry_analysis__entry_Fake__h5__120000"
    dataset.mkdir(parents=True)
    candidates = dataset / "entry_analysis_candidates_20260521_120000.csv"
    pd.DataFrame(
        {
            "entry_strategy": ["Fake", "Fake", "Fake"],
            "ticker": ["1", "2", "3"],
            "signal_date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "RSI": [45.0, 55.0, 75.0],
            "ADX_14": [25.0, 10.0, 30.0],
            "forward_return_5d_pct": [2.0, -1.0, 3.0],
        }
    ).to_csv(candidates, index=False)
    manifest = dataset / "entry_analysis_manifest.json"
    manifest.write_text(
        """
{
  "dataset_id": "entry_analysis__entry_Fake__h5__120000",
  "generated_at": "2026-05-21T12:00:00",
  "output_dir": "",
  "candidates_csv": "entry_analysis_candidates_20260521_120000.csv",
  "summary_json": "summary.json",
  "report_md": "report.md",
  "entry_strategies": ["Fake"],
  "universe_size": 3,
  "start_date": "2026-01-01",
  "end_date": "2026-01-31",
  "horizons": [5],
  "label_mode": "signal_close",
  "indicator_columns": ["RSI", "ADX_14"],
  "candidate_count": 3,
  "feature_columns": ["RSI", "ADX_14"],
  "request": {}
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(entry_analysis_router, "_entry_output_dir", lambda _output_dir=None: root)

    datasets = entry_analysis_router.list_datasets()
    schema = entry_analysis_router.get_dataset_schema(datasets[0]["id"])
    aggregate = entry_analysis_router.aggregate_dataset(
        datasets[0]["id"],
        EntryAnalysisAggregateRequest(
            conditions=[EntryAnalysisFeatureCondition(feature="RSI", min=40, max=60)],
            horizons=[5],
            logic="all",
        ),
    )

    assert datasets[0]["candidate_count"] == 3
    assert "RSI" in schema["numeric_features"]
    assert aggregate["filtered"]["candidate_count"] == 2
    assert aggregate["filtered"]["5d"]["wins"] == 1
