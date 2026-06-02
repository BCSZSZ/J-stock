from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Optional

import pandas as pd


def coerce_non_negative_int(value: object) -> int:
    if value is None:
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def count_positive_numeric_values(values: Iterable[object]) -> int:
    positive_count = 0
    for value in values:
        if value is None or pd.isna(value):
            continue
        try:
            if float(value) > 0:
                positive_count += 1
        except (TypeError, ValueError):
            continue
    return positive_count


def count_positive_rank_scores(signals: Iterable[object]) -> int:
    return count_positive_numeric_values(
        getattr(signal, "rank_score", None) for signal in signals
    )


def count_positive_priority_scores(
    ranked_signals: Iterable[tuple[Any, Any, object]],
) -> int:
    return count_positive_numeric_values(priority for _, _, priority in ranked_signals)


def resolve_tail_guard_rank_limit(
    tail_guard_config: Mapping[str, object] | None,
    positive_rank_score_count: int,
) -> Optional[int]:
    if not isinstance(tail_guard_config, Mapping):
        return None
    if not bool(tail_guard_config.get("enabled", False)):
        return None

    base_rank_limit = coerce_non_negative_int(tail_guard_config.get("max_rank"))
    effective_limit = max(base_rank_limit, max(int(positive_rank_score_count), 0))
    return effective_limit if effective_limit > 0 else None