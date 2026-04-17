import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

import boto3

from src.aws.jpx_holidays import is_jpx_trading_day
from src.aws.ticker_universe import resolve_fetch_tickers
from src.aws.job_splitter import build_fetch_jobs

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    queue_url = os.getenv("FETCH_JOB_QUEUE_URL", "")
    if not queue_url:
        raise ValueError("FETCH_JOB_QUEUE_URL is required")

    run_date_str = event.get("run_date") or datetime.now(timezone.utc).astimezone(JST).strftime("%Y-%m-%d")
    run_date = date.fromisoformat(run_date_str)

    if not event.get("force") and not is_jpx_trading_day(run_date):
        logger.info("Skipping dispatch: %s is not a JPX trading day", run_date_str)
        return {"status": "skipped", "run_date": run_date_str, "reason": "jpx_holiday"}

    universe = resolve_fetch_tickers(event)
    tickers = universe["tickers"]
    tickers_per_job = int(event.get("tickers_per_job", os.getenv("TICKERS_PER_JOB", "100")))
    update_aux_data = bool(
        event.get("update_aux_data", str(os.getenv("UPDATE_AUX_DATA", "false")).lower() == "true")
    )
    jobs = build_fetch_jobs(tickers=tickers, tickers_per_job=tickers_per_job)

    sqs = boto3.client("sqs")

    sent = 0
    for job in jobs:
        payload = {
            "run_date": run_date_str,
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
        "run_date": run_date_str,
        "total_tickers": len(tickers),
        "monitor_tickers": universe["monitor_count"],
        "sector_pool_tickers": universe["sector_pool_count"],
        "sector_pool_s3_uri": universe["sector_pool_s3_uri"],
        "jobs_sent": sent,
        "tickers_per_job": tickers_per_job,
        "update_aux_data": update_aux_data,
    }
