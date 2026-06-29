from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.artifacts.tabular import write_large_artifact
from src.entry_analysis.aggregation import aggregate_candidates, compute_baseline
from src.entry_analysis.features import normalize_indicator_columns, safe_json_dumps
from src.entry_analysis.models import (
    EntryAnalysisArtifacts,
    EntryAnalysisDatasetManifest,
    EntryAnalysisRequest,
    EntryAnalysisRunSummary,
)
from src.entry_analysis.signal_scanner import scan_entry_signals


def _sanitize_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "entry_analysis"


def _build_output_dir(request: EntryAnalysisRequest, generated_at: datetime) -> Path:
    strategies = request.entry_strategies
    if len(strategies) <= 2:
        strategy_part = "_plus_".join(strategies)
    else:
        strategy_part = f"{len(strategies)}_strategies"
    horizon_part = "_".join(str(value) for value in request.normalized_horizons)
    slug = _sanitize_slug(
        f"entry_analysis__entry_{strategy_part}__h{horizon_part}__{generated_at:%H%M%S}"
    )
    return Path(request.output_dir) / f"{generated_at:%Y%m%d}" / slug


def _records_for_json(frame: pd.DataFrame, limit: int) -> list[dict[str, object]]:
    if frame.empty:
        return []
    normalized = frame.head(limit).where(pd.notna(frame.head(limit)), None)
    return normalized.to_dict(orient="records")


def _feature_columns(frame: pd.DataFrame, horizons: list[int]) -> list[str]:
    excluded = {
        "entry_strategy",
        "ticker",
        "signal_date",
        "action",
        "confidence",
        "score",
        "reasons_json",
        "metadata_json",
    }
    for horizon in horizons:
        excluded.update({
            f"forward_date_{horizon}d",
            f"forward_price_{horizon}d",
            f"forward_return_{horizon}d_pct",
            f"forward_missing_{horizon}d",
        })
    return [column for column in frame.columns if column not in excluded]


def _write_report(path: Path, summary: EntryAnalysisRunSummary) -> None:
    baseline_lines = []
    for key, value in summary.baseline.items():
        if key == "candidate_count" or not isinstance(value, dict):
            continue
        baseline_lines.append(
            f"- {key}: count={value.get('count')}, win_rate={float(value.get('win_rate') or 0):.2%}, avg_return={float(value.get('avg_return_pct') or 0):.3f}%"
        )

    top_lines = []
    for item in summary.top_positive[:10]:
        top_lines.append(
            "- "
            f"{item.get('features')} {item.get('bucket')} h={item.get('horizon')} "
            f"count={item.get('count')} win_rate={float(item.get('win_rate') or 0):.2%} "
            f"avg={float(item.get('avg_return_pct') or 0):.3f}% score={float(item.get('score') or 0):.4f}"
        )

    content = [
        "# Entry Analysis Report",
        "",
        f"Generated At: {summary.generated_at}",
        f"Candidate Count: {summary.candidate_count}",
        f"Aggregate Count: {summary.aggregate_count}",
        "",
        "## Baseline",
        *baseline_lines,
        "",
        "## Top Positive Buckets",
        *(top_lines or ["- none"]),
        "",
        "## Artifacts",
        f"- Candidates: {summary.artifacts.candidates_parquet or summary.artifacts.candidates_csv or '-'}",
        f"- Aggregates: {summary.artifacts.aggregates_csv or '-'}",
        f"- Summary: {summary.artifacts.summary_json}",
        f"- Rules: {summary.artifacts.rules_json or '-'}",
        f"- Manifest: {summary.artifacts.manifest_json}",
    ]
    path.write_text("\n".join(content) + "\n", encoding="utf-8")


