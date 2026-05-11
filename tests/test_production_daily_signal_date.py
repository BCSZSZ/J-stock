from datetime import date

from src.cli.production_daily import _select_signal_date_from_latest_dates


def test_select_signal_date_uses_latest_majority_date() -> None:
    latest_dates = {f"T{i:03d}": date(2026, 5, 11) for i in range(1, 120)}
    latest_dates["4530"] = date(2026, 5, 8)

    decision = _select_signal_date_from_latest_dates(latest_dates, minimum_ratio=0.9)

    assert decision.signal_date == date(2026, 5, 11)
    assert decision.ready_ticker_count == 119
    assert decision.total_ticker_count == 120
    assert decision.abnormal_tickers == ("4530",)


def test_select_signal_date_falls_back_when_latest_ratio_is_only_ninety_percent() -> None:
    latest_dates = {f"T{i:03d}": date(2026, 5, 11) for i in range(1, 10)}
    latest_dates["T010"] = date(2026, 5, 10)

    decision = _select_signal_date_from_latest_dates(latest_dates, minimum_ratio=0.9)

    assert decision.signal_date == date(2026, 5, 10)
    assert decision.ready_ticker_count == 10
    assert decision.total_ticker_count == 10
    assert decision.abnormal_tickers == ()