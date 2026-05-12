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
    benchmarks_dir = tmp_path / "data" / "benchmarks"
    features_dir.mkdir(parents=True)
    benchmarks_dir.mkdir(parents=True)

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
    pd.DataFrame(
        {
            "Date": ["2026-05-02", "2026-05-05"],
            "Close": [100.0, 110.0],
        }
    ).to_parquet(benchmarks_dir / "topix_daily.parquet", index=False)
    pd.DataFrame(
        {
            "Date": ["2026-05-02", "2026-05-05"],
            "Close": [200.0, 230.0],
        }
    ).set_index("Date").to_parquet(features_dir / "1321_features.parquet")

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
    assert response.points[0].topix_value == 15_000.0
    assert response.points[2].topix_value == 16_500.0
    assert response.points[2].nikkei225_value == 17_250.0
    assert response.points[0].normalized_portfolio == pytest.approx(100.0)
    assert response.points[2].normalized_portfolio == pytest.approx(101.3333333333)
    assert response.points[2].normalized_topix == pytest.approx(110.0)
    assert response.points[2].normalized_nikkei225 == pytest.approx(115.0)


def test_build_normalized_value_by_date_ignores_midstream_cash_flows() -> None:
    normalized = state_router._build_normalized_value_by_date(
        points=[
            state_router.ValueSeriesPoint(date="2026-05-01", value=10_000.0),
            state_router.ValueSeriesPoint(date="2026-05-02", value=11_000.0),
            state_router.ValueSeriesPoint(date="2026-05-03", value=17_000.0),
        ],
        cash_flow_by_date={"2026-05-03": 5_000.0},
    )

    assert normalized["2026-05-01"] == pytest.approx(100.0)
    assert normalized["2026-05-02"] == pytest.approx(110.0)
    assert normalized["2026-05-03"] == pytest.approx(120.0)


