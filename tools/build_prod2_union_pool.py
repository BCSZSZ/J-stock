# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Final


class UnionPoolBuildError(RuntimeError):
    def __init__(self, message: str, details: dict[str, str] | None = None) -> None:
        context = ""
        if details:
            context = " [" + ", ".join(f"{key}={value}" for key, value in sorted(details.items())) + "]"
        super().__init__(f"{message}{context}")


@dataclass(frozen=True)
class ClassificationRecord:
    code: str
    name: str
    security_type: str
    sector: str
    scale_category: str


@dataclass(frozen=True)
class CandidateAggregate:
    code: str
    name: str
    sector: str
    scale_category: str
    appear_count: int
    avg_rank: float
    best_rank: int
    worst_rank: int
    ranks: tuple[int, ...]


@dataclass(frozen=True)
class BuildConfig:
    pool_files: tuple[Path, ...]
    selection_files: tuple[Path, ...]
    classification_csv: Path
    extension_count: int
    output_json: Path
    ranking_csv: Path | None
    pool_name: str | None
    description: str | None
    expected_pool: Path | None
    promote_from_pool: Path | None
    promoted_output_json: Path | None
    promoted_description: str | None


EXPECTED_SELECTION_COLUMNS: Final[tuple[str, str]] = ("Rank", "Code")
EXPECTED_CLASSIFICATION_COLUMNS: Final[tuple[str, str, str, str, str]] = (
    "Code",
    "銘柄名",
    "Type",
    "33業種区分",
    "規模区分",
)


def _parse_args() -> BuildConfig:
    parser = argparse.ArgumentParser(
        description="Build a prod2 union consensus pool from base pools and universe selection CSVs"
    )
    parser.add_argument("--pool-files", nargs="+", required=True, help="Base pool JSON files")
    parser.add_argument(
        "--selection-files",
        nargs="+",
        required=True,
        help="Universe selection CSV files used for consensus aggregation",
    )
    parser.add_argument(
        "--classification-csv",
        default="data/jpx_final_list.csv",
        help="JPX classification CSV used for stock-only filtering and metadata",
    )
    parser.add_argument(
        "--extension-count",
        type=int,
        required=True,
        help="How many out-of-union consensus extensions to add",
    )
    parser.add_argument("--output-json", required=True, help="Destination JSON artifact")
    parser.add_argument("--ranking-csv", help="Optional CSV of all ranked out-of-union candidates")
    parser.add_argument("--pool-name", help="Optional pool name to embed in the artifact")
    parser.add_argument("--description", help="Optional description override for the artifact")
    parser.add_argument(
        "--expected-pool",
        help="Optional existing pool JSON to compare against; exits non-zero on mismatch",
    )
    parser.add_argument(
        "--promote-from-pool",
        help="Optional existing live pool JSON to retain as base before adding new ranked candidates",
    )
    parser.add_argument(
        "--promoted-output-json",
        help="Optional destination JSON for the promoted live pool built from --promote-from-pool",
    )
    parser.add_argument(
        "--promoted-description",
        help="Optional description override for the promoted live pool artifact",
    )
    args = parser.parse_args()

    pool_files = tuple(Path(value) for value in args.pool_files)
    selection_files = tuple(Path(value) for value in args.selection_files)
    if len(pool_files) < 2:
        raise UnionPoolBuildError("At least two pool files are required")
    if len(selection_files) < 1:
        raise UnionPoolBuildError("At least one selection file is required")
    if args.extension_count < 1:
        raise UnionPoolBuildError(
            "Extension count must be positive",
            {"extension_count": str(args.extension_count)},
        )
    if bool(args.promote_from_pool) != bool(args.promoted_output_json):
        raise UnionPoolBuildError(
            "Promotion requires both --promote-from-pool and --promoted-output-json",
        )

    return BuildConfig(
        pool_files=pool_files,
        selection_files=selection_files,
        classification_csv=Path(args.classification_csv),
        extension_count=int(args.extension_count),
        output_json=Path(args.output_json),
        ranking_csv=Path(args.ranking_csv) if args.ranking_csv else None,
        pool_name=str(args.pool_name).strip() if args.pool_name else None,
        description=str(args.description).strip() if args.description else None,
        expected_pool=Path(args.expected_pool) if args.expected_pool else None,
        promote_from_pool=Path(args.promote_from_pool) if args.promote_from_pool else None,
        promoted_output_json=Path(args.promoted_output_json) if args.promoted_output_json else None,
        promoted_description=(
            str(args.promoted_description).strip() if args.promoted_description else None
        ),
    )


