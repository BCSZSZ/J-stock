from __future__ import annotations

import json
import math
from typing import Final

import pandas as pd

from src.analysis.signals import Position, SignalAction
from src.backtest.data_cache import BacktestDataCache
from src.entry_exit_validation.models import EntryExitValidationRequest
from src.entry_exit_validation.scanner import EntryExitCandidateContext
from src.entry_signal_analysis.scanner import _build_market_data
from src.signal_generator import generate_signal_v2
from src.utils.strategy_loader import create_strategy_instance


TRADE_COLUMNS: Final[list[str]] = [
    "ticker",
    "entry_date",
    "entry_price",
    "signal_date",
    "entry_strategy",
    "entry_filter_name",
    "exit_strategy",
    "exit_signal_date",
    "exit_date",
    "exit_price",
    "holding_days",
    "holding_trading_days",
    "return_pct",
    "exit_reason",
    "exit_urgency",
    "exit_sell_percentage",
    "no_exit",
    "rank",
    "rank_score",
    "score",
    "confidence",
    "selected",
    "ranking_strategy",
    "entry_atr",
    "entry_atr_pct",
    "initial_stop_price",
    "trailing_stop_price",
    "max_favorable_return_pct",
    "max_adverse_return_pct",
    "exit_metadata_json",
]


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _base_record(context: EntryExitCandidateContext) -> dict[str, object]:
    record = dict(context.payload)
    record.update(
        {
            "ticker": context.ticker,
            "signal_date": context.signal_date,
            "entry_strategy": context.entry_strategy,
            "entry_filter_name": context.entry_filter_name,
            "exit_strategy": context.exit_strategy,
        }
    )
    return record


def _price_at(frame: pd.DataFrame, row_pos: int, column: str) -> float | None:
    if row_pos < 0 or row_pos >= len(frame) or column not in frame.columns:
        return None
    return _to_float(frame.iloc[row_pos].get(column))


def _date_at(frame: pd.DataFrame, row_pos: int) -> str | None:
    if row_pos < 0 or row_pos >= len(frame):
        return None
    return pd.Timestamp(frame.index[row_pos]).date().isoformat()


def _entry_atr(frame: pd.DataFrame, entry_pos: int) -> float | None:
    return _price_at(frame, entry_pos, "ATR")


def _return_pct(price: float, entry_price: float) -> float:
    return ((price / entry_price) - 1.0) * 100.0


def _stop_price_from_metadata(
    metadata: dict[str, object],
    position: Position,
) -> tuple[float | None, float | None]:
    initial = _to_float(metadata.get("initial_stop_price"))
    if initial is None:
        initial = _to_float(position.initial_stop_price)

    trailing = _to_float(metadata.get("locked_stop_price"))
    if trailing is None:
        trailing = _to_float(metadata.get("trailing_stop_price"))
    if trailing is None:
        trailing = _to_float(metadata.get("trailing_stop"))
    if trailing is None:
        trailing = _to_float(metadata.get("stop_level"))
    if trailing is None:
        trailing = _to_float(position.locked_stop_price)
    return initial, trailing


def _missing_entry_record(
    context: EntryExitCandidateContext,
    frame: pd.DataFrame,
) -> dict[str, object]:
    record = _base_record(context)
    record.update(
        {
            "entry_date": _date_at(frame, context.entry_pos),
            "entry_price": None,
            "exit_signal_date": None,
            "exit_date": None,
            "exit_price": None,
            "holding_days": None,
            "holding_trading_days": None,
            "return_pct": None,
            "exit_reason": "missing_entry_price",
            "exit_urgency": "MISSING_ENTRY_PRICE",
            "exit_sell_percentage": None,
            "no_exit": True,
            "entry_atr": None,
            "entry_atr_pct": None,
            "initial_stop_price": None,
            "trailing_stop_price": None,
            "max_favorable_return_pct": None,
            "max_adverse_return_pct": None,
            "exit_metadata_json": "{}",
        }
    )
    return record


