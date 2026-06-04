from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.benchmark_manager import BenchmarkManager
from src.entry_exit_validation.models import (
    EntryExitValidationArtifacts,
    EntryExitValidationDatasetManifest,
    EntryExitValidationRequest,
    EntryExitValidationRunSummary,
)
from src.entry_exit_validation.runtime import resolve_effective_entry_filter_for_request
from src.entry_exit_validation.scanner import scan_entry_exit_candidates
from src.entry_exit_validation.simulator import simulate_candidate_exits
from src.entry_exit_validation.stats import (
    attach_market_regime,
    attach_signal_buckets,
    attach_time_columns,
    build_by_market_regime,
    build_by_month,
    build_by_signal_bucket,
    build_by_year,
    build_combo_summary,
    build_exit_reason_summary,
    build_rankings,
    build_tail_metrics,
    build_vs_fixed_horizon,
    build_warnings,
)


def _sanitize_slug(value: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    return cleaned.strip("_") or "entry_exit_validation"


def _build_output_dir(request: EntryExitValidationRequest, generated_at: datetime) -> Path:
    entry_part = "_plus_".join(request.entry_strategies) if len(request.entry_strategies) <= 2 else f"{len(request.entry_strategies)}_entries"
    exit_part = "_plus_".join(request.exit_strategies) if len(request.exit_strategies) <= 2 else f"{len(request.exit_strategies)}_exits"
    slug = _sanitize_slug(
        f"entry_exit_validation__entry_{entry_part}__exit_{exit_part}__{generated_at:%H%M%S}"
    )
    return Path(request.output_dir) / f"{generated_at:%Y%m%d}" / slug


def _load_topix_benchmark_frame(data_root: str) -> pd.DataFrame | None:
    manager = BenchmarkManager(client=None, data_root=data_root)
    frame = manager.get_topix_data()
    if frame is None or frame.empty:
        return None
    return frame.copy()


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _records(frame: pd.DataFrame, limit: int = 20) -> list[dict[str, object]]:
    if frame.empty:
        return []
    return frame.head(limit).where(pd.notna(frame.head(limit)), None).to_dict(orient="records")


def _format_pct(value: object) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.3f}%"