def test_get_sector_attribution_groups_period_pnl_by_sector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_file = tmp_path / "state.json"
    history_file = tmp_path / "history.json"
    cash_history_file = tmp_path / "cash_history.json"
    features_dir = tmp_path / "data" / "features"
    data_dir = tmp_path / "data"
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
                        "cash": 9_100.0,
                        "positions": [
                            {
                                "ticker": "6501",
                                "quantity": 10,
                                "entry_price": 50.0,
                                "entry_date": "2026-04-10",
                                "entry_score": 0.0,
                                "peak_price": 70.0,
                                "lot_id": "lot_6501",
                            },
                            {
                                "ticker": "6674",
                                "quantity": 10,
                                "entry_price": 100.0,
                                "entry_date": "2026-05-03",
                                "entry_score": 0.0,
                                "peak_price": 120.0,
                                "lot_id": "lot_6674",
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
                        "date": "2026-04-10",
                        "group_id": "group_main",
                        "ticker": "6501",
                        "action": "BUY",
                        "quantity": 10,
                        "price": 50.0,
                        "total_jpy": 500.0,
                        "entry_score": 0.0,
                        "exit_reason": None,
                        "exit_score": None,
                        "event_id": "evt_buy_6501",
                        "status": "ACTIVE",
                        "position_effects": [
                            {
                                "effect_type": "OPEN",
                                "ticker": "6501",
                                "quantity": 10,
                                "entry_price": 50.0,
                                "entry_date": "2026-04-10",
                                "entry_score": 0.0,
                                "lot_id": "lot_6501",
                            }
                        ],
                        "cash_effect": None,
                        "source": None,
                        "replaces_event_id": None,
                        "replaced_by_event_id": None,
                        "created_at": "2026-04-10T09:00:00",
                    },
                    {
                        "date": "2026-05-02",
                        "group_id": "group_main",
                        "ticker": "7203",
                        "action": "BUY",
                        "quantity": 5,
                        "price": 200.0,
                        "total_jpy": 1_000.0,
                        "entry_score": 0.0,
                        "exit_reason": None,
                        "exit_score": None,
                        "event_id": "evt_buy_7203",
                        "status": "ACTIVE",
                        "position_effects": [
                            {
                                "effect_type": "OPEN",
                                "ticker": "7203",
                                "quantity": 5,
                                "entry_price": 200.0,
                                "entry_date": "2026-05-02",
                                "entry_score": 0.0,
                                "lot_id": "lot_7203",
                            }
                        ],
                        "cash_effect": None,
                        "source": None,
                        "replaces_event_id": None,
                        "replaced_by_event_id": None,
                        "created_at": "2026-05-02T09:00:00",
                    },
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
                        "event_id": "evt_buy_6674",
                        "status": "ACTIVE",
                        "position_effects": [
                            {
                                "effect_type": "OPEN",
                                "ticker": "6674",
                                "quantity": 10,
                                "entry_price": 100.0,
                                "entry_date": "2026-05-03",
                                "entry_score": 0.0,
                                "lot_id": "lot_6674",
                            }
                        ],
                        "cash_effect": None,
                        "source": None,
                        "replaces_event_id": None,
                        "replaced_by_event_id": None,
                        "created_at": "2026-05-03T09:00:00",
                    },
                    {
                        "date": "2026-05-05",
                        "group_id": "group_main",
                        "ticker": "7203",
                        "action": "SELL",
                        "quantity": 5,
                        "price": 220.0,
                        "total_jpy": 1_100.0,
                        "entry_score": None,
                        "exit_reason": "TEST",
                        "exit_score": None,
                        "event_id": "evt_sell_7203",
                        "status": "ACTIVE",
                        "position_effects": [
                            {
                                "effect_type": "CLOSE",
                                "ticker": "7203",
                                "consumed_quantity": 5,
                                "entry_price": 200.0,
                                "entry_date": "2026-05-02",
                                "entry_score": 0.0,
                                "lot_id": "lot_7203",
                            }
                        ],
                        "cash_effect": None,
                        "source": None,
                        "replaces_event_id": None,
                        "replaced_by_event_id": None,
                        "created_at": "2026-05-05T09:00:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    cash_history_file.write_text(json.dumps({"events": []}), encoding="utf-8")

    pd.DataFrame(
        {
            "Date": ["2026-04-10", "2026-04-30", "2026-05-05"],
            "Close": [50.0, 60.0, 70.0],
        }
    ).set_index("Date").to_parquet(features_dir / "6501_features.parquet")
    pd.DataFrame(
        {
            "Date": ["2026-05-02", "2026-05-03", "2026-05-05"],
            "Close": [100.0, 100.0, 120.0],
        }
    ).set_index("Date").to_parquet(features_dir / "6674_features.parquet")
    pd.DataFrame(
        {
            "Date": ["2026-05-02", "2026-05-05"],
            "Close": [200.0, 220.0],
        }
    ).set_index("Date").to_parquet(features_dir / "7203_features.parquet")
    (data_dir / "jpx_final_list.csv").write_text(
        "Yahoo_Ticker,Code,銘柄名,Type,市場・商品区分,33業種区分,規模区分\n"
        "6501.T,6501,テスト重電,Stock,プライム,電気機器,TOPIX Mid400\n"
        "6674.T,6674,テスト電機,Stock,プライム,電気機器,TOPIX Mid400\n"
        "7203.T,7203,テスト自動車,Stock,プライム,輸送用機器,TOPIX Core30\n",
        encoding="utf-8",
    )

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

    response = state_router.get_sector_attribution()

    assert response.as_of_date == "2026-05-05"
    assert [period.key for period in response.summary_periods] == ["1W", "1M", "3M", "YTD", "ALL"]
    assert [period.label for period in response.heatmap_periods] == [
        "1月",
        "2月",
        "3月",
        "4月",
        "5月",
        "6月",
        "7月",
        "8月",
        "9月",
        "10月",
        "11月",
        "12月",
    ]

    sector_map = {item.sector: item for item in response.sectors}
    assert sector_map["電気機器"].current_value == pytest.approx(1_900.0)
    assert sector_map["輸送用機器"].current_value == pytest.approx(0.0)

    all_metrics = {
        item.sector: next(metric for metric in item.summary_periods if metric.period_key == "ALL")
        for item in response.sectors
    }
    heatmap_metric_map = {
        item.sector: {metric.period_key: metric for metric in item.heatmap_periods}
        for item in response.sectors
    }
    assert all_metrics["電気機器"].pnl == pytest.approx(400.0)
    assert all_metrics["電気機器"].buy_amount == pytest.approx(1_000.0)
    assert all_metrics["輸送用機器"].pnl == pytest.approx(100.0)
    assert all_metrics["輸送用機器"].sell_amount == pytest.approx(1_100.0)
    assert heatmap_metric_map["電気機器"]["M04"].pnl == pytest.approx(100.0)
    assert heatmap_metric_map["電気機器"]["M05"].pnl == pytest.approx(300.0)
    assert "M01" not in heatmap_metric_map["電気機器"]
    assert heatmap_metric_map["輸送用機器"]["M05"].pnl == pytest.approx(100.0)
    assert "M04" not in heatmap_metric_map["輸送用機器"]