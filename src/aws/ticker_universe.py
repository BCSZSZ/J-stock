import csv
import io
import json
import os
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import boto3


def _parse_s3_uri(s3_uri: str) -> Tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid s3 uri: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _load_monitor_list_from_s3(s3_uri: str) -> List[str]:
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    payload = json.loads(body)
    raw = payload.get("tickers", []) if isinstance(payload, dict) else payload

    result: List[str] = []
    for item in raw:
        code = item.get("code") if isinstance(item, dict) else item
        if code:
            result.append(str(code).strip())
    return [x for x in result if x]


def _list_sector_pool_csv_candidates(bucket: str, prefix: str) -> List[Dict[str, Any]]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    candidates: List[Dict[str, Any]] = []

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = str(obj.get("Key", ""))
            name = key.split("/")[-1]
            if not name.startswith("sector_pool_"):
                continue
            if not name.endswith(".csv"):
                continue
            if "summary" in name:
                continue
            candidates.append(obj)
    return candidates


def _load_sector_pool_tickers_from_s3(s3_uri: str) -> List[str]:
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    reader = csv.DictReader(io.StringIO(body))
    if not reader.fieldnames:
        return []

    code_field = None
    for field in reader.fieldnames:
        if str(field).strip().lower() == "code":
            code_field = field
            break
    if code_field is None:
        code_field = reader.fieldnames[0]

    out: List[str] = []
    for row in reader:
        raw = row.get(code_field)
        if raw is None:
            continue
        code = str(raw).strip()
        if not code:
            continue
        out.append(code.zfill(4) if code.isdigit() else code)
    return out


def _resolve_sector_pool_s3_uri(data_s3_prefix: str) -> str:
    configured = os.getenv("SECTOR_POOL_S3_URI", "").strip()
    if configured.startswith("s3://"):
        return configured

    if not data_s3_prefix.startswith("s3://"):
        return ""

    return f"{data_s3_prefix.rstrip('/')}/universe/sector_pool/"


def _pick_latest_sector_pool_csv(s3_uri_or_prefix: str) -> str:
    bucket, key = _parse_s3_uri(s3_uri_or_prefix)

    if key.endswith(".csv"):
        return s3_uri_or_prefix

    prefix = key.rstrip("/") + "/" if key else ""
    candidates = _list_sector_pool_csv_candidates(bucket, prefix)
    if not candidates:
        return ""

    latest = max(candidates, key=lambda x: x.get("LastModified"))
    return f"s3://{bucket}/{latest['Key']}"


def resolve_fetch_tickers(event: Dict[str, Any]) -> Dict[str, Any]:
    if event.get("tickers"):
        explicit = [str(t).strip() for t in event["tickers"] if str(t).strip()]
        merged = sorted(set(explicit))
        return {
            "tickers": merged,
            "monitor_count": len(merged),
            "sector_pool_count": 0,
            "sector_pool_s3_uri": None,
            "source": "event.tickers",
        }

    monitor_s3_uri = (event.get("monitor_list_s3_uri") or os.getenv("MONITOR_LIST_S3_URI", "")).strip()
    data_s3_prefix = os.getenv("DATA_S3_PREFIX", "").strip()

    if not monitor_s3_uri.startswith("s3://"):
        return {
            "tickers": [],
            "monitor_count": 0,
            "sector_pool_count": 0,
            "sector_pool_s3_uri": None,
            "source": "missing_monitor_s3_uri",
        }

    monitor_tickers = _load_monitor_list_from_s3(monitor_s3_uri)

    sector_pool_base = (event.get("sector_pool_s3_uri") or _resolve_sector_pool_s3_uri(data_s3_prefix)).strip()
    sector_pool_uri = _pick_latest_sector_pool_csv(sector_pool_base) if sector_pool_base.startswith("s3://") else ""

    sector_tickers: List[str] = []
    if sector_pool_uri:
        sector_tickers = _load_sector_pool_tickers_from_s3(sector_pool_uri)

    merged = sorted(set(monitor_tickers) | set(sector_tickers))
    return {
        "tickers": merged,
        "monitor_count": len(set(monitor_tickers)),
        "sector_pool_count": len(set(sector_tickers)),
        "sector_pool_s3_uri": sector_pool_uri or None,
        "source": "monitor_plus_sector_pool",
    }