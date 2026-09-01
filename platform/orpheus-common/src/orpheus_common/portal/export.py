"""Public data export — the static, data-only artifact the public site serves.

See docs/designs/read-only-portal.md §Epic 7. ``export_public_site`` reads entities
through the ``ReadModel`` chokepoint and writes ``entities.json``
(``PublicEntityRecord[]`` — already coarsened + allow-listed) under
``<data_root>/public_site/``. It is the SOLE writer of that dir and FULL-REPLACEs
it each run, so a later ``suppress_species`` is retroactive on the next regenerate.

Safety: every record is produced by ``PublicProjection``, which structurally cannot
emit clips/coords/exact-time/etc. The artifact-scanning test
(``test_portal_export``) greps the emitted file for ``SENSITIVE_FIELDS`` keys +
planted sentinels — so a leak fails CI before any public byte ships.

The ``orpheus-public-export`` CLI runs OFF-Jetson on the portal/mirror host, reads
the read-only replica, and is gated by ``public.enabled`` (off by default).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from orpheus_common.logging import get_logger

from .coarsen import coarsen_time
from .read_model import ReadModel

if TYPE_CHECKING:
    from orpheus_common.config import PublicProjectionConfig
    from orpheus_common.detection import DetectionDB

logger = get_logger(__name__)

# Deliberate row cap for the full-replace export. Without an explicit limit,
# ``get_entities`` silently defaults to its UI-page size (500) and the "full"
# public dataset quietly plateaus at the 500 newest entities. 100k covers years
# of entities at observed rates; ``ReadModel`` logs loudly if it is ever hit.
EXPORT_ENTITY_LIMIT = 100_000


def export_public_site(
    db: DetectionDB, config: PublicProjectionConfig, out_dir: Path, **filters: object
) -> Path:
    """Write the data-only public export to ``out_dir/entities.json`` and return it.

    Every entity passes through the ``PublicProjection`` chokepoint. Staged to a
    temp + atomically renamed (a reader never sees a partial file). Full-replace.
    Reads up to ``EXPORT_ENTITY_LIMIT`` entities unless ``limit`` is passed."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    limit = int(filters.pop("limit", EXPORT_ENTITY_LIMIT))  # type: ignore[call-overload]
    records = [
        r.model_dump()
        for r in ReadModel(db, config).public_entities(limit=limit, **filters)
    ]
    # Provenance envelope so a citizen-science consumer can judge staleness (the replica
    # is minutes-stale) + dataset scope. generated_at goes through coarsen_time at the
    # configured granularity — NEVER second-precision, so it can't become a fingerprint
    # (same guarantee the per-entity times get; the leak scan is per-record but we keep
    # the envelope honest to that rule too).
    payload = {
        "generated_at": coarsen_time(datetime.now(timezone.utc), config.time_granularity),
        "count": len(records),
        "site_label": config.site_label,
        "entities": records,
    }
    target = out_dir / "entities.json"
    tmp = target.with_name(".entities.json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
    os.replace(tmp, target)
    logger.info("Wrote public export", path=str(target), entities=len(records))
    return target


def main(argv: Optional[list[str]] = None) -> int:
    import argparse  # lazy

    parser = argparse.ArgumentParser(
        prog="orpheus-public-export",
        description="Export the data-only public site from the read-only replica.",
    )
    parser.add_argument(
        "--out", help="Output dir (default: <data_root>/public_site)."
    )
    parser.add_argument(
        "--db", help="Replica DB path (default: mirror.staging_path)."
    )
    args = parser.parse_args(argv)

    from orpheus_common.config import OrpheusConfig  # lazy
    from orpheus_common.detection import DetectionDB  # lazy
    from orpheus_common.storage import get_data_root  # lazy

    cfg = OrpheusConfig.get_instance()
    pub = getattr(cfg, "public", None)
    if pub is None or not pub.enabled:
        logger.warning(
            "public.enabled is false — refusing to export (set public.enabled + "
            "site_label after reviewing the allow-list)."
        )
        return 0

    # Fail closed on the DB path: this CLI runs on the portal/mirror host, where
    # silently falling back to the Jetson's live-DB path would either create a
    # fresh empty DB (empty export, no error) or read the live DB the portal
    # must never touch. The replica location must be stated, not guessed.
    replica = args.db or getattr(cfg.mirror, "staging_path", "")
    if not replica:
        logger.error(
            "No replica DB configured — set mirror.staging_path to the replica "
            "path on this host, or pass --db. Refusing to fall back to the "
            "live-DB path."
        )
        return 2

    db = DetectionDB(db_path=Path(replica), read_only=True)
    out_dir = Path(args.out) if args.out else get_data_root() / "public_site"
    export_public_site(db, pub, out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