def _write_report(
    path: Path,
    summary: EntryExitValidationRunSummary,
    combo_summary: pd.DataFrame,
    robustness: pd.DataFrame,
    risk: pd.DataFrame,
    vs_fixed: pd.DataFrame,
) -> None:
    lines = [
        "# Entry x Exit Combination Report",
        "",
        "## Generated Info",
        f"- generated_at: {summary.generated_at}",
        f"- candidate_count: {summary.candidate_count}",
        f"- simulated_trade_count: {summary.simulated_trade_count}",
        f"- entry_strategy_count: {summary.entry_strategy_count}",
        f"- exit_strategy_count: {summary.exit_strategy_count}",
        f"- combination_count: {summary.combination_count}",
        f"- market_regime_status: {summary.market_regime_status}",
        "",
        "## Overall Best Combinations",
        "",
        "### Robustness Ranking",
    ]
    if robustness.empty:
        lines.append("- none")
    else:
        for row in robustness.head(10).to_dict(orient="records"):
            lines.append(
                f"- {row.get('entry_strategy')} x {row.get('exit_strategy')}: count={row.get('count')}, trimmed5={_format_pct(row.get('trimmed_mean_5pct'))}, median={_format_pct(row.get('median_return'))}, top5_contrib={row.get('top_5pct_contribution_ratio')}"
            )

    lines.extend(["", "### Risk Ranking"])
    if risk.empty:
        lines.append("- none")
    else:
        for row in risk.head(10).to_dict(orient="records"):
            lines.append(
                f"- {row.get('entry_strategy')} x {row.get('exit_strategy')}: count={row.get('count')}, p10={_format_pct(row.get('p10_return'))}, es5={_format_pct(row.get('expected_shortfall_5pct'))}, loss_gt5={row.get('loss_rate_gt_5pct')}"
            )

    lines.extend(["", "## Combination Summary"])
    if combo_summary.empty:
        lines.append("- none")
    else:
        for row in combo_summary.head(20).to_dict(orient="records"):
            lines.append(
                f"- {row.get('entry_strategy')} x {row.get('exit_strategy')}: count={row.get('count')}, win={row.get('win_rate')}, avg={_format_pct(row.get('avg_return'))}, median={_format_pct(row.get('median_return'))}, p10={_format_pct(row.get('p10_return'))}"
            )

    lines.extend(["", "## Vs Fixed Horizon Benchmark"])
    if vs_fixed.empty:
        lines.append("- none")
    else:
        for row in vs_fixed.head(20).to_dict(orient="records"):
            parts = [
                f"avg_vs_5d={_format_pct(row.get('avg_return_vs_fixed_5d'))}",
                f"avg_vs_9d={_format_pct(row.get('avg_return_vs_fixed_9d'))}",
                f"avg_vs_11d={_format_pct(row.get('avg_return_vs_fixed_11d'))}",
            ]
            lines.append(
                f"- {row.get('entry_strategy')} x {row.get('exit_strategy')}: "
                + ", ".join(parts)
            )

    lines.extend(["", "## Warnings"])
    if summary.warnings:
        lines.extend(f"- {warning}" for warning in summary.warnings)
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Artifacts",
            f"- Trades: {summary.artifacts.selected_trades_csv}",
            f"- Combo Summary: {summary.artifacts.combo_summary_csv}",
            f"- Tail Metrics: {summary.artifacts.combo_tail_metrics_csv}",
            f"- Vs Fixed Horizon: {summary.artifacts.combo_vs_fixed_horizon_csv}",
            f"- By Year: {summary.artifacts.combo_by_year_csv}",
            f"- By Market Regime: {summary.artifacts.combo_by_market_regime_csv}",
            f"- Exit Reasons: {summary.artifacts.combo_by_exit_reason_csv}",
            f"- Manifest: {summary.artifacts.manifest_json}",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_entry_exit_validation(
    request: EntryExitValidationRequest,
) -> EntryExitValidationRunSummary:
    generated_at = datetime.now()
    effective_entry_filter_mode, effective_entry_filter_names = (
        resolve_effective_entry_filter_for_request(request)
    )
    scan_result = scan_entry_exit_candidates(request)
    trades = simulate_candidate_exits(scan_result.candidates, request, scan_result.cache)
    trades = attach_time_columns(trades)
    benchmark_frame = _load_topix_benchmark_frame(request.data_root)
    trades, market_regime_status, market_regime_definition = attach_market_regime(
        trades,
        benchmark_frame,
    )
    trades = attach_signal_buckets(trades)

    combo_summary = build_combo_summary(trades)
    tail_metrics = build_tail_metrics(trades)
    vs_fixed = build_vs_fixed_horizon(trades, request.normalized_horizons)
    by_year = build_by_year(trades)
    by_market_regime = build_by_market_regime(trades)
    by_exit_reason = build_exit_reason_summary(trades)
    by_signal_bucket = build_by_signal_bucket(trades)
    by_month = build_by_month(trades)
    robustness, risk = build_rankings(combo_summary)
    warnings = build_warnings(combo_summary, request.min_samples)

    output_dir = _build_output_dir(request, generated_at)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = f"{generated_at:%Y%m%d_%H%M%S}"
    selected_trades_path = output_dir / "combo_selected_trades.csv"
    combo_summary_path = output_dir / "combo_summary.csv"
    tail_metrics_path = output_dir / "combo_tail_metrics.csv"
    vs_fixed_path = output_dir / "combo_vs_fixed_horizon.csv"
    by_year_path = output_dir / "combo_by_year.csv"
    by_market_regime_path = output_dir / "combo_by_market_regime.csv"
    by_exit_reason_path = output_dir / "combo_by_exit_reason.csv"
    by_signal_bucket_path = output_dir / "combo_by_signal_bucket.csv"
    by_month_path = output_dir / "combo_by_month.csv"
    robustness_path = output_dir / "combo_robustness_ranking.csv"
    risk_path = output_dir / "combo_risk_ranking.csv"
    summary_path = output_dir / f"entry_exit_validation_summary_{timestamp}.json"
    report_path = output_dir / "combo_report.md"
    manifest_path = output_dir / "entry_exit_validation_manifest.json"

    for frame, path in [
        (trades, selected_trades_path),
        (combo_summary, combo_summary_path),
        (tail_metrics, tail_metrics_path),
        (vs_fixed, vs_fixed_path),
        (by_year, by_year_path),
        (by_market_regime, by_market_regime_path),
        (by_exit_reason, by_exit_reason_path),
        (by_signal_bucket, by_signal_bucket_path),
        (by_month, by_month_path),
        (robustness, robustness_path),
        (risk, risk_path),
    ]:
        _write_csv(frame, path)

    artifacts = EntryExitValidationArtifacts(
        output_dir=str(output_dir),
        selected_trades_csv=str(selected_trades_path),
        combo_summary_csv=str(combo_summary_path),
        combo_tail_metrics_csv=str(tail_metrics_path),
        combo_vs_fixed_horizon_csv=str(vs_fixed_path),
        combo_by_year_csv=str(by_year_path),
        combo_by_market_regime_csv=str(by_market_regime_path),
        combo_by_exit_reason_csv=str(by_exit_reason_path),
        combo_by_signal_bucket_csv=str(by_signal_bucket_path),
        combo_by_month_csv=str(by_month_path),
        combo_robustness_ranking_csv=str(robustness_path),
        combo_risk_ranking_csv=str(risk_path),
        summary_json=str(summary_path),
        report_md=str(report_path),
        manifest_json=str(manifest_path),
    )
    combination_count = len(request.entry_strategies) * len(request.exit_strategies)
    summary = EntryExitValidationRunSummary(
        generated_at=generated_at.isoformat(timespec="seconds"),
        request=request.model_dump(mode="json"),
        candidate_count=len(scan_result.candidates),
        simulated_trade_count=int(len(trades)),
        entry_strategy_count=len(request.entry_strategies),
        exit_strategy_count=len(request.exit_strategies),
        combination_count=combination_count,
        effective_entry_filter_mode=effective_entry_filter_mode,
        effective_entry_filter_names=effective_entry_filter_names,
        market_regime_status=market_regime_status,
        market_regime_definition=market_regime_definition,
        artifacts=artifacts,
        top_robust_combinations=_records(robustness, limit=10),
        top_risk_combinations=_records(risk, limit=10),
        warnings=warnings,
    )
    manifest = EntryExitValidationDatasetManifest(
        dataset_id=output_dir.name,
        generated_at=generated_at.isoformat(timespec="seconds"),
        output_dir=str(output_dir),
        selected_trades_csv=str(selected_trades_path),
        combo_summary_csv=str(combo_summary_path),
        combo_tail_metrics_csv=str(tail_metrics_path),
        combo_vs_fixed_horizon_csv=str(vs_fixed_path),
        combo_by_year_csv=str(by_year_path),
        combo_by_market_regime_csv=str(by_market_regime_path),
        combo_by_exit_reason_csv=str(by_exit_reason_path),
        combo_by_signal_bucket_csv=str(by_signal_bucket_path),
        combo_by_month_csv=str(by_month_path),
        combo_robustness_ranking_csv=str(robustness_path),
        combo_risk_ranking_csv=str(risk_path),
        summary_json=str(summary_path),
        report_md=str(report_path),
        entry_strategies=request.entry_strategies,
        exit_strategies=request.exit_strategies,
        universe_size=len(request.tickers),
        start_date=request.start_date.isoformat(),
        end_date=request.end_date.isoformat(),
        horizons=request.normalized_horizons,
        primary_horizon=request.primary_horizon,
        execution_mode=request.execution_mode,
        signal_scope=request.signal_scope,
        ranking_strategy=request.ranking_strategy,
        entry_filter_mode=request.entry_filter_mode,
        entry_filter_names=request.entry_filter_names,
        effective_entry_filter_mode=effective_entry_filter_mode,
        effective_entry_filter_names=effective_entry_filter_names,
        candidate_count=len(scan_result.candidates),
        simulated_trade_count=int(len(trades)),
        combination_count=combination_count,
        request=request.model_dump(mode="json"),
    )

    summary_path.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    _write_report(report_path, summary, combo_summary, robustness, risk, vs_fixed)

    print("[entry-exit-validation] saved dataset artifacts")
    print(f"  dataset_id: {manifest.dataset_id}")
    print(f"  trades: {artifacts.selected_trades_csv}")
    print(f"  summary: {artifacts.combo_summary_csv}")
    return summary
