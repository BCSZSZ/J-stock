"""State endpoints: portfolio, trade history, signals, reports."""

from __future__ import annotations

import calendar
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path
from statistics import median
from typing import Mapping

import pandas as pd
from fastapi import APIRouter, HTTPException

from src.analysis.strategies.exit.multiview_grid_exit import parse_mvx_exit_strategy_name
from src.production import CashHistoryManager, ProductionState, StrategyGroupState, TradeHistoryManager
from src.production.config_manager import ProductionConfig
from src.production.state_manager import CashFlowEvent, Trade, build_state_as_of
from web.api.dependencies import get_production_config, get_project_root
from web.api.schemas import PortfolioHistoryPoint, PortfolioHistoryResponse, PortfolioResponse, SectorAttributionOut, SectorAttributionResponse, SectorPeriodOut, SectorPeriodPnLOut, StrategyGroupOut, PositionOut

router = APIRouter(prefix="/api/state", tags=["state"])

TOPIX_BENCHMARK_FILENAME = "topix_daily.parquet"
NIKKEI225_PROXY_TICKER = "1321"
SECTOR_UNCLASSIFIED = "未分类"


@dataclass(frozen=True)
class CloseSeries:
    dates: tuple[str, ...]
    closes: tuple[float, ...]


@dataclass(frozen=True)
class ValueSeriesPoint:
    date: str
    value: float | None


@dataclass(frozen=True)
class SectorPeriodDefinition:
    key: str
    label: str
    days: int | None = None
    year_to_date: bool = False
    all_history: bool = False


@dataclass(frozen=True)
class SectorTradeFlow:
    buy_amount: float
    sell_amount: float


SUMMARY_PERIOD_DEFINITIONS: tuple[SectorPeriodDefinition, ...] = (
    SectorPeriodDefinition(key="1W", label="1W", days=7),
    SectorPeriodDefinition(key="1M", label="1M", days=30),
    SectorPeriodDefinition(key="3M", label="3M", days=90),
    SectorPeriodDefinition(key="YTD", label="YTD", year_to_date=True),
    SectorPeriodDefinition(key="ALL", label="ALL", all_history=True),
)


def _load_json(path: str | Path) -> object:
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p.name}")
    return json.loads(p.read_text(encoding="utf-8"))


def _positive_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed) or parsed <= 0:
        return None
    return parsed


def _first_positive_float(*values: object) -> float | None:
    for value in values:
        parsed = _positive_float(value)
        if parsed is not None:
            return parsed
    return None


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    if isinstance(value, dict):
        return value
    return {}


def _production_exit_strategy_by_group(
    cfg: ProductionConfig,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for group in cfg.strategy_groups or []:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("id") or "").strip()
        exit_strategy = str(group.get("exit_strategy") or "").strip()
        if group_id and exit_strategy:
            result[group_id] = exit_strategy
    return result


def _signal_exit_strategy_name(
    signal: Mapping[str, object],
    cfg: ProductionConfig,
    exit_strategy_by_group: Mapping[str, str],
) -> str | None:
    metadata = _mapping_or_empty(signal.get("signal_metadata"))
    bound_exit_strategy = str(metadata.get("bound_exit_strategy_name") or "").strip()
    if bound_exit_strategy:
        return bound_exit_strategy

    group_id = str(signal.get("group_id") or "").strip()
    group_exit_strategy = exit_strategy_by_group.get(group_id)
    if group_exit_strategy:
        return group_exit_strategy

    default_exit_strategy = str(getattr(cfg, "default_exit_strategy", "") or "").strip()
    return default_exit_strategy or None


def _mvx_r_multiple(strategy_name: str | None) -> float | None:
    if not strategy_name:
        return None
    spec = parse_mvx_exit_strategy_name(strategy_name)
    if spec is None:
        return None
    return _positive_float(spec.r)


def _enrich_signal_take_profit_preview(
    signal: Mapping[str, object],
    cfg: ProductionConfig,
    exit_strategy_by_group: Mapping[str, str],
) -> dict[str, object]:
    enriched = dict(signal)
    if str(signal.get("signal_type") or "").upper() != "BUY":
        return enriched

    metadata = _mapping_or_empty(signal.get("signal_metadata"))
    reference_price = _first_positive_float(
        signal.get("close_price"),
        metadata.get("close"),
        signal.get("current_price"),
        signal.get("planned_price"),
    )
    assumed_entry_price = _first_positive_float(
        signal.get("planned_price"),
        signal.get("current_price"),
        reference_price,
    )
    atr_value = _first_positive_float(
        metadata.get("ATR"),
        metadata.get("atr_jpy"),
    )
    atr_ratio = _first_positive_float(
        metadata.get("ATR_Ratio"),
        metadata.get("atr_ratio"),
    )
    if atr_value is None and reference_price is not None and atr_ratio is not None:
        atr_value = reference_price * atr_ratio

    exit_strategy = _signal_exit_strategy_name(signal, cfg, exit_strategy_by_group)
    r_multiple = _mvx_r_multiple(exit_strategy)
    if (
        reference_price is None
        or assumed_entry_price is None
        or atr_value is None
        or r_multiple is None
    ):
        enriched["tp_preview_available"] = False
        return enriched

    r_value = r_multiple * atr_value
    tp1_price = reference_price + r_value
    tp2_price = reference_price + (2.0 * r_value)
    enriched.update(
        {
            "tp_preview_available": True,
            "tp_reference_price": reference_price,
            "tp_assumed_entry_price": assumed_entry_price,
            "tp_r_multiple": r_multiple,
            "tp_r_value": r_value,
            "tp1_price": tp1_price,
            "tp2_price": tp2_price,
            "tp1_gain_pct": ((tp1_price - assumed_entry_price) / assumed_entry_price)
            * 100.0,
            "tp2_gain_pct": ((tp2_price - assumed_entry_price) / assumed_entry_price)
            * 100.0,
            "tp_exit_strategy": exit_strategy,
        }
    )
    return enriched


