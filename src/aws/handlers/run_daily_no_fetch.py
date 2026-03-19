import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import boto3

from src.aws.s3_data_sync import download_seed_for_job, is_s3_prefix


JST = timezone(timedelta(hours=9))
DEFAULT_REPORT_URL_TTL_SECONDS = 60 * 60 * 24 * 3


def _parse_s3_uri(s3_uri: str) -> tuple[str, str]:
    parsed = urlparse(s3_uri)
    if parsed.scheme != "s3" or not parsed.netloc:
        raise ValueError(f"Invalid s3 uri: {s3_uri}")
    return parsed.netloc, parsed.path.lstrip("/")


def _download_text_json(s3_uri: str, target: Path) -> Dict[str, Any]:
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    return json.loads(body)


def _download_if_exists(s3_uri: str, target: Path) -> bool:
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    except Exception:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(body)
    return True


def _upload_file(s3_uri: str, source: Path) -> None:
    if not source.exists() or not source.is_file():
        return
    bucket, key = _parse_s3_uri(s3_uri)
    s3 = boto3.client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=source.read_bytes())


def _build_presigned_download_url(s3_uri: str, expires_in: int | None = None) -> str | None:
    bucket, key = _parse_s3_uri(s3_uri)
    ttl = expires_in or int(
        os.getenv("REPORT_URL_TTL_SECONDS", DEFAULT_REPORT_URL_TTL_SECONDS)
    )
    ttl = max(60, min(int(ttl), 60 * 60 * 24 * 7))
    try:
        s3 = boto3.client("s3")
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=ttl,
        )
    except Exception:
        return None


def _resolve_monitor_tickers(monitor_file: Path) -> List[str]:
    payload = json.loads(monitor_file.read_text(encoding="utf-8"))
    raw = payload.get("tickers", []) if isinstance(payload, dict) else payload
    out = []
    for item in raw:
        if isinstance(item, dict):
            code = item.get("code")
        else:
            code = item
        if code:
            out.append(str(code).strip())
    return [x for x in out if x]


