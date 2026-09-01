"""CLI for backfilling entity_type on legacy `entities` rows.

Run once per deployment after upgrading to the entity-taxonomy stack ([ARCH]
Generalize the EntityEvent State Space Taxonomy added the additive entity_type
column; legacy rows have NULL). Derives entity_type from each entity's display
evidence using the same logic as live emission. Idempotent — safe to re-run.

Usage:
    ORPHEUS_DATA_ROOT=/data/orpheus python tools/maintenance/backfill_entity_types.py --dry-run
    ORPHEUS_DATA_ROOT=/data/orpheus python tools/maintenance/backfill_entity_types.py
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

from orpheus_common.detection import DetectionDB, backfill_entity_types  # noqa: E402


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

    result = backfill_entity_types(db, batch_size=args.batch_size, dry_run=args.dry_run)
    mode = "DRY-RUN (no writes)" if result["dry_run"] else "LIVE"
    print(
        f"[{mode}] scanned={result['scanned']} updated={result['updated']} "
        f"skipped_unresolved={result['skipped_unresolved']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
