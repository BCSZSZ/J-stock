# /// script
# requires-python = ">=3.12"
# ///

from __future__ import annotations

import argparse
import io
import pstats
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final, Sequence


TIMING_LINE_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+(?P<name>[^:]+):\s+(?P<seconds>\d+(?:\.\d+)?)s(?:\s|$)"
)
TASK_TOTAL_RE: Final[re.Pattern[str]] = re.compile(
    r"^\s*-\s+(?P<name>[^:]+):\s+total=(?P<seconds>\d+(?:\.\d+)?)s"
)
RESULT_RE: Final[re.Pattern[str]] = re.compile(
    r"Return:\s*(?P<return>-?\d+(?:\.\d+)?)%,\s*Alpha:\s*(?P<alpha>-?\d+(?:\.\d+)?)%"
)


@dataclass(frozen=True)
class CliArgs:
    mode: str
    label: str
    repeat: int
    warmup: int
    output_dir: Path
    cprofile: bool
    cprofile_sort: str
    cprofile_limit: int
    command_args: tuple[str, ...]


@dataclass(frozen=True)
class RunResult:
    run_index: int
    elapsed_seconds: float
    log_path: Path
    phase_timings: dict[str, float]
    result_return_pct: float | None
    result_alpha_pct: float | None
    prof_path: Path | None
    prof_report_path: Path | None


@dataclass(frozen=True)
class MetricSummary:
    name: str
    mean_seconds: float
    min_seconds: float
    max_seconds: float
    stdev_seconds: float


def parse_args(argv: Sequence[str]) -> CliArgs:
    parser = argparse.ArgumentParser(
        description="Benchmark J-stock evaluate/walk-forward-evaluate runs with repeatable timing output."
    )
    parser.add_argument("--label", default="", help="Output label for the benchmark run")
    parser.add_argument(
        "--repeat",
        type=int,
        default=3,
        help="Measured run count after warmup",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="Warmup run count before measured runs",
    )
    parser.add_argument(
        "--output-dir",
        default="strategy_evaluation/perf_benchmarks",
        help="Directory for benchmark logs and summaries",
    )
    parser.add_argument(
        "--cprofile",
        action="store_true",
        help="Capture cProfile output for the first measured run",
    )
    parser.add_argument(
        "--cprofile-sort",
        default="cumulative",
        choices=["cumulative", "tottime", "calls", "ncalls"],
        help="pstats sort key for the profile text report",
    )
    parser.add_argument(
        "--cprofile-limit",
        type=int,
        default=30,
        help="Top function rows to print from pstats",
    )
    parser.add_argument(
        "mode",
        choices=["evaluate", "walk-forward-evaluate"],
        help="main.py subcommand to benchmark",
    )
    parser.add_argument(
        "command_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the chosen main.py subcommand",
    )

    namespace = parser.parse_args(list(argv))
    command_args = tuple(arg for arg in namespace.command_args if arg != "--")
    label = namespace.label or namespace.mode.replace("-", "_")

    if namespace.repeat < 1:
        raise ValueError("--repeat must be at least 1")
    if namespace.warmup < 0:
        raise ValueError("--warmup must be >= 0")

    return CliArgs(
        mode=namespace.mode,
        label=label,
        repeat=namespace.repeat,
        warmup=namespace.warmup,
        output_dir=Path(namespace.output_dir),
        cprofile=bool(namespace.cprofile),
        cprofile_sort=str(namespace.cprofile_sort),
        cprofile_limit=int(namespace.cprofile_limit),
        command_args=command_args,
    )


def normalize_metric_name(name: str) -> str:
    normalized = name.strip().replace(" ", "_")
    normalized = normalized.replace("/", "_")
    return normalized


def parse_timings(output_text: str) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for raw_line in output_text.splitlines():
        line = raw_line.rstrip()
        timing_match = TIMING_LINE_RE.match(line)
        if timing_match is not None:
            metric_name = normalize_metric_name(timing_match.group("name"))
            metrics[metric_name] = float(timing_match.group("seconds"))
            continue

        task_match = TASK_TOTAL_RE.match(line)
        if task_match is not None:
            metric_name = normalize_metric_name(task_match.group("name"))
            metrics[metric_name] = float(task_match.group("seconds"))
    return metrics


def parse_result_metrics(output_text: str) -> tuple[float | None, float | None]:
    matches = list(RESULT_RE.finditer(output_text))
    if not matches:
        return None, None

    last_match = matches[-1]
    return float(last_match.group("return")), float(last_match.group("alpha"))


