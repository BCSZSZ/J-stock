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