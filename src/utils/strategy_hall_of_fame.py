from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from statistics import fmean, pstdev
from typing import TypedDict

import pandas as pd


class EvaluationBasis(TypedDict):
    mode: str
    years: list[int]
    entry_filter_mode: str
    exit_confirmation_days: int
    ranking_mode: str
    selection_rank_field: str


class MetricSources(TypedDict):
    segmented_raw_file: list[str]
    continuous_raw_file: list[str]
    continuous_stability_rank: list[str]


class ComparisonContract(TypedDict):
    final_review_metrics: list[str]
    metric_sources: MetricSources


class StrategySelectors(TypedDict):
    entry_filter: str
    position_profile: str | None
    overlay_mode: str | None
    universe_name: str | None


class SelectionInfo(TypedDict):
    results_dir: str
    ranking_file: str
    segmented_raw_file: str
    continuous_raw_file: str
    ranking_position: int
    selectors: StrategySelectors
    selection_notes: list[str]


class ComparisonSummary(TypedDict):
    hit20_years: int
    positive_years: int
    positive_alpha_years: int
    avg_yearly_return_pct: float
    avg_yearly_alpha_pct: float
    worst_year_return_pct: float
    annual_return_std_pct: float
    continuous_return_pct: float
    continuous_alpha_pct: float
    continuous_sharpe_ratio: float
    continuous_mdd_pct: float


class AnnualPeriodMetrics(TypedDict):
    return_pct: float
    alpha_pct: float
    max_drawdown_pct: float


class ContinuousPeriodMetrics(TypedDict):
    period: str
    start_date: str
    end_date: str
    return_pct: float
    alpha_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    num_trades: int


class HallOfFameReferenceRecord(TypedDict):
    reference_id: str
    display_name: str
    entry_strategy: str
    exit_strategy: str
    tags: list[str]
    selection: SelectionInfo
    comparison_summary: ComparisonSummary
    annual_period_metrics: dict[str, AnnualPeriodMetrics]
    continuous_period_metrics: ContinuousPeriodMetrics


class HallOfFameDocument(TypedDict):
    schema_version: str
    record_type: str
    description: str
    updated_at: str
    evaluation_basis: EvaluationBasis
    comparison_contract: ComparisonContract
    references: dict[str, HallOfFameReferenceRecord]


@dataclass(frozen=True)
class ResultsBundle:
    results_dir: Path
    segmented_raw_file: Path
    continuous_raw_file: Path
    ranking_file: Path


@dataclass(frozen=True)
class HallOfFameReferenceInput:
    reference_id: str
    display_name: str
    results_dir: Path
    entry_strategy: str
    exit_strategy: str
    tags: tuple[str, ...]
    entry_filter: str = "off"
    position_profile: str | None = None
    overlay_mode: str | None = None
    universe_name: str | None = None
    selection_notes: tuple[str, ...] = ()


class HallOfFameBuildError(ValueError):
    def __init__(self, message: str, *, context: dict[str, str]) -> None:
        self.context = context
        super().__init__(
            f"{message}: {json.dumps(context, ensure_ascii=True, sort_keys=True)}"
        )


FINAL_REVIEW_METRICS: list[str] = [
    "annual_period_return_pct_by_year",
    "hit20_years",
    "positive_years",
    "worst_year_return_pct",
    "annual_return_std_pct",
    "continuous_return_pct",
    "continuous_alpha_pct",
    "continuous_sharpe_ratio",
    "continuous_mdd_pct",
]

DEFAULT_EVALUATION_BASIS: EvaluationBasis = {
    "mode": "annual",
    "years": [2021, 2022, 2023, 2024, 2025],
    "entry_filter_mode": "off",
    "exit_confirmation_days": 1,
    "ranking_mode": "target20",
    "selection_rank_field": "continuous_stability_rank",
}