def ensure_output_dir(base_dir: Path, label: str, mode: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    slug = normalize_metric_name(label)
    target = base_dir / f"{slug}__{mode}__{timestamp}"
    target.mkdir(parents=True, exist_ok=False)
    return target


def resolve_project_python(project_root: Path) -> str:
    windows_python = project_root / ".venv" / "Scripts" / "python.exe"
    posix_python = project_root / ".venv" / "bin" / "python"
    if windows_python.exists():
        return str(windows_python)
    if posix_python.exists():
        return str(posix_python)
    return sys.executable


def build_command(
    project_root: Path,
    mode: str,
    command_args: Sequence[str],
    profile_path: Path | None,
) -> list[str]:
    command = [resolve_project_python(project_root)]
    if profile_path is not None:
        command.extend(["-m", "cProfile", "-o", str(profile_path)])
    command.extend(["main.py", mode, *command_args])
    return command


def run_one(
    project_root: Path,
    mode: str,
    command_args: Sequence[str],
    output_dir: Path,
    run_index: int,
    use_cprofile: bool,
    cprofile_sort: str,
    cprofile_limit: int,
) -> RunResult:
    log_path = output_dir / f"run_{run_index:02d}.log"
    prof_path = output_dir / f"run_{run_index:02d}.prof" if use_cprofile else None
    prof_report_path = (
        output_dir / f"run_{run_index:02d}_pstats.txt" if use_cprofile else None
    )
    command = build_command(
        project_root=project_root,
        mode=mode,
        command_args=command_args,
        profile_path=prof_path,
    )

    started_at = time.perf_counter()
    completed = subprocess.run(
        command,
        cwd=project_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    elapsed_seconds = time.perf_counter() - started_at

    output_text = completed.stdout
    if completed.stderr:
        output_text = f"{output_text}\n\n[stderr]\n{completed.stderr}"
    log_path.write_text(output_text, encoding="utf-8")

    if completed.returncode != 0:
        raise RuntimeError(
            f"Benchmark command failed on run {run_index} with exit code {completed.returncode}. See {log_path}"
        )

    if prof_path is not None and prof_report_path is not None:
        write_profile_report(
            profile_path=prof_path,
            report_path=prof_report_path,
            sort_key=cprofile_sort,
            limit=cprofile_limit,
        )

    phase_timings = parse_timings(output_text)
    result_return_pct, result_alpha_pct = parse_result_metrics(output_text)
    return RunResult(
        run_index=run_index,
        elapsed_seconds=elapsed_seconds,
        log_path=log_path,
        phase_timings=phase_timings,
        result_return_pct=result_return_pct,
        result_alpha_pct=result_alpha_pct,
        prof_path=prof_path,
        prof_report_path=prof_report_path,
    )


def write_profile_report(
    profile_path: Path,
    report_path: Path,
    sort_key: str,
    limit: int,
) -> None:
    buffer = io.StringIO()
    stats = pstats.Stats(str(profile_path), stream=buffer)
    stats.strip_dirs().sort_stats(sort_key).print_stats(limit)
    report_path.write_text(buffer.getvalue(), encoding="utf-8")


def summarize_metric(name: str, values: Sequence[float]) -> MetricSummary:
    if not values:
        raise ValueError(f"No values found for metric {name}")
    stdev_seconds = statistics.stdev(values) if len(values) > 1 else 0.0
    return MetricSummary(
        name=name,
        mean_seconds=statistics.mean(values),
        min_seconds=min(values),
        max_seconds=max(values),
        stdev_seconds=stdev_seconds,
    )


def collect_metric_summaries(results: Sequence[RunResult]) -> list[MetricSummary]:
    metric_values: dict[str, list[float]] = {"wall_time": []}
    for result in results:
        metric_values["wall_time"].append(result.elapsed_seconds)
        for metric_name, metric_value in result.phase_timings.items():
            metric_values.setdefault(metric_name, []).append(metric_value)

    summaries = [
        summarize_metric(name=metric_name, values=values)
        for metric_name, values in sorted(metric_values.items())
    ]
    return summaries


def write_run_csv(output_dir: Path, results: Sequence[RunResult]) -> Path:
    metric_names = sorted(
        {
            metric_name
            for result in results
            for metric_name in result.phase_timings.keys()
        }
    )
    csv_path = output_dir / "run_metrics.csv"
    header = [
        "run_index",
        "wall_time",
        "return_pct",
        "alpha_pct",
        *metric_names,
    ]

    rows = [",".join(header)]
    for result in results:
        cells = [
            str(result.run_index),
            f"{result.elapsed_seconds:.4f}",
            "" if result.result_return_pct is None else f"{result.result_return_pct:.4f}",
            "" if result.result_alpha_pct is None else f"{result.result_alpha_pct:.4f}",
        ]
        for metric_name in metric_names:
            metric_value = result.phase_timings.get(metric_name)
            cells.append("" if metric_value is None else f"{metric_value:.4f}")
        rows.append(",".join(cells))

    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return csv_path


def write_summary_markdown(
    output_dir: Path,
    args: CliArgs,
    summaries: Sequence[MetricSummary],
    results: Sequence[RunResult],
) -> Path:
    md_path = output_dir / "summary.md"
    lines = [
        "# Evaluation Performance Benchmark",
        "",
        f"- mode: {args.mode}",
        f"- label: {args.label}",
        f"- warmup_runs: {args.warmup}",
        f"- measured_runs: {args.repeat}",
        f"- command: `{sys.executable} main.py {args.mode} {' '.join(args.command_args)}`",
        "",
        "## Metric Summary",
        "",
        "| metric | mean (s) | min (s) | max (s) | stdev (s) |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            f"| {summary.name} | {summary.mean_seconds:.4f} | {summary.min_seconds:.4f} | {summary.max_seconds:.4f} | {summary.stdev_seconds:.4f} |"
        )

    return_values = [
        result.result_return_pct for result in results if result.result_return_pct is not None
    ]
    alpha_values = [
        result.result_alpha_pct for result in results if result.result_alpha_pct is not None
    ]
    if return_values or alpha_values:
        lines.extend(
            [
                "",
                "## Output Consistency",
                "",
                f"- return_pct_values: {', '.join(f'{value:.4f}' for value in return_values) if return_values else 'n/a'}",
                f"- alpha_pct_values: {', '.join(f'{value:.4f}' for value in alpha_values) if alpha_values else 'n/a'}",
            ]
        )

    profile_reports = [
        result.prof_report_path for result in results if result.prof_report_path is not None
    ]
    if profile_reports:
        lines.extend(
            [
                "",
                "## Profile Artifacts",
                "",
            ]
        )
        for profile_report in profile_reports:
            lines.append(f"- {profile_report.name}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    project_root = Path(__file__).resolve().parent.parent
    output_dir = ensure_output_dir(
        base_dir=(project_root / args.output_dir),
        label=args.label,
        mode=args.mode,
    )

    print("=" * 80)
    print("Evaluation Performance Benchmark")
    print("=" * 80)
    print(f"Mode: {args.mode}")
    print(f"Label: {args.label}")
    print(f"Warmup runs: {args.warmup}")
    print(f"Measured runs: {args.repeat}")
    print(f"Output dir: {output_dir}")
    print()

    for warmup_index in range(1, args.warmup + 1):
        print(f"[warmup {warmup_index}/{args.warmup}] starting...", flush=True)
        run_one(
            project_root=project_root,
            mode=args.mode,
            command_args=args.command_args,
            output_dir=output_dir,
            run_index=warmup_index,
            use_cprofile=False,
            cprofile_sort=args.cprofile_sort,
            cprofile_limit=args.cprofile_limit,
        )
        print(f"[warmup {warmup_index}/{args.warmup}] done", flush=True)

    measured_results: list[RunResult] = []
    for measure_index in range(1, args.repeat + 1):
        print(f"[measure {measure_index}/{args.repeat}] starting...", flush=True)
        result = run_one(
            project_root=project_root,
            mode=args.mode,
            command_args=args.command_args,
            output_dir=output_dir,
            run_index=args.warmup + measure_index,
            use_cprofile=args.cprofile and measure_index == 1,
            cprofile_sort=args.cprofile_sort,
            cprofile_limit=args.cprofile_limit,
        )
        measured_results.append(result)
        print(
            f"[measure {measure_index}/{args.repeat}] wall={result.elapsed_seconds:.2f}s return={result.result_return_pct} alpha={result.result_alpha_pct}",
            flush=True,
        )

    summaries = collect_metric_summaries(measured_results)
    csv_path = write_run_csv(output_dir=output_dir, results=measured_results)
    md_path = write_summary_markdown(
        output_dir=output_dir,
        args=args,
        summaries=summaries,
        results=measured_results,
    )

    print()
    print("Metric summary:")
    for summary in summaries:
        print(
            f"  {summary.name}: mean={summary.mean_seconds:.2f}s min={summary.min_seconds:.2f}s max={summary.max_seconds:.2f}s stdev={summary.stdev_seconds:.2f}s"
        )
    print()
    print(f"Run metrics CSV: {csv_path}")
    print(f"Summary markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))