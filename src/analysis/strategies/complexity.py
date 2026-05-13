"""Shared strategy complexity metadata for scoring and reporting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyComplexity:
    """Explicit complexity metadata for one strategy implementation."""

    numeric_param_count: int = 0
    extra_filter_count: int = 0
    conditional_rule_count: int = 0

    def penalty_points(self) -> float:
        penalty = (
            0.5 * float(self.numeric_param_count)
            + 1.0 * float(self.extra_filter_count)
            + 1.0 * float(self.conditional_rule_count)
        )
        return min(5.0, penalty)