def _normalize_code(raw_value: str) -> str:
    code = raw_value.strip().upper()
    if not code:
        return ""
    if code.isdigit():
        return code.zfill(4)
    return code


def _load_json_file(path: Path) -> object:
    if not path.exists():
        raise UnionPoolBuildError("JSON file does not exist", {"path": str(path)})
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_tickers(payload: object, path: Path) -> list[str]:
    raw_items: object
    if isinstance(payload, dict):
        raw_items = payload.get("tickers", [])
    else:
        raw_items = payload

    if not isinstance(raw_items, list):
        raise UnionPoolBuildError(
            "Ticker payload must be a list",
            {"path": str(path), "payload_type": type(raw_items).__name__},
        )

    tickers: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            raw_code = str(item.get("code", ""))
        else:
            raw_code = str(item)
        code = _normalize_code(raw_code)
        if code:
            tickers.append(code)
    return tickers


def _load_pool_codes(path: Path) -> tuple[str, ...]:
    payload = _load_json_file(path)
    tickers = _extract_tickers(payload, path)
    if not tickers:
        raise UnionPoolBuildError("Pool file contains no tickers", {"path": str(path)})
    return tuple(tickers)


def _load_classifications(path: Path) -> dict[str, ClassificationRecord]:
    if not path.exists():
        raise UnionPoolBuildError("Classification CSV does not exist", {"path": str(path)})

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise UnionPoolBuildError("Classification CSV has no header", {"path": str(path)})
        missing = [column for column in EXPECTED_CLASSIFICATION_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise UnionPoolBuildError(
                "Classification CSV missing required columns",
                {"path": str(path), "missing": ",".join(missing)},
            )

        records: dict[str, ClassificationRecord] = {}
        for row in reader:
            code = _normalize_code(row.get("Code", ""))
            if not code:
                continue
            records[code] = ClassificationRecord(
                code=code,
                name=str(row.get("銘柄名", "Unknown")).strip() or f"Stock_{code}",
                security_type=str(row.get("Type", "Unknown")).strip() or "Unknown",
                sector=str(row.get("33業種区分", "-")).strip() or "-",
                scale_category=str(row.get("規模区分", "-")).strip() or "-",
            )

    if not records:
        raise UnionPoolBuildError("Classification CSV produced no records", {"path": str(path)})
    return records


def _load_selection_ranks(path: Path) -> dict[str, int]:
    if not path.exists():
        raise UnionPoolBuildError("Selection CSV does not exist", {"path": str(path)})

    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise UnionPoolBuildError("Selection CSV has no header", {"path": str(path)})
        missing = [column for column in EXPECTED_SELECTION_COLUMNS if column not in reader.fieldnames]
        if missing:
            raise UnionPoolBuildError(
                "Selection CSV missing required columns",
                {"path": str(path), "missing": ",".join(missing)},
            )

        ranked_codes: dict[str, int] = {}
        for row in reader:
            code = _normalize_code(row.get("Code", ""))
            rank_text = str(row.get("Rank", "")).strip()
            if not code or not rank_text:
                continue
            try:
                rank_value = int(rank_text)
            except ValueError as exc:
                raise UnionPoolBuildError(
                    "Selection CSV contains a non-integer rank",
                    {"path": str(path), "code": code, "rank": rank_text},
                ) from exc
            current_rank = ranked_codes.get(code)
            if current_rank is None or rank_value < current_rank:
                ranked_codes[code] = rank_value

    if not ranked_codes:
        raise UnionPoolBuildError("Selection CSV produced no ranked codes", {"path": str(path)})
    return ranked_codes


def _build_union_codes(pool_files: tuple[Path, ...]) -> tuple[str, ...]:
    union_codes: set[str] = set()
    for pool_file in pool_files:
        union_codes.update(_load_pool_codes(pool_file))
    if not union_codes:
        raise UnionPoolBuildError("Union of base pools is empty")
    return tuple(sorted(union_codes))


def _aggregate_candidates(
    selection_files: tuple[Path, ...],
    union_codes: tuple[str, ...],
    classifications: dict[str, ClassificationRecord],
) -> list[CandidateAggregate]:
    union_set = set(union_codes)
    ranks_by_code: dict[str, list[int]] = {}

    for selection_file in selection_files:
        ranked_codes = _load_selection_ranks(selection_file)
        for code, rank_value in ranked_codes.items():
            if code in union_set:
                continue
            classification = classifications.get(code)
            if classification is None:
                continue
            if classification.security_type != "Stock":
                continue
            if code not in ranks_by_code:
                ranks_by_code[code] = []
            ranks_by_code[code].append(rank_value)

    aggregates: list[CandidateAggregate] = []
    for code, rank_values in ranks_by_code.items():
        classification = classifications[code]
        sorted_ranks = tuple(sorted(rank_values))
        avg_rank = round(sum(sorted_ranks) / len(sorted_ranks), 6)
        aggregates.append(
            CandidateAggregate(
                code=code,
                name=classification.name,
                sector=classification.sector,
                scale_category=classification.scale_category,
                appear_count=len(sorted_ranks),
                avg_rank=avg_rank,
                best_rank=min(sorted_ranks),
                worst_rank=max(sorted_ranks),
                ranks=sorted_ranks,
            )
        )

    aggregates.sort(
        key=lambda candidate: (
            -candidate.appear_count,
            candidate.avg_rank,
            candidate.code,
        )
    )
    return aggregates


def _build_artifact_payload(
    config: BuildConfig,
    union_codes: tuple[str, ...],
    extensions: tuple[str, ...],
) -> dict[str, object]:
    selection_names = "/".join(path.name for path in config.selection_files)
    description = config.description or (
        f"Union of the {len(config.pool_files)} prod2 100 pools ({len(union_codes)} names) plus "
        f"{config.extension_count} stock-only cross-model consensus extensions from universe selections."
    )
    payload: dict[str, object] = {
        "version": "1.0",
        "description": description,
        "base_union_size": len(union_codes),
        "extension_count": config.extension_count,
        "extension_method": (
            "top out-of-union stock candidates by appear_count desc, avg_rank asc across "
            f"{selection_names}"
        ),
        "tickers": sorted(set(union_codes) | set(extensions)),
    }
    if config.pool_name:
        payload["pool_name"] = config.pool_name
    return payload


def _write_ranking_csv(
    path: Path,
    ranked_candidates: list[CandidateAggregate],
    selected_codes: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    selected_index = {code: index + 1 for index, code in enumerate(selected_codes)}
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "extension_rank",
                "code",
                "name",
                "sector",
                "scale_category",
                "appear_count",
                "avg_rank",
                "best_rank",
                "worst_rank",
                "ranks",
            ],
        )
        writer.writeheader()
        for candidate in ranked_candidates:
            extension_rank = selected_index.get(candidate.code, "")
            writer.writerow(
                {
                    "extension_rank": extension_rank,
                    "code": candidate.code,
                    "name": candidate.name,
                    "sector": candidate.sector,
                    "scale_category": candidate.scale_category,
                    "appear_count": candidate.appear_count,
                    "avg_rank": f"{candidate.avg_rank:.6f}",
                    "best_rank": candidate.best_rank,
                    "worst_rank": candidate.worst_rank,
                    "ranks": "|".join(str(rank_value) for rank_value in candidate.ranks),
                }
            )


