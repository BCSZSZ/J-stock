import json
from pathlib import Path

import pandas as pd
import pytest

from src.analysis.signals import SignalAction
from src.data.stock_data_manager import StockDataManager
from src.evaluation.replay_seed import (
    ReplaySeedValidationError,
    build_synthetic_entry_signal,
    load_replay_seed,
)


def _write_state_file(state_file: Path) -> None:
    state_file.write_text(
        json.dumps(
            {
                "last_updated": "2026-05-20T12:00:00",
                "strategy_groups": [
                    {
                        "id": "group_main",
                        "name": "Main",
                        "initial_capital": 8_000_000.0,
                        "cash": 8_000_000.0,
                        "positions": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def _write_history_file(
    history_file: Path,
    positions: list[dict[str, object]],
) -> None:
    history_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "events": positions,
            }
        ),
        encoding="utf-8",
    )


def _write_cash_history_file(cash_history_file: Path) -> None:
    cash_history_file.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "date": "2026-05-01",
                        "group_id": "group_main",
                        "event_type": "DEPOSIT",
                        "amount": 2_000_000.0,
                        "old_cash": 8_000_000.0,
                        "new_cash": 10_000_000.0,
                        "reason": "top-up",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _active_buy_event(
    ticker: str,
    lot_id: str,
    quantity: int = 200,
    entry_price: float = 1_000.0,
    signal_entry_price: float = 950.0,
    status: str = "ACTIVE",
) -> dict[str, object]:
    return {
        "date": "2026-05-14",
        "group_id": "group_main",
        "ticker": ticker,
        "action": "BUY",
        "quantity": quantity,
        "price": entry_price,
        "total_jpy": quantity * entry_price,
        "entry_score": 88.0,
        "event_id": f"evt_{ticker}_{lot_id}",
        "status": status,
        "position_effects": [
            {
                "effect_type": "OPEN",
                "lot_id": lot_id,
                "ticker": ticker,
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_date": "2026-05-14",
                "entry_score": 88.0,
                "signal_entry_price": signal_entry_price,
            }
        ],
        "created_at": "2026-05-14T15:00:00",
    }


def test_load_replay_seed_builds_seed_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_file = tmp_path / "2026-05-15.md"
    state_file = tmp_path / "production_state.json"
    history_file = tmp_path / "trade_history.json"
    cash_history_file = tmp_path / "cash_history.json"

    report_file.write_text("# Daily Trading Report\n**Date:** 2026-05-15\n", encoding="utf-8")
    _write_state_file(state_file)
    _write_history_file(
        history_file,
        positions=[
            _active_buy_event("2768", "lot_1", quantity=200, entry_price=1_000.0),
            _active_buy_event(
                "2768",
                "lot_superseded",
                quantity=200,
                entry_price=1_000.0,
                status="SUPERSEDED",
            ),
        ],
    )
    _write_cash_history_file(cash_history_file)

    monkeypatch.setattr(
        StockDataManager,
        "load_stock_features",
        lambda self, ticker: pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-05-14", "2026-05-15"]),
                "Close": [1_050.0, 1_100.0],
            }
        ),
    )

    seed = load_replay_seed(
        report_file=report_file,
        state_file=state_file,
        history_file=history_file,
        cash_history_file=cash_history_file,
        data_root=str(tmp_path / "data"),
    )

    assert seed.report_date == "2026-05-15"
    assert seed.replay_start_date == "2026-05-18"
    assert seed.group_id == "group_main"
    assert seed.starting_cash_jpy == pytest.approx(9_800_000.0)
    assert seed.baseline_total_equity_jpy == pytest.approx(10_020_000.0)
    assert [position.ticker for position in seed.positions] == ["2768"]
    assert seed.positions[0].signal_entry_price == pytest.approx(950.0)
    signal = build_synthetic_entry_signal(seed.positions[0], "ReplayEntry")
    assert signal.action == SignalAction.BUY
    assert signal.metadata["score"] == pytest.approx(88.0)
    assert signal.metadata["source"] == "replay_seed"


def test_load_replay_seed_rejects_multiple_active_lots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_file = tmp_path / "2026-05-15.md"
    state_file = tmp_path / "production_state.json"
    history_file = tmp_path / "trade_history.json"

    report_file.write_text("# Daily Trading Report\n**Date:** 2026-05-15\n", encoding="utf-8")
    _write_state_file(state_file)
    _write_history_file(
        history_file,
        positions=[
            _active_buy_event("2768", "lot_1"),
            _active_buy_event("2768", "lot_2"),
        ],
    )

    monkeypatch.setattr(
        StockDataManager,
        "load_stock_features",
        lambda self, ticker: pd.DataFrame(
            {
                "Date": pd.to_datetime(["2026-05-15"]),
                "Close": [1_100.0],
            }
        ),
    )

    with pytest.raises(ReplaySeedValidationError, match="multiple active lots"):
        load_replay_seed(
            report_file=report_file,
            state_file=state_file,
            history_file=history_file,
            cash_history_file=None,
            data_root=str(tmp_path / "data"),
        )