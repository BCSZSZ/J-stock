from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.benchmark_manager import BenchmarkManager
from src.entry_signal_analysis.models import (
    EntrySignalAnalysisArtifacts,
    EntrySignalAnalysisDatasetManifest,
    EntrySignalAnalysisPrimaryGroupSummary,
    EntrySignalAnalysisPrimaryStats,
    EntrySignalAnalysisPrimaryStrategyRiskRanking,
    EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking,
    EntrySignalAnalysisRequest,
    EntrySignalAnalysisRunSummary,
    EntrySignalAnalysisTopDailyWindows,
)
from src.entry_signal_analysis.runtime import resolve_effective_entry_filter_for_request
from src.entry_signal_analysis.scanner import scan_entry_signal_candidates
from src.entry_signal_analysis.summary import (
    build_daily_summary,
    build_overall_summary,
    build_primary_horizon_validation,
    build_primary_horizon_validations,
    build_strategy_summary,
    build_top_daily_windows_by_horizon,
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


def _load_topix_benchmark_frame(data_root: str) -> pd.DataFrame | None:
    manager = BenchmarkManager(client=None, data_root=data_root)
    frame = manager.get_topix_data()
    if frame is None or frame.empty:
        return None
    return frame.copy()


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.3f}%"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_primary_stats(stats: EntrySignalAnalysisPrimaryStats) -> str:
    return (
        f"count={stats.count}, win_rate={_format_ratio(stats.win_rate)}, "
        f"avg_return={_format_percent(stats.avg_return_pct)}, "
        f"median_return={_format_percent(stats.median_return_pct)}, "
        f"mean_gt_median={'yes' if stats.mean_gt_median else 'no' if stats.mean_gt_median is not None else 'n/a'}, "
        f"avg_loss={_format_percent(stats.avg_loss_pct)}, "
        f"P10={_format_percent(stats.p10_return_pct)}, "
        f"P25={_format_percent(stats.p25_return_pct)}, "
        f"P50={_format_percent(stats.p50_return_pct)}, "
        f"P75={_format_percent(stats.p75_return_pct)}, "
        f"P90={_format_percent(stats.p90_return_pct)}, "
        f"trimmed_1={_format_percent(stats.trimmed_mean_1pct_return_pct)}, "
        f"trimmed_5={_format_percent(stats.trimmed_mean_5pct_return_pct)}, "
        f"winsorized_1={_format_percent(stats.winsorized_mean_1pct_return_pct)}, "
        f"winsorized_5={_format_percent(stats.winsorized_mean_5pct_return_pct)}, "
        f"top_1_contrib={_format_ratio(stats.top_1pct_contribution_ratio)}, "
        f"top_5_contrib={_format_ratio(stats.top_5pct_contribution_ratio)}, "
        f"net_wo_top_5={_format_percent(stats.net_without_top_5pct_return_pct)}, "
        f"max={_format_percent(stats.max_return_pct)}, "
        f"min={_format_percent(stats.min_return_pct)}"
    )


def _append_group_section(
    lines: list[str],
    title: str,
    groups: list[EntrySignalAnalysisPrimaryGroupSummary],
    heading_level: int = 3,
) -> None:
    lines.extend(["", f"{'#' * heading_level} {title}"])
    if not groups:
        lines.append("- none")
        return

    for item in groups:
        suffix = ""
        if item.strength_min is not None and item.strength_max is not None:
            suffix = f" range=[{item.strength_min:.4f}, {item.strength_max:.4f}]"
        lines.append(
            f"- {item.group_label}: {_format_primary_stats(item.stats)}{suffix}"
        )


