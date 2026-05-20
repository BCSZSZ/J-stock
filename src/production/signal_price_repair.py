from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, Optional, Tuple

from src.production.reference_price import resolve_signal_entry_price
from src.production.state_manager import Position, ProductionState, Trade, TradeHistoryManager


ReferencePriceResolver = Callable[[str, str, str | None], float | None]
LegacyEffectKey = Tuple[str, str, str, float]


@dataclass(frozen=True)
class SignalPriceRepairRecord:
    group_id: str
    ticker: str
    lot_id: str
    entry_date: str
    entry_price: float
    resolved_open_price: float | None
    signal_entry_price_before: float | None
    signal_entry_price_after: float | None
    peak_price_before: float
    peak_price_after: float
    action: str
    reason: str
    trade_event_id: str | None = None


@dataclass
class SignalPriceRepairSummary:
    scope: str
    target_date: str | None = None
    scanned_lots: int = 0
    candidate_lots: int = 0
    repaired_lots: int = 0
    skipped_lots: int = 0
    unresolved_reference_prices: int = 0
    ambiguous_history_matches: int = 0
    state_modified: bool = False
    history_modified: bool = False
    records: list[SignalPriceRepairRecord] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return self.state_modified or self.history_modified


def repair_signal_entry_prices(
    state: ProductionState,
    history: TradeHistoryManager,
    *,
    scope: str = "all",
    target_date: str | None = None,
    data_root: str | None = None,
    tolerance: float = 1e-6,
    reference_price_resolver: ReferencePriceResolver = resolve_signal_entry_price,
) -> SignalPriceRepairSummary:
    summary = SignalPriceRepairSummary(scope=scope, target_date=target_date)
    active_buy_effects_by_lot_id, active_buy_effects_by_legacy_key = _index_active_buy_effects(
        history,
        tolerance=tolerance,
    )

    for group in state.get_all_groups():
        for position in group.positions:
            if position.quantity <= 0:
                continue
            if scope == "today" and target_date and position.entry_date != target_date:
                continue

            summary.scanned_lots += 1
            match = _match_active_buy_effect(
                position=position,
                group_id=group.id,
                active_buy_effects_by_lot_id=active_buy_effects_by_lot_id,
                active_buy_effects_by_legacy_key=active_buy_effects_by_legacy_key,
                tolerance=tolerance,
            )
            if match is None:
                summary.ambiguous_history_matches += 1
                summary.skipped_lots += 1
                summary.records.append(
                    SignalPriceRepairRecord(
                        group_id=group.id,
                        ticker=position.ticker,
                        lot_id=position.lot_id,
                        entry_date=position.entry_date,
                        entry_price=float(position.entry_price),
                        resolved_open_price=None,
                        signal_entry_price_before=_coerce_optional_float(
                            position.signal_entry_price
                        ),
                        signal_entry_price_after=_coerce_optional_float(
                            position.signal_entry_price
                        ),
                        peak_price_before=float(position.peak_price),
                        peak_price_after=float(position.peak_price),
                        action="skipped",
                        reason="matching active BUY OPEN effect not found or ambiguous",
                    )
                )
                continue

            trade, effect = match
            position_signal_before = _coerce_optional_float(position.signal_entry_price)
            effect_signal_before = _coerce_optional_float(effect.get("signal_entry_price"))
            if not (_uses_fallback_anchor(position_signal_before, position.entry_price, tolerance) or _uses_fallback_anchor(effect_signal_before, effect.get("entry_price", position.entry_price), tolerance)):
                summary.skipped_lots += 1
                summary.records.append(
                    SignalPriceRepairRecord(
                        group_id=group.id,
                        ticker=position.ticker,
                        lot_id=position.lot_id,
                        entry_date=position.entry_date,
                        entry_price=float(position.entry_price),
                        resolved_open_price=None,
                        signal_entry_price_before=position_signal_before,
                        signal_entry_price_after=position_signal_before,
                        peak_price_before=float(position.peak_price),
                        peak_price_after=float(position.peak_price),
                        action="skipped",
                        reason="signal_entry_price already differs from entry_price",
                        trade_event_id=trade.event_id,
                    )
                )
                continue

            summary.candidate_lots += 1
            resolved_open_price = reference_price_resolver(
                position.ticker,
                position.entry_date,
                data_root,
            )
            if resolved_open_price is None:
                summary.unresolved_reference_prices += 1
                summary.skipped_lots += 1
                summary.records.append(
                    SignalPriceRepairRecord(
                        group_id=group.id,
                        ticker=position.ticker,
                        lot_id=position.lot_id,
                        entry_date=position.entry_date,
                        entry_price=float(position.entry_price),
                        resolved_open_price=None,
                        signal_entry_price_before=position_signal_before,
                        signal_entry_price_after=position_signal_before,
                        peak_price_before=float(position.peak_price),
                        peak_price_after=float(position.peak_price),
                        action="skipped",
                        reason="reference open price not available",
                        trade_event_id=trade.event_id,
                    )
                )
                continue

            resolved_open_price = float(resolved_open_price)
            if _floats_close(resolved_open_price, position.entry_price, tolerance):
                summary.skipped_lots += 1
                summary.records.append(
                    SignalPriceRepairRecord(
                        group_id=group.id,
                        ticker=position.ticker,
                        lot_id=position.lot_id,
                        entry_date=position.entry_date,
                        entry_price=float(position.entry_price),
                        resolved_open_price=resolved_open_price,
                        signal_entry_price_before=position_signal_before,
                        signal_entry_price_after=position_signal_before,
                        peak_price_before=float(position.peak_price),
                        peak_price_after=float(position.peak_price),
                        action="skipped",
                        reason="reference open price already matches entry_price",
                        trade_event_id=trade.event_id,
                    )
                )
                continue

            position_peak_before = float(position.peak_price)
            effect_peak_before = float(effect.get("peak_price", position_peak_before) or 0.0)
            position.peak_price = _repair_peak_anchor(
                peak_price=position.peak_price,
                entry_price=position.entry_price,
                signal_entry_price=position_signal_before,
                repaired_signal_entry_price=resolved_open_price,
                tolerance=tolerance,
            )
            effect["peak_price"] = _repair_peak_anchor(
                peak_price=effect_peak_before,
                entry_price=float(effect.get("entry_price", position.entry_price)),
                signal_entry_price=effect_signal_before,
                repaired_signal_entry_price=resolved_open_price,
                tolerance=tolerance,
            )
            position.signal_entry_price = resolved_open_price
            effect["signal_entry_price"] = resolved_open_price

            summary.repaired_lots += 1
            summary.state_modified = True
            summary.history_modified = True
            summary.records.append(
                SignalPriceRepairRecord(
                    group_id=group.id,
                    ticker=position.ticker,
                    lot_id=position.lot_id,
                    entry_date=position.entry_date,
                    entry_price=float(position.entry_price),
                    resolved_open_price=resolved_open_price,
                    signal_entry_price_before=position_signal_before,
                    signal_entry_price_after=resolved_open_price,
                    peak_price_before=position_peak_before,
                    peak_price_after=float(position.peak_price),
                    action="repaired",
                    reason="replaced fallback signal_entry_price with entry-date open price",
                    trade_event_id=trade.event_id,
                )
            )

    return summary


