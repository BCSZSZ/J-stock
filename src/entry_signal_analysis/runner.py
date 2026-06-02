from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.entry_signal_analysis.models import (
    EntrySignalAnalysisArtifacts,
    EntrySignalAnalysisDatasetManifest,
    EntrySignalAnalysisRequest,
    EntrySignalAnalysisRunSummary,
)
from src.entry_signal_analysis.runtime import resolve_effective_entry_filter_for_request
from src.entry_signal_analysis.scanner import scan_entry_signal_candidates
from src.entry_signal_analysis.summary import (
    build_daily_summary,
    build_overall_summary,
    build_strategy_summary,
    top_daily_windows,
)


def _sanitize_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "entry_signal_analysis"


def _build_output_dir(request: EntrySignalAnalysisRequest, generated_at: datetime) -> Path:
    strategies = request.entry_strategies
    if len(strategies) <= 2:
        strategy_part = "_plus_".join(strategies)
    else:
        strategy_part = f"{len(strategies)}_strategies"
    horizon_part = "_".join(str(value) for value in request.normalized_horizons)
    slug = _sanitize_slug(
        f"entry_signal_analysis__entry_{strategy_part}__h{horizon_part}__{generated_at:%H%M%S}"
    )
    return Path(request.output_dir) / f"{generated_at:%Y%m%d}" / slug