def run_entry_analysis(request: EntryAnalysisRequest) -> EntryAnalysisRunSummary:
    generated_at = datetime.now()
    indicator_columns = normalize_indicator_columns(request.indicator_columns)
    candidates = scan_entry_signals(request, indicator_columns)
    rules = request.rules
    aggregates = pd.DataFrame()
    if rules:
        aggregates = aggregate_candidates(
            candidates,
            rules,
            request.normalized_horizons,
            min_samples=request.min_samples,
            include_joint=request.include_joint,
        )
    baseline = compute_baseline(candidates, request.normalized_horizons)

    output_dir = _build_output_dir(request, generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"{generated_at:%Y%m%d_%H%M%S}"

    candidates_path = output_dir / f"entry_analysis_candidates_{timestamp}.csv"
    aggregates_path = output_dir / f"entry_analysis_aggregates_{timestamp}.csv"
    summary_path = output_dir / f"entry_analysis_summary_{timestamp}.json"
    rules_path = output_dir / f"entry_analysis_rules_{timestamp}.json"
    report_path = output_dir / f"entry_analysis_report_{timestamp}.md"
    manifest_path = output_dir / "entry_analysis_manifest.json"

    candidates_written = write_large_artifact(
        candidates,
        candidates_path,
        request.large_artifact_format,
    )
    if rules:
        aggregates.to_csv(aggregates_path, index=False, encoding="utf-8-sig")
        rules_path.write_text(
            json.dumps([rule.model_dump() for rule in rules], ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    primary = request.primary_horizon
    top_positive = aggregates[aggregates["horizon"] == primary].sort_values(
        ["score", "count"], ascending=[False, False]
    ) if not aggregates.empty and "horizon" in aggregates.columns else pd.DataFrame()
    top_avoid = aggregates[aggregates["horizon"] == primary].sort_values(
        ["score", "count"], ascending=[True, False]
    ) if not aggregates.empty and "horizon" in aggregates.columns else pd.DataFrame()

    artifacts = EntryAnalysisArtifacts(
        output_dir=str(output_dir),
        candidates_csv=str(candidates_written["csv"]) if candidates_written["csv"] is not None else None,
        candidates_parquet=str(candidates_written["parquet"]) if candidates_written["parquet"] is not None else None,
        aggregates_csv=str(aggregates_path) if rules else None,
        summary_json=str(summary_path),
        rules_json=str(rules_path) if rules else None,
        report_md=str(report_path),
        manifest_json=str(manifest_path),
    )
    summary = EntryAnalysisRunSummary(
        generated_at=generated_at.isoformat(timespec="seconds"),
        request=request.model_dump(mode="json"),
        candidate_count=int(len(candidates)),
        aggregate_count=int(len(aggregates)),
        baseline=baseline,
        top_positive=_records_for_json(top_positive, 20),
        top_avoid=_records_for_json(top_avoid, 20),
        artifacts=artifacts,
    )
    manifest = EntryAnalysisDatasetManifest(
        dataset_id=output_dir.name,
        generated_at=generated_at.isoformat(timespec="seconds"),
        output_dir=str(output_dir),
        candidates_csv=str(candidates_written["csv"]) if candidates_written["csv"] is not None else None,
        candidates_parquet=str(candidates_written["parquet"]) if candidates_written["parquet"] is not None else None,
        summary_json=str(summary_path),
        report_md=str(report_path),
        entry_strategies=request.entry_strategies,
        universe_size=len(request.tickers),
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        horizons=request.normalized_horizons,
        label_mode=request.label_mode,
        indicator_columns=list(indicator_columns),
        candidate_count=int(len(candidates)),
        feature_columns=_feature_columns(candidates, request.normalized_horizons),
        request=request.model_dump(mode="json"),
    )
    summary_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    _write_report(report_path, summary)

    print("[entry-analysis] saved dataset artifacts")
    print(f"  dataset_id: {manifest.dataset_id}")
    print(f"  candidates: {artifacts.candidates_parquet or artifacts.candidates_csv}")
    print(f"  manifest: {artifacts.manifest_json}")
    print(f"  aggregates: {artifacts.aggregates_csv or '-'}")
    print(f"  summary: {artifacts.summary_json}")
    print(f"  report: {artifacts.report_md}")
    print(f"  candidate_count={summary.candidate_count} aggregate_count={summary.aggregate_count}")
    return summary
