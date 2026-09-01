"""One-time migration: backfill entity_type on legacy `entities` rows.

[ARCH] Generalize the EntityEvent State Space Taxonomy. Idempotent (only touches
rows where entity_type IS NULL), streamed in batches (mirrors backfill.py so it
won't OOM on a large table), and uses the SAME derive_entity_type as live
emission so backfill and live can never diverge. Rewrites ONLY the additive
entity_type column — species and everything else are untouched. Rows that don't
resolve stay NULL (re-runnable: add a binding to entity_taxonomy.yaml and re-run
to pick them up).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .database import DetectionDB, open_connection
from .entity_taxonomy import derive_entity_type


def _display_evidence(evidence: list) -> Optional[dict]:
    """Highest-confidence evidence with a species_code — the SAME 'display' pick
    the correlator uses to set species_code + derive entity_type live."""
    candidates = [e for e in evidence if isinstance(e, dict) and e.get("species_code")]
    if not candidates:
        return None
    return max(candidates, key=lambda e: e.get("confidence") or 0.0)


def _entity_type_for_row(evidence_json: Optional[str]) -> Optional[str]:
    try:
        evidence = json.loads(evidence_json) if evidence_json else []
    except (TypeError, ValueError):
        return None
    display = _display_evidence(evidence)
    if display is None:
        return None
    return derive_entity_type(
        taxonomy=display.get("taxonomy"),  # a dict in persisted JSON; derive handles it
        species_code=display.get("species_code") or "",
        common_name=display.get("species_common") or "",
        detection_type=display.get("detection_type") or "",
    )


def backfill_entity_types(
    db: DetectionDB, batch_size: int = 1000, dry_run: bool = False
) -> dict[str, Any]:
    """Populate entity_type on `entities` rows where it is NULL.

    Returns ``{scanned, updated, skipped_unresolved, dry_run}``.
    """
    conn = open_connection(db.db_path)
    # Longer busy_timeout to ride out contention with the live correlator.
    conn.execute("PRAGMA busy_timeout = 30000")
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(entities)")
        cols = {row[1] for row in cur.fetchall()}
        if "entity_type" not in cols:
            # No entities table / column yet (e.g. detections-only DB) — nothing to do.
            return {"scanned": 0, "updated": 0, "skipped_unresolved": 0, "dry_run": dry_run}

        # Page through WHERE entity_type IS NULL in rowid order — dry-run
        # included (a fetchall of every NULL row's evidence JSON is exactly the
        # all-in-memory pattern this module's batching exists to avoid).
        # Unresolved rows stay NULL, so we advance an offset past them to avoid
        # re-fetching them forever; updated rows leave the IS-NULL set naturally.
        # In a dry run NOTHING leaves the set, so the offset advances past the
        # whole batch instead.
        scanned = 0
        updated = 0
        unresolved = 0
        offset = 0
        while True:
            cur.execute(
                "SELECT entity_id, evidence FROM entities "
                "WHERE entity_type IS NULL ORDER BY rowid LIMIT ? OFFSET ?",
                (batch_size, offset),
            )
            batch = cur.fetchall()
            if not batch:
                break
            pending: list[tuple[str, str]] = []
            batch_unresolved = 0
            for entity_id, evidence_json in batch:
                scanned += 1
                entity_type = _entity_type_for_row(evidence_json)
                if entity_type is None:
                    unresolved += 1
                    batch_unresolved += 1
                    continue
                pending.append((entity_type, entity_id))
            if dry_run:
                offset += len(batch)  # no writes: every scanned row stays NULL
                updated += len(pending)  # rows that WOULD update
                continue
            offset += batch_unresolved
            if pending:
                cur.executemany(
                    "UPDATE entities SET entity_type = ? WHERE entity_id = ?", pending
                )
                conn.commit()
                updated += len(pending)
        return {
            "scanned": scanned,
            "updated": updated,
            "skipped_unresolved": unresolved,
            "dry_run": dry_run,
        }
    finally:
        conn.close()