def simulate_candidate_exit(
    context: EntryExitCandidateContext,
    request: EntryExitValidationRequest,
    cache: BacktestDataCache,
) -> dict[str, object]:
    features = cache.get_features(context.ticker)
    if features is None or features.empty:
        return _missing_entry_record(context, pd.DataFrame())

    entry_price = _to_float(context.payload.get("label_entry_price"))
    if entry_price is None or entry_price <= 0 or context.entry_pos >= len(features):
        return _missing_entry_record(context, features)

    entry_date = pd.Timestamp(features.index[context.entry_pos]).normalize()
    entry_atr = _entry_atr(features, context.entry_pos)
    entry_atr_pct = (
        (entry_atr / entry_price) * 100.0
        if entry_atr is not None and entry_price > 0
        else None
    )
    position = Position(
        ticker=context.ticker,
        entry_price=entry_price,
        signal_entry_price=entry_price,
        entry_date=entry_date,
        quantity=1,
        entry_signal=context.signal,
        peak_price_since_entry=entry_price,
        entry_atr=entry_atr,
    )
    exit_strategy = create_strategy_instance(context.exit_strategy, "exit")

    start_check_pos = context.entry_pos
    if request.execution_mode == "signal_close":
        start_check_pos = context.entry_pos + 1
    max_mark_pos = min(
        len(features) - 1,
        context.entry_pos + request.max_holding_trading_days,
    )
    max_favorable = 0.0
    max_adverse = 0.0
    last_metadata: dict[str, object] = {}

    for check_pos in range(start_check_pos, max_mark_pos + 1):
        current_date = pd.Timestamp(features.index[check_pos]).normalize()
        current_close = _price_at(features, check_pos, "Close")
        if current_close is None or current_close <= 0:
            continue

        pnl = _return_pct(current_close, entry_price)
        max_favorable = max(max_favorable, pnl)
        max_adverse = min(max_adverse, pnl)
        position.peak_price_since_entry = max(
            float(position.peak_price_since_entry), current_close
        )
        market_data = _build_market_data(
            ticker=context.ticker,
            current_date=current_date,
            features=features,
            row_pos=check_pos,
            trades=cache.get_trades(context.ticker),
            financials=cache.get_financials(context.ticker),
            metadata=cache.get_metadata(context.ticker),
        )

        signal = generate_signal_v2(
            market_data=market_data,
            entry_strategy=None,
            exit_strategy=exit_strategy,
            position=position,
        )
        last_metadata = dict(signal.metadata or {})
        if signal.action != SignalAction.SELL:
            continue

        if request.execution_mode == "next_open":
            exit_pos = check_pos + 1
            exit_price = _price_at(features, exit_pos, "Open")
        else:
            exit_pos = check_pos
            exit_price = current_close
        if exit_price is None or exit_pos >= len(features):
            break

        exit_date = pd.Timestamp(features.index[exit_pos]).normalize()
        return_pct = _return_pct(exit_price, entry_price)
        initial_stop, trailing_stop = _stop_price_from_metadata(last_metadata, position)
        record = _base_record(context)
        record.update(
            {
                "entry_date": entry_date.date().isoformat(),
                "entry_price": entry_price,
                "exit_signal_date": current_date.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "exit_price": exit_price,
                "holding_days": int((exit_date - entry_date).days),
                "holding_trading_days": int(exit_pos - context.entry_pos),
                "return_pct": return_pct,
                "exit_reason": signal.reasons[0] if signal.reasons else "SELL",
                "exit_urgency": last_metadata.get("trigger", "SELL"),
                "exit_sell_percentage": _to_float(last_metadata.get("sell_percentage")) or 1.0,
                "no_exit": False,
                "entry_atr": entry_atr,
                "entry_atr_pct": entry_atr_pct,
                "initial_stop_price": initial_stop,
                "trailing_stop_price": trailing_stop,
                "max_favorable_return_pct": max(max_favorable, return_pct),
                "max_adverse_return_pct": min(max_adverse, return_pct),
                "exit_metadata_json": _json_dumps(last_metadata),
            }
        )
        return record

    mark_pos = max_mark_pos
    mark_price = _price_at(features, mark_pos, "Close")
    mark_date = pd.Timestamp(features.index[mark_pos]).normalize()
    initial_stop, trailing_stop = _stop_price_from_metadata(last_metadata, position)
    record = _base_record(context)
    record.update(
        {
            "entry_date": entry_date.date().isoformat(),
            "entry_price": entry_price,
            "exit_signal_date": None,
            "exit_date": mark_date.date().isoformat(),
            "exit_price": mark_price,
            "holding_days": int((mark_date - entry_date).days),
            "holding_trading_days": int(mark_pos - context.entry_pos),
            "return_pct": _return_pct(mark_price, entry_price) if mark_price else None,
            "exit_reason": "no_exit",
            "exit_urgency": "NO_EXIT",
            "exit_sell_percentage": 0.0,
            "no_exit": True,
            "entry_atr": entry_atr,
            "entry_atr_pct": entry_atr_pct,
            "initial_stop_price": initial_stop,
            "trailing_stop_price": trailing_stop,
            "max_favorable_return_pct": max_favorable,
            "max_adverse_return_pct": max_adverse,
            "exit_metadata_json": _json_dumps(last_metadata),
        }
    )
    return record


def simulate_candidate_exits(
    contexts: list[EntryExitCandidateContext],
    request: EntryExitValidationRequest,
    cache: BacktestDataCache,
) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for index, context in enumerate(contexts, start=1):
        if request.signal_scope == "selected" and not bool(context.payload.get("selected")):
            continue
        records.append(simulate_candidate_exit(context, request, cache))
        if index % 500 == 0:
            print(
                f"[entry-exit-validation] simulated {index}/{len(contexts)} candidate exits"
            )

    if not records:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    frame = pd.DataFrame(records)
    ordered_columns = [column for column in TRADE_COLUMNS if column in frame.columns]
    extra_columns = [column for column in frame.columns if column not in ordered_columns]
    return frame[ordered_columns + extra_columns]