def format_signal_price_repair_summary(summary: SignalPriceRepairSummary) -> list[str]:
    scope_label = summary.scope
    if summary.scope == "today" and summary.target_date:
        scope_label = f"today ({summary.target_date})"

    lines = [
        "[Signal Price Repair]",
        f"  Scope: {scope_label}",
        f"  Scanned active lots: {summary.scanned_lots}",
        f"  Candidate lots: {summary.candidate_lots}",
        f"  Repaired lots: {summary.repaired_lots}",
        f"  Skipped lots: {summary.skipped_lots}",
        f"  Unresolved reference prices: {summary.unresolved_reference_prices}",
        f"  Ambiguous or missing BUY matches: {summary.ambiguous_history_matches}",
    ]

    repaired_records = [record for record in summary.records if record.action == "repaired"]
    if repaired_records:
        lines.append("  Repaired lots:")
        for record in repaired_records:
            lines.append(
                "    "
                f"{record.group_id} {record.ticker} {record.entry_date} "
                f"lot={record.lot_id or '-'} "
                f"signal {record.signal_entry_price_before} -> {record.signal_entry_price_after} "
                f"peak {record.peak_price_before} -> {record.peak_price_after}"
            )

    return lines


def _index_active_buy_effects(
    history: TradeHistoryManager,
    *,
    tolerance: float,
) -> tuple[
    Dict[str, list[tuple[Trade, dict]]],
    Dict[LegacyEffectKey, list[tuple[Trade, dict]]],
]:
    active_buy_effects_by_lot_id: Dict[str, list[tuple[Trade, dict]]] = {}
    active_buy_effects_by_legacy_key: Dict[LegacyEffectKey, list[tuple[Trade, dict]]] = {}

    for trade in history.get_active_trades():
        if (trade.action or "").upper() != "BUY":
            continue
        for effect in trade.position_effects or []:
            if effect.get("effect_type") != "OPEN":
                continue
            lot_id = str(effect.get("lot_id") or "").strip()
            if lot_id:
                active_buy_effects_by_lot_id.setdefault(lot_id, []).append((trade, effect))

            legacy_key = _build_legacy_effect_key(
                group_id=trade.group_id,
                ticker=str(effect.get("ticker") or trade.ticker),
                entry_date=str(effect.get("entry_date") or trade.date),
                entry_price=float(effect.get("entry_price", trade.price) or trade.price),
                tolerance=tolerance,
            )
            active_buy_effects_by_legacy_key.setdefault(legacy_key, []).append((trade, effect))

    return active_buy_effects_by_lot_id, active_buy_effects_by_legacy_key


