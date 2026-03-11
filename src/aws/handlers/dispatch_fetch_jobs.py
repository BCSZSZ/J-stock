import json
import os
from datetime import datetime
from typing import Any, Dict, List
from urllib.parse import urlparse

from src.aws.job_splitter import build_fetch_jobs


def _load_monitor_list_from_s3(s3_uri: str) -> List[str]:
    parsed = urlparse(s3_uri)
    bucket = parsed.netloc
    key = parsed.path.lstrip("/")

    import boto3

    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    payload = json.loads(body)
    raw = payload.get("tickers", []) if isinstance(payload, dict) else payload
    result: List[str] = []
    for item in raw:
        if isinstance(item, dict):
            code = item.get("code")
        else:
            code = item
        if code:
            result.append(str(code).strip())
    return result


def _resolve_tickers(event: Dict[str, Any]) -> List[str]:
    if event.get("tickers"):
        return [str(t).strip() for t in event["tickers"] if str(t).strip()]

    monitor_s3_uri = event.get("monitor_list_s3_uri") or os.getenv("MONITOR_LIST_S3_URI", "")
    if monitor_s3_uri.startswith("s3://"):
        return _load_monitor_list_from_s3(monitor_s3_uri)

    return []


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    queue_url = os.getenv("FETCH_JOB_QUEUE_URL", "")
    if not queue_url:
        raise ValueError("FETCH_JOB_QUEUE_URL is required")

    tickers = _resolve_tickers(event)
    tickers_per_job = int(event.get("tickers_per_job", os.getenv("TICKERS_PER_JOB", "100")))
    update_aux_data = bool(
        event.get("update_aux_data", str(os.getenv("UPDATE_AUX_DATA", "false")).lower() == "true")
    )
    jobs = build_fetch_jobs(tickers=tickers, tickers_per_job=tickers_per_job)

    import boto3

    sqs = boto3.client("sqs")
    run_date = event.get("run_date") or datetime.utcnow().strftime("%Y-%m-%d")

    sent = 0
    for job in jobs:
        payload = {
            "run_date": run_date,
            "job_index": job["job_index"],
            "ticker_count": job["ticker_count"],
            "tickers": job["tickers"],
            "recompute_features": bool(event.get("recompute_features", False)),
            "fix_gaps": bool(event.get("fix_gaps", False)),
            "update_aux_data": update_aux_data,
        }
        sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload, ensure_ascii=False))
        sent += 1

    return {
        "status": "ok",
        "run_date": run_date,
        "total_tickers": len(tickers),
        "jobs_sent": sent,
        "tickers_per_job": tickers_per_job,
        "update_aux_data": update_aux_data,
    }
