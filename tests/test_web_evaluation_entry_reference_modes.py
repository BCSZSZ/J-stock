from types import SimpleNamespace

from web.api.routers import evaluation as evaluation_router
from web.api.schemas import EvaluationRunRequest


def test_resolve_requested_entry_reference_modes_dedupes_preserving_order() -> None:
    req = EvaluationRunRequest(
        entry_reference_modes=["buffered_fill", "raw_fill", "buffered_fill"],
    )

    resolved = evaluation_router._resolve_requested_entry_reference_modes(req)

    assert resolved == ["buffered_fill", "raw_fill"]


def test_build_cli_args_includes_entry_reference_mode(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/monitor_list.json",
            strategy_groups=[
                {
                    "id": "group_main",
                    "entry_strategy": "EntryStrategy",
                    "exit_strategy": "ExitStrategy",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        evaluation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {}}),
    )

    req = EvaluationRunRequest(
        command="evaluate",
        mode="annual",
        buy_fill_mode="next_open",
        entry_reference_mode="buffered_fill",
    )

    args = evaluation_router._build_cli_args(req)

    entry_reference_index = args.index("--entry-reference-mode")
    assert args[entry_reference_index + 1] == "buffered_fill"


def test_build_cli_args_ignores_years_for_replay_evaluation(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/monitor_list.json",
            report_file_pattern=r"G:\My Drive\AI-Stock-Sync\reports\{date}.md",
            strategy_groups=[
                {
                    "id": "group_main",
                    "entry_strategy": "EntryStrategy",
                    "exit_strategy": "ExitStrategy",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        evaluation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {}}),
    )

    req = EvaluationRunRequest(
        command="replay-evaluation",
        report_file=r"G:\My Drive\AI-Stock-Sync\reports\2026-05-15.md",
        years=[2022, 2023, 2024, 2025, 2026],
    )

    args = evaluation_router._build_cli_args(req)

    assert "--years" not in args


def test_build_cli_args_includes_launch_date_for_evaluate(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/monitor_list.json",
            strategy_groups=[
                {
                    "id": "group_main",
                    "entry_strategy": "EntryStrategy",
                    "exit_strategy": "ExitStrategy",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        evaluation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {}}),
    )

    req = EvaluationRunRequest(
        command="evaluate",
        mode="annual",
        years=[2026],
        launch_date="2026-02-01",
    )

    args = evaluation_router._build_cli_args(req)

    launch_date_index = args.index("--launch-date")
    assert args[launch_date_index + 1] == "2026-02-01"


def test_build_cli_args_includes_multiple_launch_dates_for_evaluate(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluation_router,
        "get_production_config",
        lambda: SimpleNamespace(
            monitor_list_file="data/monitor_list.json",
            strategy_groups=[
                {
                    "id": "group_main",
                    "entry_strategy": "EntryStrategy",
                    "exit_strategy": "ExitStrategy",
                }
            ],
        ),
    )
    monkeypatch.setattr(
        evaluation_router,
        "get_config_manager",
        lambda: SimpleNamespace(raw_config={"production": {}}),
    )

    req = EvaluationRunRequest(
        command="evaluate",
        mode="annual",
        years=[2026],
        launch_dates=["2026-01-01", "2026-02-01"],
    )

    args = evaluation_router._build_cli_args(req)

    launch_date_index = args.index("--launch-date")
    assert args[launch_date_index + 1 : launch_date_index + 3] == [
        "2026-01-01",
        "2026-02-01",
    ]


def test_get_report_context_extracts_entry_and_exit(tmp_path) -> None:
    report_file = tmp_path / "2026-05-15.md"
    report_file.write_text(
        "\n".join(
            [
                "# Daily Trading Report",
                "",
                "## 🧭 Strategy Overview",
                "",
                "- **Group:** 主策略组",
                "- **Entry Strategy:** `ReplayEntryStrategy`",
                "- **Exit Strategy:** `ReplayExitStrategy`",
            ]
        ),
        encoding="utf-8",
    )

    context = evaluation_router.get_report_context(str(report_file))

    assert context == {
        "report_file": str(report_file),
        "entry_strategy": "ReplayEntryStrategy",
        "exit_strategy": "ReplayExitStrategy",
    }


def test_get_report_context_falls_back_to_pair_header(tmp_path) -> None:
    report_file = tmp_path / "2026-05-15.md"
    report_file.write_text(
        "\n".join(
            [
                "# Daily Trading Report",
                "",
                "| Ticker | Name | Price | PairEntry__PAIR__PairExit | EMA20 |",
                "|--------|------|-------|---------------------------|-------|",
            ]
        ),
        encoding="utf-8",
    )

    context = evaluation_router.get_report_context(str(report_file))

    assert context == {
        "report_file": str(report_file),
        "entry_strategy": "PairEntry",
        "exit_strategy": "PairExit",
    }


def test_get_report_context_falls_back_to_report_buy_and_config_exit(tmp_path) -> None:
    report_root = tmp_path
    reports_dir = report_root / "reports"
    old_dir = report_root / "old"
    reports_dir.mkdir()
    old_dir.mkdir()

    report_file = reports_dir / "2026-02-17.md"
    report_file.write_text(
        "\n".join(
            [
                "# Daily Trading Report",
                "**Date:** 2026-02-17",
                "",
                "### 🟢 BUY Signals Summary",
                "",
                "| Rank | Ticker | Strategy | Score | Confidence | Reason |",
                "|------|--------|----------|-------|------------|--------|",
                "| 1 | 6861 | MACDCrossoverStrategy | 0.0 | 75% | MACD golden cross detected |",
            ]
        ),
        encoding="utf-8",
    )
    (old_dir / "config_20260305_205137.json").write_text(
        "\n".join(
            [
                "{",
                '  "default_strategies": {',
                '    "entry": "SnapshotEntryStrategy",',
                '    "exit": "SnapshotExitStrategy"',
                "  }",
                "}",
            ]
        ),
        encoding="utf-8",
    )

    context = evaluation_router.get_report_context(str(report_file))

    assert context == {
        "report_file": str(report_file),
        "entry_strategy": "MACDCrossoverStrategy",
        "exit_strategy": "SnapshotExitStrategy",
    }