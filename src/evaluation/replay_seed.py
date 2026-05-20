from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from src.analysis.signals import SignalAction, TradingSignal
from src.aws.jpx_holidays import next_trading_day
from src.backtest.portfolio import Position as BacktestPosition
from src.cli.production_utils import get_signal_date_from_path, parse_signal_payload
from src.data.stock_data_manager import StockDataManager
from src.production.state_manager import (
    ProductionState,
    StrategyGroupState,
    build_state_as_of,
)


REPORT_DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
REPORT_HEADER_DATE_PATTERN = re.compile(r"\*\*Date:\*\*\s*(\d{4}-\d{2}-\d{2})")


class ReplaySeedError(ValueError):
    def __init__(self, message: str, context: dict[str, str] | None = None) -> None:
        self.context = context or {}
        if self.context:
            rendered_context = json.dumps(
                self.context,
                ensure_ascii=False,
                sort_keys=True,
            )
            super().__init__(f"{message} | context={rendered_context}")
            return
        super().__init__(message)


class ReplaySeedValidationError(ReplaySeedError):
    pass


@dataclass(frozen=True)
class ReplaySeedPosition:
    ticker: str
    quantity: int
    entry_price: float
    entry_date: str
    entry_score: float
    peak_price: float
    signal_entry_price: float
    report_close_price: float


@dataclass(frozen=True)
class ReplayPendingOrder:
    group_id: str
    signal_date: str
    signal_type: str
    action: str
    ticker: str
    planned_quantity: int
    position_quantity: int | None
    sell_percentage: float | None
    current_price: float | None
    planned_price: float | None
    required_capital: float | None
    confidence: float
    score: float
    reason: str
    strategy_name: str
    signal_payload: dict[str, object]


@dataclass(frozen=True)
class ReplaySeed:
    report_file: str
    report_date: str
    replay_start_date: str
    group_id: str
    group_name: str
    starting_cash_jpy: float
    baseline_total_equity_jpy: float
    positions: tuple[ReplaySeedPosition, ...]
    prior_signal_file: str
    pending_orders: tuple[ReplayPendingOrder, ...]


def extract_report_date(report_file: Path) -> str:
    stem_match = REPORT_DATE_PATTERN.search(report_file.stem)
    if stem_match:
        return stem_match.group(1)

    try:
        text = report_file.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ReplaySeedValidationError(
            "Replay report file does not exist.",
            context={"report_file": str(report_file)},
        ) from exc

    header_match = REPORT_HEADER_DATE_PATTERN.search(text[:4096])
    if header_match:
        return header_match.group(1)

    raise ReplaySeedValidationError(
        "Unable to determine replay report date.",
        context={"report_file": str(report_file)},
    )


def build_synthetic_entry_signal(
    position: ReplaySeedPosition,
    strategy_name: str,
) -> TradingSignal:
    return TradingSignal(
        action=SignalAction.BUY,
        confidence=0.0,
        reasons=[f"Replay seeded position from {position.entry_date}"],
        metadata={
            "score": float(position.entry_score),
            "source": "replay_seed",
            "seed_entry_date": position.entry_date,
            "seed_entry_price": float(position.entry_price),
            "seed_signal_entry_price": float(position.signal_entry_price),
            "seed_peak_price": float(position.peak_price),
            "seed_report_close_price": float(position.report_close_price),
        },
        strategy_name=strategy_name,
    )


def build_seeded_backtest_position(
    position: ReplaySeedPosition,
    strategy_name: str,
) -> BacktestPosition:
    return BacktestPosition(
        ticker=position.ticker,
        quantity=int(position.quantity),
        entry_price=float(position.entry_price),
        signal_entry_price=float(position.signal_entry_price),
        entry_date=pd.Timestamp(position.entry_date),
        entry_signal=build_synthetic_entry_signal(position, strategy_name),
        peak_price_since_entry=float(position.peak_price),
    )