def _validate_expected_pool(expected_pool: Path, built_tickers: list[str]) -> None:
    expected_payload = _load_json_file(expected_pool)
    expected_tickers = _extract_tickers(expected_payload, expected_pool)
    if expected_tickers == built_tickers:
        return

    built_set = set(built_tickers)
    expected_set = set(expected_tickers)
    missing = sorted(expected_set - built_set)
    extra = sorted(built_set - expected_set)
    raise UnionPoolBuildError(
        "Built pool does not match expected pool",
        {
            "expected_pool": str(expected_pool),
            "missing": "|".join(missing[:10]),
            "extra": "|".join(extra[:10]),
            "built_count": str(len(built_tickers)),
            "expected_count": str(len(expected_tickers)),
        },
    )


def _build_promoted_payload(
    config: BuildConfig,
    raw_tickers: list[str],
    ranked_candidates: list[CandidateAggregate],
) -> dict[str, object]:
    if config.promote_from_pool is None:
        raise UnionPoolBuildError("Promotion base pool is missing")

    promoted_base_codes = list(_load_pool_codes(config.promote_from_pool))
    target_total = len(raw_tickers)
    if len(promoted_base_codes) > target_total:
        raise UnionPoolBuildError(
            "Promotion base pool is larger than the raw target pool",
            {
                "base_count": str(len(promoted_base_codes)),
                "target_total": str(target_total),
            },
        )

    promoted_codes = list(promoted_base_codes)
    promoted_set = set(promoted_codes)
    for candidate in ranked_candidates:
        if candidate.code in promoted_set:
            continue
        promoted_codes.append(candidate.code)
        promoted_set.add(candidate.code)
        if len(promoted_codes) >= target_total:
            break

    if len(promoted_codes) != target_total:
        raise UnionPoolBuildError(
            "Unable to extend the live base pool to the target size",
            {
                "base_count": str(len(promoted_base_codes)),
                "target_total": str(target_total),
                "current_total": str(len(promoted_codes)),
            },
        )

    source_pool_name = config.pool_name or config.output_json.stem
    added_count = target_total - len(promoted_base_codes)
    description = config.promoted_description or (
        f"Promoted live pool derived from {source_pool_name} by keeping the current live base "
        f"and adding the next {added_count} ranked out-of-union stock candidates not already present."
    )
    return {
        "version": "1.0",
        "description": description,
        "source_pool": source_pool_name,
        "live_base_pool": str(config.promote_from_pool),
        "added_count": added_count,
        "tickers": sorted(promoted_set),
    }


