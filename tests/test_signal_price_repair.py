from src.production.signal_price_repair import repair_signal_entry_prices
from src.production.state_manager import ProductionState, TradeHistoryManager


def _build_open_effect(position) -> dict:
    return {
        "effect_type": "OPEN",
        "lot_id": position.lot_id,
        "ticker": position.ticker,
        "quantity": position.quantity,
        "entry_price": position.entry_price,
        "entry_date": position.entry_date,
        "entry_score": position.entry_score,
        "peak_price": position.peak_price,
        "signal_entry_price": position.signal_entry_price,
    }


def test_repair_updates_state_and_matching_buy_effect_and_peak(tmp_path) -> None:
    state = ProductionState(str(tmp_path / "state.json"))
    group = state.add_group("group_main", "Main", 1_000_000)
    position = group.add_position(
        ticker="8306",
        quantity=100,
        entry_price=100.0,
        entry_date="2026-05-20",
        entry_score=0.0,
        signal_entry_price=100.0,
    )

    history = TradeHistoryManager(str(tmp_path / "history.json"))
    trade = history.record_trade(
        date="2026-05-20",
        group_id="group_main",
        ticker="8306",
        action="BUY",
        quantity=100,
        price=100.0,
        entry_score=0.0,
        position_effects=[_build_open_effect(position)],
        source={"channel": "manual_csv"},
    )

    summary = repair_signal_entry_prices(
        state,
        history,
        scope="today",
        target_date="2026-05-20",
        reference_price_resolver=lambda ticker, trade_date, data_root=None: 120.0,
    )

    assert summary.repaired_lots == 1
    assert summary.has_changes is True
    assert position.signal_entry_price == 120.0
    assert position.peak_price == 120.0
    assert trade.position_effects[0]["signal_entry_price"] == 120.0
    assert trade.position_effects[0]["peak_price"] == 120.0


def test_repair_preserves_higher_peak_price(tmp_path) -> None:
    state = ProductionState(str(tmp_path / "state.json"))
    group = state.add_group("group_main", "Main", 1_000_000)
    position = group.add_position(
        ticker="8308",
        quantity=100,
        entry_price=100.0,
        entry_date="2026-05-20",
        entry_score=0.0,
        signal_entry_price=100.0,
    )
    position.peak_price = 155.0

    history = TradeHistoryManager(str(tmp_path / "history.json"))
    open_effect = _build_open_effect(position)
    open_effect["peak_price"] = 155.0
    trade = history.record_trade(
        date="2026-05-20",
        group_id="group_main",
        ticker="8308",
        action="BUY",
        quantity=100,
        price=100.0,
        entry_score=0.0,
        position_effects=[open_effect],
        source={"channel": "manual_csv"},
    )

    summary = repair_signal_entry_prices(
        state,
        history,
        scope="all",
        reference_price_resolver=lambda ticker, trade_date, data_root=None: 120.0,
    )

    assert summary.repaired_lots == 1
    assert position.signal_entry_price == 120.0
    assert position.peak_price == 155.0
    assert trade.position_effects[0]["signal_entry_price"] == 120.0
    assert trade.position_effects[0]["peak_price"] == 155.0


def test_repair_skips_when_reference_open_matches_entry(tmp_path) -> None:
    state = ProductionState(str(tmp_path / "state.json"))
    group = state.add_group("group_main", "Main", 1_000_000)
    position = group.add_position(
        ticker="5741",
        quantity=100,
        entry_price=100.0,
        entry_date="2026-05-20",
        entry_score=0.0,
        signal_entry_price=100.0,
    )

    history = TradeHistoryManager(str(tmp_path / "history.json"))
    trade = history.record_trade(
        date="2026-05-20",
        group_id="group_main",
        ticker="5741",
        action="BUY",
        quantity=100,
        price=100.0,
        entry_score=0.0,
        position_effects=[_build_open_effect(position)],
        source={"channel": "manual_csv"},
    )

    summary = repair_signal_entry_prices(
        state,
        history,
        scope="all",
        reference_price_resolver=lambda ticker, trade_date, data_root=None: 100.0,
    )

    assert summary.repaired_lots == 0
    assert summary.skipped_lots == 1
    assert summary.has_changes is False
    assert position.signal_entry_price == 100.0
    assert position.peak_price == 100.0
    assert trade.position_effects[0]["signal_entry_price"] == 100.0
    assert trade.position_effects[0]["peak_price"] == 100.0