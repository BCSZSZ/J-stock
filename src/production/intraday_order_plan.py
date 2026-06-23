from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

from src.analysis.strategies.exit.locked_atr_stop import calculate_locked_atr_stop
from src.analysis.strategies.exit.multiview_grid_exit import parse_mvx_exit_strategy_name

DEFAULT_TP1_R = 1.0
DEFAULT_TP2_R = 2.0
DEFAULT_STOP_LIMIT_ATR_BUFFER = 0.15


@dataclass(frozen=True)
class IntradaySignalPlanCandidate:
    ticker: str
    group_id: str
    ticker_name: str | None
    industry_name: str | None
    suggested_quantity: int
    default_entry_price: float | None
    reference_price: float | None
    atr_value: float | None
    exit_strategy: str | None
    r_multiple: float | None
    trail_multiple: float | None
    initial_stop_multiple: float | None
    rank: int | None
    rank_score: float | None
    reason: str | None
    can_plan: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class IntradayOrderPlanInput:
    ticker: str
    quantity: int
    actual_entry_price: float
    atr_value: float
    r_multiple: float
    trail_multiple: float
    initial_stop_multiple: float
    high_since_buy: float | None = None
    tp1_r: float = DEFAULT_TP1_R
    tp2_r: float = DEFAULT_TP2_R
    stop_limit_atr_buffer: float = DEFAULT_STOP_LIMIT_ATR_BUFFER


@dataclass(frozen=True)
class IntradayOrderPlan:
    ticker: str
    quantity: int
    actual_entry_price: float
    high_since_buy: float
    atr_value: float
    r_multiple: float
    r_value: float
    tp1_r: float
    tp2_r: float
    tp1_price: float
    tp2_price: float
    tp1_gain_pct: float
    tp2_gain_pct: float
    tp1_quantity: int
    remaining_quantity_after_tp1: int
    initial_stop_multiple: float
    trail_multiple: float
    initial_stop_price: float
    dynamic_trail_price: float
    stop_trigger_price: float
    stop_limit_price: float
    stop_loss_pct: float
    stop_limit_loss_pct: float
    stop_limit_atr_buffer: float
    stop_limit_buffer_jpy: float
    formula_basis: str


def build_intraday_signal_candidate(
    signal: Mapping[str, object],
    *,
    exit_strategy_by_group: Mapping[str, str],
    default_exit_strategy: str | None,
) -> IntradaySignalPlanCandidate | None:
    if not _is_executable_buy_signal(signal):
        return None

    ticker = str(signal.get("ticker") or "").strip()
    if not ticker:
        return None

    metadata = _mapping_or_empty(signal.get("signal_metadata"))
    group_id = str(signal.get("group_id") or "").strip()
    reference_price = _first_positive_float(
        signal.get("close_price"),
        metadata.get("close"),
        signal.get("current_price"),
        signal.get("planned_price"),
    )
    default_entry_price = _first_positive_float(
        signal.get("planned_price"),
        signal.get("current_price"),
        reference_price,
    )
    atr_value = _extract_atr_value(signal, reference_price=reference_price)
    exit_strategy = _resolve_exit_strategy_name(
        signal,
        exit_strategy_by_group=exit_strategy_by_group,
        default_exit_strategy=default_exit_strategy,
    )
    r_multiple, trail_multiple, initial_stop_multiple = _resolve_mvx_plan_params(
        exit_strategy
    )
    warnings: list[str] = []
    blocking_warnings: list[str] = []
    if default_entry_price is None:
        warnings.append("default entry price unavailable")
    if atr_value is None:
        blocking_warnings.append("ATR unavailable")
    if exit_strategy is None:
        blocking_warnings.append("exit strategy unavailable")
    elif r_multiple is None or trail_multiple is None or initial_stop_multiple is None:
        blocking_warnings.append(f"unsupported exit strategy: {exit_strategy}")
    warnings.extend(blocking_warnings)

    return IntradaySignalPlanCandidate(
        ticker=ticker,
        group_id=group_id,
        ticker_name=_clean_optional_text(signal.get("ticker_name")),
        industry_name=_clean_optional_text(signal.get("industry_name")),
        suggested_quantity=_positive_int(signal.get("suggested_qty")) or 0,
        default_entry_price=default_entry_price,
        reference_price=reference_price,
        atr_value=atr_value,
        exit_strategy=exit_strategy,
        r_multiple=r_multiple,
        trail_multiple=trail_multiple,
        initial_stop_multiple=initial_stop_multiple,
        rank=_positive_int(signal.get("momentum_rank") or signal.get("rank")),
        rank_score=_finite_float_or_none(
            signal.get("momentum_value") or signal.get("rank_score")
        ),
        reason=_clean_optional_text(signal.get("reason")),
        can_plan=not blocking_warnings,
        warnings=tuple(warnings),
    )