def _build_runtime_config(base_config_path: Path, runtime_root: Path, monitor_local_path: Path) -> Path:
    base = json.loads(base_config_path.read_text(encoding="utf-8"))

    data_dir = runtime_root / "data"
    output_root = runtime_root / "output"
    state_root = output_root / "state"

    base.setdefault("runtime", {})
    base["runtime"]["mode"] = "aws"
    base["runtime"]["storage_backend"] = "local_fs"
    base["runtime"]["state_backend"] = "json"

    base.setdefault("data", {})
    base["data"]["data_dir"] = str(data_dir)
    base["data"]["monitor_list_file"] = str(monitor_local_path)

    base.setdefault("evaluation", {})
    base["evaluation"]["output_dir"] = str(output_root / "strategy_evaluation")

    base.setdefault("production", {})
    base["production"]["monitor_list_file"] = str(monitor_local_path)
    base["production"]["state_file"] = str(state_root / "production_state.json")
    base["production"]["history_file"] = str(state_root / "trade_history.json")
    base["production"]["cash_history_file"] = str(state_root / "cash_history.json")
    base["production"]["fetch_universe_file"] = str(state_root / "fetch_universe.json")
    base["production"]["sector_pool_file"] = str(data_dir / "universe" / "sector_pool")
    base["production"]["signal_file_pattern"] = str(output_root / "signals" / "{date}.json")
    base["production"]["report_file_pattern"] = str(output_root / "reports" / "{date}.md")

    runtime_root.mkdir(parents=True, exist_ok=True)
    cfg_path = runtime_root / "config.runtime.aws-no-fetch.json"
    cfg_path.write_text(json.dumps(base, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg_path


def _send_notification_if_configured(subject: str, body: str) -> None:
    topic_arn = os.getenv("NOTIFY_SNS_TOPIC_ARN", "").strip()
    if not topic_arn:
        return
    sns = boto3.client("sns")
    sns.publish(TopicArn=topic_arn, Subject=subject[:100], Message=body)


def _jst_today_str() -> str:
    return datetime.now(timezone.utc).astimezone(JST).strftime("%Y-%m-%d")


def _read_readiness(ops_s3_prefix: str, run_date: str) -> Dict[str, Any] | None:
    bucket, prefix = _parse_s3_uri(ops_s3_prefix)
    key_prefix = prefix.rstrip("/")
    key = f"{key_prefix}/run_status/date={run_date}/readiness.json" if key_prefix else f"run_status/date={run_date}/readiness.json"
    s3 = boto3.client("s3")
    try:
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    except Exception:
        return None
    return json.loads(body)


def _format_readiness_summary(readiness: Dict[str, Any] | None) -> str:
    if not readiness:
        return "readiness: missing"
    return (
        f"readiness.ready={bool(readiness.get('ready', False))}, "
        f"missing_prices_count={int(readiness.get('missing_prices_count', 0))}, "
        f"missing_features_count={int(readiness.get('missing_features_count', 0))}, "
        f"benchmark_ok={bool(readiness.get('benchmark_ok', False))}, "
        f"redispatched={bool(readiness.get('redispatched', False))}"
    )


def _build_notification_body(
    readiness: Dict[str, Any] | None,
    result_summary: str,
    report_s3_uri: str | None = None,
    report_download_url: str | None = None,
) -> str:
    lines = [_format_readiness_summary(readiness), "", result_summary]

    if report_s3_uri:
        ttl_seconds = max(
            60,
            min(
                int(os.getenv("REPORT_URL_TTL_SECONDS", DEFAULT_REPORT_URL_TTL_SECONDS)),
                60 * 60 * 24 * 7,
            ),
        )
        ttl_hours = ttl_seconds / 3600
        lines.extend(["", f"Report S3: {report_s3_uri}"])
        if report_download_url:
            lines.append(f"Report Download URL (expires in {ttl_hours:.0f}h): {report_download_url}")

    return "\n".join(lines)


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    monitor_s3_uri = os.getenv("MONITOR_LIST_S3_URI", "").strip()
    data_s3_prefix = os.getenv("DATA_S3_PREFIX", "").strip()
    ops_s3_prefix = os.getenv("OPS_S3_PREFIX", "").strip()

    if not monitor_s3_uri.startswith("s3://"):
        raise ValueError("MONITOR_LIST_S3_URI must be s3://...")
    if not is_s3_prefix(data_s3_prefix):
        raise ValueError("DATA_S3_PREFIX must be s3://...")
    if not is_s3_prefix(ops_s3_prefix):
        raise ValueError("OPS_S3_PREFIX must be s3://...")

    run_date = event.get("run_date") or _jst_today_str()
    readiness = _read_readiness(ops_s3_prefix, run_date)
    if not readiness or not bool(readiness.get("ready", False)):
        reason = "missing_readiness" if readiness is None else "readiness_not_ready"
        _send_notification_if_configured(
            subject=f"[JSA] daily --no-fetch SKIPPED {run_date}",
            body=f"Skipped daily run because readiness gate failed: {reason}\n"
            f"{_format_readiness_summary(readiness)}\n"
            f"readiness_raw={json.dumps(readiness, ensure_ascii=False) if readiness else 'null'}",
        )
        return {
            "status": "skipped",
            "run_date": run_date,
            "reason": reason,
            "readiness": readiness,
        }

    repo_root = Path(__file__).resolve().parents[3]
    runtime_root = Path("/tmp/jsa_runtime")
    monitor_local = runtime_root / "state" / "production_monitor_list.json"

    _download_text_json(monitor_s3_uri, monitor_local)
    tickers = _resolve_monitor_tickers(monitor_local)

    # Pull latest data/state into local runtime folder.
    download_seed_for_job(data_s3_prefix, str(runtime_root / "data"), tickers)
    _download_if_exists(f"{ops_s3_prefix.rstrip('/')}/state/production_state.json", runtime_root / "output" / "state" / "production_state.json")
    _download_if_exists(f"{ops_s3_prefix.rstrip('/')}/state/trade_history.json", runtime_root / "output" / "state" / "trade_history.json")
    _download_if_exists(f"{ops_s3_prefix.rstrip('/')}/state/cash_history.json", runtime_root / "output" / "state" / "cash_history.json")

    cfg_path = _build_runtime_config(repo_root / "config.local.json", runtime_root, monitor_local)

    env = os.environ.copy()
    env["JSA_CONFIG_FILE"] = str(cfg_path)
    layer_python_path = "/opt/python"
    existing_python_path = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = (
        f"{layer_python_path}:{existing_python_path}" if existing_python_path else layer_python_path
    )

    cmd = [sys.executable, "main.py", "production", "--daily", "--skip-fetch"]
    run = subprocess.run(cmd, cwd=str(repo_root), env=env, capture_output=True, text=True)

    # Push state/signal/report outputs back to S3 ops prefix.
    _upload_file(f"{ops_s3_prefix.rstrip('/')}/state/production_state.json", runtime_root / "output" / "state" / "production_state.json")
    _upload_file(f"{ops_s3_prefix.rstrip('/')}/state/trade_history.json", runtime_root / "output" / "state" / "trade_history.json")
    _upload_file(f"{ops_s3_prefix.rstrip('/')}/state/cash_history.json", runtime_root / "output" / "state" / "cash_history.json")

    signals_s3_uri = f"{ops_s3_prefix.rstrip('/')}/signals/{run_date}.json"
    report_s3_uri = f"{ops_s3_prefix.rstrip('/')}/reports/{run_date}.md"
    _upload_file(signals_s3_uri, runtime_root / "output" / "signals" / f"{run_date}.json")
    _upload_file(report_s3_uri, runtime_root / "output" / "reports" / f"{run_date}.md")

    ok = run.returncode == 0
    result_summary = run.stdout[-3000:] if ok else (run.stderr or run.stdout)[-3000:]
    report_download_url = None
    report_local_path = runtime_root / "output" / "reports" / f"{run_date}.md"
    if report_local_path.exists():
        report_download_url = _build_presigned_download_url(report_s3_uri)
    _send_notification_if_configured(
        subject=f"[JSA] daily --no-fetch {'SUCCESS' if ok else 'FAILED'} {run_date}",
        body=_build_notification_body(
            readiness=readiness,
            result_summary=result_summary,
            report_s3_uri=report_s3_uri if report_local_path.exists() else None,
            report_download_url=report_download_url,
        ),
    )

    return {
        "status": "ok" if ok else "error",
        "run_date": run_date,
        "return_code": run.returncode,
        "stdout_tail": run.stdout[-1000:],
        "stderr_tail": run.stderr[-1000:],
    }