def _match_active_buy_effect(
    *,
    position: Position,
    group_id: str,
    active_buy_effects_by_lot_id: Dict[str, list[tuple[Trade, dict]]],
    active_buy_effects_by_legacy_key: Dict[LegacyEffectKey, list[tuple[Trade, dict]]],
    tolerance: float,
) -> tuple[Trade, dict] | None:
    lot_id = str(position.lot_id or "").strip()
    if lot_id:
        matches = active_buy_effects_by_lot_id.get(lot_id, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None

    legacy_key = _build_legacy_effect_key(
        group_id=group_id,
        ticker=position.ticker,
        entry_date=position.entry_date,
        entry_price=float(position.entry_price),
        tolerance=tolerance,
    )
    matches = active_buy_effects_by_legacy_key.get(legacy_key, [])
    if len(matches) == 1:
        return matches[0]
    return None


def _build_legacy_effect_key(
    *,
    group_id: str,
    ticker: str,
    entry_date: str,
    entry_price: float,
    tolerance: float,
) -> LegacyEffectKey:
    normalized_price = round(float(entry_price) / max(tolerance, 1e-6)) * max(tolerance, 1e-6)
    return group_id, ticker, entry_date, float(normalized_price)


def _repair_peak_anchor(
    *,
    peak_price: float,
    entry_price: float,
    signal_entry_price: float | None,
    repaired_signal_entry_price: float,
    tolerance: float,
) -> float:
    if _floats_close(peak_price, entry_price, tolerance):
        return float(max(peak_price, repaired_signal_entry_price))
    if signal_entry_price is not None and _floats_close(peak_price, signal_entry_price, tolerance):
        return float(max(peak_price, repaired_signal_entry_price))
    return float(peak_price)


def _uses_fallback_anchor(
    signal_entry_price: float | None,
    entry_price: float,
    tolerance: float,
) -> bool:
    if signal_entry_price is None:
        return True
    return _floats_close(signal_entry_price, entry_price, tolerance)


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _floats_close(left: float | None, right: float | None, tolerance: float) -> bool:
    if left is None or right is None:
        return left is right
    return abs(float(left) - float(right)) <= tolerance