def _enrich_signals_take_profit_preview(
    signals: object,
    cfg: ProductionConfig,
) -> list[dict[str, object]]:
    if not isinstance(signals, list):
        return []
    exit_strategy_by_group = _production_exit_strategy_by_group(cfg)
    return [
        _enrich_signal_take_profit_preview(signal, cfg, exit_strategy_by_group)
        for signal in signals
        if isinstance(signal, dict)
    ]


def _load_state_data(path: str | Path) -> dict[str, object]:
    data = _load_json(path)
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Invalid portfolio state format")
    return data


def _normalize_group_items(raw_groups: object) -> list[tuple[str, dict[str, object]]]:
    items: list[tuple[str, dict[str, object]]] = []
    if isinstance(raw_groups, list):
        items = [
            (str(group.get("id", f"group_{index}")), group)
            for index, group in enumerate(raw_groups)
            if isinstance(group, dict)
        ]
    elif isinstance(raw_groups, dict):
        items = [
            (str(group_id), group)
            for group_id, group in raw_groups.items()
            if isinstance(group, dict)
        ]
    return items


def _features_path(ticker: str) -> Path:
    root = get_project_root()
    return root / "data" / "features" / f"{ticker}_features.parquet"


def _jpx_master_path() -> Path:
    root = get_project_root()
    return root / "data" / "jpx_final_list.csv"


def _benchmark_path(filename: str) -> Path:
    root = get_project_root()
    return root / "data" / "benchmarks" / filename