def main() -> None:
    config = _parse_args()
    classifications = _load_classifications(config.classification_csv)
    union_codes = _build_union_codes(config.pool_files)
    ranked_candidates = _aggregate_candidates(config.selection_files, union_codes, classifications)
    if len(ranked_candidates) < config.extension_count:
        raise UnionPoolBuildError(
            "Not enough out-of-union stock candidates for the requested extension count",
            {
                "requested": str(config.extension_count),
                "available": str(len(ranked_candidates)),
            },
        )

    selected_codes = tuple(candidate.code for candidate in ranked_candidates[: config.extension_count])
    payload = _build_artifact_payload(config, union_codes, selected_codes)
    built_tickers = _extract_tickers(payload, config.output_json)

    if config.expected_pool is not None:
        _validate_expected_pool(config.expected_pool, built_tickers)

    config.output_json.parent.mkdir(parents=True, exist_ok=True)
    with open(config.output_json, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")

    if config.ranking_csv is not None:
        _write_ranking_csv(config.ranking_csv, ranked_candidates, selected_codes)

    if config.promoted_output_json is not None:
        promoted_payload = _build_promoted_payload(config, built_tickers, ranked_candidates)
        promoted_output_path = config.promoted_output_json
        promoted_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(promoted_output_path, "w", encoding="utf-8") as handle:
            json.dump(promoted_payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        promoted_tickers = _extract_tickers(promoted_payload, promoted_output_path)
        print(
            f"✅ Wrote promoted pool: {promoted_output_path} with {len(promoted_tickers)} tickers"
        )

    print(
        f"✅ Wrote {config.output_json} with {len(built_tickers)} tickers "
        f"({len(union_codes)} union + {config.extension_count} extensions)"
    )
    print("Extensions:", ", ".join(selected_codes))
    if config.ranking_csv is not None:
        print(f"✅ Wrote ranking CSV: {config.ranking_csv}")
    if config.expected_pool is not None:
        print(f"✅ Matched expected pool: {config.expected_pool}")


if __name__ == "__main__":
    main()