def build_replay_pending_signal(
    order: ReplayPendingOrder,
    priority: int | None = None,
) -> TradingSignal:
    metadata = {
        "score": float(order.score),
        "source": "replay_prior_signal",
        "signal_date": order.signal_date,
        "planned_quantity": int(order.planned_quantity),
        "planned_price": order.planned_price,
        "required_capital": order.required_capital,
        "signal_payload": dict(order.signal_payload),
    }
    if priority is not None:
        metadata["replay_pending_order_priority"] = int(priority)
    if order.signal_type == "SELL":
        metadata["planned_sell_quantity"] = int(order.planned_quantity)
        if order.position_quantity is not None:
            metadata["position_quantity"] = int(order.position_quantity)
        if order.sell_percentage is not None:
            metadata["sell_percentage"] = float(order.sell_percentage)

    return TradingSignal(
        action=SignalAction.BUY if order.signal_type == "BUY" else SignalAction.SELL,
        confidence=float(order.confidence),
        reasons=[order.reason or f"Replay pending {order.signal_type} order"],
        metadata=metadata,
        strategy_name=order.strategy_name or "ReplayPendingOrder",
    )


def load_replay_seed(
    report_file: Path,
    state_file: Path,
    history_file: Path | None,
    cash_history_file: Path | None,
    prior_signal_file: Path,
    data_root: str = "data",
) -> ReplaySeed:
    if not report_file.exists():
        raise ReplaySeedValidationError(
            "Replay report file does not exist.",
            context={"report_file": str(report_file)},
        )

    if not state_file.exists():
        raise ReplaySeedValidationError(
            "Production state file does not exist.",
            context={"state_file": str(state_file)},
        )

    report_date = extract_report_date(report_file)
    state_snapshot = _build_replay_state_snapshot(
        state_file=state_file,
        history_file=history_file,
        cash_history_file=cash_history_file,
        report_date=report_date,
    )
    seed_group = _select_replay_group(state_snapshot, report_file=report_file)
    _ensure_single_lot_per_ticker(seed_group, report_file=report_file)
    pending_orders = _load_pending_orders(
        signal_file=prior_signal_file,
        report_date=report_date,
        group_id=seed_group.id,
    )

    price_manager = StockDataManager(api_key=None, data_root=data_root)
    seed_positions = _build_seed_positions(
        group=seed_group,
        report_date=report_date,
        price_manager=price_manager,
    )
    total_market_value = sum(
        position.report_close_price * position.quantity for position in seed_positions
    )
    replay_start = next_trading_day(
        date.fromisoformat(report_date) + timedelta(days=1)
    ).isoformat()

    return ReplaySeed(
        report_file=str(report_file),
        report_date=report_date,
        replay_start_date=replay_start,
        group_id=seed_group.id,
        group_name=seed_group.name,
        starting_cash_jpy=float(seed_group.cash),
        baseline_total_equity_jpy=float(seed_group.cash + total_market_value),
        positions=tuple(seed_positions),
        prior_signal_file=str(prior_signal_file),
        pending_orders=tuple(pending_orders),
    )


def resolve_latest_available_end_date(
    tickers: list[str],
    data_root: str = "data",
) -> str:
    if not tickers:
        raise ReplaySeedValidationError(
            "Replay universe is empty.",
            context={"data_root": data_root},
        )

    price_manager = StockDataManager(api_key=None, data_root=data_root)
    latest_date: pd.Timestamp | None = None
    for ticker in tickers:
        frame = price_manager.load_stock_features(ticker)
        if frame is None or frame.empty:
            continue
        normalized = _normalize_price_frame(frame)
        if normalized.empty:
            continue
        ticker_latest = pd.Timestamp(normalized["Date"].max())
        latest_date = ticker_latest if latest_date is None else max(latest_date, ticker_latest)

    if latest_date is None:
        raise ReplaySeedValidationError(
            "Unable to find any feature data for replay universe.",
            context={"ticker_count": str(len(tickers)), "data_root": data_root},
        )

    return latest_date.strftime("%Y-%m-%d")


