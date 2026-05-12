import json
import logging
import os
from io import BytesIO
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple, TypedDict
from urllib.parse import urlparse

import boto3
import pandas as pd
from botocore.exceptions import ClientError

from src.aws.jpx_holidays import is_jpx_trading_day
from src.aws.ticker_universe import resolve_fetch_tickers

logger = logging.getLogger(__name__)


JST = timezone(timedelta(hours=9))


class ReadinessObjectStatus(TypedDict):
    exists: bool
    ready: bool
    last_modified_jst: str | None
    content_latest_date: str | None
    error_code: str | None


def _parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid s3 uri: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _parse_s3_prefix(s3_uri: str) -> Tuple[str, str]:
    bucket, key = _parse_s3_uri(s3_uri)
    return bucket, key.rstrip("/")


def _jst_today_str() -> str:
    return datetime.now(timezone.utc).astimezone(JST).strftime("%Y-%m-%d")


def _extract_latest_parquet_date(body: bytes) -> str | None:
    try:
        df = pd.read_parquet(BytesIO(body))
    except Exception:
        return None

    if df.empty:
        return None

    if "Date" in df.columns:
        date_series = pd.to_datetime(df["Date"], errors="coerce")
    elif isinstance(df.index, pd.DatetimeIndex):
        date_series = pd.Series(df.index)
    else:
        reset_df = df.reset_index()
        if "Date" in reset_df.columns:
            date_series = pd.to_datetime(reset_df["Date"], errors="coerce")
        else:
            return None

    valid_dates = date_series.dropna()
    if valid_dates.empty:
        return None
    return valid_dates.max().strftime("%Y-%m-%d")


def _object_status_for_date(
    s3,
    bucket: str,
    key: str,
    run_date: str,
) -> ReadinessObjectStatus:
    try:
        resp = s3.head_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        return {
            "exists": False,
            "ready": False,
            "last_modified_jst": None,
            "content_latest_date": None,
            "error_code": error_code,
        }

    last_modified_jst = resp["LastModified"].astimezone(JST).strftime("%Y-%m-%d")
    content_latest_date: str | None = None
    if last_modified_jst == run_date:
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "ClientError")
            return {
                "exists": True,
                "ready": False,
                "last_modified_jst": last_modified_jst,
                "content_latest_date": None,
                "error_code": error_code,
            }
        content_latest_date = _extract_latest_parquet_date(body)

    return {
        "exists": True,
        "ready": last_modified_jst == run_date and content_latest_date == run_date,
        "last_modified_jst": last_modified_jst,
        "content_latest_date": content_latest_date,
        "error_code": None,
    }


def _head_ok_for_date(s3, bucket: str, key: str, run_date: str) -> bool:
    return bool(_object_status_for_date(s3, bucket, key, run_date)["ready"])


def _format_ticker_readiness_sample(ticker: str, status: ReadinessObjectStatus) -> str:
    content_latest_date = status.get("content_latest_date")
    if content_latest_date and content_latest_date != status.get("last_modified_jst"):
        return f"{ticker}@content:{content_latest_date}"
    if content_latest_date:
        return f"{ticker}@content:{content_latest_date}"
    return ticker


def _validate_data_freshness(data_s3_prefix: str, tickers: List[str], run_date: str) -> Dict[str, Any]:
    s3 = boto3.client("s3")
    bucket, prefix = _parse_s3_prefix(data_s3_prefix)

    missing_prices: List[str] = []
    missing_features: List[str] = []

    for t in tickers:
        price_key = f"{prefix}/raw_prices/{t}.parquet" if prefix else f"raw_prices/{t}.parquet"
        feature_key = f"{prefix}/features/{t}_features.parquet" if prefix else f"features/{t}_features.parquet"

        price_status = _object_status_for_date(s3, bucket, price_key, run_date)
        feature_status = _object_status_for_date(s3, bucket, feature_key, run_date)

        if not price_status["ready"]:
            missing_prices.append(_format_ticker_readiness_sample(t, price_status))
        if not feature_status["ready"]:
            missing_features.append(_format_ticker_readiness_sample(t, feature_status))

    bench_key = f"{prefix}/benchmarks/topix_daily.parquet" if prefix else "benchmarks/topix_daily.parquet"
    benchmark_status = _object_status_for_date(s3, bucket, bench_key, run_date)
    benchmark_ok = bool(benchmark_status["ready"])

    ready = (not missing_prices) and (not missing_features) and benchmark_ok
    return {
        "ready": ready,
        "missing_prices_count": len(missing_prices),
        "missing_features_count": len(missing_features),
        "missing_prices_sample": missing_prices[:30],
        "missing_features_sample": missing_features[:30],
        "benchmark_ok": benchmark_ok,
        "benchmark_key": bench_key,
        "benchmark_exists": bool(benchmark_status["exists"]),
        "benchmark_last_modified_jst": benchmark_status["last_modified_jst"],
        "benchmark_content_latest_date": benchmark_status["content_latest_date"],
        "benchmark_error_code": benchmark_status["error_code"],
    }