def build_intraday_order_plan(request: IntradayOrderPlanInput) -> IntradayOrderPlan:
    quantity = _require_positive_int("quantity", request.quantity)
    actual_entry_price = _require_positive_float(
        "actual_entry_price", request.actual_entry_price
    )
    atr_value = _require_positive_float("atr_value", request.atr_value)
    r_multiple = _require_positive_float("r_multiple", request.r_multiple)
    trail_multiple = _require_positive_float("trail_multiple", request.trail_multiple)
    initial_stop_multiple = _require_positive_float(
        "initial_stop_multiple", request.initial_stop_multiple
    )
    tp1_r = _require_positive_float("tp1_r", request.tp1_r)
    tp2_r = _require_positive_float("tp2_r", request.tp2_r)
    stop_limit_atr_buffer = _require_positive_float(
        "stop_limit_atr_buffer", request.stop_limit_atr_buffer
    )
    high_since_buy = (
        _finite_float_or_none(request.high_since_buy) or actual_entry_price
    )
    high_since_buy = max(high_since_buy, actual_entry_price)

    r_value = r_multiple * atr_value
    tp1_price = actual_entry_price + (tp1_r * r_value)
    tp2_price = actual_entry_price + (tp2_r * r_value)
    stop = calculate_locked_atr_stop(
        entry_price=actual_entry_price,
        peak_price=high_since_buy,
        entry_atr=atr_value,
        current_atr=atr_value,
        initial_stop_multiple=initial_stop_multiple,
        trail_multiple=trail_multiple,
    )
    stop_limit_buffer_jpy = stop_limit_atr_buffer * atr_value
    stop_limit_price = max(1.0, stop.effective_stop_price - stop_limit_buffer_jpy)
    tp1_quantity = max(1, int(quantity * 0.5))
    remaining_quantity_after_tp1 = max(0, quantity - tp1_quantity)

    return IntradayOrderPlan(
        ticker=request.ticker,
        quantity=quantity,
        actual_entry_price=_round_price(actual_entry_price),
        high_since_buy=_round_price(high_since_buy),
        atr_value=_round_price(atr_value),
        r_multiple=r_multiple,
        r_value=_round_price(r_value),
        tp1_r=tp1_r,
        tp2_r=tp2_r,
        tp1_price=_round_price(tp1_price),
        tp2_price=_round_price(tp2_price),
        tp1_gain_pct=((tp1_price - actual_entry_price) / actual_entry_price) * 100.0,
        tp2_gain_pct=((tp2_price - actual_entry_price) / actual_entry_price) * 100.0,
        tp1_quantity=tp1_quantity,
        remaining_quantity_after_tp1=remaining_quantity_after_tp1,
        initial_stop_multiple=initial_stop_multiple,
        trail_multiple=trail_multiple,
        initial_stop_price=_round_price(stop.initial_stop_price),
        dynamic_trail_price=_round_price(stop.dynamic_trail_price),
        stop_trigger_price=_round_price(stop.effective_stop_price),
        stop_limit_price=_round_price(stop_limit_price),
        stop_loss_pct=(
            (stop.effective_stop_price - actual_entry_price) / actual_entry_price
        )
        * 100.0,
        stop_limit_loss_pct=((stop_limit_price - actual_entry_price) / actual_entry_price)
        * 100.0,
        stop_limit_atr_buffer=stop_limit_atr_buffer,
        stop_limit_buffer_jpy=_round_price(stop_limit_buffer_jpy),
        formula_basis=(
            "R = r_mult * ATR; TP1/TP2 = actual_fill + R multiples; "
            "R1 = max(actual_fill - I*ATR, high_since_buy - T*ATR); "
            "stop limit = R1 trigger - buffer*ATR"
        ),
    )


def _is_executable_buy_signal(signal: Mapping[str, object]) -> bool:
    if str(signal.get("signal_type") or "").upper() != "BUY":
        return False
    executable_buy = signal.get("is_executable_buy")
    if isinstance(executable_buy, bool):
        return executable_buy
    return (_positive_int(signal.get("suggested_qty")) or 0) > 0


def _resolve_exit_strategy_name(
    signal: Mapping[str, object],
    *,
    exit_strategy_by_group: Mapping[str, str],
    default_exit_strategy: str | None,
) -> str | None:
    metadata = _mapping_or_empty(signal.get("signal_metadata"))
    bound_exit_strategy = str(metadata.get("bound_exit_strategy_name") or "").strip()
    if bound_exit_strategy:
        return bound_exit_strategy
    group_id = str(signal.get("group_id") or "").strip()
    group_exit_strategy = exit_strategy_by_group.get(group_id)
    if group_exit_strategy:
        return group_exit_strategy
    fallback = str(default_exit_strategy or "").strip()
    return fallback or None


def _resolve_mvx_plan_params(
    exit_strategy: str | None,
) -> tuple[float | None, float | None, float | None]:
    if not exit_strategy:
        return None, None, None
    spec = parse_mvx_exit_strategy_name(exit_strategy)
    if spec is None:
        return None, None, None
    initial_stop_multiple = spec.i if spec.i is not None else spec.t
    return spec.r, spec.t, initial_stop_multiple


def _extract_atr_value(
    signal: Mapping[str, object],
    *,
    reference_price: float | None,
) -> float | None:
    metadata = _mapping_or_empty(signal.get("signal_metadata"))
    atr_value = _first_positive_float(metadata.get("ATR"), metadata.get("atr_jpy"))
    if atr_value is not None:
        return atr_value

    atr_ratio = _first_positive_float(
        metadata.get("ATR_Ratio"),
        metadata.get("atr_ratio"),
    )
    if atr_ratio is not None and reference_price is not None:
        return atr_ratio * reference_price
    return None


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _first_positive_float(*values: object) -> float | None:
    for value in values:
        parsed = _finite_float_or_none(value)
        if parsed is not None and parsed > 0:
            return parsed
    return None


def _finite_float_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_int(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _clean_optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _require_positive_float(name: str, value: object) -> float:
    parsed = _finite_float_or_none(value)
    if parsed is None or parsed <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return parsed


def _require_positive_int(name: str, value: object) -> int:
    parsed = _positive_int(value)
    if parsed is None:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _round_price(value: float) -> float:
    return round(max(float(value), 1.0), 2)