def _build_replay_state_snapshot(
    state_file: Path,
    history_file: Path | None,
    cash_history_file: Path | None,
    report_date: str,
) -> ProductionState:
    base_state = ProductionState(state_file=str(state_file))
    return build_state_as_of(
        base_state=base_state,
        history_file=str(history_file) if history_file else None,
        cash_history_file=str(cash_history_file) if cash_history_file else None,
        as_of_date=report_date,
    )


def _select_replay_group(
    state_snapshot: ProductionState,
    report_file: Path,
) -> StrategyGroupState:
    groups = state_snapshot.get_all_groups()
    active_groups = [
        group
        for group in groups
        if group.positions or abs(float(group.cash) - float(group.initial_capital)) > 1e-9
    ]

    if not active_groups and len(groups) == 1:
        return groups[0]

    if len(active_groups) != 1:
        raise ReplaySeedValidationError(
            "Replay currently supports exactly one active strategy group.",
            context={
                "report_file": str(report_file),
                "active_groups": ",".join(group.id for group in active_groups),
            },
        )

    return active_groups[0]


def _ensure_single_lot_per_ticker(
    group: StrategyGroupState,
    report_file: Path,
) -> None:
    ticker_counts = Counter(position.ticker for position in group.positions)
    duplicate_tickers = sorted(
        ticker for ticker, count in ticker_counts.items() if count > 1
    )
    if duplicate_tickers:
        raise ReplaySeedValidationError(
            "Replay currently does not support multiple active lots for the same ticker.",
            context={
                "report_file": str(report_file),
                "group_id": group.id,
                "duplicate_tickers": ",".join(duplicate_tickers),
            },
        )


def _build_seed_positions(
    group: StrategyGroupState,
    report_date: str,
    price_manager: StockDataManager,
) -> list[ReplaySeedPosition]:
    seed_positions: list[ReplaySeedPosition] = []
    for raw_position in sorted(group.positions, key=lambda item: (item.entry_date, item.ticker)):
        if int(raw_position.quantity) <= 0:
            continue
        report_close_price = _load_report_close_price(
            price_manager=price_manager,
            ticker=raw_position.ticker,
            report_date=report_date,
        )
        signal_entry_price = float(
            raw_position.signal_entry_price
            if raw_position.signal_entry_price is not None
            else raw_position.entry_price
        )
        peak_price = float(raw_position.peak_price or signal_entry_price)
        seed_positions.append(
            ReplaySeedPosition(
                ticker=raw_position.ticker,
                quantity=int(raw_position.quantity),
                entry_price=float(raw_position.entry_price),
                entry_date=str(raw_position.entry_date),
                entry_score=float(raw_position.entry_score),
                peak_price=peak_price,
                signal_entry_price=signal_entry_price,
                report_close_price=report_close_price,
            )
        )
    return seed_positions


