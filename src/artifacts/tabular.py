from __future__ import annotations

from pathlib import Path
from typing import Literal, TypedDict

import pandas as pd


LargeArtifactFormat = Literal["parquet", "csv", "both"]


class LargeArtifactPaths(TypedDict):
    csv: Path | None
    parquet: Path | None


def _category_candidate(series: pd.Series) -> bool:
    if isinstance(series.dtype, pd.CategoricalDtype):
        return False
    if not pd.api.types.is_object_dtype(series.dtype) and not pd.api.types.is_string_dtype(series.dtype):
        return False
    non_null = series.dropna()
    if non_null.empty:
        return False
    if not non_null.map(lambda value: isinstance(value, str)).all():
        return False
    unique_count = int(non_null.nunique(dropna=True))
    return unique_count <= 512 and unique_count <= max(64, int(len(non_null) * 0.5))


def optimize_large_artifact_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a Parquet-friendly copy without changing numeric precision."""
    if frame.empty:
        return frame.copy()
    optimized = frame.copy()
    for column in optimized.columns:
        if _category_candidate(optimized[column]):
            optimized[column] = optimized[column].astype("category")

    integer_name_hints = {
        "event_row",
        "horizon",
        "days_to_target",
        "days_to_stop",
        "days_to_hit",
        "entry_pos",
        "signal_pos",
        "rank",
        "quantity",
        "shares",
        "holding_days",
        "num_trades",
        "window_index",
    }
    for column in integer_name_hints.intersection(optimized.columns):
        numeric = pd.to_numeric(optimized[column], errors="coerce")
        finite = numeric.dropna()
        if finite.empty or (finite % 1 == 0).all():
            optimized[column] = numeric.astype("Int64")
    return optimized


def _artifact_paths(base_path: Path) -> LargeArtifactPaths:
    if base_path.suffix.lower() == ".csv":
        return {"csv": base_path, "parquet": base_path.with_suffix(".parquet")}
    if base_path.suffix.lower() == ".parquet":
        return {"csv": base_path.with_suffix(".csv"), "parquet": base_path}
    return {"csv": base_path.with_suffix(".csv"), "parquet": base_path.with_suffix(".parquet")}


def write_csv_artifact(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def write_large_artifact(
    frame: pd.DataFrame,
    base_path: Path,
    large_artifact_format: LargeArtifactFormat,
) -> LargeArtifactPaths:
    if large_artifact_format not in {"parquet", "csv", "both"}:
        raise ValueError(
            "large_artifact_format must be one of parquet, csv, or both; "
            f"got {large_artifact_format!r}"
        )

    resolved = _artifact_paths(base_path)
    written: LargeArtifactPaths = {"csv": None, "parquet": None}

    if large_artifact_format in {"csv", "both"}:
        csv_path = resolved["csv"]
        if csv_path is None:
            raise ValueError("CSV output path could not be resolved")
        write_csv_artifact(frame, csv_path)
        written["csv"] = csv_path

    if large_artifact_format in {"parquet", "both"}:
        parquet_path = resolved["parquet"]
        if parquet_path is None:
            raise ValueError("Parquet output path could not be resolved")
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        optimize_large_artifact_frame(frame).to_parquet(parquet_path, index=False)
        written["parquet"] = parquet_path

    return written


def read_table_auto(
    path: Path | str,
    *,
    csv_kwargs: dict[str, object] | None = None,
    parquet_kwargs: dict[str, object] | None = None,
) -> pd.DataFrame:
    table_path = Path(path)
    suffix = table_path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(table_path, **(parquet_kwargs or {}))
    if suffix == ".csv":
        return pd.read_csv(table_path, **(csv_kwargs or {}))
    raise ValueError(f"Unsupported table artifact extension: {table_path}")
