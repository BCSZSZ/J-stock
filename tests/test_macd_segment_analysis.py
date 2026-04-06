import pandas as pd

from src.analysis.macd_segment_analysis import (
    OVERALL_TICKER,
    build_rule_details,
    build_segment_summaries,
    extract_segment_records,
    normalize_ticker_inputs,
    summarize_rule_details,
)


def _make_feature_frame() -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=14, freq="B")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": [100, 101, 102, 104, 106, 107, 108, 109, 108, 107, 106, 105, 104, 103],
            "High": [101, 102, 105, 108, 111, 110, 109, 112, 111, 108, 107, 106, 105, 104],
            "Close": [100, 101, 104, 107, 110, 109, 108, 111, 109, 107, 106, 105, 104, 103],
            "MACD": [-0.5, -0.2, 0.2, 0.6, 0.9, 0.8, 0.6, -0.2, -0.3, 0.2, 0.5, 0.3, -0.1, -0.2],
            "MACD_Signal": [-0.4, -0.1, 0.1, 0.4, 0.7, 0.75, 0.7, 0.0, -0.2, 0.1, 0.3, 0.35, 0.0, -0.1],
            "MACD_Hist": [-0.1, -0.1, 0.1, 0.2, 0.2, 0.05, -0.1, -0.2, -0.1, 0.1, 0.2, 0.05, -0.1, -0.1],
        }
    )


def test_normalize_ticker_inputs_dedupes_and_strips_suffix():
    assert normalize_ticker_inputs(["1321", "1321.T", " 7203 "], "7203,6758.t") == [
        "1321",
        "7203",
        "6758",
    ]


def test_extract_segment_records_uses_next_open_and_skips_incomplete_tail():
    features = _make_feature_frame()
    records = extract_segment_records("1321", features)

    assert len(records) == 2

    first = records[0].row
    assert first["golden_cross_date"] == "2025-01-03"
    assert first["entry_date"] == "2025-01-06"
    assert first["entry_open"] == 104.0
    assert first["death_cross_date"] == "2025-01-09"
    assert first["death_exit_date"] == "2025-01-10"
    assert first["peak_high"] == 111.0
    assert first["peak_high_date"] == "2025-01-07"
    assert first["macd_peak_date"] == "2025-01-07"
    assert first["macd_turn_signal_date"] == "2025-01-08"
    assert first["macd_peak_confirmed_date"] == "2025-01-07"
    assert first["macd_peak_confirm_signal_date"] == "2025-01-08"
    assert first["macd_peak_confirm_exit_date"] == "2025-01-09"
    assert first["death_return_pct"] == 4.807692307692313


def test_rule_details_and_summaries_cover_per_ticker_and_overall_views():
    features = _make_feature_frame()
    records_a = extract_segment_records("1321", features)

    features_b = features.copy()
    features_b["Date"] = features_b["Date"] + pd.offsets.BDay(30)
    features_b["Open"] = features_b["Open"] * 2
    features_b["High"] = features_b["High"] * 2
    features_b["Close"] = features_b["Close"] * 2
    records_b = extract_segment_records("7203", features_b)

    all_records = records_a + records_b
    segment_df = pd.DataFrame([record.row for record in all_records])
    summary_by_ticker, summary_overall = build_segment_summaries(segment_df)
    derived_map = {
        row["ticker"]: {
            "anchor": row["derived_confirmed_anchor"],
            "lag_bars": int(row["derived_confirmed_lag_bars"]),
        }
        for _, row in summary_by_ticker.iterrows()
    }
    rule_details = build_rule_details(all_records, derived_map)
    rule_summary = summarize_rule_details(rule_details)

    assert sorted(summary_by_ticker["ticker"].tolist()) == ["1321", "7203"]
    assert summary_overall.iloc[0]["ticker"] == OVERALL_TICKER

    derived_rows = rule_details[rule_details["rule_name"] == "derived_confirmed_lag"]
    assert set(derived_rows["ticker"]) == {"1321", "7203"}
    assert (derived_rows["derived_lag_bars"] >= 0).all()

    overall_rule_rows = rule_summary[rule_summary["ticker"] == OVERALL_TICKER]
    assert set(overall_rule_rows["rule_name"]) == {
        "death_cross_confirmed",
        "macd_peak_confirmed",
        "macd_hist_peak_confirmed",
        "derived_confirmed_lag",
    }