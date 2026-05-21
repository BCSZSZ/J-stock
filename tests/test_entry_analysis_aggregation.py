import pandas as pd

from src.entry_analysis.aggregation import aggregate_candidates, aggregate_filtered_candidates, compute_baseline
from src.entry_analysis.models import FeatureBucketRule, FeatureCondition, ManualRange


def test_manual_bucket_aggregation_computes_win_loss_capture() -> None:
    frame = pd.DataFrame(
        {
            "RSI": [45.0, 55.0, 62.0, 68.0, 82.0],
            "forward_return_5d_pct": [-1.0, 2.0, 4.0, 3.0, -2.0],
        }
    )
    rules = [
        FeatureBucketRule(
            feature="RSI",
            mode="manual",
            ranges=[ManualRange(label="mid", min=50, max=70)],
        )
    ]

    result = aggregate_candidates(frame, rules, [5], min_samples=1, include_joint=True)
    row = result.iloc[0]

    assert row["bucket"] == "mid"
    assert row["count"] == 3
    assert row["wins"] == 3
    assert row["losses"] == 0
    assert row["win_rate"] == 1.0
    assert row["win_capture"] == 1.0
    assert row["loss_capture"] == 0.0


def test_sliding_bucket_and_baseline_are_horizon_specific() -> None:
    frame = pd.DataFrame(
        {
            "ADX_14": [12.0, 16.0, 19.0, 24.0],
            "forward_return_3d_pct": [1.0, -1.0, 2.0, 3.0],
            "forward_return_5d_pct": [-1.0, -2.0, 2.0, 4.0],
        }
    )
    rules = [FeatureBucketRule(feature="ADX_14", mode="sliding", min=10, max=30, window=10, step=5)]

    result = aggregate_candidates(frame, rules, [3, 5], min_samples=1, include_joint=False)
    baseline = compute_baseline(frame, [3, 5])

    assert baseline["3d"]["wins"] == 3
    assert baseline["5d"]["wins"] == 2
    assert set(result["horizon"]) == {3, 5}
    assert "ADX_14:[15,25)" in set(result["bucket"])


def test_filtered_aggregation_supports_intersection_and_union() -> None:
    frame = pd.DataFrame(
        {
            "RSI": [35.0, 45.0, 55.0, 75.0],
            "ADX_14": [10.0, 25.0, 15.0, 30.0],
            "forward_return_5d_pct": [-2.0, 3.0, -1.0, 4.0],
        }
    )
    conditions = [
        FeatureCondition(feature="RSI", operator="between", min=40, max=60),
        FeatureCondition(feature="ADX_14", operator=">=", value=20),
    ]

    intersection = aggregate_filtered_candidates(frame, conditions, [5], logic="all")
    union = aggregate_filtered_candidates(frame, conditions, [5], logic="any")

    assert intersection["filtered"]["candidate_count"] == 1
    assert intersection["filtered"]["5d"]["wins"] == 1
    assert union["filtered"]["candidate_count"] == 3
    assert union["filtered"]["5d"]["wins"] == 2
