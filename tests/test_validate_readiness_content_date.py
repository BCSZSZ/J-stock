from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import ModuleType
import sys
from typing import TypedDict

import pandas as pd
import pytest

fake_boto3 = ModuleType("boto3")
fake_boto3.client = lambda service: None  # type: ignore[attr-defined]
fake_botocore = ModuleType("botocore")
fake_botocore_exceptions = ModuleType("botocore.exceptions")


class FakeClientError(Exception):
    pass


fake_botocore_exceptions.ClientError = FakeClientError  # type: ignore[attr-defined]
sys.modules.setdefault("boto3", fake_boto3)
sys.modules.setdefault("botocore", fake_botocore)
sys.modules.setdefault("botocore.exceptions", fake_botocore_exceptions)

from src.aws.handlers import validate_readiness


JST = timezone(timedelta(hours=9))


class FakeS3Object(TypedDict):
    body: bytes
    last_modified: datetime


class FakeBody:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class FakeS3Client:
    def __init__(self, objects: dict[str, FakeS3Object]) -> None:
        self._objects = objects

    def head_object(self, Bucket: str, Key: str) -> dict[str, datetime]:
        return {"LastModified": self._objects[Key]["last_modified"]}

    def get_object(self, Bucket: str, Key: str) -> dict[str, FakeBody]:
        return {"Body": FakeBody(self._objects[Key]["body"])}


def _parquet_bytes(date_values: list[str]) -> bytes:
    df = pd.DataFrame(
        {
            "Date": pd.to_datetime(date_values),
            "Close": [100.0 + index for index, _ in enumerate(date_values)],
        }
    )
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    return buffer.getvalue()


def test_validate_data_freshness_rejects_stale_content_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_date = "2026-05-11"
    last_modified = datetime(2026, 5, 11, 19, 0, tzinfo=JST)
    fake_s3 = FakeS3Client(
        {
            "prefix/raw_prices/4530.parquet": {
                "body": _parquet_bytes(["2026-05-09", "2026-05-11"]),
                "last_modified": last_modified,
            },
            "prefix/features/4530_features.parquet": {
                "body": _parquet_bytes(["2026-05-07", "2026-05-08"]),
                "last_modified": last_modified,
            },
            "prefix/benchmarks/topix_daily.parquet": {
                "body": _parquet_bytes(["2026-05-09", "2026-05-11"]),
                "last_modified": last_modified,
            },
        }
    )

    monkeypatch.setattr(validate_readiness.boto3, "client", lambda service: fake_s3)

    result = validate_readiness._validate_data_freshness(
        "s3://bucket/prefix",
        ["4530"],
        run_date,
    )

    assert result["ready"] is False
    assert result["missing_prices_count"] == 0
    assert result["missing_features_count"] == 1
    assert result["missing_features_sample"] == ["4530@content:2026-05-08"]
    assert result["benchmark_ok"] is True
    assert result["benchmark_content_latest_date"] == run_date


def test_validate_data_freshness_accepts_matching_content_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_date = "2026-05-11"
    last_modified = datetime(2026, 5, 11, 19, 30, tzinfo=JST)
    fake_s3 = FakeS3Client(
        {
            "prefix/raw_prices/6501.parquet": {
                "body": _parquet_bytes(["2026-05-09", "2026-05-11"]),
                "last_modified": last_modified,
            },
            "prefix/features/6501_features.parquet": {
                "body": _parquet_bytes(["2026-05-09", "2026-05-11"]),
                "last_modified": last_modified,
            },
            "prefix/benchmarks/topix_daily.parquet": {
                "body": _parquet_bytes(["2026-05-09", "2026-05-11"]),
                "last_modified": last_modified,
            },
        }
    )

    monkeypatch.setattr(validate_readiness.boto3, "client", lambda service: fake_s3)

    result = validate_readiness._validate_data_freshness(
        "s3://bucket/prefix",
        ["6501"],
        run_date,
    )

    assert result["ready"] is True
    assert result["missing_prices_count"] == 0
    assert result["missing_features_count"] == 0
    assert result["benchmark_ok"] is True
    assert result["benchmark_content_latest_date"] == run_date