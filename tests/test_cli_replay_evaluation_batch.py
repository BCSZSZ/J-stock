from pathlib import Path
from types import SimpleNamespace

from src.cli import evaluate as evaluate_cli


def test_resolve_replay_report_files_dedupes_preserving_order() -> None:
    args = SimpleNamespace(
        report_file=[
            r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md",
            r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md",
            r"G:\My Drive\AI-Stock-Sync\reports\2026-05-15.md",
        ]
    )

    resolved = evaluate_cli._resolve_replay_report_files(args)

    assert resolved == [
        Path(r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"),
        Path(r"G:\My Drive\AI-Stock-Sync\reports\2026-05-15.md"),
    ]


def test_build_replay_report_run_args_uses_report_context_when_cli_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "resolve_report_strategy_context",
        lambda _path: {
            "entry_strategy": "ReplayEntryFromReport",
            "exit_strategy": "ReplayExitFromReport",
        },
    )
    args = SimpleNamespace(
        report_file=[r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"],
        entry_strategies=None,
        exit_strategies=None,
    )

    run_args, context = evaluate_cli._build_replay_report_run_args(
        args,
        Path(r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"),
    )

    assert context == {
        "entry_strategy": "ReplayEntryFromReport",
        "exit_strategy": "ReplayExitFromReport",
    }
    assert run_args.entry_strategies == ["ReplayEntryFromReport"]
    assert run_args.exit_strategies == ["ReplayExitFromReport"]
    assert run_args.report_file == r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"


def test_build_replay_report_run_args_preserves_manual_strategy_overrides(monkeypatch) -> None:
    monkeypatch.setattr(
        evaluate_cli,
        "resolve_report_strategy_context",
        lambda _path: {
            "entry_strategy": "ReplayEntryFromReport",
            "exit_strategy": "ReplayExitFromReport",
        },
    )
    args = SimpleNamespace(
        report_file=[r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"],
        entry_strategies=["ManualEntry"],
        exit_strategies=["ManualExit"],
    )

    run_args, context = evaluate_cli._build_replay_report_run_args(
        args,
        Path(r"G:\My Drive\AI-Stock-Sync\reports\2026-05-14.md"),
    )

    assert context == {}
    assert run_args.entry_strategies == ["ManualEntry"]
    assert run_args.exit_strategies == ["ManualExit"]