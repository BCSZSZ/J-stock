import json
import logging
import os
from typing import Any, Dict, List, Union

from src.aws.s3_data_sync import (
    download_seed_for_job,
    is_s3_prefix,
    upload_outputs_for_job,
)
from src.client.jquants_client import JQuantsV2Client
from src.data.benchmark_manager import update_benchmarks
from src.data.pipeline import StockETLPipeline


logger = logging.getLogger(__name__)


def _load_api_key() -> str:
    # Keep deployment simple: API key is provided only via environment variable.
    api_key = os.getenv("JQUANTS_API_KEY", "").strip()
    return api_key


def _extract_ticker_code(raw: Union[Dict[str, str], str, int]) -> str:
    """Extract plain ticker code string from raw ticker (str, int, or dict with 'code' key)."""
    if isinstance(raw, dict):
        return str(raw.get("code", "")).strip()
    return str(raw).strip()


def _refresh_benchmark_if_needed(
    *, api_key: str, data_root: str, recompute_features: bool
) -> Dict[str, object]:
    if recompute_features:
        return {
            "attempted": False,
            "success": True,
            "topix_records": 0,
            "error": None,
        }

    result = update_benchmarks(JQuantsV2Client(api_key), data_root=data_root)
    if result["success"]:
        logger.info(
            "Benchmark refresh completed before batch ETL: topix_records=%s",
            result["topix_records"],
        )
    else:
        logger.warning(
            "Benchmark refresh issue before batch ETL: %s",
            result.get("error", "unknown"),
        )

    return {
        "attempted": True,
        "success": bool(result["success"]),
        "topix_records": int(result["topix_records"]),
        "error": result.get("error"),
    }


def _process_job(job: Dict[str, Any]) -> Dict[str, Any]:
    tickers: List[str] = [c for t in job.get("tickers", []) if (c := _extract_ticker_code(t))]
    if not tickers:
        return {"status": "skip", "reason": "empty_tickers"}

    recompute_features = bool(job.get("recompute_features", False))
    api_key = _load_api_key()
    if not api_key and not recompute_features:
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

    benchmark_refresh = _refresh_benchmark_if_needed(
        api_key=api_key,
        data_root=data_root,
        recompute_features=recompute_features,
    )

    pipeline = StockETLPipeline(api_key=api_key, data_root=data_root)

    summary = pipeline.run_batch(
        tickers=tickers,
        fetch_aux_data=(
            update_aux_data and not recompute_features
        ),
        recompute_features=recompute_features,
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
        "benchmark_refresh_attempted": benchmark_refresh["attempted"],
        "benchmark_refresh_success": benchmark_refresh["success"],
        "benchmark_topix_records": benchmark_refresh["topix_records"],
        "benchmark_refresh_error": benchmark_refresh["error"],
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