def _append_strategy_risk_ranking_section(
    lines: list[str],
    rankings: list[EntrySignalAnalysisPrimaryStrategyRiskRanking],
    title: str = "Primary Horizon Risk Ranking",
    heading_level: int = 2,
) -> None:
    lines.extend(
        [
            "",
            f"{'#' * heading_level} {title}",
            "- Strategy groups are defined as entry_strategy + entry_filter_name.",
            "- Primary score ranks avg_loss, P10, and P25 with lower downside preferred.",
            "- Secondary score ranks median_return, win_rate, and count.",
            "- Lower primary_score and secondary_score are better. avg_return is used only as a tie-break.",
        ]
    )
    if not rankings:
        lines.append("- none")
        return

    lines.extend(
        [
            "",
            "| Rank | Strategy | Filter | Primary Score | Secondary Score | Count | Avg Return | Median | Avg Loss | P10 | P25 | Win Rate |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in rankings:
        stats = item.stats
        lines.append(
            "| "
            f"{item.rank} | {item.entry_strategy} | {item.entry_filter_name} | {item.primary_score} | {item.secondary_score} | "
            f"{stats.count} | {_format_percent(stats.avg_return_pct)} | {_format_percent(stats.median_return_pct)} | "
            f"{_format_percent(stats.avg_loss_pct)} | {_format_percent(stats.p10_return_pct)} | "
            f"{_format_percent(stats.p25_return_pct)} | {_format_ratio(stats.win_rate)} |"
        )


def _append_strategy_tail_robustness_section(
    lines: list[str],
    rankings: list[EntrySignalAnalysisPrimaryStrategyTailRobustnessRanking],
    title: str = "Primary Horizon Tail Robustness Ranking",
    heading_level: int = 2,
) -> None:
    lines.extend(
        [
            "",
            f"{'#' * heading_level} {title}",
            "- Strategy groups are defined as entry_strategy + entry_filter_name.",
            "- Primary score ranks trimmed_mean_5pct, median_return, top_5pct_contribution, P10, and avg_loss.",
            "- Lower primary_score and secondary_score are better.",
        ]
    )
    if not rankings:
        lines.append("- none")
        return

    lines.extend(
        [
            "",
            "| Rank | Strategy | Filter | Primary Score | Secondary Score | Trimmed 5% | Winsorized 5% | Median | Top 5% Contribution | Net w/o Top 5% | P10 | Avg Loss | Max | Min |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in rankings:
        stats = item.stats
        lines.append(
            "| "
            f"{item.rank} | {item.entry_strategy} | {item.entry_filter_name} | {item.primary_score} | {item.secondary_score} | "
            f"{_format_percent(stats.trimmed_mean_5pct_return_pct)} | {_format_percent(stats.winsorized_mean_5pct_return_pct)} | "
            f"{_format_percent(stats.median_return_pct)} | {_format_ratio(stats.top_5pct_contribution_ratio)} | "
            f"{_format_percent(stats.net_without_top_5pct_return_pct)} | {_format_percent(stats.p10_return_pct)} | "
            f"{_format_percent(stats.avg_loss_pct)} | {_format_percent(stats.max_return_pct)} | {_format_percent(stats.min_return_pct)} |"
        )


def _append_tail_metrics_detail_table(
    lines: list[str],
    stats: EntrySignalAnalysisPrimaryStats,
    title: str,
    heading_level: int = 4,
) -> None:
    metric_rows = [
        ("trimmed_mean_1pct_return_pct", _format_percent(stats.trimmed_mean_1pct_return_pct)),
        ("trimmed_mean_5pct_return_pct", _format_percent(stats.trimmed_mean_5pct_return_pct)),
        ("winsorized_mean_1pct_return_pct", _format_percent(stats.winsorized_mean_1pct_return_pct)),
        ("winsorized_mean_5pct_return_pct", _format_percent(stats.winsorized_mean_5pct_return_pct)),
        ("p01_return_pct", _format_percent(stats.p01_return_pct)),
        ("p05_return_pct", _format_percent(stats.p05_return_pct)),
        ("p95_return_pct", _format_percent(stats.p95_return_pct)),
        ("p99_return_pct", _format_percent(stats.p99_return_pct)),
        ("max_return_pct", _format_percent(stats.max_return_pct)),
        ("min_return_pct", _format_percent(stats.min_return_pct)),
        ("total_sum_return_pct", _format_percent(stats.total_sum_return_pct)),
        ("top_1pct_sum_return_pct", _format_percent(stats.top_1pct_sum_return_pct)),
        ("top_5pct_sum_return_pct", _format_percent(stats.top_5pct_sum_return_pct)),
        ("bottom_1pct_sum_return_pct", _format_percent(stats.bottom_1pct_sum_return_pct)),
        ("bottom_5pct_sum_return_pct", _format_percent(stats.bottom_5pct_sum_return_pct)),
        ("top_1pct_contribution_ratio", _format_ratio(stats.top_1pct_contribution_ratio)),
        ("top_5pct_contribution_ratio", _format_ratio(stats.top_5pct_contribution_ratio)),
        ("bottom_1pct_contribution_ratio", _format_ratio(stats.bottom_1pct_contribution_ratio)),
        ("bottom_5pct_contribution_ratio", _format_ratio(stats.bottom_5pct_contribution_ratio)),
        ("net_without_top_1pct_return_pct", _format_percent(stats.net_without_top_1pct_return_pct)),
        ("net_without_top_5pct_return_pct", _format_percent(stats.net_without_top_5pct_return_pct)),
        ("net_without_bottom_1pct_return_pct", _format_percent(stats.net_without_bottom_1pct_return_pct)),
        ("net_without_bottom_5pct_return_pct", _format_percent(stats.net_without_bottom_5pct_return_pct)),
    ]

    lines.extend(
        [
            "",
            f"{'#' * heading_level} {title}",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
        ]
    )
    for metric_name, value_text in metric_rows:
        lines.append(f"| {metric_name} | {value_text} |")


def _append_primary_validation_section(
    lines: list[str],
    validation: EntrySignalAnalysisPrimaryGroupSummary | EntrySignalAnalysisPrimaryStrategyRiskRanking | EntrySignalAnalysisPrimaryStats | object,
) -> None:
    primary_validation = validation
    assert hasattr(primary_validation, "primary_horizon_label")
    assert hasattr(primary_validation, "primary_return_column")
    assert hasattr(primary_validation, "overall")
    assert hasattr(primary_validation, "signal_strength_metric")
    assert hasattr(primary_validation, "signal_strength_bucket_method")
    assert hasattr(primary_validation, "market_regime_source")
    assert hasattr(primary_validation, "market_regime_status")
    assert hasattr(primary_validation, "market_regime_definition")
    assert hasattr(primary_validation, "by_year")
    assert hasattr(primary_validation, "by_month")
    assert hasattr(primary_validation, "by_strategy")
    assert hasattr(primary_validation, "by_strategy_bucket")
    assert hasattr(primary_validation, "by_market_regime")
    assert hasattr(primary_validation, "by_entry_filter")
    assert hasattr(primary_validation, "by_signal_strength_bucket")
    assert hasattr(primary_validation, "by_strategy_risk")
    assert hasattr(primary_validation, "by_strategy_tail_robustness")

    lines.extend(
        [
            "",
            f"### {primary_validation.primary_horizon_label}",
            f"- Return Column: {primary_validation.primary_return_column}",
            f"- Overall: {_format_primary_stats(primary_validation.overall)}",
            f"- Signal Strength Metric: {primary_validation.signal_strength_metric or 'none'}",
            f"- Signal Strength Buckets: {primary_validation.signal_strength_bucket_method or 'none'}",
            f"- Market Regime Source: {primary_validation.market_regime_source or 'none'}",
            f"- Market Regime Status: {primary_validation.market_regime_status}",
            f"- Market Regime Definition: {primary_validation.market_regime_definition or 'n/a'}",
        ]
    )
    _append_tail_metrics_detail_table(
        lines,
        primary_validation.overall,
        title=f"{primary_validation.primary_horizon_label} Tail Metrics Detail",
        heading_level=4,
    )
    _append_group_section(lines, "By Year", primary_validation.by_year, heading_level=4)
    _append_group_section(lines, "By Month", primary_validation.by_month, heading_level=4)
    _append_group_section(lines, "By Strategy", primary_validation.by_strategy, heading_level=4)
    _append_group_section(lines, "By Strategy Bucket", primary_validation.by_strategy_bucket, heading_level=4)
    _append_group_section(lines, "By Market Regime", primary_validation.by_market_regime, heading_level=4)
    _append_group_section(lines, "By Entry Filter", primary_validation.by_entry_filter, heading_level=4)
    _append_group_section(lines, "By Signal Strength Bucket", primary_validation.by_signal_strength_bucket, heading_level=4)
    _append_strategy_risk_ranking_section(
        lines,
        primary_validation.by_strategy_risk,
        title=f"{primary_validation.primary_horizon_label} Strategy Risk Ranking",
        heading_level=4,
    )
    _append_strategy_tail_robustness_section(
        lines,
        primary_validation.by_strategy_tail_robustness,
        title=f"{primary_validation.primary_horizon_label} Tail Robustness Ranking",
        heading_level=4,
    )


def _append_top_daily_windows_section(
    lines: list[str],
    top_daily_windows_by_horizon: list[EntrySignalAnalysisTopDailyWindows],
) -> None:
    lines.extend(["", "## Top Daily Windows"])
    if not top_daily_windows_by_horizon:
        lines.append("- none")
        return

    for grouped_windows in top_daily_windows_by_horizon:
        lines.extend(
            [
                "",
                f"### {grouped_windows.primary_horizon_label}",
                f"- Sort Column: {grouped_windows.sort_column}",
            ]
        )
        if not grouped_windows.windows:
            lines.append("- none")
            continue
        for item in grouped_windows.windows:
            sort_value = pd.to_numeric(item.get(grouped_windows.sort_column), errors="coerce")
            sort_text = _format_percent(float(sort_value)) if pd.notna(sort_value) else "n/a"
            lines.append(
                f"- {item.get('signal_date')} {item.get('entry_strategy')} {item.get('entry_filter_name')} selected={item.get('selected_count')} metric={sort_text}"
            )


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

    primary_validations = summary.primary_horizon_validations or [summary.primary_horizon_validation]
    lines.extend(
        [
            "",
            "## Detailed Horizon Validations",
            f"- Requested detailed horizons: {', '.join(item.primary_horizon_label for item in primary_validations)}",
            f"- Legacy primary horizon: {summary.primary_horizon_validation.primary_horizon_label}",
        ]
    )
    for primary_validation in primary_validations:
        _append_primary_validation_section(lines, primary_validation)

    top_daily_windows_by_horizon = summary.top_daily_windows_by_horizon
    if not top_daily_windows_by_horizon and summary.top_daily_windows:
        top_daily_windows_by_horizon = [
            EntrySignalAnalysisTopDailyWindows(
                primary_horizon=summary.primary_horizon_validation.primary_horizon,
                primary_horizon_label=summary.primary_horizon_validation.primary_horizon_label,
                sort_column=f"selected_{summary.primary_horizon_validation.primary_horizon}d_avg_return_pct",
                windows=summary.top_daily_windows,
            )
        ]
    _append_top_daily_windows_section(lines, top_daily_windows_by_horizon)

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
    benchmark_frame = _load_topix_benchmark_frame(request.data_root)
    primary_horizon_validations = build_primary_horizon_validations(
        candidates,
        request.normalized_primary_horizons,
        benchmark_frame=benchmark_frame,
    )
    primary_horizon_validation = primary_horizon_validations[0] if primary_horizon_validations else build_primary_horizon_validation(
        candidates,
        request.primary_horizon,
        benchmark_frame=benchmark_frame,
    )
    top_daily_windows_by_horizon = build_top_daily_windows_by_horizon(
        daily_summary,
        request.normalized_primary_horizons,
        limit=10,
    )
    legacy_top_daily_windows = (
        top_daily_windows_by_horizon[0].windows
        if top_daily_windows_by_horizon
        else top_daily_windows(daily_summary, request.primary_horizon, limit=10)
    )

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
        primary_horizon_validation=primary_horizon_validation,
        primary_horizon_validations=primary_horizon_validations,
        per_strategy=strategy_summary.where(pd.notna(strategy_summary), None).to_dict(orient="records") if not strategy_summary.empty else [],
        top_daily_windows=legacy_top_daily_windows,
        top_daily_windows_by_horizon=top_daily_windows_by_horizon,
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
        primary_horizons=request.normalized_primary_horizons,
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