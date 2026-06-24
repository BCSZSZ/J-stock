import math

import pytest

from src.analysis.strategies.entry.crossover_utils import (
    crossed_up,
    gt_latest,
    macd_position_ok,
    rsi_not_overheated,
    volume_ratio_ok,
)


def test_crossed_up_accepts_negative_to_positive_and_equal_start() -> None:
    assert crossed_up(-0.1, 0.0, 0.2, 0.1)
    assert crossed_up(1.0, 1.0, 1.2, 1.1)


def test_crossed_up_rejects_missing_or_non_cross() -> None:
    assert not crossed_up(0.2, 0.1, 0.3, 0.2)
    assert not crossed_up(math.nan, 0.1, 0.3, 0.2)


def test_basic_rule_helpers() -> None:
    assert gt_latest(11.0, 10.0)
    assert volume_ratio_ok(130.0, 100.0, 1.2)
    assert rsi_not_overheated(69.9, 70.0)
    assert not rsi_not_overheated(70.0, 70.0)


def test_macd_position_modes() -> None:
    assert macd_position_ok(-0.01, -0.01, mode="any")
    assert macd_position_ok(-0.01, -0.02, mode="near_zero", near_zero_abs=0.02)
    assert macd_position_ok(0.01, -0.02, mode="above_zero")
    assert not macd_position_ok(-0.01, -0.02, mode="above_zero")

    with pytest.raises(ValueError):
        macd_position_ok(0.1, 0.0, mode="bad")
