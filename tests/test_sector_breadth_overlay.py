import pandas as pd

from src.overlays import OverlayContext
from src.overlays.sector_breadth_overlay import SectorBreadthOverlay


def _build_context(date_str: str) -> OverlayContext:
    return OverlayContext(
        current_date=pd.Timestamp(date_str),
        portfolio_cash=1_000_000,
        portfolio_value=1_000_000,
        positions={},
        current_prices={},
        benchmark_data=None,
    )


def test_overlay_uses_time_aligned_snapshot(tmp_path):
    metrics_path = tmp_path / "sector_daily_metrics.parquet"
    metrics = pd.DataFrame(
        {
            "Date": [
                "2021-06-01",
                "2021-06-01",
                "2023-06-01",
                "2023-06-01",
                "2025-06-01",
                "2025-06-01",
            ],
            "sector": ["A", "B", "A", "B", "A", "B"],
            # 2021 -> risk_off, 2023 -> risk_on, 2025 -> neutral
            # For 2025: median=57 (<58 risk_on threshold), strong_ratio=0.5 (>=0.3 neutral threshold).
            "sector_score": [40.0, 43.0, 70.0, 68.0, 62.0, 52.0],
            "is_low_coverage": [False, False, False, False, False, False],
        }
    )
    metrics.to_parquet(metrics_path, index=False)

    overlay = SectorBreadthOverlay(
        config={
            "enabled": True,
            "metrics_file": str(metrics_path),
            "risk_on_min_score": 58.0,
            "risk_on_min_strong_ratio": 0.45,
            "risk_on_max_weak_ratio": 0.25,
            "neutral_min_score": 52.0,
            "neutral_min_strong_ratio": 0.30,
            "sector_score_strong": 60.0,
            "sector_score_weak": 45.0,
            "low_coverage_block_ratio": 0.40,
            "block_new_entries_when_risk_off": True,
            "risk_on_max_new_positions": 3,
            "neutral_max_new_positions": 1,
            "risk_off_max_new_positions": 0,
            "risk_on_target_exposure": 1.0,
            "neutral_target_exposure": 0.8,
            "risk_off_target_exposure": 0.55,
            "enable_exit_overrides": False,
        }
    )

    d2021 = overlay.evaluate(_build_context("2021-06-01"))
    d2023 = overlay.evaluate(_build_context("2023-06-01"))
    d2025 = overlay.evaluate(_build_context("2025-06-01"))

    assert d2021.metadata.get("latest_date") == "2021-06-01"
    assert d2023.metadata.get("latest_date") == "2023-06-01"
    assert d2025.metadata.get("latest_date") == "2025-06-01"

    assert d2021.metadata.get("regime") == "RISK_OFF"
    assert d2023.metadata.get("regime") == "RISK_ON"
    assert d2025.metadata.get("regime") == "NEUTRAL"


def test_overlay_no_metrics_for_date_uses_conservative_fallback(tmp_path):
    metrics_path = tmp_path / "sector_daily_metrics.parquet"
    metrics = pd.DataFrame(
        {
            "Date": ["2025-01-01", "2025-01-01"],
            "sector": ["A", "B"],
            "sector_score": [60.0, 62.0],
            "is_low_coverage": [False, False],
        }
    )
    metrics.to_parquet(metrics_path, index=False)

    overlay = SectorBreadthOverlay(
        config={
            "enabled": True,
            "metrics_file": str(metrics_path),
            "risk_off_target_exposure": 0.55,
        }
    )

    decision = overlay.evaluate(_build_context("2021-01-01"))

    assert decision.metadata.get("status") == "no_metrics_for_date"
    assert decision.block_new_entries is True
    assert decision.max_new_positions == 0
    assert decision.target_exposure == 0.55
