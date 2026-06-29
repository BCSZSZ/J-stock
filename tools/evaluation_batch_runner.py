#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
DEFAULT_SPEC_PATH = TMP_ROOT / "evaluationtmp.json"
DEFAULT_RUNS_ROOT = TMP_ROOT / "parallel_eval"
DEFAULT_MAX_WORKERS = 8

_OUTPUT_DIR_RE = re.compile(r"本次输出目录:\s*([^\r\n]+)")
_SUMMARY_HEARTBEAT_WRITE_INTERVAL_SECONDS = 5.0


def _timestamp_now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    return slug.strip("_") or "worker"


class WorkerJobSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1)
    job_name: str = Field(min_length=1)
    command: str = Field(default="evaluate", min_length=1)
    base_args: list[str] = Field(default_factory=list)
    exit_strategies: list[str] = Field(default_factory=list)
    expected_output_root: str | None = None
    job_group: str | None = None
    notes: str | None = None

    @field_validator("worker_id", "job_name", "command", mode="before")
    @classmethod
    def _normalize_scalar(cls, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must be non-empty")
        return text

    @field_validator("base_args", mode="before")
    @classmethod
    def _normalize_base_args(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("base_args must be a list of strings")
        normalized = [str(item).strip() for item in value if str(item).strip()]
        disallowed = {"uv", "run", "python", "main.py", "--exit-strategies"}
        for item in normalized:
            if item in disallowed:
                raise ValueError(
                    "base_args must not include wrapper tokens or --exit-strategies"
                )
        return normalized

    @field_validator("exit_strategies", mode="before")
    @classmethod
    def _normalize_exit_strategies(cls, value: object) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("exit_strategies must be a list of strings")
        return [str(item).strip() for item in value if str(item).strip()]


class BatchManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    max_workers: int = Field(default=DEFAULT_MAX_WORKERS, ge=1)
    jobs: list[WorkerJobSpec] = Field(min_length=1)


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str
    job_name: str
    command: str
    exit_strategies: list[str]
    full_command: str
    start_time: str | None = None
    end_time: str | None = None
    exit_code: int | None = None
    log_file: str
    worker_pid: int | None = None
    output_dir: str | None = None
    last_output_at: str | None = None
    output_line_count: int = 0
    status: Literal["pending", "running", "completed", "failed"]


class RunnerSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest_path: str
    repo_root: str
    run_dir: str
    max_workers: int = Field(ge=1)
    started_at: str
    finished_at: str | None = None
    failed_worker_count: int = 0
    workers: list[WorkerStatus]


def load_manifest(spec_path: Path) -> BatchManifest:
    text = spec_path.read_text(encoding="utf-8-sig")
    return BatchManifest.model_validate(json.loads(text))


def build_worker_command(job: WorkerJobSpec) -> list[str]:
    command = ["uv", "run", "python", "main.py", job.command, *job.base_args]
    if job.exit_strategies:
        command.extend(["--exit-strategies", *job.exit_strategies])
    return command


def parse_output_dir(text: str) -> str | None:
    explicit = _OUTPUT_DIR_RE.search(text)
    if explicit is not None:
        return explicit.group(1).strip().rstrip(".")
    return None


def write_worker_output_sidecar(
    job: WorkerJobSpec,
    run_dir: Path,
    log_file: Path,
    output_dir: str | None,
    exit_code: int,
) -> None:
    if not output_dir:
        return

    output_path = Path(output_dir)
    if not output_path.exists():
        return

    payload = {
        "schema_version": 1,
        "recorded_at": _timestamp_now(),
        "worker_id": job.worker_id,
        "job_name": job.job_name,
        "job_group": job.job_group,
        "command": job.command,
        "base_args": list(job.base_args),
        "exit_strategies": list(job.exit_strategies),
        "expected_output_root": job.expected_output_root,
        "notes": job.notes,
        "full_command": " ".join(build_worker_command(job)),
        "exit_code": int(exit_code),
        "runner_run_dir": str(run_dir),
        "runner_summary_json": str(run_dir / "summary.json"),
        "log_file": str(log_file),
        "output_dir": str(output_path),
    }
    sidecar_path = output_path / f"evaluation_batch_job_{_slugify(job.worker_id)}.json"
    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _initial_summary(
    manifest: BatchManifest,
    spec_path: Path,
    run_dir: Path,
    max_workers: int,
) -> RunnerSummary:
    workers: list[WorkerStatus] = []
    for job in manifest.jobs:
        log_file = run_dir / f"{_slugify(job.worker_id)}__{_slugify(job.job_name)}.log"
        workers.append(
            WorkerStatus(
                worker_id=job.worker_id,
                job_name=job.job_name,
                command=job.command,
                exit_strategies=list(job.exit_strategies),
                full_command=" ".join(build_worker_command(job)),
                log_file=str(log_file),
                status="pending",
            )
        )
    return RunnerSummary(
        manifest_path=str(spec_path),
        repo_root=str(REPO_ROOT),
        run_dir=str(run_dir),
        max_workers=max_workers,
        started_at=_timestamp_now(),
        workers=workers,
    )


class SummaryTracker:
    def __init__(self, summary: RunnerSummary, summary_path: Path) -> None:
        self._summary = summary
        self._summary_path = summary_path
        self._lock = threading.Lock()
        self._last_write_monotonic = 0.0
        self.write()

    def write(self) -> None:
        self._summary_path.write_text(
            json.dumps(self._summary.model_dump(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._last_write_monotonic = monotonic()

    def mark_running(self, worker_id: str, worker_pid: int | None) -> None:
        with self._lock:
            worker = self._find(worker_id)
            worker.status = "running"
            worker.start_time = _timestamp_now()
            worker.worker_pid = worker_pid
            self.write()

    def record_output(self, worker_id: str, line: str) -> None:
        with self._lock:
            worker = self._find(worker_id)
            worker.output_line_count += 1
            worker.last_output_at = _timestamp_now()

            discovered_output_dir = parse_output_dir(line)
            output_dir_changed = False
            if discovered_output_dir is not None and discovered_output_dir != worker.output_dir:
                worker.output_dir = discovered_output_dir
                output_dir_changed = True

            should_write = (
                worker.output_line_count == 1
                or output_dir_changed
                or monotonic() - self._last_write_monotonic
                >= _SUMMARY_HEARTBEAT_WRITE_INTERVAL_SECONDS
            )
            if should_write:
                self.write()

    def mark_finished(self, worker_id: str, exit_code: int, output_dir: str | None) -> None:
        with self._lock:
            worker = self._find(worker_id)
            worker.end_time = _timestamp_now()
            worker.exit_code = exit_code
            if output_dir is not None:
                worker.output_dir = output_dir
            worker.status = "completed" if exit_code == 0 else "failed"
            self._summary.failed_worker_count = sum(
                1 for item in self._summary.workers if item.status == "failed"
            )
            self.write()

    def finish(self) -> RunnerSummary:
        with self._lock:
            self._summary.finished_at = _timestamp_now()
            self._summary.failed_worker_count = sum(
                1 for item in self._summary.workers if item.status == "failed"
            )
            self.write()
            return self._summary

    def _find(self, worker_id: str) -> WorkerStatus:
        for worker in self._summary.workers:
            if worker.worker_id == worker_id:
                return worker
        raise KeyError(f"Unknown worker_id: {worker_id}")


def run_worker_job(job: WorkerJobSpec, run_dir: Path, tracker: SummaryTracker) -> int:
    command = build_worker_command(job)
    log_file = run_dir / f"{_slugify(job.worker_id)}__{_slugify(job.job_name)}.log"

    combined_output: list[str] = []
    with log_file.open("w", encoding="utf-8") as handle:
        handle.write(f"=== Worker {job.worker_id} / {job.job_name} ===\n")
        handle.write(f"Command: {' '.join(command)}\n\n")
        handle.flush()

        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        tracker.mark_running(job.worker_id, getattr(process, "pid", None))
        assert process.stdout is not None
        for line in process.stdout:
            handle.write(line)
            handle.flush()
            combined_output.append(line)
            tracker.record_output(job.worker_id, line)
        exit_code = process.wait()

    output_dir = parse_output_dir("".join(combined_output))
    tracker.mark_finished(job.worker_id, exit_code, output_dir)
    write_worker_output_sidecar(
        job=job,
        run_dir=run_dir,
        log_file=log_file,
        output_dir=output_dir,
        exit_code=exit_code,
    )
    return exit_code


def _resolve_effective_max_workers(requested_max_workers: int, job_count: int) -> int:
    if requested_max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    return min(requested_max_workers, job_count)


def execute_manifest(
    manifest: BatchManifest,
    spec_path: Path,
    *,
    runs_root: Path = DEFAULT_RUNS_ROOT,
    max_workers: int | None = None,
) -> tuple[RunnerSummary, int]:
    run_dir = runs_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_path = run_dir / "summary.json"
    effective_max_workers = _resolve_effective_max_workers(
        max_workers if max_workers is not None else manifest.max_workers,
        len(manifest.jobs),
    )

    summary = _initial_summary(
        manifest,
        spec_path,
        run_dir,
        effective_max_workers,
    )
    tracker = SummaryTracker(summary, summary_path)

    with ThreadPoolExecutor(max_workers=effective_max_workers) as executor:
        futures = [
            executor.submit(run_worker_job, job, run_dir, tracker)
            for job in manifest.jobs
        ]
        for future in as_completed(futures):
            future.result()

    final_summary = tracker.finish()
    exit_code = 0 if final_summary.failed_worker_count == 0 else 1
    return final_summary, exit_code


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Execute worker-ready evaluation batch manifests.")
    parser.add_argument(
        "--spec",
        default=str(DEFAULT_SPEC_PATH),
        help="Path to the strict JSON manifest file.",
    )
    parser.add_argument(
        "--runs-root",
        default=str(DEFAULT_RUNS_ROOT),
        help="Local directory where worker logs and summary.json are written.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help=(
            "Maximum concurrent worker processes. Overrides manifest max_workers "
            f"when provided; default manifest value is {DEFAULT_MAX_WORKERS}."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    spec_path = Path(args.spec)
    runs_root = Path(args.runs_root)
    runs_root.mkdir(parents=True, exist_ok=True)

    try:
        manifest = load_manifest(spec_path)
    except FileNotFoundError:
        print(f"Manifest not found: {spec_path}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, ValidationError) as exc:
        print(f"Invalid manifest: {exc}", file=sys.stderr)
        return 1

    try:
        _, exit_code = execute_manifest(
            manifest,
            spec_path,
            runs_root=runs_root,
            max_workers=args.max_workers,
        )
    except ValueError as exc:
        print(f"Invalid runner configuration: {exc}", file=sys.stderr)
        return 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
