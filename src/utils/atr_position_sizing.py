from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal, Mapping


PositionSizingMode = Literal["fixed", "atr"]


@dataclass(frozen=True)
class AtrPositionSizingConfig:
    risk_per_trade_pct: float = 0.006
    atr_stop_multiple: float = 2.0
    min_position_value_jpy: float = 0.0


@dataclass(frozen=True)
class PortfolioSizingConfig:
    mode: PositionSizingMode = "fixed"
    max_positions: int = 7
    max_position_pct: float = 0.18
    atr: AtrPositionSizingConfig = AtrPositionSizingConfig()

    @property
    def unlimited_positions(self) -> bool:
        return self.mode == "atr"


@dataclass(frozen=True)
class AtrSizingInput:
    ticker: str
    planning_price: float
    portfolio_value_jpy: float
    available_cash_jpy: float
    atr_jpy: float
    lot_size: int
    config: AtrPositionSizingConfig
    signal_scale: float = 1.0
    order_value_cap_jpy: float | None = None
    atr_ratio: float | None = None


@dataclass(frozen=True)
class AtrSizingResult:
    quantity: int
    required_capital_jpy: float
    target_position_value_jpy: float
    risk_amount_jpy: float
    per_share_risk_jpy: float
    atr_ratio: float | None
    blocking_reason: str | None

    @property
    def is_executable(self) -> bool:
        return self.quantity > 0 and self.blocking_reason is None

    def with_capital_limit(self, limit_jpy: float | None, lot_size: int, price: float) -> "AtrSizingResult":
        if limit_jpy is None:
            return self
        capped_value = min(self.target_position_value_jpy, max(float(limit_jpy), 0.0))
        if price <= 0 or lot_size <= 0 or capped_value <= 0:
            return replace(
                self,
                quantity=0,
                required_capital_jpy=0.0,
                target_position_value_jpy=capped_value,
                blocking_reason="order_cap_zero",
            )
        lots = int(capped_value // (price * lot_size))
        quantity = lots * lot_size
        required_capital = quantity * price
        return replace(
            self,
            quantity=quantity,
            required_capital_jpy=required_capital,
            target_position_value_jpy=capped_value,
            blocking_reason=None if quantity > 0 else "lot_size",
        )


def normalize_position_sizing_mode(value: object) -> PositionSizingMode:
    normalized = str(value or "fixed").strip().lower()
    if normalized in {"atr", "van_tharp", "van-tharp"}:
        return "atr"
    return "fixed"


def parse_atr_position_sizing_config(raw_config: object) -> AtrPositionSizingConfig:
    data = raw_config if isinstance(raw_config, Mapping) else {}
    return AtrPositionSizingConfig(
        risk_per_trade_pct=_read_float(data, "risk_per_trade_pct", 0.006),
        atr_stop_multiple=_read_float(data, "atr_stop_multiple", 2.0),
        min_position_value_jpy=_read_float(data, "min_position_value_jpy", 0.0),
    )


def parse_portfolio_sizing_config(
    portfolio_config: object,
    overrides: object | None = None,
) -> PortfolioSizingConfig:
    portfolio_data = portfolio_config if isinstance(portfolio_config, Mapping) else {}
    override_data = overrides if isinstance(overrides, Mapping) else {}

    mode = normalize_position_sizing_mode(
        override_data.get("position_sizing_mode", portfolio_data.get("position_sizing_mode", "fixed"))
    )
    max_positions = int(
        _read_float(override_data, "max_positions", _read_float(portfolio_data, "max_positions", 7.0))
    )
    max_position_pct = _read_float(
        override_data,
        "max_position_pct",
        _read_float(portfolio_data, "max_position_pct", 0.18),
    )

    atr_source: dict[str, object] = {}
    raw_portfolio_atr = portfolio_data.get("atr_position_sizing")
    if isinstance(raw_portfolio_atr, Mapping):
        atr_source.update(dict(raw_portfolio_atr))
    raw_override_atr = override_data.get("atr_position_sizing")
    if isinstance(raw_override_atr, Mapping):
        atr_source.update(dict(raw_override_atr))
    for key in ("risk_per_trade_pct", "atr_stop_multiple", "min_position_value_jpy"):
        if key in override_data:
            atr_source[key] = override_data[key]

    return PortfolioSizingConfig(
        mode=mode,
        max_positions=max_positions,
        max_position_pct=max_position_pct,
        atr=parse_atr_position_sizing_config(atr_source),
    )


def calculate_atr_position_size(sizing_input: AtrSizingInput) -> AtrSizingResult:
    price = float(sizing_input.planning_price)
    portfolio_value = float(sizing_input.portfolio_value_jpy)
    available_cash = max(float(sizing_input.available_cash_jpy), 0.0)
    atr = float(sizing_input.atr_jpy)
    lot_size = int(sizing_input.lot_size)
    signal_scale = max(float(sizing_input.signal_scale), 0.0)

    if price <= 0 or not math.isfinite(price):
        return _blocked("invalid_price", sizing_input, 0.0, 0.0, None)
    if lot_size <= 0:
        return _blocked("invalid_lot_size", sizing_input, 0.0, 0.0, None)
    if portfolio_value <= 0 or not math.isfinite(portfolio_value):
        return _blocked("invalid_portfolio_value", sizing_input, 0.0, 0.0, None)
    if atr <= 0 or not math.isfinite(atr):
        return _blocked("invalid_atr", sizing_input, 0.0, 0.0, _resolve_atr_ratio(atr, price, sizing_input.atr_ratio))
    if sizing_input.config.risk_per_trade_pct <= 0 or sizing_input.config.atr_stop_multiple <= 0:
        return _blocked("invalid_risk_config", sizing_input, 0.0, 0.0, _resolve_atr_ratio(atr, price, sizing_input.atr_ratio))
    if available_cash <= 0:
        return _blocked("cash", sizing_input, 0.0, atr * sizing_input.config.atr_stop_multiple, _resolve_atr_ratio(atr, price, sizing_input.atr_ratio))

    per_share_risk = atr * sizing_input.config.atr_stop_multiple
    risk_amount = portfolio_value * sizing_input.config.risk_per_trade_pct * signal_scale
    raw_quantity = risk_amount / per_share_risk
    target_position_value = max(raw_quantity * price, 0.0)

    if sizing_input.order_value_cap_jpy is not None:
        target_position_value = min(target_position_value, max(float(sizing_input.order_value_cap_jpy), 0.0))
    target_position_value = min(target_position_value, available_cash)

    if target_position_value <= 0:
        return _blocked("order_cap_zero", sizing_input, risk_amount, per_share_risk, _resolve_atr_ratio(atr, price, sizing_input.atr_ratio))

    lot_value = price * lot_size
    lots = int(target_position_value // lot_value)
    quantity = lots * lot_size
    required_capital = quantity * price
    atr_ratio = _resolve_atr_ratio(atr, price, sizing_input.atr_ratio)

    if quantity <= 0:
        return AtrSizingResult(
            quantity=0,
            required_capital_jpy=0.0,
            target_position_value_jpy=target_position_value,
            risk_amount_jpy=risk_amount,
            per_share_risk_jpy=per_share_risk,
            atr_ratio=atr_ratio,
            blocking_reason="lot_size",
        )
    if required_capital < sizing_input.config.min_position_value_jpy:
        return AtrSizingResult(
            quantity=0,
            required_capital_jpy=0.0,
            target_position_value_jpy=target_position_value,
            risk_amount_jpy=risk_amount,
            per_share_risk_jpy=per_share_risk,
            atr_ratio=atr_ratio,
            blocking_reason="min_position_value",
        )

    return AtrSizingResult(
        quantity=quantity,
        required_capital_jpy=required_capital,
        target_position_value_jpy=target_position_value,
        risk_amount_jpy=risk_amount,
        per_share_risk_jpy=per_share_risk,
        atr_ratio=atr_ratio,
        blocking_reason=None,
    )


def atr_sizing_metadata(
    result: AtrSizingResult,
    config: AtrPositionSizingConfig,
) -> dict[str, object]:
    return {
        "position_sizing_mode": "atr",
        "atr_risk_per_trade_pct": float(config.risk_per_trade_pct),
        "atr_stop_multiple": float(config.atr_stop_multiple),
        "atr_risk_amount_jpy": float(result.risk_amount_jpy),
        "atr_per_share_risk_jpy": float(result.per_share_risk_jpy),
        "atr_ratio": result.atr_ratio,
        "atr_sizing_target_value_jpy": float(result.target_position_value_jpy),
        "atr_sizing_blocking_reason": result.blocking_reason,
    }


def _read_float(data: Mapping[object, object], key: str, default: float) -> float:
    value = data.get(key, default)
    if value is None or isinstance(value, bool):
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _resolve_atr_ratio(atr: float, price: float, explicit_ratio: float | None) -> float | None:
    if explicit_ratio is not None and math.isfinite(float(explicit_ratio)) and float(explicit_ratio) > 0:
        return float(explicit_ratio)
    if price > 0 and atr > 0:
        return atr / price
    return None


def _blocked(
    reason: str,
    sizing_input: AtrSizingInput,
    risk_amount: float,
    per_share_risk: float,
    atr_ratio: float | None,
) -> AtrSizingResult:
    return AtrSizingResult(
        quantity=0,
        required_capital_jpy=0.0,
        target_position_value_jpy=0.0,
        risk_amount_jpy=risk_amount,
        per_share_risk_jpy=per_share_risk,
        atr_ratio=atr_ratio,
        blocking_reason=reason,
    )