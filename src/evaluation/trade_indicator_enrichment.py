from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.artifacts.tabular import (
    LargeArtifactFormat,
    read_table_auto,
    write_large_artifact,
)


DEFAULT_INDICATOR_COLUMNS: tuple[str, ...] = (
    "RSI",
    "RSI_9",
    "RSI_14",
    "RSI_22",
    "EMA_20",
    "EMA_50",
    "EMA_200",
    "ATR",
    "ADX_14",
    "MACD",
    "MACD_Signal",
    "MACD_Hist",
)


def _normalize_ticker(value: object) -> str:
    ticker = str(value or "").strip()
    if ticker.endswith(".0") and ticker[:-2].isdigit():
        ticker = ticker[:-2]
    return ticker


def _parse_metadata(value: object) -> dict[str, object]:
    if value is None:
        return {}
    try:
        if pd.isna(value):
            return {}
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def _metadata_date(
    metadata: dict[str, object],
    primary_key: str,
    fallback_key: str = "signal_date",
) -> object:
    primary = metadata.get(primary_key)
    if primary:
        return primary
    return metadata.get(fallback_key)


def _coerce_date(value: object) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _normalize_ticker_series(values: pd.Series) -> pd.Series:
    return pd.Series(
        [_normalize_ticker(value) for value in values.tolist()],
        index=values.index,
        dtype="object",
    )


def _normalize_date_series(values: pd.Series | None, index: pd.Index) -> pd.Series:
    if values is None:
        return pd.Series(pd.NaT, index=index)
    parsed = pd.to_datetime(values, errors="coerce")
    if isinstance(parsed, pd.Series):
        return parsed.dt.normalize()
    return pd.Series(pd.DatetimeIndex(parsed).normalize(), index=index)


def _extract_metadata_date_series(
    values: pd.Series | None,
    index: pd.Index,
    primary_key: str,
    fallback_key: str = "signal_date",
) -> pd.Series:
    if values is None:
        return pd.Series(pd.NaT, index=index)

    raw_dates: list[object] = []
    for value in values.tolist():
        metadata = _parse_metadata(value)
        raw_dates.append(_metadata_date(metadata, primary_key, fallback_key))

    parsed = pd.to_datetime(raw_dates, errors="coerce")
    return pd.Series(pd.DatetimeIndex(parsed).normalize(), index=index)


def load_feature_table(data_root: Path | str, ticker: str) -> pd.DataFrame:
    feature_path = Path(data_root) / "features" / f"{ticker}_features.parquet"
    if not feature_path.exists():
        return pd.DataFrame()

    df = pd.read_parquet(feature_path)
    if df.empty:
        return df

    normalized = df.copy()
    if "Date" in normalized.columns:
        date_values = pd.to_datetime(normalized["Date"], errors="coerce")
    else:
        date_values = pd.to_datetime(normalized.index, errors="coerce")
    normalized.index = pd.DatetimeIndex(date_values).normalize()
    normalized.index.name = "Date"
    normalized = normalized[normalized.index.notna()]
    normalized = normalized[~normalized.index.duplicated(keep="last")]
    return normalized.sort_index()


def _build_feature_lookup(
    data_root: Path | str,
    tickers: pd.Series,
    indicator_columns: tuple[str, ...],
) -> tuple[pd.DataFrame, dict[str, bool]]:
    feature_found_by_ticker: dict[str, bool] = {}
    feature_frames: list[pd.DataFrame] = []

    for ticker in sorted({value for value in tickers.tolist() if value}):
        features = load_feature_table(data_root, ticker)
        feature_found = not features.empty
        feature_found_by_ticker[ticker] = feature_found
        if not feature_found:
            continue

        selected = features.reindex(columns=list(indicator_columns)).copy()
        selected["__lookup_date"] = selected.index
        selected["__ticker"] = ticker
        feature_frames.append(selected.reset_index(drop=True))

    if not feature_frames:
        empty = pd.DataFrame(columns=["__ticker", "__lookup_date", *indicator_columns])
        return empty.set_index(["__ticker", "__lookup_date"]), feature_found_by_ticker

    feature_lookup = pd.concat(feature_frames, ignore_index=True)
    return (
        feature_lookup.set_index(["__ticker", "__lookup_date"]),
        feature_found_by_ticker,
    )