def _load_close_series_from_path(path: Path) -> CloseSeries | None:
    if not path.exists():
        return None

    try:
        df = pd.read_parquet(path)
    except Exception:
        return None

    if df.empty or "Close" not in df.columns:
        return None

    if "Date" not in df.columns:
        df = df.reset_index()
    if "Date" not in df.columns:
        return None

    close_frame = df[["Date", "Close"]].copy()
    close_frame["Date"] = pd.to_datetime(
        close_frame["Date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    close_frame = close_frame.dropna(subset=["Date", "Close"])
    if close_frame.empty:
        return None

    dates = tuple(str(value) for value in close_frame["Date"].tolist())
    closes = tuple(float(value) for value in close_frame["Close"].tolist())
    return CloseSeries(dates=dates, closes=closes)


def _load_close_series(ticker: str) -> CloseSeries | None:
    return _load_close_series_from_path(_features_path(ticker))


def _load_open_lookup_from_path(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}

    try:
        df = pd.read_parquet(path)
    except Exception:
        return {}

    if df.empty or "Open" not in df.columns:
        return {}

    if "Date" not in df.columns:
        df = df.reset_index()
    if "Date" not in df.columns:
        return {}

    open_frame = df[["Date", "Open"]].copy()
    open_frame["Date"] = pd.to_datetime(
        open_frame["Date"], errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    open_frame = open_frame.dropna(subset=["Date", "Open"])
    if open_frame.empty:
        return {}

    open_frame = open_frame.drop_duplicates(subset=["Date"], keep="last")
    return {
        str(trade_date): float(open_price)
        for trade_date, open_price in zip(
            open_frame["Date"].tolist(),
            open_frame["Open"].tolist(),
        )
    }


def _load_open_lookup(ticker: str) -> dict[str, float]:
    return _load_open_lookup_from_path(_features_path(ticker))


def _is_active_trade_event(event: dict[str, object]) -> bool:
    return str(event.get("status") or "ACTIVE") == "ACTIVE"


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / len(values))


def _capital_weighted_slippage_pct(events: list[dict[str, object]]) -> float | None:
    total_benchmark_notional = 0.0
    total_adverse_jpy = 0.0

    for event in events:
        slippage_pct = _to_float(event.get("slippage_pct"))
        execution_open_price = _to_float(event.get("execution_open_price"))
        quantity = _to_float(event.get("quantity"))
        if (
            slippage_pct is None
            or execution_open_price is None
            or quantity is None
            or execution_open_price <= 0
            or quantity <= 0
        ):
            continue

        benchmark_notional = execution_open_price * quantity
        total_benchmark_notional += benchmark_notional
        total_adverse_jpy += benchmark_notional * (slippage_pct / 100.0)

    if total_benchmark_notional == 0:
        return None

    return (total_adverse_jpy / total_benchmark_notional) * 100.0


def _enrich_trade_event_with_execution_open(
    event: dict[str, object],
    open_lookup_cache: dict[str, dict[str, float]],
) -> dict[str, object]:
    enriched = dict(event)
    ticker = str(enriched.get("ticker") or "")
    trade_date = str(enriched.get("date") or "")
    actual_price = _to_float(enriched.get("price"))

    if not ticker or not trade_date:
        enriched["benchmark_status"] = "MISSING_TRADE_KEYS"
        enriched["execution_open_price"] = None
        enriched["actual_vs_open_jpy"] = None
        enriched["actual_vs_open_pct"] = None
        enriched["slippage_pct"] = None
        enriched["slippage_bps"] = None
        enriched["slippage_direction"] = "UNKNOWN"
        return enriched

    open_lookup = open_lookup_cache.get(ticker)
    if open_lookup is None:
        open_lookup = _load_open_lookup(ticker)
        open_lookup_cache[ticker] = open_lookup

    execution_open = open_lookup.get(trade_date)
    if execution_open is None:
        enriched["benchmark_status"] = "MISSING_OPEN"
        enriched["execution_open_price"] = None
        enriched["actual_vs_open_jpy"] = None
        enriched["actual_vs_open_pct"] = None
        enriched["slippage_pct"] = None
        enriched["slippage_bps"] = None
        enriched["slippage_direction"] = "UNKNOWN"
        return enriched

    if actual_price is None or execution_open == 0:
        enriched["benchmark_status"] = "MISSING_PRICE"
        enriched["execution_open_price"] = execution_open
        enriched["actual_vs_open_jpy"] = None
        enriched["actual_vs_open_pct"] = None
        enriched["slippage_pct"] = None
        enriched["slippage_bps"] = None
        enriched["slippage_direction"] = "UNKNOWN"
        return enriched

    raw_error_jpy = actual_price - execution_open
    raw_error_pct = (raw_error_jpy / execution_open) * 100.0
    if str(enriched.get("action") or "") == "SELL":
        slippage_pct = -raw_error_pct
    else:
        slippage_pct = raw_error_pct

    if slippage_pct > 0:
        slippage_direction = "WORSE"
    elif slippage_pct < 0:
        slippage_direction = "BETTER"
    else:
        slippage_direction = "MATCH"

    enriched["benchmark_status"] = "AVAILABLE"
    enriched["execution_open_price"] = execution_open
    enriched["actual_vs_open_jpy"] = raw_error_jpy
    enriched["actual_vs_open_pct"] = raw_error_pct
    enriched["slippage_pct"] = slippage_pct
    enriched["slippage_bps"] = slippage_pct * 100.0
    enriched["slippage_direction"] = slippage_direction
    return enriched


def _build_trade_history_summary(events: list[dict[str, object]]) -> dict[str, object]:
    active_events = [event for event in events if _is_active_trade_event(event)]
    benchmarked_events = [
        event
        for event in active_events
        if event.get("benchmark_status") == "AVAILABLE"
    ]

    overall_slippage = [
        float(event["slippage_pct"])
        for event in benchmarked_events
        if event.get("slippage_pct") is not None
    ]
    buy_slippage = [
        float(event["slippage_pct"])
        for event in benchmarked_events
        if event.get("action") == "BUY" and event.get("slippage_pct") is not None
    ]
    sell_slippage = [
        float(event["slippage_pct"])
        for event in benchmarked_events
        if event.get("action") == "SELL" and event.get("slippage_pct") is not None
    ]
    buy_events = [
        event for event in benchmarked_events if event.get("action") == "BUY"
    ]
    sell_events = [
        event for event in benchmarked_events if event.get("action") == "SELL"
    ]
    absolute_errors = [
        abs(float(event["actual_vs_open_jpy"]))
        for event in benchmarked_events
        if event.get("actual_vs_open_jpy") is not None
    ]

    return {
        "total_trades": len(active_events),
        "benchmarked_trades": len(benchmarked_events),
        "missing_open_trades": len(active_events) - len(benchmarked_events),
        "capital_weighted_avg_slippage_pct_overall": _capital_weighted_slippage_pct(
            benchmarked_events
        ),
        "capital_weighted_avg_slippage_pct_buy": _capital_weighted_slippage_pct(
            buy_events
        ),
        "capital_weighted_avg_slippage_pct_sell": _capital_weighted_slippage_pct(
            sell_events
        ),
        "avg_slippage_pct_overall": _average(overall_slippage),
        "avg_slippage_pct_buy": _average(buy_slippage),
        "avg_slippage_pct_sell": _average(sell_slippage),
        "avg_abs_error_jpy": _average(absolute_errors),
        "median_slippage_pct": float(median(overall_slippage)) if overall_slippage else None,
    }


def _enrich_trade_history_payload(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Invalid trade history format")

    raw_events = data.get("events") or data.get("trades") or []
    if not isinstance(raw_events, list):
        raise HTTPException(status_code=500, detail="Invalid trade history events format")

    open_lookup_cache: dict[str, dict[str, float]] = {}
    enriched_events = [
        _enrich_trade_event_with_execution_open(event, open_lookup_cache)
        if isinstance(event, dict)
        else {"benchmark_status": "INVALID_EVENT"}
        for event in raw_events
    ]

    payload = dict(data)
    payload["events"] = enriched_events
    payload["summary"] = _build_trade_history_summary(enriched_events)
    return payload


def _load_topix_close_series() -> CloseSeries | None:
    return _load_close_series_from_path(_benchmark_path(TOPIX_BENCHMARK_FILENAME))


def _load_latest_close_point(ticker: str) -> tuple[str | None, float] | None:
    close_series = _load_close_series(ticker)
    if close_series is not None and close_series.dates and close_series.closes:
        return close_series.dates[-1], close_series.closes[-1]

    path = _features_path(ticker)
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path, columns=["Close"])
    except Exception:
        return None
    if df.empty or "Close" not in df.columns:
        return None
    latest_close = df["Close"].iloc[-1]
    if pd.isna(latest_close):
        return None
    latest_date: str | None = None
    if not isinstance(df.index, pd.RangeIndex):
        parsed_date = pd.to_datetime(df.index[-1], errors="coerce")
        if not pd.isna(parsed_date):
            latest_date = parsed_date.strftime("%Y-%m-%d")
    return latest_date, float(latest_close)


def _lookup_close_point_on_or_before(
    close_series: CloseSeries | None,
    target_date: str,
) -> tuple[str, float] | None:
    if close_series is None or not close_series.dates:
        return None

    target_index = bisect_right(close_series.dates, target_date) - 1
    if target_index < 0:
        return None
    return close_series.dates[target_index], close_series.closes[target_index]


def _lookup_close_on_or_before(
    close_series: CloseSeries | None,
    target_date: str,
) -> float | None:
    close_point = _lookup_close_point_on_or_before(close_series, target_date)
    if close_point is None:
        return None

    _, close = close_point
    return close


def _lookup_position_close_on_or_before(
    close_series: CloseSeries | None,
    target_date: str,
    entry_date: str,
) -> float | None:
    close_point = _lookup_close_point_on_or_before(close_series, target_date)
    if close_point is None:
        return None

    resolved_date, resolved_close = close_point
    if resolved_date < entry_date:
        return None
    return resolved_close


def _latest_close_for_position(
    close_point: tuple[str | None, float] | None,
    entry_date: str,
) -> float | None:
    if close_point is None:
        return None

    resolved_date, resolved_close = close_point
    if resolved_date is not None and resolved_date < entry_date:
        return None
    return resolved_close


def _build_base_state(
    state_data: dict[str, object],
    state_file: str,
) -> ProductionState:
    base_state = ProductionState.__new__(ProductionState)
    base_state.state_file = state_file
    base_state.last_updated = str(state_data.get("last_updated", ""))
    base_state.strategy_groups = {}

    for group_id, group in _normalize_group_items(state_data.get("strategy_groups", [])):
        group_name = str(group.get("name", group_id))
        initial_capital = float(group.get("initial_capital", 0.0))
        base_state.strategy_groups[group_id] = StrategyGroupState(
            id=group_id,
            name=group_name,
            initial_capital=initial_capital,
            cash=initial_capital,
            positions=[],
        )

    return base_state


def _collect_relevant_tickers(
    group_items: list[tuple[str, dict[str, object]]],
    trades: list[Trade],
) -> list[str]:
    tickers: set[str] = set()
    for _, group in group_items:
        for position in group.get("positions", []):
            if isinstance(position, dict) and position.get("ticker"):
                tickers.add(str(position["ticker"]))
    for trade in trades:
        if trade.ticker:
            tickers.add(str(trade.ticker))
    return sorted(tickers)


def _collect_anchor_dates(
    group_items: list[tuple[str, dict[str, object]]],
    trades: list[Trade],
    cash_events: list[CashFlowEvent],
) -> list[str]:
    dates: set[str] = set()
    for _, group in group_items:
        for position in group.get("positions", []):
            if isinstance(position, dict) and position.get("entry_date"):
                dates.add(str(position["entry_date"]))
    for trade in trades:
        if trade.date:
            dates.add(str(trade.date))
    for event in cash_events:
        if event.date:
            dates.add(str(event.date))
    return sorted(dates)


def _collect_history_dates(
    price_series_by_ticker: dict[str, CloseSeries],
    anchor_dates: list[str],
) -> list[str]:
    all_dates: set[str] = set(anchor_dates)
    for close_series in price_series_by_ticker.values():
        all_dates.update(close_series.dates)

    if not all_dates:
        return []

    sorted_dates = sorted(all_dates)
    if not anchor_dates:
        return sorted_dates

    start_date = anchor_dates[0]
    return [date_str for date_str in sorted_dates if date_str >= start_date]


def _build_current_prices_for_snapshot(
    snapshot: ProductionState,
    price_series_by_ticker: dict[str, CloseSeries],
    target_date: str,
) -> dict[str, float]:
    current_prices: dict[str, float] = {}
    for group in snapshot.get_all_groups():
        for position in group.positions:
            if position.ticker in current_prices:
                continue
            resolved_price = _lookup_position_close_on_or_before(
                price_series_by_ticker.get(position.ticker),
                target_date,
                str(position.entry_date),
            )
            if resolved_price is not None:
                current_prices[position.ticker] = resolved_price
    return current_prices


def _net_cash_flow_as_of(
    cash_events: list[CashFlowEvent],
    group_id: str,
    target_date: str,
) -> float:
    return float(
        sum(
            float(event.amount or 0.0)
            for event in cash_events
            if event.group_id == group_id and str(event.date) <= target_date
        )
    )


def _calculate_total_pnl_pct(total_pnl: float, total_capital: float) -> float:
    if total_capital == 0:
        return 0.0
    return float((total_pnl / total_capital) * 100.0)


def _normalize_sector_name(value: object) -> str:
    sector = str(value or "").strip()
    if not sector or sector == "-":
        return SECTOR_UNCLASSIFIED
    return sector


def _load_sector_by_ticker() -> dict[str, str]:
    path = _jpx_master_path()
    if not path.exists():
        return {}

    df = pd.read_csv(path, dtype=str, usecols=["Code", "33業種区分"])
    return {
        str(row["Code"]): _normalize_sector_name(row["33業種区分"])
        for _, row in df.iterrows()
        if row.get("Code")
    }


def _lookup_sector_for_ticker(
    ticker: str,
    sector_by_ticker: dict[str, str],
) -> str:
    return sector_by_ticker.get(ticker, SECTOR_UNCLASSIFIED)


def _build_sector_holdings_value(
    snapshot: ProductionState,
    current_prices: dict[str, float],
    sector_by_ticker: dict[str, str],
) -> dict[str, float]:
    holdings_value_by_sector: dict[str, float] = {}
    for group in snapshot.get_all_groups():
        for position in group.positions:
            effective_price = current_prices.get(position.ticker, float(position.entry_price))
            sector = _lookup_sector_for_ticker(position.ticker, sector_by_ticker)
            position_value = float(position.quantity * effective_price)
            holdings_value_by_sector[sector] = holdings_value_by_sector.get(sector, 0.0) + position_value
    return holdings_value_by_sector


def _build_sector_trade_flows(
    trades: list[Trade],
    sector_by_ticker: dict[str, str],
    start_date: str,
    end_date: str,
) -> dict[str, SectorTradeFlow]:
    buys_by_sector: dict[str, float] = {}
    sells_by_sector: dict[str, float] = {}
    for trade in trades:
        trade_date = str(trade.date)
        if trade_date <= start_date or trade_date > end_date:
            continue
        sector = _lookup_sector_for_ticker(trade.ticker, sector_by_ticker)
        if trade.action == "BUY":
            buys_by_sector[sector] = buys_by_sector.get(sector, 0.0) + float(trade.total_jpy)
        elif trade.action == "SELL":
            sells_by_sector[sector] = sells_by_sector.get(sector, 0.0) + float(trade.total_jpy)

    sectors = set(buys_by_sector) | set(sells_by_sector)
    return {
        sector: SectorTradeFlow(
            buy_amount=float(buys_by_sector.get(sector, 0.0)),
            sell_amount=float(sells_by_sector.get(sector, 0.0)),
        )
        for sector in sectors
    }


def _resolve_history_boundary_date(
    history_dates: list[str],
    anchor_date: str,
) -> str:
    if not history_dates:
        return ""
    index = bisect_right(history_dates, anchor_date) - 1
    if index < 0:
        return history_dates[0]
    return history_dates[index]


def _resolve_period_start_date(
    history_dates: list[str],
    end_date: str,
    definition: SectorPeriodDefinition,
) -> str:
    if not history_dates:
        return ""
    if definition.all_history:
        return history_dates[0]

    end_dt = date.fromisoformat(end_date)
    if definition.year_to_date:
        anchor_dt = end_dt.replace(month=1, day=1)
    else:
        anchor_dt = end_dt - timedelta(days=definition.days or 0)
    return _resolve_history_boundary_date(history_dates, anchor_dt.isoformat())


def _build_year_month_heatmap_periods(
    end_date: str,
) -> list[SectorPeriodOut]:
    display_year = date.fromisoformat(end_date).year
    periods: list[SectorPeriodOut] = []
    for month in range(1, 13):
        month_start = date(display_year, month, 1)
        month_end = date(
            display_year,
            month,
            calendar.monthrange(display_year, month)[1],
        )
        periods.append(
            SectorPeriodOut(
                key=f"M{month:02d}",
                label=f"{month}月",
                start_date=month_start.isoformat(),
                end_date=month_end.isoformat(),
            )
        )
    return periods


def _has_history_date_in_range(
    history_dates: list[str],
    start_date: str,
    end_date: str,
) -> bool:
    if not history_dates:
        return False
    start_index = bisect_left(history_dates, start_date)
    if start_index >= len(history_dates):
        return False
    return history_dates[start_index] <= end_date


def _resolve_heatmap_window_dates(
    history_dates: list[str],
    start_date: str,
    end_date: str,
    as_of_date: str,
) -> tuple[str, str] | None:
    effective_end_date = min(end_date, as_of_date)
    if effective_end_date < start_date:
        return None
    if not _has_history_date_in_range(history_dates, start_date, effective_end_date):
        return None

    resolved_start_date = _resolve_history_boundary_date(history_dates, start_date)
    resolved_end_date = _resolve_history_boundary_date(history_dates, effective_end_date)
    if resolved_end_date < resolved_start_date:
        return None
    return resolved_start_date, resolved_end_date


def _build_snapshot_for_date(
    base_state: ProductionState,
    history_file: str,
    cash_history_file: str,
    price_series_by_ticker: dict[str, CloseSeries],
    target_date: str,
) -> tuple[ProductionState, dict[str, float]]:
    snapshot = build_state_as_of(
        base_state=base_state,
        history_file=history_file,
        cash_history_file=cash_history_file,
        as_of_date=target_date,
    )
    current_prices = _build_current_prices_for_snapshot(
        snapshot,
        price_series_by_ticker,
        target_date,
    )
    return snapshot, current_prices


def _build_sector_period_metrics(
    trades: list[Trade],
    sector_by_ticker: dict[str, str],
    start_values: dict[str, float],
    end_values: dict[str, float],
    start_date: str,
    end_date: str,
) -> dict[str, SectorPeriodPnLOut]:
    flows_by_sector = _build_sector_trade_flows(
        trades,
        sector_by_ticker,
        start_date,
        end_date,
    )
    sectors = set(start_values) | set(end_values) | set(flows_by_sector)
    metrics: dict[str, SectorPeriodPnLOut] = {}
    for sector in sectors:
        start_value = float(start_values.get(sector, 0.0))
        end_value = float(end_values.get(sector, 0.0))
        flow = flows_by_sector.get(sector, SectorTradeFlow(buy_amount=0.0, sell_amount=0.0))
        pnl = float(end_value - start_value + flow.sell_amount - flow.buy_amount)
        metrics[sector] = SectorPeriodPnLOut(
            period_key="",
            pnl=pnl,
            start_value=start_value,
            end_value=end_value,
            buy_amount=flow.buy_amount,
            sell_amount=flow.sell_amount,
        )
    return metrics


def _build_cash_flow_by_date(cash_events: list[CashFlowEvent]) -> dict[str, float]:
    cash_flow_by_date: dict[str, float] = {}
    for event in cash_events:
        event_date = str(event.date)
        cash_flow_by_date[event_date] = cash_flow_by_date.get(event_date, 0.0) + float(
            event.amount or 0.0
        )
    return cash_flow_by_date


def _build_benchmark_value_by_date(
    history_points: list[PortfolioHistoryPoint],
    benchmark_series: CloseSeries | None,
    cash_flow_by_date: dict[str, float],
) -> dict[str, float | None]:
    value_by_date: dict[str, float | None] = {
        point.date: None for point in history_points
    }
    if not history_points or benchmark_series is None:
        return value_by_date

    first_point = history_points[0]
    first_price = _lookup_close_on_or_before(benchmark_series, first_point.date)
    if first_price is None or first_price <= 0:
        return value_by_date

    units = first_point.total_capital / first_price
    value_by_date[first_point.date] = float(first_point.total_capital)
    for point in history_points[1:]:
        price = _lookup_close_on_or_before(benchmark_series, point.date)
        if price is None or price <= 0:
            continue
        units += cash_flow_by_date.get(point.date, 0.0) / price
        value_by_date[point.date] = float(units * price)
    return value_by_date


def _build_normalized_value_by_date(
    points: list[ValueSeriesPoint],
    cash_flow_by_date: dict[str, float],
) -> dict[str, float | None]:
    normalized_by_date: dict[str, float | None] = {
        point.date: None for point in points
    }
    valid_points = [point for point in points if point.value is not None]
    if not valid_points:
        return normalized_by_date

    first_point = valid_points[0]
    if first_point.value is None or first_point.value <= 0:
        return normalized_by_date

    normalized_value = 100.0
    previous_value = first_point.value
    normalized_by_date[first_point.date] = normalized_value
    for point in valid_points[1:]:
        current_value = point.value
        if current_value is None:
            continue
        if previous_value <= 0:
            normalized_by_date[point.date] = normalized_value
            previous_value = current_value
            continue

        cash_flow = cash_flow_by_date.get(point.date, 0.0)
        period_return = (current_value - previous_value - cash_flow) / previous_value
        normalized_value = float(normalized_value * (1.0 + period_return))
        normalized_by_date[point.date] = normalized_value
        previous_value = current_value
    return normalized_by_date


def _enrich_portfolio_history_points(
    points: list[PortfolioHistoryPoint],
    cash_events: list[CashFlowEvent],
) -> list[PortfolioHistoryPoint]:
    if not points:
        return []

    cash_flow_by_date = _build_cash_flow_by_date(cash_events)
    topix_value_by_date = _build_benchmark_value_by_date(
        points,
        _load_topix_close_series(),
        cash_flow_by_date,
    )
    nikkei225_value_by_date = _build_benchmark_value_by_date(
        points,
        _load_close_series(NIKKEI225_PROXY_TICKER),
        cash_flow_by_date,
    )
    normalized_portfolio_by_date = _build_normalized_value_by_date(
        [
            ValueSeriesPoint(date=point.date, value=point.current_value)
            for point in points
        ],
        cash_flow_by_date,
    )
    normalized_topix_by_date = _build_normalized_value_by_date(
        [
            ValueSeriesPoint(date=point.date, value=topix_value_by_date[point.date])
            for point in points
        ],
        cash_flow_by_date,
    )
    normalized_nikkei225_by_date = _build_normalized_value_by_date(
        [
            ValueSeriesPoint(date=point.date, value=nikkei225_value_by_date[point.date])
            for point in points
        ],
        cash_flow_by_date,
    )

    return [
        PortfolioHistoryPoint(
            **point.model_dump(
                exclude={
                    "topix_value",
                    "nikkei225_value",
                    "normalized_portfolio",
                    "normalized_topix",
                    "normalized_nikkei225",
                }
            ),
            topix_value=topix_value_by_date.get(point.date),
            nikkei225_value=nikkei225_value_by_date.get(point.date),
            normalized_portfolio=normalized_portfolio_by_date.get(point.date),
            normalized_topix=normalized_topix_by_date.get(point.date),
            normalized_nikkei225=normalized_nikkei225_by_date.get(point.date),
        )
        for point in points
    ]

@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio() -> PortfolioResponse:
    cfg = get_production_config()
    state_data = _load_state_data(cfg.state_file)
    cash_history = CashHistoryManager(cfg.cash_history_file)
    latest_close_cache: dict[str, tuple[str | None, float] | None] = {}

    groups: list[StrategyGroupOut] = []
    group_items = _normalize_group_items(state_data.get("strategy_groups", []))
    for gid, g in group_items:
        positions: list[PositionOut] = []
        holdings_value = 0.0
        for p in g.get("positions", []):
            if not isinstance(p, dict):
                continue
            ticker = str(p["ticker"])
            quantity = int(p["quantity"])
            entry_price = float(p["entry_price"])
            entry_date = str(p["entry_date"])
            latest_close_point = latest_close_cache.get(ticker)
            if ticker not in latest_close_cache:
                latest_close_point = _load_latest_close_point(ticker)
                latest_close_cache[ticker] = latest_close_point

            latest_close = _latest_close_for_position(latest_close_point, entry_date)
            effective_price = latest_close if latest_close is not None else entry_price
            position_current_value = float(quantity * effective_price)
            holdings_value += position_current_value
            positions.append(
                PositionOut(
                    ticker=ticker,
                    quantity=quantity,
                    entry_price=entry_price,
                    entry_date=entry_date,
                    entry_score=float(p.get("entry_score", 0.0)),
                    peak_price=float(p.get("peak_price", p["entry_price"])),
                    lot_id=str(p.get("lot_id", "")),
                    current_price=latest_close,
                    current_value=position_current_value,
                )
            )

        initial_capital = float(g.get("initial_capital", 0.0))
        cash = float(g.get("cash", 0.0))
        net_cash_flow = float(cash_history.get_net_cash_flow(gid))
        total_capital = float(initial_capital + net_cash_flow)
        current_value = float(cash + holdings_value)
        total_pnl = float(current_value - total_capital)
        groups.append(
            StrategyGroupOut(
                id=gid,
                name=g.get("name", gid),
                initial_capital=initial_capital,
                cash=cash,
                net_cash_flow=net_cash_flow,
                total_capital=total_capital,
                holdings_value=holdings_value,
                current_value=current_value,
                total_pnl=total_pnl,
                total_pnl_pct=_calculate_total_pnl_pct(total_pnl, total_capital),
                positions=positions,
            )
        )

    return PortfolioResponse(
        groups=groups,
        last_updated=state_data.get("last_updated", ""),
    )


@router.get("/portfolio-history", response_model=PortfolioHistoryResponse)
def get_portfolio_history() -> PortfolioHistoryResponse:
    cfg = get_production_config()
    state_data = _load_state_data(cfg.state_file)
    group_items = _normalize_group_items(state_data.get("strategy_groups", []))
    base_state = _build_base_state(state_data, cfg.state_file)

    trade_history = TradeHistoryManager(cfg.history_file)
    active_trades = list(trade_history.get_active_trades())
    cash_history = CashHistoryManager(cfg.cash_history_file)
    cash_events = list(cash_history.events)

    relevant_tickers = _collect_relevant_tickers(group_items, active_trades)
    price_series_by_ticker: dict[str, CloseSeries] = {}
    for ticker in relevant_tickers:
        close_series = _load_close_series(ticker)
        if close_series is not None:
            price_series_by_ticker[ticker] = close_series

    anchor_dates = _collect_anchor_dates(group_items, active_trades, cash_events)
    history_dates = _collect_history_dates(price_series_by_ticker, anchor_dates)
    if not history_dates:
        current_portfolio = get_portfolio()
        fallback_date = str(current_portfolio.last_updated)[:10]
        total_capital = float(sum(group.total_capital for group in current_portfolio.groups))
        current_value = float(sum(group.current_value for group in current_portfolio.groups))
        total_pnl = float(current_value - total_capital)
        if not fallback_date:
            return PortfolioHistoryResponse(points=[])
        return PortfolioHistoryResponse(
            points=_enrich_portfolio_history_points(
                [
                    PortfolioHistoryPoint(
                        date=fallback_date,
                        total_capital=total_capital,
                        current_value=current_value,
                        total_pnl=total_pnl,
                        total_pnl_pct=_calculate_total_pnl_pct(total_pnl, total_capital),
                    )
                ],
                cash_events,
            )
        )

    points: list[PortfolioHistoryPoint] = []
    for history_date in history_dates:
        snapshot = build_state_as_of(
            base_state=base_state,
            history_file=cfg.history_file,
            cash_history_file=cfg.cash_history_file,
            as_of_date=history_date,
        )
        current_prices = _build_current_prices_for_snapshot(
            snapshot,
            price_series_by_ticker,
            history_date,
        )
        current_value = float(snapshot.get_portfolio_status(current_prices)["total_value"])
        total_capital = float(
            sum(
                float(group.initial_capital) + _net_cash_flow_as_of(cash_events, group.id, history_date)
                for group in snapshot.get_all_groups()
            )
        )
        total_pnl = float(current_value - total_capital)
        points.append(
            PortfolioHistoryPoint(
                date=history_date,
                total_capital=total_capital,
                current_value=current_value,
                total_pnl=total_pnl,
                total_pnl_pct=_calculate_total_pnl_pct(total_pnl, total_capital),
            )
        )

    return PortfolioHistoryResponse(
        points=_enrich_portfolio_history_points(points, cash_events)
    )


@router.get("/sector-attribution", response_model=SectorAttributionResponse)
def get_sector_attribution() -> SectorAttributionResponse:
    cfg = get_production_config()
    state_data = _load_state_data(cfg.state_file)
    group_items = _normalize_group_items(state_data.get("strategy_groups", []))
    base_state = _build_base_state(state_data, cfg.state_file)

    trade_history = TradeHistoryManager(cfg.history_file)
    active_trades = list(trade_history.get_active_trades())
    cash_history = CashHistoryManager(cfg.cash_history_file)
    cash_events = list(cash_history.events)
    sector_by_ticker = _load_sector_by_ticker()

    relevant_tickers = _collect_relevant_tickers(group_items, active_trades)
    price_series_by_ticker: dict[str, CloseSeries] = {}
    for ticker in relevant_tickers:
        close_series = _load_close_series(ticker)
        if close_series is not None:
            price_series_by_ticker[ticker] = close_series

    anchor_dates = _collect_anchor_dates(group_items, active_trades, cash_events)
    history_dates = _collect_history_dates(price_series_by_ticker, anchor_dates)
    if not history_dates:
        return SectorAttributionResponse(
            as_of_date="",
            summary_periods=[],
            heatmap_periods=[],
            sectors=[],
        )

    end_date = history_dates[-1]
    snapshot_cache: dict[str, tuple[ProductionState, dict[str, float]]] = {}

    def get_snapshot_bundle(target_date: str) -> tuple[ProductionState, dict[str, float]]:
        if target_date not in snapshot_cache:
            snapshot_cache[target_date] = _build_snapshot_for_date(
                base_state=base_state,
                history_file=cfg.history_file,
                cash_history_file=cfg.cash_history_file,
                price_series_by_ticker=price_series_by_ticker,
                target_date=target_date,
            )
        return snapshot_cache[target_date]

    end_snapshot, end_prices = get_snapshot_bundle(end_date)
    current_values = _build_sector_holdings_value(
        end_snapshot,
        end_prices,
        sector_by_ticker,
    )

    summary_payload_by_sector: dict[str, list[SectorPeriodPnLOut]] = {}
    summary_periods_payload: list[SectorPeriodOut] = []
    for definition in SUMMARY_PERIOD_DEFINITIONS:
        start_date = _resolve_period_start_date(history_dates, end_date, definition)
        start_snapshot, start_prices = get_snapshot_bundle(start_date)
        start_values = _build_sector_holdings_value(
            start_snapshot,
            start_prices,
            sector_by_ticker,
        )
        period_metrics = _build_sector_period_metrics(
            trades=active_trades,
            sector_by_ticker=sector_by_ticker,
            start_values=start_values,
            end_values=current_values,
            start_date=start_date,
            end_date=end_date,
        )
        summary_periods_payload.append(
            SectorPeriodOut(
                key=definition.key,
                label=definition.label,
                start_date=start_date,
                end_date=end_date,
            )
        )
        for sector, metric in period_metrics.items():
            summary_payload_by_sector.setdefault(sector, []).append(
                SectorPeriodPnLOut(
                    period_key=definition.key,
                    pnl=metric.pnl,
                    start_value=metric.start_value,
                    end_value=metric.end_value,
                    buy_amount=metric.buy_amount,
                    sell_amount=metric.sell_amount,
                )
            )

    heatmap_periods_payload = _build_year_month_heatmap_periods(end_date)
    heatmap_payload_by_sector: dict[str, list[SectorPeriodPnLOut]] = {}
    for period in heatmap_periods_payload:
        heatmap_window = _resolve_heatmap_window_dates(
            history_dates,
            period.start_date,
            period.end_date,
            end_date,
        )
        if heatmap_window is None:
            continue

        period_start_date, period_end_date = heatmap_window
        start_snapshot, start_prices = get_snapshot_bundle(period_start_date)
        start_values = _build_sector_holdings_value(
            start_snapshot,
            start_prices,
            sector_by_ticker,
        )
        period_end_snapshot, period_end_prices = get_snapshot_bundle(period_end_date)
        period_end_values = _build_sector_holdings_value(
            period_end_snapshot,
            period_end_prices,
            sector_by_ticker,
        )
        period_metrics = _build_sector_period_metrics(
            trades=active_trades,
            sector_by_ticker=sector_by_ticker,
            start_values=start_values,
            end_values=period_end_values,
            start_date=period_start_date,
            end_date=period_end_date,
        )
        for sector, metric in period_metrics.items():
            heatmap_payload_by_sector.setdefault(sector, []).append(
                SectorPeriodPnLOut(
                    period_key=period.key,
                    pnl=metric.pnl,
                    start_value=metric.start_value,
                    end_value=metric.end_value,
                    buy_amount=metric.buy_amount,
                    sell_amount=metric.sell_amount,
                )
            )

    sector_names = (
        set(current_values)
        | set(summary_payload_by_sector)
        | set(heatmap_payload_by_sector)
    )

    sectors = [
        SectorAttributionOut(
            sector=sector,
            current_value=float(current_values.get(sector, 0.0)),
            summary_periods=summary_payload_by_sector.get(sector, []),
            heatmap_periods=heatmap_payload_by_sector.get(sector, []),
        )
        for sector in sector_names
        if float(current_values.get(sector, 0.0)) != 0.0
        or any(metric.pnl != 0.0 for metric in summary_payload_by_sector.get(sector, []))
        or any(metric.pnl != 0.0 for metric in heatmap_payload_by_sector.get(sector, []))
    ]
    sectors.sort(key=lambda item: (-abs(item.current_value), item.sector))

    return SectorAttributionResponse(
        as_of_date=end_date,
        summary_periods=summary_periods_payload,
        heatmap_periods=heatmap_periods_payload,
        sectors=sectors,
    )


@router.get("/trade-history")
def get_trade_history() -> dict[str, object]:
    cfg = get_production_config()
    data = _load_json(cfg.history_file)
    return _enrich_trade_history_payload(data)


@router.get("/cash-history")
def get_cash_history() -> dict[str, object]:
    cfg = get_production_config()
    data = _load_json(cfg.cash_history_file)
    return data


@router.get("/signals")
def list_signals() -> list[str]:
    """List available signal dates."""
    cfg = get_production_config()
    pattern = cfg.signal_file_pattern
    signal_dir = Path(pattern).parent
    if not signal_dir.exists():
        return []
    dates = sorted(
        [f.stem for f in signal_dir.glob("*.json")],
        reverse=True,
    )
    return dates


@router.get("/signals/{date}")
def get_signals(date: str) -> list[dict[str, object]]:
    cfg = get_production_config()
    path = cfg.signal_file_pattern.replace("{date}", date)
    data = _load_json(path)
    if isinstance(data, list):
        return _enrich_signals_take_profit_preview(data, cfg)
    if isinstance(data, dict):
        return _enrich_signals_take_profit_preview(data.get("signals", []), cfg)
    return []


@router.get("/reports")
def list_reports() -> list[str]:
    """List available report dates."""
    cfg = get_production_config()
    pattern = cfg.report_file_pattern
    report_dir = Path(pattern).parent
    if not report_dir.exists():
        return []
    dates = sorted(
        [f.stem for f in report_dir.glob("*.md")],
        reverse=True,
    )
    return dates


@router.get("/reports/{date}")
def get_report(date: str) -> dict[str, str]:
    cfg = get_production_config()
    path = Path(cfg.report_file_pattern.replace("{date}", date))
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Report not found: {date}")
    content = path.read_text(encoding="utf-8")
    return {"date": date, "content": content}
