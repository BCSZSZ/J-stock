"""State endpoints: portfolio, trade history, signals, reports."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import json
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from src.production import CashHistoryManager, ProductionState, StrategyGroupState, TradeHistoryManager
from src.production.state_manager import CashFlowEvent, Trade, build_state_as_of
from web.api.dependencies import get_production_config, get_project_root
from web.api.schemas import PortfolioHistoryPoint, PortfolioHistoryResponse, PortfolioResponse, StrategyGroupOut, PositionOut

router = APIRouter(prefix="/api/state", tags=["state"])


@dataclass(frozen=True)
class CloseSeries:
    dates: tuple[str, ...]
    closes: tuple[float, ...]


def _load_json(path: str | Path) -> object:
    p = Path(path)
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p.name}")
    return json.loads(p.read_text(encoding="utf-8"))


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


def _load_close_series(ticker: str) -> CloseSeries | None:
    path = _features_path(ticker)
    if not path.exists():
        return None

    try:
        df = pd.read_parquet(path)
    except Exception:
        return None

    if df.empty or "Close" not in df.columns:
        return None

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


def _load_latest_close(ticker: str) -> float | None:
    close_series = _load_close_series(ticker)
    if close_series is None or not close_series.closes:
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
        return float(latest_close)
    return close_series.closes[-1]


def _lookup_close_on_or_before(
    close_series: CloseSeries | None,
    target_date: str,
) -> float | None:
    if close_series is None or not close_series.dates:
        return None

    target_index = bisect_right(close_series.dates, target_date) - 1
    if target_index < 0:
        return None
    return close_series.closes[target_index]


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
            resolved_price = _lookup_close_on_or_before(
                price_series_by_ticker.get(position.ticker),
                target_date,
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

    latest_close = df["Close"].iloc[-1]
    if pd.isna(latest_close):
        return None
    return float(latest_close)


@router.get("/portfolio", response_model=PortfolioResponse)
def get_portfolio() -> PortfolioResponse:
    cfg = get_production_config()
    state_data = _load_state_data(cfg.state_file)
    cash_history = CashHistoryManager(cfg.cash_history_file)
    latest_close_cache: dict[str, float | None] = {}

    groups: list[StrategyGroupOut] = []
    group_items = _normalize_group_items(state_data.get("strategy_groups", []))
    for gid, g in group_items:
        positions: list[PositionOut] = []
        holdings_value = 0.0
        for p in g.get("positions", []):
            if not isinstance(p, dict):
                continue
            ticker = str(p["ticker"])
            latest_close = latest_close_cache.get(ticker)
            if ticker not in latest_close_cache:
                latest_close = _load_latest_close(ticker)
                latest_close_cache[ticker] = latest_close

            quantity = int(p["quantity"])
            entry_price = float(p["entry_price"])
            effective_price = latest_close if latest_close is not None else entry_price
            position_current_value = float(quantity * effective_price)
            holdings_value += position_current_value
            positions.append(
                PositionOut(
                    ticker=ticker,
                    quantity=quantity,
                    entry_price=entry_price,
                    entry_date=str(p["entry_date"]),
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
            points=[
                PortfolioHistoryPoint(
                    date=fallback_date,
                    total_capital=total_capital,
                    current_value=current_value,
                    total_pnl=total_pnl,
                    total_pnl_pct=_calculate_total_pnl_pct(total_pnl, total_capital),
                )
            ]
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

    return PortfolioHistoryResponse(points=points)


@router.get("/trade-history")
def get_trade_history() -> dict[str, object]:
    cfg = get_production_config()
    data = _load_json(cfg.history_file)
    return data


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
        return data
    return data.get("signals", [])


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
