import logging
from dataclasses import asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .base import BaseOverlay, OverlayContext, OverlayDecision
from .regime_overlay import RegimeOverlay
from .sector_breadth_overlay import SectorBreadthOverlay


OVERLAY_REGISTRY = {
    "RegimeOverlay": RegimeOverlay,
    "SectorBreadthOverlay": SectorBreadthOverlay,
}


logger = logging.getLogger(__name__)


class OverlayManager:
    """Evaluate and merge overlay decisions."""

    def __init__(self, overlays: Optional[Iterable[BaseOverlay]] = None):
        self.overlays = sorted(
            [o for o in (overlays or []) if o.enabled],
            key=lambda o: o.priority,
        )

    @property
    def needs_benchmark_data(self) -> bool:
        return any(o.requires_benchmark_data for o in self.overlays)

    def evaluate(self, context: OverlayContext) -> Tuple[OverlayDecision, List[OverlayDecision]]:
        decisions: List[OverlayDecision] = []
        for overlay in self.overlays:
            decisions.append(overlay.evaluate(context))

        combined = self._merge_decisions(decisions)
        return combined, decisions

    def _merge_decisions(self, decisions: List[OverlayDecision]) -> OverlayDecision:
        combined = OverlayDecision(source="OverlayManager")
        if not decisions:
            return combined

        target_exposure = None
        position_scale = None
        max_new_positions = None
        exit_overrides: Dict[str, str] = {}

        for decision in decisions:
            if decision.target_exposure is not None:
                target_exposure = (
                    decision.target_exposure
                    if target_exposure is None
                    else min(target_exposure, decision.target_exposure)
                )
            if decision.position_scale is not None:
                position_scale = (
                    decision.position_scale
                    if position_scale is None
                    else min(position_scale, decision.position_scale)
                )
            if decision.max_new_positions is not None:
                max_new_positions = (
                    decision.max_new_positions
                    if max_new_positions is None
                    else min(max_new_positions, decision.max_new_positions)
                )
            if decision.exit_overrides:
                for ticker, reason in decision.exit_overrides.items():
                    if ticker not in exit_overrides:
                        exit_overrides[ticker] = reason

            combined.block_new_entries = (
                combined.block_new_entries or decision.block_new_entries
            )
            combined.force_exit = combined.force_exit or decision.force_exit

        combined.target_exposure = target_exposure
        combined.position_scale = position_scale
        combined.max_new_positions = max_new_positions
        combined.exit_overrides = exit_overrides
        combined.metadata = {
            d.source: d.metadata for d in decisions if d.metadata is not None
        }
        return combined

    @staticmethod
    def from_config(config: Dict[str, Any], data_root: str = "data") -> "OverlayManager":
        overlays_cfg = config.get("overlays", {}) if config else {}
        global_enabled = bool(overlays_cfg.get("enabled", False))

        if not global_enabled:
            return OverlayManager([])

        active = overlays_cfg.get("active", [])

        enabled = set(active if isinstance(active, list) else [])
        overlays: List[BaseOverlay] = []

        if "RegimeOverlay" in enabled:
            logger.warning(
                "RegimeOverlay is deprecated and kept for backward compatibility. "
                "Use SectorBreadthOverlay as the primary overlay."
            )

        for name in enabled:
            overlay_class = OVERLAY_REGISTRY.get(name)
            if overlay_class is None:
                continue
            overlay_cfg = overlays_cfg.get(name, {})
            overlays.append(overlay_class(config=overlay_cfg, data_root=data_root))

        return OverlayManager(overlays)

    @staticmethod
    def summarize(decision: OverlayDecision, per_overlay: List[OverlayDecision]) -> Dict[str, Any]:
        return {
            "combined": {
                "target_exposure": decision.target_exposure,
                "position_scale": decision.position_scale,
                "max_new_positions": decision.max_new_positions,
                "block_new_entries": decision.block_new_entries,
                "force_exit": decision.force_exit,
                "exit_overrides": decision.exit_overrides,
                "metadata": decision.metadata,
            },
            "overlays": [asdict(d) for d in per_overlay],
        }
