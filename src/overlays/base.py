from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import pandas as pd


@dataclass
class OverlayContext:
    """Common context passed to overlays."""

    current_date: pd.Timestamp
    portfolio_cash: float
    portfolio_value: float
    positions: Dict[str, Any]
    current_prices: Dict[str, float]
    benchmark_data: Optional[pd.DataFrame] = None
    group_id: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class OverlayDecision:
    """Unified overlay decision output."""

    source: str
    target_exposure: Optional[float] = None
    position_scale: Optional[float] = None
    max_new_positions: Optional[int] = None
    block_new_entries: bool = False
    force_exit: bool = False
    exit_overrides: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseOverlay:
    """Base class for all overlays."""

    name = "BaseOverlay"
    priority = 100
    requires_benchmark_data = False

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled", True))

    def evaluate(self, context: OverlayContext) -> OverlayDecision:
        raise NotImplementedError
