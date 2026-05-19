from __future__ import annotations

RAW_FILL_ENTRY_REFERENCE = "raw_fill"
BUFFERED_FILL_ENTRY_REFERENCE = "buffered_fill"
VALID_ENTRY_REFERENCE_MODES = {
    RAW_FILL_ENTRY_REFERENCE,
    BUFFERED_FILL_ENTRY_REFERENCE,
}


def normalize_entry_reference_mode(entry_reference_mode: str | None) -> str:
    normalized = str(entry_reference_mode or RAW_FILL_ENTRY_REFERENCE).strip().lower()
    if normalized not in VALID_ENTRY_REFERENCE_MODES:
        expected = ", ".join(sorted(VALID_ENTRY_REFERENCE_MODES))
        raise ValueError(
            f"Unsupported entry_reference_mode: {entry_reference_mode}. Expected one of: {expected}."
        )
    return normalized


def resolve_signal_entry_price(
    raw_fill_price: float,
    executed_fill_price: float,
    entry_reference_mode: str | None,
) -> float:
    normalized_mode = normalize_entry_reference_mode(entry_reference_mode)
    if normalized_mode == BUFFERED_FILL_ENTRY_REFERENCE:
        return float(executed_fill_price)
    return float(raw_fill_price)