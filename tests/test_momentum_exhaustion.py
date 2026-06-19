from __future__ import annotations

from src.utils.momentum_exhaustion import (
    DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE,
    DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE,
    MomentumExhaustionConfig,
    evaluate_momentum_exhaustion,
    resolve_momentum_exhaustion_config,
)


def test_momentum_exhaustion_allows_below_and_equal_threshold() -> None:
    config = MomentumExhaustionConfig(mode="enforce", max_score=4.0)

    below = evaluate_momentum_exhaustion(3.999, config)
    equal = evaluate_momentum_exhaustion(4.0, config)

    assert below.blocked is False
    assert below.filtered is False
    assert equal.blocked is False
    assert equal.filtered is False


def test_momentum_exhaustion_filters_above_threshold_in_enforce_mode() -> None:
    decision = evaluate_momentum_exhaustion(
        4.0001,
        MomentumExhaustionConfig(mode="enforce", max_score=4.0),
    )

    assert decision.blocked is True
    assert decision.filtered is True
    assert decision.shadowed is False
    assert decision.reason is not None
    assert "4.0001 > 4.0000" in decision.reason


def test_momentum_exhaustion_shadows_above_threshold_in_shadow_mode() -> None:
    decision = evaluate_momentum_exhaustion(
        5.0,
        MomentumExhaustionConfig(mode="shadow", max_score=4.0),
    )

    assert decision.blocked is True
    assert decision.filtered is False
    assert decision.shadowed is True


def test_momentum_exhaustion_ignores_missing_or_non_numeric_rank_score() -> None:
    config = MomentumExhaustionConfig(mode="enforce", max_score=4.0)

    missing = evaluate_momentum_exhaustion(None, config)
    non_numeric = evaluate_momentum_exhaustion("n/a", config)

    assert missing.blocked is False
    assert missing.threshold is None
    assert non_numeric.blocked is False
    assert non_numeric.threshold is None


def test_momentum_exhaustion_resolves_rollout_defaults_from_production_config() -> None:
    raw_config = {"production": {"momentum_exhaustion_filter": {"enabled": True}}}

    evaluation_config = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
    )
    production_config = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE,
    )

    assert evaluation_config.mode == "off"
    assert production_config.mode == "off"
    assert evaluation_config.max_score == DEFAULT_MOMENTUM_EXHAUSTION_MAX_SCORE


def test_analysis_resolution_uses_threshold_but_not_production_mode() -> None:
    raw_config = {
        "production": {
            "momentum_exhaustion_filter": {
                "enabled": True,
                "mode": "shadow",
                "max_score": 3.5,
            }
        }
    }

    evaluation_config = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_ANALYSIS_MOMENTUM_EXHAUSTION_MODE,
        use_configured_mode=False,
    )
    production_config = resolve_momentum_exhaustion_config(
        raw_config,
        default_mode=DEFAULT_PRODUCTION_MOMENTUM_EXHAUSTION_MODE,
    )

    assert evaluation_config.mode == "off"
    assert evaluation_config.max_score == 3.5
    assert production_config.mode == "shadow"
