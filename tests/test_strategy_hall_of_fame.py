from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.utils.strategy_hall_of_fame import (
    HallOfFameBuildError,
    HallOfFameReferenceInput,
    build_reference_record,
    find_latest_results_bundle,
    new_hall_of_fame_document,
    upsert_reference_record,
    write_hall_of_fame_document,
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


def _write_sample_results(results_dir: Path) -> None:
    _write_csv(
        results_dir / "strategy_evaluation_raw_20260409_131306.csv",
        [
            {
                "period": "2021",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 21.868133544921875,
                "alpha": 15.04766086756062,
                "max_drawdown_pct": 12.952677385713745,
            },
            {
                "period": "2022",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 37.193741981506356,
                "alpha": 44.01615531602183,
                "max_drawdown_pct": 10.989475677834022,
            },
            {
                "period": "2023",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 26.682295776367184,
                "alpha": 0.012060516885895822,
                "max_drawdown_pct": 11.458792584278829,
            },
            {
                "period": "2024",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 6.391091857910158,
                "alpha": -10.681873809509003,
                "max_drawdown_pct": 21.923916413671797,
            },
            {
                "period": "2025",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 111.80737487792966,
                "alpha": 88.13175685719234,
                "max_drawdown_pct": 6.000945733796018,
            },
            {
                "period": "2025",
                "entry_strategy": "OtherEntry",
                "exit_strategy": "OtherExit",
                "entry_filter": "off",
                "return_pct": 1.0,
                "alpha": 1.0,
                "max_drawdown_pct": 1.0,
            },
        ],
    )

    _write_csv(
        results_dir / "strategy_evaluation_raw_20260409_120000.csv",
        [
            {
                "period": "2025",
                "entry_strategy": "OldEntry",
                "exit_strategy": "OldExit",
                "entry_filter": "off",
                "return_pct": 0.0,
                "alpha": 0.0,
                "max_drawdown_pct": 0.0,
            }
        ],
    )

    _write_csv(
        results_dir / "strategy_evaluation_continuous_raw_20260409_133658.csv",
        [
            {
                "period": "2021-2025_continuous",
                "start_date": "2021-01-01",
                "end_date": "2025-12-31",
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "return_pct": 349.9233356170654,
                "alpha": 267.148500753893,
                "sharpe_ratio": 1.676798808686809,
                "max_drawdown_pct": 24.702982660746652,
                "num_trades": 1006,
            },
            {
                "period": "2021-2025_continuous",
                "start_date": "2021-01-01",
                "end_date": "2025-12-31",
                "entry_strategy": "OtherEntry",
                "exit_strategy": "OtherExit",
                "entry_filter": "off",
                "return_pct": 1.0,
                "alpha": 1.0,
                "sharpe_ratio": 1.0,
                "max_drawdown_pct": 1.0,
                "num_trades": 1,
            },
        ],
    )

    _write_csv(
        results_dir / "strategy_evaluation_continuous_raw_20260409_120000.csv",
        [
            {
                "period": "2021-2025_continuous",
                "start_date": "2021-01-01",
                "end_date": "2025-12-31",
                "entry_strategy": "OldEntry",
                "exit_strategy": "OldExit",
                "entry_filter": "off",
                "return_pct": 0.0,
                "alpha": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown_pct": 0.0,
                "num_trades": 0,
            }
        ],
    )

    _write_csv(
        results_dir / "strategy_evaluation_continuous_stability_rank_20260409_133712.csv",
        [
            {
                "continuous_stability_rank": 1,
                "entry_strategy": "MACDCrossoverStrategy",
                "exit_strategy": "MVX_N3_R3p85_T2p0_D21_B20p0",
                "entry_filter": "off",
                "continuous_return_pct": 349.9233356170654,
            },
            {
                "continuous_stability_rank": 2,
                "entry_strategy": "OtherEntry",
                "exit_strategy": "OtherExit",
                "entry_filter": "off",
                "continuous_return_pct": 1.0,
            },
        ],
    )

    _write_csv(
        results_dir / "strategy_evaluation_continuous_stability_rank_20260409_120000.csv",
        [
            {
                "continuous_stability_rank": 1,
                "entry_strategy": "OldEntry",
                "exit_strategy": "OldExit",
                "entry_filter": "off",
                "continuous_return_pct": 0.0,
            }
        ],
    )


def test_find_latest_results_bundle_picks_latest_matching_files(tmp_path: Path) -> None:
    _write_sample_results(tmp_path)

    bundle = find_latest_results_bundle(tmp_path)

    assert bundle.segmented_raw_file.name == "strategy_evaluation_raw_20260409_131306.csv"
    assert (
        bundle.continuous_raw_file.name
        == "strategy_evaluation_continuous_raw_20260409_133658.csv"
    )
    assert (
        bundle.ranking_file.name
        == "strategy_evaluation_continuous_stability_rank_20260409_133712.csv"
    )


def test_build_reference_record_extracts_final_review_metrics(tmp_path: Path) -> None:
    _write_sample_results(tmp_path)

    record = build_reference_record(
        HallOfFameReferenceInput(
            reference_id="baseline_champion",
            display_name="Baseline Champion",
            results_dir=tmp_path,
            entry_strategy="MACDCrossoverStrategy",
            exit_strategy="MVX_N3_R3p85_T2p0_D21_B20p0",
            tags=("baseline", "champion", "benchmark"),
        )
    )

    assert record["reference_id"] == "baseline_champion"
    assert record["comparison_summary"]["hit20_years"] == 4
    assert record["comparison_summary"]["positive_years"] == 5
    assert record["comparison_summary"]["positive_alpha_years"] == 4
    assert record["comparison_summary"]["worst_year_return_pct"] == pytest.approx(
        6.391091857910158
    )
    assert record["comparison_summary"]["continuous_return_pct"] == pytest.approx(
        349.9233356170654
    )
    assert record["comparison_summary"]["continuous_alpha_pct"] == pytest.approx(
        267.148500753893
    )
    assert record["comparison_summary"]["continuous_sharpe_ratio"] == pytest.approx(
        1.676798808686809
    )
    assert record["comparison_summary"]["continuous_mdd_pct"] == pytest.approx(
        24.702982660746652
    )
    assert record["annual_period_metrics"]["2024"]["return_pct"] == pytest.approx(
        6.391091857910158
    )
    assert record["annual_period_metrics"]["2024"]["alpha_pct"] == pytest.approx(
        -10.681873809509003
    )
    assert record["selection"]["ranking_position"] == 1


def test_build_reference_record_raises_when_target_strategy_is_missing(
    tmp_path: Path,
) -> None:
    _write_sample_results(tmp_path)

    with pytest.raises(HallOfFameBuildError):
        build_reference_record(
            HallOfFameReferenceInput(
                reference_id="missing_reference",
                display_name="Missing Reference",
                results_dir=tmp_path,
                entry_strategy="NotPresentEntry",
                exit_strategy="NotPresentExit",
                tags=("candidate",),
            )
        )


def test_upsert_and_write_document_produces_stable_sorted_output(tmp_path: Path) -> None:
    document = new_hall_of_fame_document(updated_at="2026-04-10")
    baseline_record = {
        "reference_id": "baseline_champion",
        "display_name": "Baseline Champion",
        "entry_strategy": "MACDCrossoverStrategy",
        "exit_strategy": "MVX_A",
        "tags": ["baseline", "champion"],
        "selection": {
            "results_dir": "G:/results/baseline",
            "ranking_file": "G:/results/baseline/rank.csv",
            "segmented_raw_file": "G:/results/baseline/raw.csv",
            "continuous_raw_file": "G:/results/baseline/continuous.csv",
            "ranking_position": 1,
        },
        "comparison_summary": {
            "hit20_years": 4,
            "positive_years": 5,
            "positive_alpha_years": 4,
            "avg_yearly_return_pct": 40.0,
            "avg_yearly_alpha_pct": 27.0,
            "worst_year_return_pct": 6.0,
            "annual_return_std_pct": 36.0,
            "continuous_return_pct": 349.0,
            "continuous_alpha_pct": 267.0,
            "continuous_sharpe_ratio": 1.6,
            "continuous_mdd_pct": 24.7,
        },
        "annual_period_metrics": {
            "2024": {
                "return_pct": 6.0,
                "alpha_pct": -10.0,
                "max_drawdown_pct": 21.9,
            }
        },
        "continuous_period_metrics": {
            "period": "2021-2025_continuous",
            "start_date": "2021-01-01",
            "end_date": "2025-12-31",
            "return_pct": 349.0,
            "alpha_pct": 267.0,
            "sharpe_ratio": 1.6,
            "max_drawdown_pct": 24.7,
            "num_trades": 1006,
        },
    }
    production_record = {
        "reference_id": "production_reference",
        "display_name": "Production Reference",
        "entry_strategy": "MACDCrossoverStrategy",
        "exit_strategy": "MVX_B",
        "tags": ["benchmark", "production"],
        "selection": {
            "results_dir": "G:/results/production",
            "ranking_file": "G:/results/production/rank.csv",
            "segmented_raw_file": "G:/results/production/raw.csv",
            "continuous_raw_file": "G:/results/production/continuous.csv",
            "ranking_position": 1,
        },
        "comparison_summary": {
            "hit20_years": 4,
            "positive_years": 5,
            "positive_alpha_years": 3,
            "avg_yearly_return_pct": 30.0,
            "avg_yearly_alpha_pct": 16.0,
            "worst_year_return_pct": 1.0,
            "annual_return_std_pct": 24.0,
            "continuous_return_pct": 275.0,
            "continuous_alpha_pct": 192.0,
            "continuous_sharpe_ratio": 1.5,
            "continuous_mdd_pct": 23.1,
        },
        "annual_period_metrics": {
            "2024": {
                "return_pct": 1.0,
                "alpha_pct": -15.9,
                "max_drawdown_pct": 23.0,
            }
        },
        "continuous_period_metrics": {
            "period": "2021-2025_continuous",
            "start_date": "2021-01-01",
            "end_date": "2025-12-31",
            "return_pct": 275.0,
            "alpha_pct": 192.0,
            "sharpe_ratio": 1.5,
            "max_drawdown_pct": 23.1,
            "num_trades": 1128,
        },
    }

    document = upsert_reference_record(document, production_record)
    document = upsert_reference_record(document, baseline_record)
    output_path = tmp_path / "strategy_hall_of_fame.json"
    write_hall_of_fame_document(output_path, document)

    saved_document = json.loads(output_path.read_text(encoding="utf-8"))

    assert saved_document["comparison_contract"]["final_review_metrics"] == [
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
    assert list(saved_document["references"].keys()) == [
        "baseline_champion",
        "production_reference",
    ]