def _write_report(path: Path, summary: EntrySignalAnalysisRunSummary) -> None:
    lines = [
        "# Entry Signal Analysis Report",
        "",
        f"Generated At: {summary.generated_at}",
        f"Candidate Count: {summary.candidate_count}",
        f"Selected Count: {summary.selected_count}",
        f"Trading Days: {summary.trading_day_count}",
        f"Effective Entry Filter Mode: {summary.effective_entry_filter_mode}",
        f"Effective Entry Filter Names: {', '.join(summary.effective_entry_filter_names) if summary.effective_entry_filter_names else 'none'}",
        "",
        "## Overall",
    ]
    for key, value in summary.overall.items():
        if isinstance(value, dict):
            lines.append(
                f"- {key}: count={value.get('count')}, win_rate={float(value.get('win_rate') or 0):.2%}, avg_return={float(value.get('avg_return_pct') or 0):.3f}%"
            )
        else:
            lines.append(f"- {key}: {value}")

    lines.extend(["", "## Top Daily Windows"])
    if summary.top_daily_windows:
        for item in summary.top_daily_windows:
            lines.append(
                f"- {item.get('signal_date')} {item.get('entry_strategy')} {item.get('entry_filter_name')} selected={item.get('selected_count')}"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "## Artifacts",
        f"- Candidates: {summary.artifacts.candidates_csv}",
        f"- Selected: {summary.artifacts.selected_csv}",
        f"- Daily Summary: {summary.artifacts.daily_summary_csv}",
        f"- Strategy Summary: {summary.artifacts.strategy_summary_csv}",
        f"- Summary: {summary.artifacts.summary_json}",
        f"- Manifest: {summary.artifacts.manifest_json}",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_entry_signal_analysis(
    request: EntrySignalAnalysisRequest,
) -> EntrySignalAnalysisRunSummary:
    generated_at = datetime.now()
    effective_entry_filter_mode, effective_entry_filter_names = (
        resolve_effective_entry_filter_for_request(request)
    )
    candidates = scan_entry_signal_candidates(request)
    selected = candidates[candidates["selected"] == True].copy() if not candidates.empty else pd.DataFrame()  # noqa: E712
    daily_summary = build_daily_summary(candidates, request.normalized_horizons)
    strategy_summary = build_strategy_summary(candidates, request.normalized_horizons)
    overall = build_overall_summary(candidates, request.normalized_horizons)

    output_dir = _build_output_dir(request, generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"{generated_at:%Y%m%d_%H%M%S}"
    candidates_path = output_dir / f"entry_signal_analysis_candidates_{timestamp}.csv"
    selected_path = output_dir / f"entry_signal_analysis_selected_{timestamp}.csv"
    daily_summary_path = output_dir / f"entry_signal_analysis_daily_summary_{timestamp}.csv"
    strategy_summary_path = output_dir / f"entry_signal_analysis_strategy_summary_{timestamp}.csv"
    summary_path = output_dir / f"entry_signal_analysis_summary_{timestamp}.json"
    report_path = output_dir / f"entry_signal_analysis_report_{timestamp}.md"
    manifest_path = output_dir / "entry_signal_analysis_manifest.json"

    candidates.to_csv(candidates_path, index=False, encoding="utf-8-sig")
    selected.to_csv(selected_path, index=False, encoding="utf-8-sig")
    daily_summary.to_csv(daily_summary_path, index=False, encoding="utf-8-sig")
    strategy_summary.to_csv(strategy_summary_path, index=False, encoding="utf-8-sig")

    artifacts = EntrySignalAnalysisArtifacts(
        output_dir=str(output_dir),
        candidates_csv=str(candidates_path),
        selected_csv=str(selected_path),
        daily_summary_csv=str(daily_summary_path),
        strategy_summary_csv=str(strategy_summary_path),
        summary_json=str(summary_path),
        report_md=str(report_path),
        manifest_json=str(manifest_path),
    )
    summary = EntrySignalAnalysisRunSummary(
        generated_at=generated_at.isoformat(timespec="seconds"),
        request=request.model_dump(mode="json"),
        candidate_count=int(len(candidates)),
        selected_count=int(len(selected)),
        trading_day_count=int(candidates["signal_date"].nunique()) if not candidates.empty else 0,
        strategy_count=int(candidates[["entry_strategy", "entry_filter_name"]].drop_duplicates().shape[0]) if not candidates.empty else 0,
        effective_entry_filter_mode=effective_entry_filter_mode,
        effective_entry_filter_names=effective_entry_filter_names,
        overall=overall,
        per_strategy=strategy_summary.where(pd.notna(strategy_summary), None).to_dict(orient="records") if not strategy_summary.empty else [],
        top_daily_windows=top_daily_windows(daily_summary, request.primary_horizon, limit=10),
        artifacts=artifacts,
    )
    manifest = EntrySignalAnalysisDatasetManifest(
        dataset_id=output_dir.name,
        generated_at=generated_at.isoformat(timespec="seconds"),
        output_dir=str(output_dir),
        candidates_csv=str(candidates_path),
        selected_csv=str(selected_path),
        daily_summary_csv=str(daily_summary_path),
        strategy_summary_csv=str(strategy_summary_path),
        summary_json=str(summary_path),
        report_md=str(report_path),
        entry_strategies=request.entry_strategies,
        universe_size=len(request.tickers),
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        horizons=request.normalized_horizons,
        primary_horizon=request.primary_horizon,
        label_mode=request.label_mode,
        ranking_strategy=request.ranking_strategy,
        entry_filter_mode=request.entry_filter_mode,
        entry_filter_names=request.entry_filter_names,
        effective_entry_filter_mode=effective_entry_filter_mode,
        effective_entry_filter_names=effective_entry_filter_names,
        candidate_count=int(len(candidates)),
        selected_count=int(len(selected)),
        request=request.model_dump(mode="json"),
    )

    summary_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    _write_report(report_path, summary)

    print("[entry-signal-analysis] saved dataset artifacts")
    print(f"  dataset_id: {manifest.dataset_id}")
    print(f"  candidates: {artifacts.candidates_csv}")
    print(f"  selected: {artifacts.selected_csv}")
    print(f"  daily_summary: {artifacts.daily_summary_csv}")
    print(f"  strategy_summary: {artifacts.strategy_summary_csv}")
    print(f"  summary: {artifacts.summary_json}")
    print(f"  report: {artifacts.report_md}")
    return summary