def _format_snapshot_date_series(
    original_values: pd.Series | None,
    normalized_dates: pd.Series,
) -> pd.Series:
    formatted = pd.Series(pd.NA, index=normalized_dates.index, dtype="object")
    valid_mask = normalized_dates.notna()
    if valid_mask.any():
        formatted.loc[valid_mask] = normalized_dates.loc[valid_mask].dt.strftime("%Y-%m-%d")
    if original_values is not None and (~valid_mask).any():
        formatted.loc[~valid_mask] = original_values.loc[~valid_mask]
    return formatted


def _build_snapshot_frame(
    *,
    tickers: pd.Series,
    lookup_dates: pd.Series,
    original_dates: pd.Series | None,
    feature_lookup: pd.DataFrame,
    feature_found_by_ticker: dict[str, bool],
    prefix: str,
    indicator_columns: tuple[str, ...],
) -> pd.DataFrame:
    snapshot = pd.DataFrame(index=tickers.index)
    snapshot[f"{prefix}_date"] = _format_snapshot_date_series(
        original_values=original_dates,
        normalized_dates=lookup_dates,
    )
    feature_found = tickers.map(feature_found_by_ticker).fillna(False).astype(bool)
    snapshot[f"{prefix}_feature_found"] = feature_found

    indicator_frame = pd.DataFrame(
        pd.NA,
        index=tickers.index,
        columns=list(indicator_columns),
    )
    valid_mask = tickers.ne("") & lookup_dates.notna()
    if valid_mask.any() and not feature_lookup.empty:
        lookup_keys = pd.MultiIndex.from_frame(
            pd.DataFrame(
                {
                    "__ticker": tickers.loc[valid_mask].values,
                    "__lookup_date": lookup_dates.loc[valid_mask].values,
                }
            )
        )
        matched = feature_lookup.reindex(lookup_keys)
        matched.index = tickers.index[valid_mask]
        indicator_frame.loc[valid_mask, :] = matched.loc[:, list(indicator_columns)].values

    renamed_indicator_frame = indicator_frame.rename(
        columns={column: f"{prefix}_{column}" for column in indicator_columns}
    )
    valid_count = renamed_indicator_frame.notna().sum(axis=1).astype(int)

    snapshot = pd.concat([snapshot, renamed_indicator_frame], axis=1)
    snapshot[f"{prefix}_indicator_valid_count"] = valid_count
    snapshot[f"{prefix}_indicator_missing_count"] = len(indicator_columns) - valid_count
    snapshot[f"{prefix}_indicator_quality"] = (
        valid_count / len(indicator_columns) if indicator_columns else 1.0
    )
    return snapshot


def _empty_snapshot(
    prefix: str,
    date_value: object,
    indicator_columns: tuple[str, ...],
    feature_found: bool,
) -> dict[str, object]:
    row: dict[str, object] = {
        f"{prefix}_date": date_value,
        f"{prefix}_feature_found": feature_found,
        f"{prefix}_indicator_valid_count": 0,
        f"{prefix}_indicator_missing_count": len(indicator_columns),
        f"{prefix}_indicator_quality": 0.0 if indicator_columns else 1.0,
    }
    for column in indicator_columns:
        row[f"{prefix}_{column}"] = pd.NA
    return row


def _snapshot_for_date(
    features: pd.DataFrame,
    prefix: str,
    date_value: object,
    indicator_columns: tuple[str, ...],
) -> dict[str, object]:
    feature_found = not features.empty
    timestamp = _coerce_date(date_value)
    if timestamp is None or features.empty or timestamp not in features.index:
        return _empty_snapshot(prefix, date_value, indicator_columns, feature_found)

    feature_row = features.loc[timestamp]
    snapshot: dict[str, object] = {
        f"{prefix}_date": str(timestamp.date()),
        f"{prefix}_feature_found": True,
    }
    valid_count = 0
    for column in indicator_columns:
        value: object = pd.NA
        if column in feature_row.index:
            value = feature_row.get(column)
            if not pd.isna(value):
                valid_count += 1
        snapshot[f"{prefix}_{column}"] = value

    missing_count = len(indicator_columns) - valid_count
    snapshot[f"{prefix}_indicator_valid_count"] = valid_count
    snapshot[f"{prefix}_indicator_missing_count"] = missing_count
    snapshot[f"{prefix}_indicator_quality"] = (
        valid_count / len(indicator_columns) if indicator_columns else 1.0
    )
    return snapshot


def resolve_indicator_columns(raw_columns: list[str] | None) -> tuple[str, ...]:
    if not raw_columns:
        return DEFAULT_INDICATOR_COLUMNS
    columns: list[str] = []
    for raw_column in raw_columns:
        for column in raw_column.split(","):
            cleaned = column.strip()
            if cleaned and cleaned not in columns:
                columns.append(cleaned)
    return tuple(columns)