def _load_pending_orders(
    signal_file: Path,
    report_date: str,
    group_id: str,
) -> list[ReplayPendingOrder]:
    if not signal_file.exists():
        raise ReplaySeedValidationError(
            "Replay requires prior-day production signals file.",
            context={
                "report_date": report_date,
                "signal_file": str(signal_file),
            },
        )

    signal_date = get_signal_date_from_path(signal_file)
    if signal_date and signal_date != report_date:
        raise ReplaySeedValidationError(
            "Replay prior-day signals file date does not match report date.",
            context={
                "report_date": report_date,
                "signal_file": str(signal_file),
                "signal_date": signal_date,
            },
        )

    raw_signals = parse_signal_payload(signal_file)
    pending_orders: list[ReplayPendingOrder] = []
    for raw_signal in raw_signals:
        raw_group_id = str(raw_signal.get("group_id") or "").strip()
        if raw_group_id != group_id:
            continue

        if not _is_executable_signal(raw_signal):
            continue

        signal_type = str(raw_signal.get("signal_type") or raw_signal.get("action") or "").upper()
        if signal_type not in {"BUY", "SELL"}:
            continue

        planned_quantity = _resolve_planned_quantity(signal_type, raw_signal)
        if planned_quantity <= 0:
            continue

        position_quantity = _safe_int(raw_signal.get("position_qty"))
        pending_orders.append(
            ReplayPendingOrder(
                group_id=raw_group_id,
                signal_date=signal_date or report_date,
                signal_type=signal_type,
                action=str(raw_signal.get("action") or signal_type),
                ticker=str(raw_signal.get("ticker") or "").strip(),
                planned_quantity=planned_quantity,
                position_quantity=position_quantity,
                sell_percentage=_resolve_sell_percentage(
                    action=str(raw_signal.get("action") or signal_type),
                    planned_quantity=planned_quantity,
                    position_quantity=position_quantity,
                ),
                current_price=_safe_float(raw_signal.get("current_price")),
                planned_price=_safe_float(raw_signal.get("planned_price")),
                required_capital=_safe_float(raw_signal.get("required_capital")),
                confidence=float(raw_signal.get("confidence") or 0.0),
                score=float(raw_signal.get("score") or 0.0),
                reason=str(raw_signal.get("reason") or ""),
                strategy_name=str(raw_signal.get("strategy_name") or ""),
                signal_payload=dict(raw_signal),
            )
        )

    return pending_orders


def _is_executable_signal(raw_signal: dict[str, object]) -> bool:
    return bool(
        raw_signal.get("is_executable")
        or raw_signal.get("is_executable_buy")
        or raw_signal.get("is_executable_sell")
    )


def _resolve_planned_quantity(signal_type: str, raw_signal: dict[str, object]) -> int:
    if signal_type == "BUY":
        return _safe_int(raw_signal.get("suggested_qty")) or 0
    return _safe_int(raw_signal.get("planned_sell_qty")) or 0


def _resolve_sell_percentage(
    action: str,
    planned_quantity: int,
    position_quantity: int | None,
) -> float | None:
    if position_quantity and position_quantity > 0:
        return max(0.0, min(1.0, float(planned_quantity) / float(position_quantity)))

    normalized = action.strip().upper()
    if "25" in normalized:
        return 0.25
    if "50" in normalized:
        return 0.5
    if "75" in normalized:
        return 0.75
    if "100" in normalized or normalized == "SELL":
        return 1.0
    return None


def _safe_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_report_close_price(
    price_manager: StockDataManager,
    ticker: str,
    report_date: str,
) -> float:
    frame = price_manager.load_stock_features(ticker)
    if frame is None or frame.empty:
        raise ReplaySeedValidationError(
            "Replay seed is missing feature data for seeded ticker.",
            context={"ticker": ticker, "report_date": report_date},
        )

    normalized = _normalize_price_frame(frame)
    filtered = normalized.loc[normalized["Date"] <= pd.Timestamp(report_date)]
    if filtered.empty:
        raise ReplaySeedValidationError(
            "Replay seed has no close price on or before report date.",
            context={"ticker": ticker, "report_date": report_date},
        )

    close_value = filtered.iloc[-1]["Close"]
    return float(close_value)


def _normalize_price_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if "Date" in frame.columns:
        normalized = frame.copy()
        normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
        normalized = normalized.dropna(subset=["Date", "Close"])
        return normalized.sort_values("Date")

    normalized = frame.copy().reset_index()
    index_column = str(normalized.columns[0])
    normalized = normalized.rename(columns={index_column: "Date"})
    normalized["Date"] = pd.to_datetime(normalized["Date"], errors="coerce")
    normalized = normalized.dropna(subset=["Date", "Close"])
    return normalized.sort_values("Date")