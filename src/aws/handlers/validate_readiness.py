import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


JST = timezone(timedelta(hours=9))


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


def _load_monitor_tickers(monitor_s3_uri: str) -> List[str]:
    bucket, key = _parse_s3_uri(monitor_s3_uri)
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    payload = json.loads(body)
    raw = payload.get("tickers", []) if isinstance(payload, dict) else payload

    out: List[str] = []
    for item in raw:
        code = item.get("code") if isinstance(item, dict) else item
        if code:
            out.append(str(code).strip())
    return [x for x in out if x]


def _head_ok_for_date(s3, bucket: str, key: str, run_date: str) -> bool:
    try:
        resp = s3.head_object(Bucket=bucket, Key=key)
    except ClientError:
        return False

    last_modified = resp["LastModified"].astimezone(JST).strftime("%Y-%m-%d")
    return last_modified == run_date


def _validate_data_freshness(data_s3_prefix: str, tickers: List[str], run_date: str) -> Dict[str, Any]:
    s3 = boto3.client("s3")
    bucket, prefix = _parse_s3_prefix(data_s3_prefix)

    missing_prices: List[str] = []
    missing_features: List[str] = []

    for t in tickers:
        price_key = f"{prefix}/raw_prices/{t}.parquet" if prefix else f"raw_prices/{t}.parquet"
        feature_key = f"{prefix}/features/{t}_features.parquet" if prefix else f"features/{t}_features.parquet"

        if not _head_ok_for_date(s3, bucket, price_key, run_date):
            missing_prices.append(t)
        if not _head_ok_for_date(s3, bucket, feature_key, run_date):
            missing_features.append(t)

    bench_key = f"{prefix}/benchmarks/topix_daily.parquet" if prefix else "benchmarks/topix_daily.parquet"
    benchmark_ok = _head_ok_for_date(s3, bucket, bench_key, run_date)

    ready = (not missing_prices) and (not missing_features) and benchmark_ok
    return {
        "ready": ready,
        "missing_prices_count": len(missing_prices),
        "missing_features_count": len(missing_features),
        "missing_prices_sample": missing_prices[:30],
        "missing_features_sample": missing_features[:30],
        "benchmark_ok": benchmark_ok,
    }


def _write_readiness(ops_s3_prefix: str, run_date: str, payload: Dict[str, Any]) -> str:
    bucket, prefix = _parse_s3_prefix(ops_s3_prefix)
    key = f"{prefix}/run_status/date={run_date}/readiness.json" if prefix else f"run_status/date={run_date}/readiness.json"
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"


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
    tickers = _load_monitor_tickers(monitor_s3_uri)

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