DEFAULT_METRIC_SOURCES: MetricSources = {
    "segmented_raw_file": [
        "annual_period_metrics.*.return_pct",
        "annual_period_metrics.*.alpha_pct",
        "annual_period_metrics.*.max_drawdown_pct",
        "comparison_summary.hit20_years",
        "comparison_summary.positive_years",
        "comparison_summary.positive_alpha_years",
        "comparison_summary.avg_yearly_return_pct",
        "comparison_summary.avg_yearly_alpha_pct",
        "comparison_summary.worst_year_return_pct",
        "comparison_summary.annual_return_std_pct",
    ],
    "continuous_raw_file": [
        "continuous_period_metrics.*",
        "comparison_summary.continuous_return_pct",
        "comparison_summary.continuous_alpha_pct",
        "comparison_summary.continuous_sharpe_ratio",
        "comparison_summary.continuous_mdd_pct",
    ],
    "continuous_stability_rank": ["selection.ranking_position"],
}


def new_hall_of_fame_document(updated_at: str | None = None) -> HallOfFameDocument:
    resolved_updated_at = updated_at or date.today().isoformat()
    return {
        "schema_version": "1.0",
        "record_type": "strategy_hall_of_fame",
        "description": (
            "Reusable reference strategy registry for future annual CLI strategy "
            "comparisons under the locked 2021-2025 evaluation basis."
        ),
        "updated_at": resolved_updated_at,
        "evaluation_basis": dict(DEFAULT_EVALUATION_BASIS),
        "comparison_contract": {
            "final_review_metrics": list(FINAL_REVIEW_METRICS),
            "metric_sources": {
                "segmented_raw_file": list(DEFAULT_METRIC_SOURCES["segmented_raw_file"]),
                "continuous_raw_file": list(
                    DEFAULT_METRIC_SOURCES["continuous_raw_file"]
                ),
                "continuous_stability_rank": list(
                    DEFAULT_METRIC_SOURCES["continuous_stability_rank"]
                ),
            },
        },
        "references": {},
    }


def load_hall_of_fame_document(path: Path) -> HallOfFameDocument:
    if not path.exists():
        return new_hall_of_fame_document()

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("record_type") != "strategy_hall_of_fame":
        raise HallOfFameBuildError(
            "hall-of-fame file format invalid",
            context={"path": str(path)},
        )
    if "references" not in payload:
        raise HallOfFameBuildError(
            "hall-of-fame file missing references",
            context={"path": str(path)},
        )
    return payload  # type: ignore[return-value]


def find_latest_results_bundle(results_dir: Path) -> ResultsBundle:
    if not results_dir.exists() or not results_dir.is_dir():
        raise HallOfFameBuildError(
            "results directory does not exist",
            context={"results_dir": str(results_dir)},
        )

    segmented_raw_file = _find_latest_file(results_dir, "strategy_evaluation_raw_*.csv")
    continuous_raw_file = _find_latest_file(
        results_dir, "strategy_evaluation_continuous_raw_*.csv"
    )
    ranking_file = _find_latest_file(
        results_dir, "strategy_evaluation_continuous_stability_rank_*.csv"
    )
    return ResultsBundle(
        results_dir=results_dir,
        segmented_raw_file=segmented_raw_file,
        continuous_raw_file=continuous_raw_file,
        ranking_file=ranking_file,
    )


