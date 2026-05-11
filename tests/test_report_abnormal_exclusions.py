from pathlib import Path

from src.production.report_builder import AbnormalSignalTicker, ReportBuilder
from src.production.state_manager import ProductionState


class MockDataManager:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.data_dir = data_root


def test_report_lists_abnormal_signal_exclusions(tmp_path: Path) -> None:
    state = ProductionState(state_file=str(tmp_path / "state.json"))
    state.add_group(
        group_id="core",
        name="Core Strategy",
        initial_capital=1_000_000.0,
    )
    builder = ReportBuilder(state, MockDataManager(tmp_path))

    report = builder.generate_daily_report(
        signals=[],
        report_date="2026-05-11",
        abnormal_tickers=[
            AbnormalSignalTicker(
                ticker="4530",
                ticker_name="久光製薬",
                latest_data_date="2026-05-08",
                expected_date="2026-05-11",
                lag_days=3,
                exclusion_reason="Missing feature data for selected signal date",
                held_by_groups=("Core Strategy",),
            )
        ],
    )

    assert "## ⚠️ Abnormal Signal Exclusions" in report
    assert "| 4530 | 久光製薬 | 2026-05-08 | 2026-05-11 | 3d | Core Strategy | Missing feature data for selected signal date |" in report