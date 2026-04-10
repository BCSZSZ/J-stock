from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.strategy_hall_of_fame import (
    HallOfFameReferenceInput,
    build_reference_record,
    load_hall_of_fame_document,
    upsert_reference_record,
    write_hall_of_fame_document,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upsert a reference strategy into docs/strategy_hall_of_fame.json"
    )
    parser.add_argument("--results-dir", required=True)
    parser.add_argument("--reference-id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--entry-strategy", required=True)
    parser.add_argument("--exit-strategy", required=True)
    parser.add_argument(
        "--hall-file",
        default=str(REPO_ROOT / "docs" / "strategy_hall_of_fame.json"),
    )
    parser.add_argument("--entry-filter", default="off")
    parser.add_argument("--position-profile")
    parser.add_argument("--overlay-mode")
    parser.add_argument("--universe-name")
    parser.add_argument("--updated-at", default=date.today().isoformat())
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--note", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reference_input = HallOfFameReferenceInput(
        reference_id=args.reference_id,
        display_name=args.display_name,
        results_dir=Path(args.results_dir),
        entry_strategy=args.entry_strategy,
        exit_strategy=args.exit_strategy,
        tags=tuple(args.tag),
        entry_filter=args.entry_filter,
        position_profile=args.position_profile,
        overlay_mode=args.overlay_mode,
        universe_name=args.universe_name,
        selection_notes=tuple(args.note),
    )
    hall_file = Path(args.hall_file)
    document = load_hall_of_fame_document(hall_file)
    record = build_reference_record(reference_input)
    updated_document = upsert_reference_record(
        document,
        record,
        updated_at=args.updated_at,
    )
    write_hall_of_fame_document(hall_file, updated_document)
    print(f"Updated hall-of-fame: {hall_file}")
    print(f"  reference_id: {record['reference_id']}")
    print(f"  display_name: {record['display_name']}")
    print(f"  ranking_position: {record['selection']['ranking_position']}")
    print(f"  continuous_return_pct: {record['comparison_summary']['continuous_return_pct']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())