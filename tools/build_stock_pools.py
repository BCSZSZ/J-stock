from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Final

import pandas as pd


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class PoolBuildError(RuntimeError):
    def __init__(self, message: str, details: dict[str, str] | None = None) -> None:
        context = ""
        if details:
            pairs = ", ".join(f"{key}={value}" for key, value in sorted(details.items()))
            context = f" [{pairs}]"
        super().__init__(f"{message}{context}")


@dataclass(frozen=True)
class BasePoolSnapshot:
    ordered_codes: list[str]
    names: dict[str, str]


@dataclass(frozen=True)
class PoolTickerRecord:
    code: str
    name: str
    sector: str
    source: str
    reason: str
    score_model: str
    score: float | None

    def to_json(self) -> dict[str, str | float | None]:
        return {
            "code": self.code,
            "name": self.name,
            "sector": self.sector,
            "source": self.source,
            "reason": self.reason,
            "score_model": self.score_model,
            "score": self.score,
        }


@dataclass(frozen=True)
class PoolArtifact:
    pool_name: str
    description: str
    score_model: str
    selection_rule: str
    tickers: list[PoolTickerRecord]

    def to_json(self) -> dict[str, object]:
        return {
            "version": "1.0",
            "selection_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pool_name": self.pool_name,
            "description": self.description,
            "score_model": self.score_model,
            "selection_rule": self.selection_rule,
            "total_count": len(self.tickers),
            "tickers": [ticker.to_json() for ticker in self.tickers],
        }


@dataclass(frozen=True)
class PoolSummaryRecord:
    pool_name: str
    score_model: str
    selection_rule: str
    target_size: int
    actual_size: int
    unique_sector_count: int
    min_score: float | None
    avg_score: float | None
    max_score: float | None
    overlap_with_production: int
    overlap_pct: float
    sector_counts: str
    top_additions: str
    top_removals: str

    def to_dict(self) -> dict[str, object]:
        return {
            "pool_name": self.pool_name,
            "score_model": self.score_model,
            "selection_rule": self.selection_rule,
            "target_size": self.target_size,
            "actual_size": self.actual_size,
            "unique_sector_count": self.unique_sector_count,
            "min_score": self.min_score,
            "avg_score": self.avg_score,
            "max_score": self.max_score,
            "overlap_with_production": self.overlap_with_production,
            "overlap_pct": self.overlap_pct,
            "sector_counts": self.sector_counts,
            "top_additions": self.top_additions,
            "top_removals": self.top_removals,
        }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build approved stock pool review variants")
    parser.add_argument("--base-pool", required=True, help="Production pool snapshot JSON")
    parser.add_argument("--scores-dir-v2", required=True, help="Directory or parquet file for v2 scores")
    parser.add_argument("--scores-dir-v4", required=True, help="Directory or parquet file for v4 scores")
    parser.add_argument("--scores-dir-v6", required=True, help="Directory or parquet file for v6 scores")
    parser.add_argument(
        "--classification-csv",
        default="data/jpx_final_list.csv",
        help="JPX classification CSV with Type, sector, and size columns",
    )
    parser.add_argument("--output-dir", required=True, help="Directory to write pool JSON files and summary CSV")
    parser.add_argument("--target-size", type=int, default=100, help="Target ticker count per pool")
    return parser.parse_args()


