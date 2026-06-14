import json
import threading
from pathlib import Path
from time import sleep

import pytest

from tools.evaluation_batch_runner import (
    BatchManifest,
    DEFAULT_MAX_WORKERS,
    build_worker_command,
    execute_manifest,
    load_manifest,
    parse_output_dir,
)


def _write_manifest(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_load_manifest_rejects_runner_side_worker_planning_fields(tmp_path: Path) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "w1",
                    "job_name": "job-1",
                    "num_workers": 2,
                    "base_args": ["--mode", "annual"],
                }
            ],
        },
    )

    with pytest.raises(Exception):
        load_manifest(spec_path)


def test_load_manifest_defaults_to_bounded_max_workers(tmp_path: Path) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "w1",
                    "job_name": "job-1",
                    "base_args": ["--mode", "annual"],
                }
            ],
        },
    )

    manifest = load_manifest(spec_path)

    assert manifest.max_workers == DEFAULT_MAX_WORKERS


def test_load_manifest_accepts_top_level_max_workers(tmp_path: Path) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "max_workers": 3,
            "jobs": [
                {
                    "worker_id": "w1",
                    "job_name": "job-1",
                    "base_args": ["--mode", "annual"],
                }
            ],
        },
    )

    manifest = load_manifest(spec_path)

    assert manifest.max_workers == 3


def test_build_worker_command_assembles_manifest_without_resplitting() -> None:
    manifest = BatchManifest.model_validate(
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "worker-01",
                    "job_name": "job-1",
                    "command": "evaluate",
                    "base_args": [
                        "--mode",
                        "annual",
                        "--years",
                        "2026",
                        "--entry-strategies",
                        "FooEntry",
                    ],
                    "exit_strategies": ["ExitA", "ExitB"],
                }
            ],
        }
    )

    command = build_worker_command(manifest.jobs[0])

    assert command == [
        "uv",
        "run",
        "python",
        "main.py",
        "evaluate",
        "--mode",
        "annual",
        "--years",
        "2026",
        "--entry-strategies",
        "FooEntry",
        "--exit-strategies",
        "ExitA",
        "ExitB",
    ]


def test_parse_output_dir_prefers_explicit_output_dir() -> None:
    text = "hello\n本次输出目录: G:\\My Drive\\AI-Stock-Sync\\strategy_evaluation\\20260528\\run_1\nbye"
    assert parse_output_dir(text) == r"G:\My Drive\AI-Stock-Sync\strategy_evaluation\20260528\run_1"


class _FakeProcess:
    def __init__(
        self,
        stdout_lines: list[str],
        return_code: int,
        *,
        pid: int = 1234,
        wait_callback=None,
    ) -> None:
        self.stdout = stdout_lines
        self._return_code = return_code
        self.pid = pid
        self._wait_callback = wait_callback

    def wait(self) -> int:
        if self._wait_callback is not None:
            self._wait_callback()
        return self._return_code


def test_execute_manifest_records_live_worker_telemetry_before_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "worker-telemetry",
                    "job_name": "job-telemetry",
                    "base_args": ["--mode", "annual", "--years", "2026"],
                    "exit_strategies": ["ExitTelemetry"],
                }
            ],
        },
    )
    manifest = load_manifest(spec_path)

    telemetry_snapshot: dict[str, object] = {}
    expected_output_dir = (
        r"G:\My Drive\AI-Stock-Sync\strategy_evaluation\20260528\run_telemetry"
    )

    def _wait_callback() -> None:
        summary_path = next((tmp_path / "parallel_eval").glob("*/summary.json"))
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        worker = data["workers"][0]
        telemetry_snapshot["worker"] = worker
        telemetry_snapshot["log_text"] = Path(worker["log_file"]).read_text(
            encoding="utf-8"
        )

    outputs = [
        _FakeProcess(
            [
                "heartbeat-1\n",
                f"本次输出目录: {expected_output_dir}\n",
            ],
            0,
            pid=4321,
            wait_callback=_wait_callback,
        )
    ]

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        return outputs.pop(0)

    monkeypatch.setattr("tools.evaluation_batch_runner.subprocess.Popen", _fake_popen)

    summary, exit_code = execute_manifest(
        manifest,
        spec_path,
        runs_root=tmp_path / "parallel_eval",
    )

    assert exit_code == 0
    worker_snapshot = telemetry_snapshot["worker"]
    assert isinstance(worker_snapshot, dict)
    assert worker_snapshot["status"] == "running"
    assert worker_snapshot["worker_pid"] == 4321
    assert worker_snapshot["output_line_count"] == 2
    assert worker_snapshot["last_output_at"] is not None
    assert worker_snapshot["output_dir"] == expected_output_dir
    assert "heartbeat-1\n" in telemetry_snapshot["log_text"]
    assert f"本次输出目录: {expected_output_dir}\n" in telemetry_snapshot["log_text"]

    worker = summary.workers[0]
    assert worker.worker_pid == 4321
    assert worker.output_line_count == 2
    assert worker.last_output_at is not None
    assert worker.output_dir == expected_output_dir


