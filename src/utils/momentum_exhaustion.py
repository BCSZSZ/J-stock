from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE = 4.0
DEFAULT_MOMENTUM_EXHAUSTION_METHOD = "absolute"
DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE = "shadow"
DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE = "enforce"

MOMENTUM_EXHAUSTION_MODES = {"off", "shadow", "enforce"}
MOMENTUM_EXHAUSTION_THRESHOLD_METHODS = {"absolute"}


class MomentumThresholdProvider(Protocol):
    """Extension point for future dynamic momentum thresholds."""

    @property
    def method(self) -> str:
        ...

    def threshold_for(self, rank_score: float) -> float | None:
        ...


@dataclass(frozen=True)
class AbsoluteMomentumThresholdProvider:
    max_score: float = DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE

    @property
    def method(self) -> str:
        return DEFAULT_MOMENTUM_EXHAUSTION_METHOD

    def threshold_for(self, rank_score: float) -> float | None:
        return float(self.max_score)


@dataclass(frozen=True)
class MomentumExhaustionConfig:
    mode: str = "off"
    threshold_method: str = DEFAULT_MOMENTUM_EXHAUSTION_METHOD
    max_score: float = DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE

    @property
    def enabled(self) -> bool:
        return self.mode != "off"


@dataclass(frozen=True)
class MomentumExhaustionDecision:
    mode: str
    threshold_method: str
    max_score: float
    rank_score: float | None
    threshold: float | None
    blocked: bool
    filtered: bool
    reason: str | None = None

    @property
    def shadowed(self) -> bool:
        return self.blocked and self.mode == "shadow"

    def to_metadata(self) -> dict[str, object]:
        return {
            "momentum_exhaustion_mode": self.mode,
            "momentum_exhaustion_threshold_method": self.threshold_method,
            "momentum_exhaustion_max_score": self.max_score,
            "momentum_exhaustion_score": self.rank_score,
            "momentum_exhaustion_threshold": self.threshold,
            "momentum_exhaustion_blocked": self.blocked,
            "momentum_exhaustion_filtered": self.filtered,
            "momentum_exhaustion_reason": self.reason,
        }


def _coerce_mode(value: object, default_mode: str) -> str:
    mode = str(value if value is not None else default_mode).strip().lower()
    if mode not in MOMENTUM_EXHAUSTION_MODES:
        raise ValueError(
            f"Unsupported momentum exhaustion mode: {value}. "
            "Expected off, shadow, or enforce."
        )
    return mode


def _coerce_threshold_method(value: object) -> str:
    method = str(value or DEFAULT_MOMENTUM_EXHAUSTION_METHOD).strip().lower()
    if method not in MOMENTUM_EXHAUSTION_THRESHOLD_METHODS:
        raise ValueError(
            f"Unsupported momentum exhaustion threshold method: {value}. "
            "Only absolute is supported in this release."
        )
    return method


def _coerce_max_score(value: object) -> float:
    try:
        parsed = float(
            DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE
            if value is None
            else value
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("momentum exhaustion max_score must be numeric") from exc
    return parsed


def _coerce_rank_score(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_momentum_exhaustion_config(
    raw_config: Mapping[str, object] | None,
    *,
    default_mode: str,
    mode_override: str | None = None,
    max_score_override: float | None = None,
    threshold_method_override: str | None = None,
    use_configured_mode: bool = True,
) -> MomentumExhaustionConfig:
    raw = dict(raw_config or {})
    enabled = raw.get("enabled") if use_configured_mode else None
    configured_mode = raw.get("mode") if use_configured_mode else None
    if configured_mode is None and enabled is False:
        configured_mode = "off"

    mode = _coerce_mode(
        mode_override if mode_override is not None else configured_mode,
        default_mode,
    )
    threshold_method = _coerce_threshold_method(
        threshold_method_override
        if threshold_method_override is not None
        else raw.get("threshold_method")
    )
    max_score = _coerce_max_score(
        max_score_override
        if max_score_override is not None
        else raw.get("max_score")
    )
    return MomentumExhaustionConfig(
        mode=mode,
        threshold_method=threshold_method,
        max_score=max_score,
    )


def resolve_momentum_exhaustion_config(
    root_config: Mapping[str, object] | None,
    *,
    default_mode: str,
    mode_override: str | None = None,
    max_score_override: float | None = None,
    threshold_method_override: str | None = None,
    use_configured_mode: bool = True,
) -> MomentumExhaustionConfig:
    production_cfg = {}
    if isinstance(root_config, Mapping):
        production_raw = root_config.get("production", {})
        if isinstance(production_raw, Mapping):
            production_cfg = production_raw
    raw_filter = production_cfg.get("momentum_exhaustion_filter", {})
    if not isinstance(raw_filter, Mapping):
        raw_filter = {}
    return normalize_momentum_exhaustion_config(
        raw_filter,
        default_mode=default_mode,
        mode_override=mode_override,
        max_score_override=max_score_override,
        threshold_method_override=threshold_method_override,
        use_configured_mode=use_configured_mode,
    )


def build_threshold_provider(
    config: MomentumExhaustionConfig,
) -> MomentumThresholdProvider:
    if config.threshold_method == DEFAULT_MOMENTUM_EXHAUSTION_METHOD:
        return AbsoluteMomentumThresholdProvider(max_score=config.max_score)
    raise ValueError(
        f"Unsupported momentum exhaustion threshold method: {config.threshold_method}"
    )


def evaluate_momentum_exhaustion(
    rank_score: object,
    config: MomentumExhaustionConfig | Mapping[str, object] | None,
) -> MomentumExhaustionDecision:
    if isinstance(config, MomentumExhaustionConfig):
        normalized = config
    else:
        normalized = normalize_momentum_exhaustion_config(
            config,
            default_mode="off",
        )

    parsed_score = _coerce_rank_score(rank_score)
    provider = build_threshold_provider(normalized)
    threshold = (
        provider.threshold_for(parsed_score)
        if parsed_score is not None and normalized.enabled
        else None
    )
    blocked = bool(
        normalized.enabled
        and parsed_score is not None
        and threshold is not None
        and parsed_score > threshold
    )
    filtered = bool(blocked and normalized.mode == "enforce")
    reason = None
    if blocked:
        verb = "Filtered" if filtered else "Shadow blocked"
        reason = (
            f"{verb}: momentum exhaustion rank_score "
            f"{parsed_score:.4f} > {threshold:.4f}"
        )

    return MomentumExhaustionDecision(
        mode=normalized.mode,
        threshold_method=provider.method,
        max_score=float(normalized.max_score),
        rank_score=parsed_score,
        threshold=threshold,
        blocked=blocked,
        filtered=filtered,
        reason=reason,
    )
