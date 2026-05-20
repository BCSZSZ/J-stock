from types import SimpleNamespace

from src.cli import production_daily


def test_daily_repairs_signal_prices_before_building_effective_state(monkeypatch) -> None:
    call_order: list[str] = []

    def fake_run_signal_price_check(prod_cfg, state, **kwargs):
        call_order.append(f"repair:{kwargs['target_date']}")
        return SimpleNamespace(has_changes=False)

    def fake_build_state_as_of(*, base_state, history_file, cash_history_file, as_of_date):
        call_order.append(f"build:{as_of_date}")
        return "effective-state"

    monkeypatch.setattr(production_daily, "run_signal_price_check", fake_run_signal_price_check)
    monkeypatch.setattr(production_daily, "build_state_as_of", fake_build_state_as_of)

    result = production_daily._repair_and_build_effective_state(
        prod_cfg=SimpleNamespace(history_file="history.json", cash_history_file="cash.json"),
        state=object(),
        signal_date="2026-05-20",
        data_root="data",
    )

    assert result == "effective-state"
    assert call_order == ["repair:2026-05-20", "build:2026-05-20"]