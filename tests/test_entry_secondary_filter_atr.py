from src.analysis.filters.entry_secondary_filter import EntrySecondaryFilter


def _atr_only_filter() -> EntrySecondaryFilter:
    return EntrySecondaryFilter.from_dict(
        {
            "enabled": True,
            "require_ema_bull_stack": False,
            "rsi_min": None,
            "rsi_max": None,
            "atr_price_min": 0.015,
            "atr_price_max": 0.03,
            "min_price": None,
        }
    )


def test_entry_filter_accepts_atr_ratio_inside_window() -> None:
    entry_filter = _atr_only_filter()

    assert entry_filter.passes_latest({"Close": 1000.0, "ATR_Ratio": 0.015})
    assert entry_filter.passes_latest({"Close": 1000.0, "ATR_Ratio": 0.02})
    assert entry_filter.passes_latest({"Close": 1000.0, "ATR_Ratio": 0.03})


def test_entry_filter_rejects_atr_ratio_outside_window() -> None:
    entry_filter = _atr_only_filter()

    assert not entry_filter.passes_latest({"Close": 1000.0, "ATR_Ratio": 0.0149})
    assert not entry_filter.passes_latest({"Close": 1000.0, "ATR_Ratio": 0.0301})


def test_entry_filter_falls_back_to_atr_over_close() -> None:
    entry_filter = _atr_only_filter()

    assert entry_filter.passes_latest({"Close": 1000.0, "ATR": 20.0})
    assert not entry_filter.passes_latest({"Close": 1000.0, "ATR": 40.0})


def test_entry_filter_disabled_keeps_existing_behavior() -> None:
    entry_filter = EntrySecondaryFilter.from_dict({"enabled": False})

    assert entry_filter.passes_latest({})