def test_execute_manifest_writes_summary_and_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "worker-01",
                    "job_name": "job-a",
                    "base_args": ["--mode", "annual", "--years", "2026"],
                    "exit_strategies": ["ExitA", "ExitB"],
                },
                {
                    "worker_id": "worker-02",
                    "job_name": "job-b",
                    "base_args": ["--mode", "annual", "--years", "2026"],
                    "exit_strategies": ["ExitC"],
                },
            ],
        },
    )
    manifest = load_manifest(spec_path)

    outputs = [
        _FakeProcess([
            "line-1\n",
            "本次输出目录: G:\\My Drive\\AI-Stock-Sync\\strategy_evaluation\\20260528\\run_a\n",
        ], 0),
        _FakeProcess([
            "line-2\n",
            "本次输出目录: G:\\My Drive\\AI-Stock-Sync\\strategy_evaluation\\20260528\\run_b\n",
        ], 0),
    ]

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        return outputs.pop(0)

    monkeypatch.setattr("tools.evaluation_batch_runner.subprocess.Popen", _fake_popen)

    summary, exit_code = execute_manifest(
        manifest,
        spec_path,
        runs_root=tmp_path / "parallel_eval",
    )

    assert exit_code == 0
    assert summary.failed_worker_count == 0
    assert len(summary.workers) == 2
    assert {worker.output_dir for worker in summary.workers} == {
        r"G:\My Drive\AI-Stock-Sync\strategy_evaluation\20260528\run_a",
        r"G:\My Drive\AI-Stock-Sync\strategy_evaluation\20260528\run_b",
    }
    assert all(worker.worker_pid is not None for worker in summary.workers)
    assert all(worker.last_output_at is not None for worker in summary.workers)
    assert all(worker.output_line_count == 2 for worker in summary.workers)

    run_dir = Path(summary.run_dir)
    assert (run_dir / "summary.json").exists()
    assert all(Path(worker.log_file).exists() for worker in summary.workers)


def test_execute_manifest_limits_concurrent_workers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "max_workers": 2,
            "jobs": [
                {
                    "worker_id": f"worker-{index}",
                    "job_name": f"job-{index}",
                    "base_args": ["--mode", "annual"],
                }
                for index in range(5)
            ],
        },
    )
    manifest = load_manifest(spec_path)
    lock = threading.Lock()
    active_workers = 0
    max_seen_active_workers = 0

    def _wait_callback() -> None:
        nonlocal active_workers
        sleep(0.05)
        with lock:
            active_workers -= 1

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal active_workers, max_seen_active_workers
        with lock:
            active_workers += 1
            max_seen_active_workers = max(max_seen_active_workers, active_workers)
        return _FakeProcess(["ok\n"], 0, wait_callback=_wait_callback)

    monkeypatch.setattr("tools.evaluation_batch_runner.subprocess.Popen", _fake_popen)

    summary, exit_code = execute_manifest(
        manifest,
        spec_path,
        runs_root=tmp_path / "parallel_eval",
    )

    assert exit_code == 0
    assert summary.max_workers == 2
    assert len(summary.workers) == 5
    assert max_seen_active_workers <= 2


def test_execute_manifest_returns_nonzero_when_worker_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec_path = _write_manifest(
        tmp_path / "spec.json",
        {
            "schema_version": 1,
            "jobs": [
                {
                    "worker_id": "worker-01",
                    "job_name": "job-a",
                    "base_args": ["--mode", "annual"],
                    "exit_strategies": ["ExitA"],
                },
                {
                    "worker_id": "worker-02",
                    "job_name": "job-b",
                    "base_args": ["--mode", "annual"],
                    "exit_strategies": ["ExitB"],
                },
            ],
        },
    )
    manifest = load_manifest(spec_path)

    outputs = [
        _FakeProcess(["ok\n"], 0),
        _FakeProcess(["bad\n"], 2),
    ]

    def _fake_popen(*args, **kwargs):  # type: ignore[no-untyped-def]
        return outputs.pop(0)

    monkeypatch.setattr("tools.evaluation_batch_runner.subprocess.Popen", _fake_popen)

    summary, exit_code = execute_manifest(
        manifest,
        spec_path,
        runs_root=tmp_path / "parallel_eval",
    )

    assert exit_code == 1
    assert summary.failed_worker_count == 1
    statuses = {worker.worker_id: worker.status for worker in summary.workers}
    assert statuses["worker-01"] == "completed"
    assert statuses["worker-02"] == "failed"
    assert all(worker.worker_pid is not None for worker in summary.workers)
    assert all(worker.output_line_count == 1 for worker in summary.workers)
