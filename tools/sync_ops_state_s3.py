import argparse
import json
import subprocess
from pathlib import Path


def upload_file(s3_uri: str, local_file: Path):
    if not local_file.exists():
        return False
    cmd = ["aws", "s3", "cp", str(local_file), s3_uri]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or run.stdout.strip())
    return True


def download_file(s3_uri: str, local_file: Path):
    local_file.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["aws", "s3", "cp", s3_uri, str(local_file)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    if run.returncode != 0:
        raise RuntimeError(run.stderr.strip() or run.stdout.strip())
    return True


def main():
    ap = argparse.ArgumentParser(description="Sync production state files between local and S3")
    ap.add_argument("mode", choices=["push", "pull"])
    ap.add_argument("--ops-s3-prefix", required=True, help="e.g. s3://bucket/prod/ops")
    ap.add_argument("--config", default="G:/My Drive/AI-Stock-Sync/config.json")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    prod = cfg.get("production", {})

    mappings = [
        (Path(prod.get("state_file", "output/state/production_state.json")), f"{args.ops_s3_prefix.rstrip('/')}/state/production_state.json"),
        (Path(prod.get("history_file", "output/state/trade_history.json")), f"{args.ops_s3_prefix.rstrip('/')}/state/trade_history.json"),
        (Path(prod.get("cash_history_file", "output/state/cash_history.json")), f"{args.ops_s3_prefix.rstrip('/')}/state/cash_history.json"),
        (Path(prod.get("monitor_list_file", "data/production_monitor_list.json")), f"{args.ops_s3_prefix.rstrip('/')}/config/production_monitor_list.json"),
    ]

    ok = 0
    for local, s3_uri in mappings:
        if args.mode == "push":
            if upload_file(s3_uri, local):
                print(f"[PUSH] {local} -> {s3_uri}")
                ok += 1
        else:
            try:
                download_file(s3_uri, local)
                print(f"[PULL] {s3_uri} -> {local}")
                ok += 1
            except Exception as e:
                print(f"[SKIP] {s3_uri}: {e}")

    print(f"done, synced={ok}")


if __name__ == "__main__":
    main()
