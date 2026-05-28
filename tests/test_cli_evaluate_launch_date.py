from types import SimpleNamespace

import pytest

from src.cli.evaluate import _apply_launch_date_clip, _build_periods


def test_apply_launch_date_clip_adjusts_and_skips_periods() -> None:
    periods = [
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026", "2026-01-01", "2026-12-31"),
    ]

    clipped = _apply_launch_date_clip(periods, "2026-02-01")

    assert clipped == [
        ("2026_from_2026-02-01", "2026-02-01", "2026-12-31"),
    ]


def test_apply_launch_date_clip_rejects_invalid_format() -> None:
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _apply_launch_date_clip([("2026", "2026-01-01", "2026-12-31")], "2026/02/01")


def test_build_periods_applies_launch_date_to_annual_mode() -> None:
    args = SimpleNamespace(
        mode="annual",
        years=[2026],
        months=None,
        custom_periods=None,
        launch_date="2026-02-01",
    )

    periods = _build_periods(args)

    assert periods == [("2026_from_2026-02-01", "2026-02-01", "2026-12-31")]


def test_apply_launch_date_clip_expands_periods_for_multiple_launch_dates() -> None:
    periods = [("2026", "2026-01-01", "2026-12-31")]

    clipped = _apply_launch_date_clip(periods, ["2026-01-01", "2026-02-01"])

    assert clipped == [
        ("2026_launch_2026-01-01", "2026-01-01", "2026-12-31"),
        ("2026_launch_2026-02-01_from_2026-02-01", "2026-02-01", "2026-12-31"),
    ]


def test_apply_launch_date_clip_skips_cross_period_pairs_in_multi_launch_mode() -> None:
    periods = [
        ("2025", "2025-01-01", "2025-12-31"),
        ("2026", "2026-01-01", "2026-12-31"),
    ]

    clipped = _apply_launch_date_clip(periods, ["2025-03-10", "2026-03-10"])

    assert clipped == [
        ("2025_launch_2025-03-10_from_2025-03-10", "2025-03-10", "2025-12-31"),
        ("2026_launch_2026-03-10_from_2026-03-10", "2026-03-10", "2026-12-31"),
    ]