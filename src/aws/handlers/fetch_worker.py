import json
import os
from typing import Any, Dict, List

from src.aws.s3_data_sync import (
    download_seed_for_job,
    is_s3_prefix,
    upload_outputs_for_job,
)
from src.data.pipeline import StockETLPipeline


def _load_api_key() -> str:
    # Keep deployment simple: API key is provided only via environment variable.
    api_key = os.getenv("JQUANTS_API_KEY", "").strip()
    return api_key


def _process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    tickers: List[str] = [str(t).strip() for t in job.get("tickers", []) if str(t).strip()]
    if not tickers:
        return {"status": "skip", "reason": "empty_tickers"}

    api_key = _load_api_key()
    if not api_key and not bool(job.get("recompute_features", False)):
        raise ValueError("JQUANTS_API_KEY missing and recompute_features is false")

    data_root = os.getenv("DATA_ROOT", "/tmp/data")
    data_s3_prefix = os.getenv("DATA_S3_PREFIX", "").strip()
    update_aux_data = bool(job.get("update_aux_data", False))
    sync_layers = ["prices", "features", "benchmark"]
    if update_aux_data:
        sync_layers.append("aux")

    downloaded_files = 0
    uploaded_files = 0
    if is_s3_prefix(data_s3_prefix):
        downloaded_files = download_seed_for_job(
            s3_uri_prefix=data_s3_prefix,
            data_root=data_root,
            tickers=tickers,
            layers=sync_layers,
        )

    pipeline = StockETLPipeline(api_key=api_key, data_root=data_root)

    summary = pipeline.run_batch(
        tickers=tickers,
        fetch_aux_data=(
            update_aux_data and not bool(job.get("recompute_features", False))
        ),
        recompute_features=bool(job.get("recompute_features", False)),
        fix_gaps=bool(job.get("fix_gaps", False)),
    )

    if is_s3_prefix(data_s3_prefix):
        uploaded_files = upload_outputs_for_job(
            s3_uri_prefix=data_s3_prefix,
            data_root=data_root,
            tickers=tickers,
            layers=sync_layers,
        )

    return {
        "status": "ok",
        "job_index": job.get("job_index"),
        "run_date": job.get("run_date"),
        "total": summary.get("total", 0),
        "successful": summary.get("successful", 0),
        "failed": summary.get("failed", 0),
        "downloaded_files": downloaded_files,
        "uploaded_files": uploaded_files,
        "update_aux_data": update_aux_data,
    }


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    # SQS trigger sends Records.
    records = event.get("Records", [])
    results = []
    for record in records:
        body = record.get("body", "{}")
        payload = json.loads(body)
        results.append(_process_job(payload))

    return {"status": "ok", "results": results, "record_count": len(records)}
