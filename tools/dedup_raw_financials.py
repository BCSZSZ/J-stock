from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def pick_dedup_subset(df: pd.DataFrame) -> list[str] | None:
    candidates = [
        ["DiscNo"],
        ["DisclosedUnixTime"],
        ["DisclosedDate", "TypeOfDocument", "CurrentPeriodEndDate"],
        ["DiscDate", "DocType", "CurPerType", "CurPerEn"],
        ["DiscDate", "DocType", "CurPerType"],
        ["DiscDate", "Quarter"],
        ["DiscDate"],
    ]
    for cols in candidates:
        if all(col in df.columns for col in cols):
            return cols
    return None


def dedup_file(parquet_path: Path, dry_run: bool = False) -> tuple[int, int, str]:
    df = pd.read_parquet(parquet_path)
    before = len(df)

    subset = pick_dedup_subset(df)
    if subset:
        deduped = df.drop_duplicates(subset=subset, keep="last")
        dedup_key = "+".join(subset)
    else:
        deduped = df.drop_duplicates(keep="last")
        dedup_key = "all-columns"

    if "DiscDate" in deduped.columns:
        deduped = deduped.sort_values("DiscDate").reset_index(drop=True)

    after = len(deduped)

    if not dry_run and after < before:
        deduped.to_parquet(parquet_path, index=False)

    return before, after, dedup_key


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deduplicate data/raw_financials parquet files"
    )
    parser.add_argument(
        "--data-root", default="data", help="Data root containing raw_financials"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Analyze only, do not modify files"
    )
    args = parser.parse_args()

    raw_financials_dir = Path(args.data_root) / "raw_financials"
    files = sorted(raw_financials_dir.glob("*_financials.parquet"))

    if not files:
        print(f"No financial parquet files found in: {raw_financials_dir}")
        return

    total_before = 0
    total_after = 0
    changed_files = 0

    print(f"Scanning {len(files)} files in {raw_financials_dir} ...")

    for file_path in files:
        before, after, dedup_key = dedup_file(file_path, dry_run=args.dry_run)
        removed = before - after
        total_before += before
        total_after += after

        code = file_path.name.replace("_financials.parquet", "")
        if removed > 0:
            changed_files += 1
            print(
                f"[{code}] {before} -> {after} (removed {removed}, key={dedup_key})"
            )

    print("\nSummary")
    print(f"- files_scanned: {len(files)}")
    print(f"- files_changed: {changed_files}")
    print(f"- rows_before: {total_before}")
    print(f"- rows_after: {total_after}")
    print(f"- rows_removed: {total_before - total_after}")
    print(f"- dry_run: {args.dry_run}")


if __name__ == "__main__":
    main()