def _write_readiness(ops_s3_prefix: str, run_date: str, payload: Dict[str, Any]) -> str:
    bucket, prefix = _parse_s3_prefix(ops_s3_prefix)
    base = f"{prefix}/run_status/date={run_date}" if prefix else f"run_status/date={run_date}"
    s3 = boto3.client("s3")
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    # Write per-attempt file for debugging history (never overwritten).
    attempt = str(payload.get("attempt", "unknown"))
    attempt_key = f"{base}/readiness_attempt={attempt}.json"
    s3.put_object(Bucket=bucket, Key=attempt_key, Body=body, ContentType="application/json")

    # Write canonical readiness.json (latest attempt wins — consumed by DailyNoFetch).
    canonical_key = f"{base}/readiness.json"
    s3.put_object(Bucket=bucket, Key=canonical_key, Body=body, ContentType="application/json")

    return f"s3://{bucket}/{canonical_key}"


def _maybe_redispatch(event: Dict[str, Any], run_date: str) -> bool:
    allow_redispatch = bool(event.get("allow_redispatch", False))
    if not allow_redispatch:
        return False

    dispatch_fn = os.getenv("DISPATCH_FUNCTION_NAME", "").strip()
    if not dispatch_fn:
        return False

    tickers_per_job = int(event.get("tickers_per_job", os.getenv("TICKERS_PER_JOB", "100")))
    update_aux_data = bool(
        event.get("update_aux_data", str(os.getenv("UPDATE_AUX_DATA", "false")).lower() == "true")
    )

    payload = {
        "run_date": run_date,
        "tickers_per_job": tickers_per_job,
        "update_aux_data": update_aux_data,
    }
    boto3.client("lambda").invoke(
        FunctionName=dispatch_fn,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    return True


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    monitor_s3_uri = os.getenv("MONITOR_LIST_S3_URI", "").strip()
    data_s3_prefix = os.getenv("DATA_S3_PREFIX", "").strip()
    ops_s3_prefix = os.getenv("OPS_S3_PREFIX", "").strip()

    if not monitor_s3_uri.startswith("s3://"):
        raise ValueError("MONITOR_LIST_S3_URI must be s3://...")
    if not data_s3_prefix.startswith("s3://"):
        raise ValueError("DATA_S3_PREFIX must be s3://...")
    if not ops_s3_prefix.startswith("s3://"):
        raise ValueError("OPS_S3_PREFIX must be s3://...")

    run_date = str(event.get("run_date") or _jst_today_str())

    if not event.get("force") and not is_jpx_trading_day(date.fromisoformat(run_date)):
        logger.info("Skipping validation: %s is not a JPX trading day", run_date)
        return {"status": "skipped", "run_date": run_date, "reason": "jpx_holiday"}

    universe = resolve_fetch_tickers(event)
    tickers = universe["tickers"]

    check = _validate_data_freshness(data_s3_prefix, tickers, run_date)
    re_dispatched = False
    if not check["ready"]:
        re_dispatched = _maybe_redispatch(event, run_date)

    readiness_payload = {
        "run_date": run_date,
        "attempt": str(event.get("attempt", "manual")),
        "validated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ready": bool(check["ready"]),
        "redispatched": re_dispatched,
        "total_tickers": len(tickers),
        "monitor_tickers": universe["monitor_count"],
        "sector_pool_tickers": universe["sector_pool_count"],
        "sector_pool_s3_uri": universe["sector_pool_s3_uri"],
        **check,
    }
    readiness_uri = _write_readiness(ops_s3_prefix, run_date, readiness_payload)

    return {
        "status": "ok",
        "run_date": run_date,
        "ready": bool(check["ready"]),
        "redispatched": re_dispatched,
        "readiness_uri": readiness_uri,
        "missing_prices_count": check["missing_prices_count"],
        "missing_features_count": check["missing_features_count"],
        "benchmark_ok": check["benchmark_ok"],
    }
