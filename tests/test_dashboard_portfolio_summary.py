import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from web.api.routers import state as state_router


def test_get_portfolio_includes_cash_flow_and_market_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    cash_history_file = tmp_path / "cash_history.json"
    features_dir = tmp_path / "data" / "features"
    features_dir.mkdir(parents=True)

    state_file.write_text(
        json.dumps(
            {
                "last_updated": "2026-05-11T12:00:00",
                "strategy_groups": [
                    {
                        "id": "group_main",
                        "name": "Main",
                        "initial_capital": 8_000_000.0,
                        "cash": 33_500.0,
                        "positions": [
                            {
                                "ticker": "6674",
                                "quantity": 400,
                                "entry_price": 6_000.0,
                                "entry_date": "2026-05-11",
                                "entry_score": 0.0,
                                "peak_price": 6_000.0,
                                "lot_id": "lot_1",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cash_history_file.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "date": "2026-05-01",
                        "group_id": "group_main",
                        "event_type": "DEPOSIT",
                        "amount": 2_000_000.0,
                        "old_cash": 0.0,
                        "new_cash": 2_000_000.0,
                        "reason": "Admin add-cash",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pd.DataFrame({"Close": [6_500.0, 6_750.0]}).to_parquet(
        features_dir / "6674_features.parquet"
    )

    monkeypatch.setattr(
        state_router,
        "get_production_config",
        lambda: SimpleNamespace(
            state_file=str(state_file),
            cash_history_file=str(cash_history_file),
        ),
    )
    monkeypatch.setattr(state_router, "get_project_root", lambda: tmp_path)

    response = state_router.get_portfolio()
    group = response.groups[0]
    position = group.positions[0]

    assert position.current_price == 6_750.0
    assert position.current_value == 2_700_000.0
    assert group.net_cash_flow == 2_000_000.0
    assert group.total_capital == 10_000_000.0
    assert group.holdings_value == 2_700_000.0
    assert group.current_value == 2_733_500.0
    assert group.total_pnl == -7_266_500.0
    assert group.total_pnl_pct == pytest.approx(-72.665)


def test_get_portfolio_history_builds_total_asset_series(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    history_file = tmp_path / "history.json"
    cash_history_file = tmp_path / "cash_history.json"
    features_dir = tmp_path / "data" / "features"
    features_dir.mkdir(parents=True)

    state_file.write_text(
        json.dumps(
            {
                "last_updated": "2026-05-05T12:00:00",
                "strategy_groups": [
                    {
                        "id": "group_main",
                        "name": "Main",
                        "initial_capital": 10_000.0,
                        "cash": 14_000.0,
                        "positions": [
                            {
                                "ticker": "6674",
                                "quantity": 10,
                                "entry_price": 100.0,
                                "entry_date": "2026-05-03",
                                "entry_score": 0.0,
                                "peak_price": 120.0,
                                "lot_id": "lot_1",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    history_file.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "events": [
                    {
                        "date": "2026-05-03",
                        "group_id": "group_main",
                        "ticker": "6674",
                        "action": "BUY",
                        "quantity": 10,
                        "price": 100.0,
                        "total_jpy": 1_000.0,
                        "entry_score": 0.0,
                        "exit_reason": None,
                        "exit_score": None,
                        "event_id": "evt_1",
                        "status": "ACTIVE",
                        "position_effects": [
                            {
                                "effect_type": "OPEN",
                                "ticker": "6674",
                                "quantity": 10,
                                "entry_price": 100.0,
                                "entry_date": "2026-05-03",
                                "entry_score": 0.0,
                                "lot_id": "lot_1",
                            }
                        ],
                        "cash_effect": None,
                        "source": None,
                        "replaces_event_id": None,
                        "replaced_by_event_id": None,
                        "created_at": "2026-05-03T09:00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cash_history_file.write_text(
        json.dumps(
            {
                "events": [
                    {
                        "date": "2026-05-02",
                        "group_id": "group_main",
                        "event_type": "DEPOSIT",
                        "amount": 5_000.0,
                        "old_cash": 10_000.0,
                        "new_cash": 15_000.0,
                        "reason": "Admin add-cash",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pd.DataFrame(
        {
            "Date": ["2026-05-02", "2026-05-05"],
            "Close": [100.0, 120.0],
        }
    ).set_index("Date").to_parquet(features_dir / "6674_features.parquet")

    monkeypatch.setattr(
        state_router,
        "get_production_config",
        lambda: SimpleNamespace(
            state_file=str(state_file),
            history_file=str(history_file),
            cash_history_file=str(cash_history_file),
        ),
    )
    monkeypatch.setattr(state_router, "get_project_root", lambda: tmp_path)

    response = state_router.get_portfolio_history()

    assert [point.date for point in response.points] == [
        "2026-05-02",
        "2026-05-03",
        "2026-05-05",
    ]
    assert response.points[0].current_value == 15_000.0
    assert response.points[0].total_capital == 15_000.0
    assert response.points[1].current_value == 15_000.0
    assert response.points[2].current_value == 15_200.0
    assert response.points[2].total_pnl == 200.0
    assert response.points[2].total_pnl_pct == pytest.approx(1.3333333333)