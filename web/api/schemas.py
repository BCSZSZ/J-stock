"""Pydantic response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str


class PositionOut(BaseModel):
    ticker: str
    quantity: int
    entry_price: float
    entry_date: str
    entry_score: float
    peak_price: float
    lot_id: str
    current_price: float | None = None
    current_value: float | None = None


class StrategyGroupOut(BaseModel):
    id: str
    name: str
    initial_capital: float
    cash: float
    net_cash_flow: float = 0.0
    total_capital: float = 0.0
    holdings_value: float = 0.0
    current_value: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float = 0.0
    positions: list[PositionOut]


class PortfolioResponse(BaseModel):
    groups: list[StrategyGroupOut]
    last_updated: str


class PortfolioHistoryPoint(BaseModel):
    date: str
    total_capital: float
    current_value: float
    total_pnl: float
    total_pnl_pct: float
    topix_value: float | None = None
    nikkei225_value: float | None = None
    normalized_portfolio: float | None = None
    normalized_topix: float | None = None
    normalized_nikkei225: float | None = None


class PortfolioHistoryResponse(BaseModel):
    points: list[PortfolioHistoryPoint]


class TradeEvent(BaseModel):
    date: str
    ticker: str
    action: str
    quantity: int
    price: float
    reason: str | None = None


class SignalOut(BaseModel):
    group_id: str
    ticker: str
    signal_type: str
    action: str
    confidence: float
    score: float
    reason: str | None = None
    current_price: float | None = None
    strategy_name: str | None = None


class StrategyInfo(BaseModel):
    name: str
    type: str
    category: str
    description: str
    parameters: list[dict[str, str]]


class EvaluationRunRequest(BaseModel):
    entry_strategies: list[str]
    exit_strategies: list[str]
    mode: str = "annual"
    years: list[int] | None = None
    ranking_mode: str = "target20"
    enable_overlay: bool = False
    entry_filter_mode: str = "off"


class ProductionDailyRequest(BaseModel):
    no_fetch: bool = False
    confirm: bool = False


class SetCashRequest(BaseModel):
    group_id: str = "group_main"
    amount: float
    confirm: bool = False


class InputTradeRequest(BaseModel):
    trades: list[TradeEvent]
    confirm: bool = False
    aws_profile: str | None = None