def build_reference_record(
    reference_input: HallOfFameReferenceInput,
) -> HallOfFameReferenceRecord:
    bundle = find_latest_results_bundle(reference_input.results_dir)
    segmented_df = pd.read_csv(bundle.segmented_raw_file)
    continuous_df = pd.read_csv(bundle.continuous_raw_file)
    ranking_df = pd.read_csv(bundle.ranking_file)

    segmented_matches = _filter_strategy_rows(segmented_df, reference_input)
    if segmented_matches.empty:
        raise _build_missing_strategy_error(reference_input, bundle)
    if segmented_matches["period"].duplicated().any():
        raise HallOfFameBuildError(
            "segmented raw contains duplicate periods for the selected strategy",
            context=_error_context(reference_input, bundle),
        )

    continuous_matches = _filter_strategy_rows(continuous_df, reference_input)
    if len(continuous_matches.index) != 1:
        raise HallOfFameBuildError(
            "continuous raw did not resolve to exactly one row",
            context=_error_context(reference_input, bundle),
        )

    ranking_matches = _filter_strategy_rows(ranking_df, reference_input)
    if len(ranking_matches.index) != 1:
        raise HallOfFameBuildError(
            "ranking file did not resolve to exactly one row",
            context=_error_context(reference_input, bundle),
        )

    annual_period_metrics = _build_annual_period_metrics(segmented_matches)
    continuous_period_metrics = _build_continuous_period_metrics(continuous_matches.iloc[0])
    comparison_summary = _build_comparison_summary(
        annual_period_metrics=annual_period_metrics,
        continuous_period_metrics=continuous_period_metrics,
    )

    ranking_row = ranking_matches.iloc[0]
    ranking_position = _resolve_ranking_position(ranking_row, ranking_matches.index[0])
    selectors: StrategySelectors = {
        "entry_filter": reference_input.entry_filter,
        "position_profile": reference_input.position_profile,
        "overlay_mode": reference_input.overlay_mode,
        "universe_name": reference_input.universe_name,
    }
    selection: SelectionInfo = {
        "results_dir": str(bundle.results_dir),
        "ranking_file": str(bundle.ranking_file),
        "segmented_raw_file": str(bundle.segmented_raw_file),
        "continuous_raw_file": str(bundle.continuous_raw_file),
        "ranking_position": ranking_position,
        "selectors": selectors,
        "selection_notes": list(reference_input.selection_notes),
    }
    return {
        "reference_id": reference_input.reference_id,
        "display_name": reference_input.display_name,
        "entry_strategy": reference_input.entry_strategy,
        "exit_strategy": reference_input.exit_strategy,
        "tags": _normalize_tags(reference_input.tags),
        "selection": selection,
        "comparison_summary": comparison_summary,
        "annual_period_metrics": annual_period_metrics,
        "continuous_period_metrics": continuous_period_metrics,
    }


def upsert_reference_record(
    document: HallOfFameDocument,
    reference_record: HallOfFameReferenceRecord,
    updated_at: str | None = None,
) -> HallOfFameDocument:
    references = dict(document["references"])
    references[reference_record["reference_id"]] = reference_record
    ordered_references = {
        key: references[key]
        for key in sorted(references)
    }
    return {
        "schema_version": document["schema_version"],
        "record_type": document["record_type"],
        "description": document["description"],
        "updated_at": updated_at or document["updated_at"],
        "evaluation_basis": document["evaluation_basis"],
        "comparison_contract": document["comparison_contract"],
        "references": ordered_references,
    }


def write_hall_of_fame_document(path: Path, document: HallOfFameDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, ensure_ascii=True), encoding="utf-8")


def _find_latest_file(results_dir: Path, pattern: str) -> Path:
    matches = sorted(results_dir.glob(pattern))
    if not matches:
        raise HallOfFameBuildError(
            "required results file not found",
            context={"results_dir": str(results_dir), "pattern": pattern},
        )
    return matches[-1]


def _filter_strategy_rows(
    frame: pd.DataFrame,
    reference_input: HallOfFameReferenceInput,
) -> pd.DataFrame:
    required_columns = {"entry_strategy", "exit_strategy", "entry_filter"}
    missing_columns = required_columns.difference(frame.columns)
    if missing_columns:
        raise HallOfFameBuildError(
            "results file missing required columns",
            context={
                "missing_columns": ",".join(sorted(missing_columns)),
                "reference_id": reference_input.reference_id,
            },
        )

    filtered = frame[
        (frame["entry_strategy"] == reference_input.entry_strategy)
        & (frame["exit_strategy"] == reference_input.exit_strategy)
        & (frame["entry_filter"] == reference_input.entry_filter)
    ]
    filtered = _apply_optional_selector(
        filtered,
        frame,
        column="position_profile",
        value=reference_input.position_profile,
        reference_input=reference_input,
    )
    filtered = _apply_optional_selector(
        filtered,
        frame,
        column="overlay_mode",
        value=reference_input.overlay_mode,
        reference_input=reference_input,
    )
    filtered = _apply_optional_selector(
        filtered,
        frame,
        column="universe_name",
        value=reference_input.universe_name,
        reference_input=reference_input,
    )
    return filtered


