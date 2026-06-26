from __future__ import annotations

from datetime import date

import pandas as pd

from src.analysis.signals import SignalAction, TradingSignal
from src.backtest.data_cache import BacktestDataCache
from src.entry_signal_analysis.models import EntrySignalAnalysisRequest
from src.entry_signal_analysis.priority15 import build_priority15_outputs
from src.entry_signal_analysis.scanner import EntrySignalEventContext, EntrySignalScanResult
from src.utils.forward_returns import compute_forward_returns


def _feature_frame() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=560)
    base = pd.Series([100.0 + i * 0.08 for i in range(len(dates))], index=dates)
    frame = pd.DataFrame(
        {
            "Open": base,
            "High": base + 1.0,
            "Low": base - 1.0,
            "Close": base + 0.2,
            "Volume": 1_000_000.0,
            "EMA_20": base - 0.5,
            "EMA_50": base - 1.0,
            "EMA_200": base - 2.0,
            "Volume_SMA_20": 900_000.0,
            "ATR_Ratio": 0.02,
            "RSI": 58.0,
            "ADX_14": 24.0,
            "BB_Width": 0.08,
            "Ichi_SpanA": base - 0.3,
            "Ichi_SpanB": base - 0.8,
            "Ichi_Kijun": base - 0.6,
            "Turnover": base * 1_000_000.0,
            "Turnover_Median_20": base * 900_000.0,
        },
        index=dates,
    )
    # Same-day target/stop tie after next-open entry. Stop must win the tie.
    entry_pos = 21
    frame.iloc[entry_pos, frame.columns.get_loc("Open")] = 100.0
    frame.iloc[entry_pos, frame.columns.get_loc("High")] = 108.0
    frame.iloc[entry_pos, frame.columns.get_loc("Low")] = 95.0
    frame.iloc[entry_pos, frame.columns.get_loc("Close")] = 102.0
    return frame


def _candidate_and_context(
    *,
    frame: pd.DataFrame,
    request: EntrySignalAnalysisRequest,
    signal_pos: int,
) -> tuple[dict[str, object], EntrySignalEventContext]:
    ticker = "7203"
    signal_date = pd.Timestamp(frame.index[signal_pos]).date().isoformat()
    event_id = f"EntryA::production::{ticker}::{signal_date}"
    forward = compute_forward_returns(
        features=frame,
        signal_pos=signal_pos,
        horizons=request.required_analysis_horizons,
        label_mode=request.label_mode,
    )
    payload: dict[str, object] = {
        "event_id": event_id,
        "entry_strategy": "EntryA",
        "entry_filter_name": "production",
        "ticker": ticker,
        "signal_date": signal_date,
        "entry_date": forward.get("label_entry_date"),
        "entry_price": forward.get("label_entry_price"),
        "label_entry_date": forward.get("label_entry_date"),
        "label_entry_price": forward.get("label_entry_price"),
        "confidence": 0.8,
        "score": 7.0,
        "rank": 1,
        "rank_score": 0.5,
        "positive_rank_score": True,
        "tail_guard_limit": 10,
        "selected": True,
        "ranking_strategy": "momentum",
    }
    payload.update(forward)
    for horizon in request.required_analysis_horizons:
        entry_price = forward.get("label_entry_price")
        target_price = forward.get(f"forward_price_{horizon}d")
        payload[f"forward_diff_{horizon}d"] = (
            float(target_price) - float(entry_price)
            if entry_price not in (None, 0) and target_price is not None
            else None
        )
    context = EntrySignalEventContext(
        ticker=ticker,
        entry_strategy="EntryA",
        entry_filter_name="production",
        signal_date=signal_date,
        signal_pos=signal_pos,
        entry_pos=signal_pos + 1,
        signal=TradingSignal(
            action=SignalAction.BUY,
            confidence=0.8,
            reasons=["synthetic"],
            metadata={"score": 7.0},
            strategy_name="EntryA",
        ),
        payload=payload,
    )
    return payload, context


def test_priority15_outputs_cover_core_event_derived_artifacts() -> None:
    request = EntrySignalAnalysisRequest(
        entry_strategies=["EntryA"],
        tickers=["7203"],
        start_date=date(2024, 1, 1),
        end_date=date(2026, 3, 31),
        horizons=[5, 10, 20, 40, 60, 80],
        primary_horizon=20,
        target_pcts=[5],
        stop_pcts=[3],
        target_stop_horizons=[10],
        checkpoint_days=[10, 20, 40],
        cooldown_days=[5],
        late_entry_days=[1],
        cost_bps=[10],
    )
    frame = _feature_frame()
    cache = BacktestDataCache(data_root="data")
    cache.features_cache["7203"] = frame
    cache.date_pos_cache["7203"] = {ts: idx for idx, ts in enumerate(frame.index)}

    payloads: list[dict[str, object]] = []
    contexts: list[EntrySignalEventContext] = []
    for signal_pos in (20, 22, 300):
        payload, context = _candidate_and_context(
            frame=frame,
            request=request,
            signal_pos=signal_pos,
        )
        payloads.append(payload)
        contexts.append(context)

    scan_result = EntrySignalScanResult(
        candidates=pd.DataFrame(payloads),
        event_contexts=contexts,
        cache=cache,
        trading_dates=list(frame.index),
    )

    outputs = build_priority15_outputs(scan_result, request, benchmark_frame=None)

    assert len(outputs.event_metrics) == 3
    assert not hasattr(outputs, "over" + "lap_matrix")
    assert not hasattr(outputs, "incremental" + "_lift")
    first_event = outputs.event_metrics.iloc[0]
    assert first_event["MFE_10d_pct"] >= 8.0
    assert first_event["MAE_10d_pct"] <= -5.0
    assert "marginal_return_5d_to_10d_pct" in outputs.event_metrics.columns
    assert "net_return_after_10bps_20d_pct" in outputs.event_metrics.columns
    assert "decay_1d_20d_pct" in outputs.event_metrics.columns

    first_target_stop = outputs.target_stop_events[
        outputs.target_stop_events["event_id"] == first_event["event_id"]
    ].iloc[0]
    assert first_target_stop["hit_type"] == "stop_first"
    assert first_target_stop["rule_return_pct"] == -3

    assert set(outputs.checkpoint_events["checkpoint_day"]) == {10, 20, 40}
    assert "cooldown_5d" in set(outputs.cooldown_summary["scope"])
    cooldown_row = outputs.cooldown_summary[outputs.cooldown_summary["scope"] == "cooldown_5d"].iloc[0]
    assert cooldown_row["event_count"] == 2

    assert not outputs.path_summary.empty
    assert not outputs.trend_feature_summary.empty
    assert not outputs.execution_summary.empty
    assert not outputs.exit_rule_summary.empty
    assert not outputs.walk_forward_summary.empty