def _resolve_latest_score_file(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_file():
        return path
    if not path.exists():
        raise PoolBuildError("Score path does not exist", {"path": str(path)})

    candidates = sorted(
        path.glob("scores_all_final_*.parquet"),
        key=lambda file_path: file_path.stat().st_mtime,
    )
    if not candidates:
        raise PoolBuildError("No scores_all_final parquet found", {"path": str(path)})
    return candidates[-1]


def _load_classification_frame(path_value: str) -> pd.DataFrame:
    path = Path(path_value)
    if not path.exists():
        raise PoolBuildError("Classification CSV does not exist", {"path": str(path)})

    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"Code", "Type", "33業種区分", "規模区分"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PoolBuildError(
            "Classification CSV missing required columns",
            {"path": str(path), "missing": ",".join(missing)},
        )

    name_column = "銘柄名" if "銘柄名" in frame.columns else "Code"
    normalized = pd.DataFrame(
        {
            "code": frame["Code"].astype(str).str.strip().str.zfill(4),
            "classification_name": frame[name_column].fillna("Unknown").astype(str).str.strip(),
            "classification_sector": _normalize_text_column(frame, "33業種区分", "Unknown"),
            "classification_size": _normalize_text_column(frame, "規模区分", "Unknown"),
            "classification_type": _normalize_text_column(frame, "Type", "Unknown"),
        }
    )
    normalized = normalized[normalized["code"] != ""].drop_duplicates(subset=["code"], keep="first")
    return normalized


def _pick_name_column(frame: pd.DataFrame) -> str:
    for column in ["銘柄名", "CompanyName", "name"]:
        if column in frame.columns:
            return column
    raise PoolBuildError("Score file lacks a name column", {"columns": ",".join(frame.columns)})


def _normalize_text_column(frame: pd.DataFrame, column: str, fallback: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([fallback] * len(frame), index=frame.index, dtype="object")
    return frame[column].fillna(fallback).astype(str).str.strip().replace("", fallback)


def _prefer_series(primary: pd.Series, fallback: pd.Series) -> pd.Series:
    return primary.where(primary.notna() & primary.astype(str).ne(""), fallback)


def _prefer_name_series(primary: pd.Series, fallback: pd.Series, codes: pd.Series) -> pd.Series:
    normalized = primary.fillna("").astype(str).str.strip()
    placeholder_mask = (
        normalized.eq("")
        | normalized.eq("Unknown")
        | normalized.str.startswith("Stock_")
        | normalized.eq(codes.astype(str).str.strip())
    )
    return primary.where(~placeholder_mask, fallback)


def _load_score_frame(score_path: Path, classification_frame: pd.DataFrame) -> pd.DataFrame:
    if score_path.suffix.lower() == ".csv":
        frame = pd.read_csv(score_path, encoding="utf-8-sig")
    else:
        frame = pd.read_parquet(score_path)
    required = {"Code", "TotalScore"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise PoolBuildError(
            "Score file missing required columns",
            {"path": str(score_path), "missing": ",".join(missing)},
        )

    normalized_codes = frame["Code"].astype(str).str.strip().str.zfill(4)
    merged = frame.copy()
    merged["code"] = normalized_codes
    merged = merged.merge(classification_frame, on="code", how="left")

    name_series = None
    for column in ["銘柄名", "CompanyName", "name"]:
        if column in merged.columns:
            name_series = _normalize_text_column(merged, column, "Unknown")
            break
    if name_series is None:
        name_series = pd.Series(["Unknown"] * len(merged), index=merged.index, dtype="object")

    sector_series = _prefer_series(
        _normalize_text_column(merged, "33業種区分", ""),
        _normalize_text_column(merged, "classification_sector", "Unknown"),
    )
    size_series = _prefer_series(
        _normalize_text_column(merged, "規模区分", ""),
        _normalize_text_column(merged, "classification_size", "Unknown"),
    )
    type_series = _prefer_series(
        _normalize_text_column(merged, "Type", ""),
        _normalize_text_column(merged, "classification_type", "Unknown"),
    )
    merged_name_series = _prefer_name_series(
        name_series,
        _normalize_text_column(merged, "classification_name", "Unknown"),
        merged["code"],
    )

    rank_liq_series = (
        pd.to_numeric(merged["Rank_Liq"], errors="coerce")
        if "Rank_Liq" in merged.columns
        else pd.Series([0.0] * len(merged), index=merged.index, dtype="float64")
    )

    normalized = pd.DataFrame(
        {
            "code": merged["code"],
            "name": merged_name_series,
            "sector": sector_series,
            "size_bucket": size_series,
            "security_type": type_series,
            "score": pd.to_numeric(merged["TotalScore"], errors="coerce").fillna(0.0),
            "rank_liq": rank_liq_series.fillna(0.0),
        }
    )
    normalized = normalized[normalized["code"] != ""].drop_duplicates(subset=["code"], keep="first")
    normalized = normalized.sort_values("score", ascending=False).reset_index(drop=True)
    return normalized


def _load_base_pool(path_value: str) -> BasePoolSnapshot:
    path = Path(path_value)
    if not path.exists():
        raise PoolBuildError("Base pool file does not exist", {"path": str(path)})

    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_items = payload.get("tickers", []) if isinstance(payload, dict) else payload
    ordered_codes: list[str] = []
    names: dict[str, str] = {}
    for item in raw_items:
        if isinstance(item, dict):
            code = str(item.get("code", "")).strip().zfill(4)
            name = str(item.get("name", f"Stock_{code}")).strip()
        else:
            code = str(item).strip().zfill(4)
            name = f"Stock_{code}"
        if not code:
            continue
        ordered_codes.append(code)
        names[code] = name
    return BasePoolSnapshot(ordered_codes=ordered_codes, names=names)


def _stock_only(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["security_type"].eq("Stock")].copy().reset_index(drop=True)


def _build_lookup(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.set_index("code", drop=False)


def _dedupe_codes(codes: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for code in codes:
        if code in seen:
            continue
        ordered.append(code)
        seen.add(code)
    return ordered


def _pick_with_size_balance(df_sector: pd.DataFrame, quota: int) -> list[str]:
    buckets: list[pd.DataFrame] = []
    for _, group in df_sector.groupby("size_bucket", dropna=False):
        bucket = group.sort_values("score", ascending=False).reset_index(drop=True)
        if not bucket.empty:
            buckets.append(bucket)

    if not buckets:
        return df_sector.head(quota)["code"].astype(str).tolist()

    indices = [0] * len(buckets)
    selected: list[str] = []

    while len(selected) < quota:
        progressed = False
        for bucket_index, bucket in enumerate(buckets):
            if len(selected) >= quota:
                break
            if indices[bucket_index] < len(bucket):
                selected.append(str(bucket.iloc[indices[bucket_index]]["code"]))
                indices[bucket_index] += 1
                progressed = True
        if not progressed:
            break

    return _dedupe_codes(selected)[:quota]


def _fill_to_target(
    selected_codes: list[str],
    ranked_frame: pd.DataFrame,
    target_size: int,
) -> list[str]:
    selected = list(selected_codes)
    selected_set = set(selected)
    if len(selected) >= target_size:
        return selected[:target_size]

    for _, row in ranked_frame.iterrows():
        code = str(row["code"])
        if code in selected_set:
            continue
        selected.append(code)
        selected_set.add(code)
        if len(selected) >= target_size:
            break

    return selected


def _select_with_sector_cap(
    ranked_frame: pd.DataFrame,
    target_size: int,
    sector_cap: int,
) -> list[str]:
    selected: list[str] = []
    selected_set: set[str] = set()
    sector_counts: Counter[str] = Counter()

    for _, row in ranked_frame.iterrows():
        code = str(row["code"])
        sector = str(row["sector"])
        if code in selected_set:
            continue
        if sector_counts[sector] >= sector_cap:
            continue
        selected.append(code)
        selected_set.add(code)
        sector_counts[sector] += 1
        if len(selected) >= target_size:
            return selected

    return _fill_to_target(selected, ranked_frame, target_size)


def _expand_from_base(
    base_codes: list[str],
    ranked_frame: pd.DataFrame,
    target_size: int,
    sector_cap: int,
) -> list[str]:
    lookup = _build_lookup(ranked_frame)
    selected = [code for code in base_codes if code in lookup.index]
    selected_set = set(selected)
    sector_counts: Counter[str] = Counter()
    for code in selected:
        sector_counts[str(lookup.loc[code, "sector"])] += 1

    for _, row in ranked_frame.iterrows():
        code = str(row["code"])
        sector = str(row["sector"])
        if code in selected_set:
            continue
        if sector_counts[sector] >= sector_cap:
            continue
        selected.append(code)
        selected_set.add(code)
        sector_counts[sector] += 1
        if len(selected) >= target_size:
            return selected

    return _fill_to_target(selected, ranked_frame, target_size)


def _select_sector_balanced(
    ranked_frame: pd.DataFrame,
    per_sector: int,
    target_size: int,
) -> list[str]:
    selected: list[str] = []
    selected_set: set[str] = set()

    for sector, group in ranked_frame.groupby("sector", sort=True):
        quota = min(per_sector, len(group))
        picked_codes = _pick_with_size_balance(group, quota)
        for code in picked_codes:
            if code in selected_set:
                continue
            selected.append(code)
            selected_set.add(code)

    return _fill_to_target(selected, ranked_frame, target_size)


def _code_score(code: str, lookup: pd.DataFrame) -> float:
    if code not in lookup.index:
        return -1.0
    return float(lookup.loc[code, "score"])


def _format_code_name_list(
    codes: list[str],
    lookup: pd.DataFrame,
    fallback_names: dict[str, str],
    limit: int,
) -> str:
    formatted: list[str] = []
    for code in codes[:limit]:
        if code in lookup.index:
            name = str(lookup.loc[code, "name"])
        else:
            name = fallback_names.get(code, f"Stock_{code}")
        formatted.append(f"{code}:{name}")
    return "|".join(formatted)


def _sector_counts_string(tickers: list[PoolTickerRecord]) -> str:
    counts = Counter(ticker.sector for ticker in tickers)
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return "|".join(f"{sector}:{count}" for sector, count in ordered)


def _build_ticker_records(
    codes: list[str],
    lookup: pd.DataFrame,
    fallback_names: dict[str, str],
    *,
    score_model: str,
    base_codes: set[str],
    added_reason: str,
    base_reason: str,
) -> list[PoolTickerRecord]:
    records: list[PoolTickerRecord] = []
    for code in codes:
        if code in lookup.index:
            row = lookup.loc[code]
            name = str(row["name"])
            sector = str(row["sector"])
            score = float(row["score"])
        else:
            name = fallback_names.get(code, f"Stock_{code}")
            sector = "Unknown"
            score = None
        if code in base_codes:
            source = "production_base"
            reason = base_reason
        else:
            source = "model_selected"
            reason = added_reason
        records.append(
            PoolTickerRecord(
                code=code,
                name=name,
                sector=sector,
                source=source,
                reason=reason,
                score_model=score_model,
                score=score,
            )
        )
    return records


def _build_summary_record(
    artifact: PoolArtifact,
    production_codes: list[str],
    lookup: pd.DataFrame,
    fallback_names: dict[str, str],
    target_size: int,
) -> PoolSummaryRecord:
    production_set = set(production_codes)
    pool_codes = [ticker.code for ticker in artifact.tickers]
    pool_set = set(pool_codes)

    overlap_count = len(production_set & pool_set)
    overlap_pct = round((overlap_count / len(production_set)) * 100, 2) if production_set else 0.0

    additions = [code for code in pool_codes if code not in production_set]
    removals = sorted(
        [code for code in production_codes if code not in pool_set],
        key=lambda code: _code_score(code, lookup),
        reverse=True,
    )

    scores = [ticker.score for ticker in artifact.tickers if ticker.score is not None]
    min_score = round(min(scores), 6) if scores else None
    avg_score = round(sum(scores) / len(scores), 6) if scores else None
    max_score = round(max(scores), 6) if scores else None

    return PoolSummaryRecord(
        pool_name=artifact.pool_name,
        score_model=artifact.score_model,
        selection_rule=artifact.selection_rule,
        target_size=target_size,
        actual_size=len(artifact.tickers),
        unique_sector_count=len({ticker.sector for ticker in artifact.tickers}),
        min_score=min_score,
        avg_score=avg_score,
        max_score=max_score,
        overlap_with_production=overlap_count,
        overlap_pct=overlap_pct,
        sector_counts=_sector_counts_string(artifact.tickers),
        top_additions=_format_code_name_list(additions, lookup, fallback_names, 10),
        top_removals=_format_code_name_list(removals, lookup, fallback_names, 10),
    )


def _write_pool_artifact(artifact: PoolArtifact, output_dir: Path) -> None:
    output_path = output_dir / f"{artifact.pool_name}.json"
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(artifact.to_json(), handle, indent=2, ensure_ascii=False)


def _validate_size(name: str, codes: list[str], target_size: int) -> None:
    if len(codes) != target_size:
        raise PoolBuildError(
            "Pool size mismatch",
            {"pool": name, "actual": str(len(codes)), "target": str(target_size)},
        )


def _build_prod_expand_pool(
    target_size: int,
    base_pool: BasePoolSnapshot,
    v2_frame: pd.DataFrame,
) -> tuple[PoolArtifact, PoolSummaryRecord]:
    lookup = _build_lookup(v2_frame)
    production_stock_codes = [code for code in base_pool.ordered_codes if code in lookup.index]
    selected_codes = _expand_from_base(production_stock_codes, v2_frame, target_size, sector_cap=8)
    _validate_size("prod_expand_v2_100", selected_codes, target_size)

    artifact = PoolArtifact(
        pool_name="prod_expand_v2_100",
        description="Expand the current production stock pool with top v2 names while minimizing drift.",
        score_model="v2",
        selection_rule="production stocks only, then highest v2 TotalScore additions, sector cap 8 with score-order backfill",
        tickers=_build_ticker_records(
            selected_codes,
            lookup,
            base_pool.names,
            score_model="v2",
            base_codes=set(production_stock_codes),
            added_reason="v2_expand_sector_cap8",
            base_reason="production_stock_base",
        ),
    )
    summary = _build_summary_record(artifact, base_pool.ordered_codes, lookup, base_pool.names, target_size)
    return artifact, summary


def _build_top_v2_pool(
    target_size: int,
    base_pool: BasePoolSnapshot,
    v2_frame: pd.DataFrame,
) -> tuple[PoolArtifact, PoolSummaryRecord]:
    lookup = _build_lookup(v2_frame)
    selected_codes = _select_with_sector_cap(v2_frame, target_size, sector_cap=12)
    _validate_size("top100_v2_raw", selected_codes, target_size)

    artifact = PoolArtifact(
        pool_name="top100_v2_raw",
        description="Pure top-100 v2 score pool with a light sector concentration backstop.",
        score_model="v2",
        selection_rule="highest v2 TotalScore, sector cap 12 with score-order backfill",
        tickers=_build_ticker_records(
            selected_codes,
            lookup,
            base_pool.names,
            score_model="v2",
            base_codes=set(),
            added_reason="v2_top100_sector_cap12",
            base_reason="",
        ),
    )
    summary = _build_summary_record(artifact, base_pool.ordered_codes, lookup, base_pool.names, target_size)
    return artifact, summary


def _build_sector_v2_pool(
    target_size: int,
    base_pool: BasePoolSnapshot,
    v2_frame: pd.DataFrame,
) -> tuple[PoolArtifact, PoolSummaryRecord]:
    lookup = _build_lookup(v2_frame)
    selected_codes = _select_sector_balanced(v2_frame, per_sector=3, target_size=target_size)
    _validate_size("sector33x3p1_v2", selected_codes, target_size)

    artifact = PoolArtifact(
        pool_name="sector33x3p1_v2",
        description="Three names per 33-sector bucket using v2 scores, then global score backfill to target size.",
        score_model="v2",
        selection_rule="3 per sector with size-balance round-robin, then highest remaining v2 TotalScore backfill",
        tickers=_build_ticker_records(
            selected_codes,
            lookup,
            base_pool.names,
            score_model="v2",
            base_codes=set(),
            added_reason="v2_sector33x3_balance",
            base_reason="",
        ),
    )
    summary = _build_summary_record(artifact, base_pool.ordered_codes, lookup, base_pool.names, target_size)
    return artifact, summary


def _build_sector_v4_pool(
    target_size: int,
    base_pool: BasePoolSnapshot,
    v4_frame: pd.DataFrame,
) -> tuple[PoolArtifact, PoolSummaryRecord]:
    lookup = _build_lookup(v4_frame)
    selected_codes = _select_sector_balanced(v4_frame, per_sector=3, target_size=target_size)
    _validate_size("sector33x3p1_v4", selected_codes, target_size)

    artifact = PoolArtifact(
        pool_name="sector33x3p1_v4",
        description="Three names per 33-sector bucket using v4 trend-momentum scores, then global score backfill.",
        score_model="v4",
        selection_rule="3 per sector with size-balance round-robin, then highest remaining v4 TotalScore backfill",
        tickers=_build_ticker_records(
            selected_codes,
            lookup,
            base_pool.names,
            score_model="v4",
            base_codes=set(),
            added_reason="v4_sector33x3_balance",
            base_reason="",
        ),
    )
    summary = _build_summary_record(artifact, base_pool.ordered_codes, lookup, base_pool.names, target_size)
    return artifact, summary


def _build_top_v6_liquidity_pool(
    target_size: int,
    base_pool: BasePoolSnapshot,
    v6_frame: pd.DataFrame,
) -> tuple[PoolArtifact, PoolSummaryRecord]:
    filtered = v6_frame[v6_frame["rank_liq"] >= 0.50].copy().reset_index(drop=True)
    lookup = _build_lookup(filtered)
    selected_codes = _select_with_sector_cap(filtered, target_size, sector_cap=8)
    _validate_size("top100_v6_liq50_cap8", selected_codes, target_size)

    artifact = PoolArtifact(
        pool_name="top100_v6_liq50_cap8",
        description="Top v6 score pool after a Rank_Liq >= 0.50 liquidity floor and sector cap 8.",
        score_model="v6",
        selection_rule="Rank_Liq >= 0.50, then highest v6 TotalScore, sector cap 8 with score-order backfill",
        tickers=_build_ticker_records(
            selected_codes,
            lookup,
            base_pool.names,
            score_model="v6",
            base_codes=set(),
            added_reason="v6_top100_liq50_sector_cap8",
            base_reason="",
        ),
    )
    summary = _build_summary_record(artifact, base_pool.ordered_codes, lookup, base_pool.names, target_size)
    return artifact, summary


def main() -> None:
    args = _parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    classification_frame = _load_classification_frame(args.classification_csv)
    classification_names = {
        str(row["code"]): str(row["classification_name"])
        for _, row in classification_frame.iterrows()
    }
    base_pool_snapshot = _load_base_pool(args.base_pool)
    merged_base_names = dict(base_pool_snapshot.names)
    for code, name in classification_names.items():
        if name and name != "Unknown":
            merged_base_names[code] = name
    base_pool = BasePoolSnapshot(
        ordered_codes=base_pool_snapshot.ordered_codes,
        names=merged_base_names,
    )

    v2_frame = _stock_only(_load_score_frame(_resolve_latest_score_file(args.scores_dir_v2), classification_frame))
    v4_frame = _stock_only(_load_score_frame(_resolve_latest_score_file(args.scores_dir_v4), classification_frame))
    v6_frame = _stock_only(_load_score_frame(_resolve_latest_score_file(args.scores_dir_v6), classification_frame))

    builders = [
        _build_prod_expand_pool(args.target_size, base_pool, v2_frame),
        _build_top_v2_pool(args.target_size, base_pool, v2_frame),
        _build_sector_v2_pool(args.target_size, base_pool, v2_frame),
        _build_sector_v4_pool(args.target_size, base_pool, v4_frame),
        _build_top_v6_liquidity_pool(args.target_size, base_pool, v6_frame),
    ]

    summaries: list[PoolSummaryRecord] = []
    for artifact, summary in builders:
        _write_pool_artifact(artifact, output_dir)
        summaries.append(summary)
        print(f"✅ Pool written: {output_dir / f'{artifact.pool_name}.json'} ({len(artifact.tickers)} names)")

    summary_frame = pd.DataFrame([record.to_dict() for record in summaries])
    summary_path = output_dir / "pool_summary.csv"
    summary_frame.to_csv(summary_path, index=False, encoding="utf-8-sig")
    print(f"✅ Summary written: {summary_path}")


if __name__ == "__main__":
    main()