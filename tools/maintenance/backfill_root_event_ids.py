"""CLI for backfilling root_event_id on legacy detection rows.

Run once per deployment after upgrading to the cross-classifier-identity
stack (Layer 1.5 added the column; legacy rows have NULL). The backfill
walks the source_event_id chain and writes the audio.motion root back
to each row.

Usage:
    ORPHEUS_DATA_ROOT=/data/orpheus python -m orpheus_common.detection.backfill --dry-run
    ORPHEUS_DATA_ROOT=/data/orpheus python -m orpheus_common.detection.backfill

Or directly:
    python tools/maintenance/backfill_root_event_ids.py --dry-run
"""

import argparse
import os
import sys
from pathlib import Path

# Allow running this script from a checkout without installing first.
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "platform" / "orpheus-common" / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from orpheus_common.detection import DetectionDB, backfill_root_event_ids  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan and report what would be updated, but don't write.",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Path to the SQLite DB (default: ORPHEUS_DATA_ROOT/detections/orpheus.db).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Commit batch size (default 1000).",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else None
    if db_path:
        db = DetectionDB(db_path=db_path)
    else:
        if "ORPHEUS_DATA_ROOT" not in os.environ:
            print(
                "WARN: ORPHEUS_DATA_ROOT not set; using default /data/orpheus.",
                file=sys.stderr,
            )
        db = DetectionDB()

    print(f"Backfilling {db.db_path}")
    stats = backfill_root_event_ids(
        db, batch_size=args.batch_size, dry_run=args.dry_run
    )
    print(f"  Scanned:               {stats['scanned']}")
    print(f"  Updated:               {stats['updated']}")
    print(f"  Skipped (chain broken):{stats['skipped_chain_broken']}")
    if args.dry_run:
        print("\nDRY RUN — no changes written.")
    else:
        print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
