from types import SimpleNamespace

from src.cli.production_input import run_input_workflow
from src.production.state_manager import ProductionState, TradeHistoryManager


def _make_args(csv_path: str) -> SimpleNamespace:
    return SimpleNamespace(
        manual=True,
        manual_file=csv_path,
        trade_date=None,
        yes=True,
        aws_profile=None,
        input=False,
        signal_date=None,
    )


def _make_prod_cfg(state_file: str, history_file: str) -> SimpleNamespace:
    return SimpleNamespace(
        state_file=state_file,
        history_file=history_file,
        ops_s3_prefix=None,
        signal_file_pattern="",
    )


def test_manual_buy_overwrite_keeps_single_active_trade(tmp_path):
    state_file = tmp_path / "state.json"
    history_file = tmp_path / "history.json"
    csv_file = tmp_path / "buy.csv"

    state = ProductionState(str(state_file))
    state.add_group("group_main", "Main", 100000)
    state.save()

    history = TradeHistoryManager(str(history_file))
    history.save()

    csv_file.write_text("ticker,action,qty,price,date\n4082,BUY,100,100,2026-03-19\n", encoding="utf-8")
    run_input_workflow(_make_args(str(csv_file)), _make_prod_cfg(str(state_file), str(history_file)), state)

    csv_file.write_text("ticker,action,qty,price,date\n4082,BUY,100,105,2026-03-19\n", encoding="utf-8")
    state = ProductionState(str(state_file))
    run_input_workflow(_make_args(str(csv_file)), _make_prod_cfg(str(state_file), str(history_file)), state)

    reloaded_state = ProductionState(str(state_file))
    reloaded_history = TradeHistoryManager(str(history_file))

    positions = reloaded_state.get_group("group_main").get_positions_by_ticker("4082")
    assert len(positions) == 1
    assert positions[0].quantity == 100
    assert positions[0].entry_price == 105
    assert reloaded_state.get_group("group_main").cash == 89500

    assert len(reloaded_history.trades) == 2
    assert reloaded_history.count_active_trades() == 1
    active_buy = reloaded_history.find_active_trade("2026-03-19", "group_main", "4082", "BUY")
    assert active_buy is not None
    assert active_buy.price == 105
    assert any(trade.status == "SUPERSEDED" for trade in reloaded_history.trades)


def test_manual_sell_overwrite_restores_original_lot_then_reapplies(tmp_path):
    state_file = tmp_path / "state.json"
    history_file = tmp_path / "history.json"
    buy_csv = tmp_path / "buy.csv"
    sell_csv = tmp_path / "sell.csv"

    state = ProductionState(str(state_file))
    state.add_group("group_main", "Main", 100000)
    state.save()

    history = TradeHistoryManager(str(history_file))
    history.save()

    buy_csv.write_text("ticker,action,qty,price,date\n7011,BUY,100,100,2026-03-18\n", encoding="utf-8")
    run_input_workflow(_make_args(str(buy_csv)), _make_prod_cfg(str(state_file), str(history_file)), state)

    sell_csv.write_text("ticker,action,qty,price,date\n7011,SELL,40,110,2026-03-19\n", encoding="utf-8")
    state = ProductionState(str(state_file))
    run_input_workflow(_make_args(str(sell_csv)), _make_prod_cfg(str(state_file), str(history_file)), state)

    sell_csv.write_text("ticker,action,qty,price,date\n7011,SELL,50,120,2026-03-19\n", encoding="utf-8")
    state = ProductionState(str(state_file))
    run_input_workflow(_make_args(str(sell_csv)), _make_prod_cfg(str(state_file), str(history_file)), state)

    reloaded_state = ProductionState(str(state_file))
    reloaded_history = TradeHistoryManager(str(history_file))
    group = reloaded_state.get_group("group_main")
    positions = group.get_positions_by_ticker("7011")

    assert len(positions) == 1
    assert positions[0].quantity == 50
    assert positions[0].entry_price == 100
    assert group.cash == 96000

    assert len(reloaded_history.trades) == 3
    assert reloaded_history.count_active_trades() == 2
    active_sell = reloaded_history.find_active_trade("2026-03-19", "group_main", "7011", "SELL")
    assert active_sell is not None
    assert active_sell.quantity == 50
    assert active_sell.price == 120
    superseded_sells = [
        trade for trade in reloaded_history.trades
        if trade.action == "SELL" and trade.status == "SUPERSEDED"
    ]
    assert len(superseded_sells) == 1