import os
from pathlib import Path
from typing import List, Set, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


def _parse_s3_prefix(s3_uri_prefix: str) -> Tuple[str, str]:
    parsed = urlparse(s3_uri_prefix)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid S3 URI prefix: {s3_uri_prefix}")
    bucket = parsed.netloc
    prefix = parsed.path.lstrip("/").rstrip("/")
    return bucket, prefix


def _ticker_relative_paths(ticker: str, include_aux: bool = False) -> List[str]:
    t = str(ticker).strip()
    base = [
        f"raw_prices/{t}.parquet",
        f"features/{t}_features.parquet",
    ]
    if include_aux:
        base.extend(
            [
        f"raw_trades/{t}_trades.parquet",
        f"raw_financials/{t}_financials.parquet",
        f"metadata/{t}_metadata.json",
            ]
        )
    return base


def _optional_common_paths() -> List[str]:
    return [
        "benchmarks/topix_daily.parquet",
    ]


def _download_if_exists(s3_client, bucket: str, key: str, target_file: Path) -> bool:
    try:
        obj = s3_client.get_object(Bucket=bucket, Key=key)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_bytes(obj["Body"].read())
        return True
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return False
        raise


def _normalized_layers(layers: List[str] | None) -> Set[str]:
    if not layers:
        return {"prices", "features", "benchmark"}
    normalized = {str(x).strip().lower() for x in layers if str(x).strip()}
    return normalized or {"prices", "features", "benchmark"}


def _build_rel_paths_for_layers(tickers: List[str], layers: Set[str]) -> List[str]:
    include_aux = "aux" in layers
    rel_paths: List[str] = []

    if "prices" in layers or "features" in layers or include_aux:
        for ticker in tickers:
            all_paths = _ticker_relative_paths(ticker, include_aux=include_aux)
            for p in all_paths:
                if p.startswith("raw_prices/") and "prices" not in layers:
                    continue
                if p.startswith("features/") and "features" not in layers:
                    continue
                rel_paths.append(p)

    if "benchmark" in layers:
        rel_paths.extend(_optional_common_paths())

    return rel_paths


def download_seed_for_job(
    s3_uri_prefix: str, data_root: str, tickers: List[str], layers: List[str] | None = None
) -> int:
    bucket, prefix = _parse_s3_prefix(s3_uri_prefix)
    s3 = boto3.client("s3")
    downloaded = 0

    rel_paths = _build_rel_paths_for_layers(tickers, _normalized_layers(layers))

    root = Path(data_root)
    for rel in rel_paths:
        key = f"{prefix}/{rel}" if prefix else rel
        target = root / rel
        if _download_if_exists(s3, bucket, key, target):
            downloaded += 1

    return downloaded


def _upload_file(s3_client, source_file: Path, bucket: str, key: str) -> None:
    s3_client.put_object(Bucket=bucket, Key=key, Body=source_file.read_bytes())


def upload_outputs_for_job(
    s3_uri_prefix: str, data_root: str, tickers: List[str], layers: List[str] | None = None
) -> int:
    bucket, prefix = _parse_s3_prefix(s3_uri_prefix)
    s3 = boto3.client("s3")
    uploaded = 0

    rel_paths = _build_rel_paths_for_layers(tickers, _normalized_layers(layers))

    root = Path(data_root)
    for rel in rel_paths:
        source = root / rel
        if not source.exists() or not source.is_file():
            continue
        key = f"{prefix}/{rel}" if prefix else rel
        _upload_file(s3, source, bucket, key)
        uploaded += 1

    # Upload latest ETL summary for troubleshooting.
    reports_dir = root / "metadata" / "reports"
    if reports_dir.exists():
        summaries = sorted(
            [p for p in reports_dir.glob("etl_summary_*.json") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if summaries:
            latest = summaries[0]
            rel = f"metadata/reports/{latest.name}"
            key = f"{prefix}/{rel}" if prefix else rel
            _upload_file(s3, latest, bucket, key)
            uploaded += 1

    return uploaded


def is_s3_prefix(value: str) -> bool:
    return str(value or "").strip().lower().startswith("s3://")