def enrich_trade_dataframe_with_indicators(
    trades: pd.DataFrame,
    data_root: Path | str,
    indicator_columns: tuple[str, ...] = DEFAULT_INDICATOR_COLUMNS,
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()

    index = trades.index
    ticker_values = trades.get("ticker")
    if ticker_values is None:
        ticker_values = pd.Series("", index=index)
    normalized_tickers = _normalize_ticker_series(ticker_values)

    entry_exec_dates = _normalize_date_series(trades.get("entry_date"), index)
    exit_exec_dates = _normalize_date_series(trades.get("exit_date"), index)
    entry_signal_dates = _extract_metadata_date_series(
        trades.get("entry_metadata_json"),
        index,
        "entry_signal_date",
    ).fillna(entry_exec_dates)
    exit_signal_dates = _extract_metadata_date_series(
        trades.get("exit_metadata_json"),
        index,
        "exit_signal_date",
    ).fillna(exit_exec_dates)

    feature_lookup, feature_found_by_ticker = _build_feature_lookup(
        data_root=data_root,
        tickers=normalized_tickers,
        indicator_columns=indicator_columns,
    )

    snapshots = [
        _build_snapshot_frame(
            tickers=normalized_tickers,
            lookup_dates=entry_signal_dates,
            original_dates=trades.get("entry_date"),
            feature_lookup=feature_lookup,
            feature_found_by_ticker=feature_found_by_ticker,
            prefix="entry_signal",
            indicator_columns=indicator_columns,
        ),
        _build_snapshot_frame(
            tickers=normalized_tickers,
            lookup_dates=entry_exec_dates,
            original_dates=trades.get("entry_date"),
            feature_lookup=feature_lookup,
            feature_found_by_ticker=feature_found_by_ticker,
            prefix="entry_exec",
            indicator_columns=indicator_columns,
        ),
        _build_snapshot_frame(
            tickers=normalized_tickers,
            lookup_dates=exit_signal_dates,
            original_dates=trades.get("exit_date"),
            feature_lookup=feature_lookup,
            feature_found_by_ticker=feature_found_by_ticker,
            prefix="exit_signal",
            indicator_columns=indicator_columns,
        ),
        _build_snapshot_frame(
            tickers=normalized_tickers,
            lookup_dates=exit_exec_dates,
            original_dates=trades.get("exit_date"),
            feature_lookup=feature_lookup,
            feature_found_by_ticker=feature_found_by_ticker,
            prefix="exit_exec",
            indicator_columns=indicator_columns,
        ),
    ]

    return pd.concat([trades.copy(), *snapshots], axis=1)


def enrich_trades_with_indicators(
    trades_csv: Path | str,
    data_root: Path | str,
    indicator_columns: tuple[str, ...] = DEFAULT_INDICATOR_COLUMNS,
) -> pd.DataFrame:
    trades = read_table_auto(trades_csv, csv_kwargs={"dtype": {"ticker": str}})
    return enrich_trade_dataframe_with_indicators(
        trades=trades,
        data_root=data_root,
        indicator_columns=indicator_columns,
    )


def default_indicator_output_path(trades_csv: Path | str) -> Path:
    trades_path = Path(trades_csv)
    return trades_path.with_name(f"{trades_path.stem}_indicators.csv")


def write_enriched_trades_sidecar(
    trades_csv: Path | str,
    data_root: Path | str,
    output_path: Path | str | None = None,
    indicator_columns: tuple[str, ...] = DEFAULT_INDICATOR_COLUMNS,
    trades_df: pd.DataFrame | None = None,
    large_artifact_format: LargeArtifactFormat = "parquet",
) -> Path:
    trades_path = Path(trades_csv)
    resolved_output_path = (
        Path(output_path) if output_path is not None else default_indicator_output_path(trades_path)
    )
    if trades_df is None:
        source_trades = read_table_auto(trades_path, csv_kwargs={"dtype": {"ticker": str}})
    else:
        source_trades = trades_df
    enriched = enrich_trade_dataframe_with_indicators(
        trades=source_trades,
        data_root=data_root,
        indicator_columns=indicator_columns,
    )
    written = write_large_artifact(
        enriched,
        resolved_output_path,
        large_artifact_format,
    )
    return written["parquet"] or written["csv"] or resolved_output_path