def _apply_optional_selector(
    filtered: pd.DataFrame,
    full_frame: pd.DataFrame,
    *,
    column: str,
    value: str | None,
    reference_input: HallOfFameReferenceInput,
) -> pd.DataFrame:
    if value is None:
        return filtered
    if column not in full_frame.columns:
        raise HallOfFameBuildError(
            "requested selector column missing from results file",
            context={"column": column, "reference_id": reference_input.reference_id},
        )
    return filtered[filtered[column] == value]


def _build_annual_period_metrics(
    segmented_matches: pd.DataFrame,
) -> dict[str, AnnualPeriodMetrics]:
    annual_period_metrics: dict[str, AnnualPeriodMetrics] = {}
    sorted_rows = segmented_matches.sort_values("period", kind="mergesort")
    for _, row in sorted_rows.iterrows():
        period_key = str(row["period"])
        annual_period_metrics[period_key] = {
            "return_pct": _round_float(row["return_pct"]),
            "alpha_pct": _round_float(row["alpha"]),
            "max_drawdown_pct": _round_float(row["max_drawdown_pct"]),
        }
    return annual_period_metrics


def _build_continuous_period_metrics(
    row: pd.Series,
) -> ContinuousPeriodMetrics:
    return {
        "period": str(row["period"]),
        "start_date": str(row["start_date"]),
        "end_date": str(row["end_date"]),
        "return_pct": _round_float(row["return_pct"]),
        "alpha_pct": _round_float(row["alpha"]),
        "sharpe_ratio": _round_float(row["sharpe_ratio"]),
        "max_drawdown_pct": _round_float(row["max_drawdown_pct"]),
        "num_trades": int(float(row["num_trades"])),
    }


def _build_comparison_summary(
    *,
    annual_period_metrics: dict[str, AnnualPeriodMetrics],
    continuous_period_metrics: ContinuousPeriodMetrics,
) -> ComparisonSummary:
    annual_returns = [
        annual_period_metrics[period]["return_pct"] for period in annual_period_metrics
    ]
    annual_alphas = [
        annual_period_metrics[period]["alpha_pct"] for period in annual_period_metrics
    ]
    hit20_years = sum(1 for value in annual_returns if value >= 20.0)
    positive_years = sum(1 for value in annual_returns if value > 0.0)
    positive_alpha_years = sum(1 for value in annual_alphas if value > 0.0)
    annual_return_std_pct = 0.0
    if len(annual_returns) > 1:
        annual_return_std_pct = pstdev(annual_returns)

    return {
        "hit20_years": hit20_years,
        "positive_years": positive_years,
        "positive_alpha_years": positive_alpha_years,
        "avg_yearly_return_pct": _round_float(fmean(annual_returns)),
        "avg_yearly_alpha_pct": _round_float(fmean(annual_alphas)),
        "worst_year_return_pct": _round_float(min(annual_returns)),
        "annual_return_std_pct": _round_float(annual_return_std_pct),
        "continuous_return_pct": continuous_period_metrics["return_pct"],
        "continuous_alpha_pct": continuous_period_metrics["alpha_pct"],
        "continuous_sharpe_ratio": continuous_period_metrics["sharpe_ratio"],
        "continuous_mdd_pct": continuous_period_metrics["max_drawdown_pct"],
    }


def _resolve_ranking_position(row: pd.Series, row_index: int) -> int:
    if "continuous_stability_rank" in row.index:
        return int(float(row["continuous_stability_rank"]))
    return row_index + 1


def _normalize_tags(tags: tuple[str, ...]) -> list[str]:
    return sorted(set(tags))


def _round_float(value: object) -> float:
    return round(float(value), 6)


def _error_context(
    reference_input: HallOfFameReferenceInput,
    bundle: ResultsBundle,
) -> dict[str, str]:
    return {
        "reference_id": reference_input.reference_id,
        "entry_strategy": reference_input.entry_strategy,
        "exit_strategy": reference_input.exit_strategy,
        "results_dir": str(bundle.results_dir),
    }


def _build_missing_strategy_error(
    reference_input: HallOfFameReferenceInput,
    bundle: ResultsBundle,
) -> HallOfFameBuildError:
    return HallOfFameBuildError(
        "target strategy pair not found in segmented raw file",
        context=_error_context(reference_input, bundle),
    )