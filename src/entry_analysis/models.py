from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from src.artifacts.tabular import LargeArtifactFormat


ForwardLabelMode = Literal["signal_close", "next_open"]
BucketMode = Literal["manual", "sliding", "fixed", "quantile", "categorical"]
FeatureConditionOperator = Literal[
    "between",
    ">=",
    ">",
    "<=",
    "<",
    "==",
    "!=",
    "is_null",
    "not_null",
]
FeatureLogicMode = Literal["all", "any"]


class ManualRange(BaseModel):
    label: str | None = None
    min: float | None = None
    max: float | None = None


class FeatureBucketRule(BaseModel):
    feature: str
    mode: BucketMode = "sliding"
    label: str | None = None
    ranges: list[ManualRange] = Field(default_factory=list)
    min: float | None = None
    max: float | None = None
    window: float | None = None
    step: float | None = None
    bin_width: float | None = None
    quantiles: int | None = None
    include_null: bool = False


class EntryAnalysisRequest(BaseModel):
    entry_strategies: list[str]
    tickers: list[str]
    start_date: date
    end_date: date
    horizons: list[int] = Field(default_factory=lambda: [3, 5, 10])
    indicator_columns: list[str] = Field(default_factory=list)
    rules: list[FeatureBucketRule] = Field(default_factory=list)
    label_mode: ForwardLabelMode = "signal_close"
    primary_horizon: int = 5
    min_samples: int = 30
    include_joint: bool = True
    data_root: str = "data"
    output_dir: str = "entry_analysis"
    save_candidates: bool = True
    large_artifact_format: LargeArtifactFormat = "parquet"

    @property
    def normalized_horizons(self) -> list[int]:
        return sorted({int(value) for value in self.horizons if int(value) > 0})


class EntrySignalCandidate(BaseModel):
    entry_strategy: str
    ticker: str
    signal_date: str
    action: str = "BUY"
    confidence: float
    score: float | None = None
    reasons_json: str
    metadata_json: str


class EntryAnalysisArtifacts(BaseModel):
    output_dir: str
    candidates_csv: str | None = None
    candidates_parquet: str | None = None
    aggregates_csv: str | None = None
    summary_json: str
    rules_json: str | None = None
    report_md: str
    manifest_json: str


class EntryAnalysisDatasetManifest(BaseModel):
    dataset_id: str
    generated_at: str
    output_dir: str
    candidates_csv: str | None = None
    candidates_parquet: str | None = None
    summary_json: str
    report_md: str
    entry_strategies: list[str]
    universe_size: int
    start_date: str
    end_date: str
    horizons: list[int]
    label_mode: ForwardLabelMode
    indicator_columns: list[str]
    candidate_count: int
    feature_columns: list[str]
    request: dict[str, object]


class FeatureCondition(BaseModel):
    feature: str
    operator: FeatureConditionOperator = "between"
    min: float | None = None
    max: float | None = None
    value: str | float | bool | None = None


class EntryAnalysisRunSummary(BaseModel):
    generated_at: str
    request: dict[str, object]
    candidate_count: int
    aggregate_count: int
    baseline: dict[str, object]
    top_positive: list[dict[str, object]]
    top_avoid: list[dict[str, object]]
    artifacts: EntryAnalysisArtifacts
