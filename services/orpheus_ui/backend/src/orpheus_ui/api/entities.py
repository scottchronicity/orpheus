"""Entity event API endpoints.

Provides endpoints for viewing correlated animal entity events
persisted to SQLite by the event correlator agent.

The ``on_entity_event_message`` MQTT callback is retained so that the
Entities page can still display real-time events before they are flushed
to disk by the correlator.  The primary ``GET /api/entities`` endpoint
reads from the database and supports filtering by species and date range.
"""

import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from orpheus_common.detection import DetectionDB
from orpheus_common.logging import get_logger
from orpheus_common.utils.time import is_full_day, parse_hhmm, timestamp_in_window

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["entities"])

# Lazily-initialized DB instance (created on first request)
_db: Optional[DetectionDB] = None


def _get_db() -> DetectionDB:
    """Return the shared DetectionDB instance, creating it on first access."""
    global _db
    if _db is None:
        _db = DetectionDB()
    return _db


def _compute_entity_stats(
    db: DetectionDB,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    species: Optional[str] = None,
    exclude_species: Optional[str] = None,
    start_hhmm: Optional[tuple] = None,
    end_hhmm: Optional[tuple] = None,
    tz: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute aggregated chart stats for all entities in the date range (no limit).

    Also returns an evenly-distributed scatter_sample (up to 500 points) spanning
    the full date range so charts are not biased by the per-request row cap.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(str(db.db_path))
    conn.row_factory = _sqlite3.Row
    try:
        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params: list = []
        if start_time:
            ts = start_time.replace(microsecond=0)
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            where_clauses.append("timestamp >= ?")
            params.append(ts.isoformat())
        if end_time:
            ts = end_time.replace(microsecond=999999)
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            where_clauses.append("timestamp <= ?")
            params.append(ts.isoformat())
        if species:
            species_list = [s.strip() for s in species.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in species_list)
            where_clauses.append(f"species IN ({placeholders})")
            params.extend(species_list)
        if exclude_species:
            exclude_list = [s.strip() for s in exclude_species.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in exclude_list)
            where_clauses.append(f"species NOT IN ({placeholders})")
            params.extend(exclude_list)
        where = " AND ".join(where_clauses)

        cursor.execute(f"SELECT COUNT(*) as total FROM entities WHERE {where}", params)
        row = cursor.fetchone()
        total = row["total"] if row else 0

        cursor.execute(
            f"SELECT CAST(strftime('%H', timestamp) AS INTEGER) as hour, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY hour ORDER BY hour",
            params,
        )
        hourly = {r["hour"]: r["count"] for r in cursor.fetchall()}
        hourly_activity = [{"hour": h, "count": hourly.get(h, 0)} for h in range(24)]

        cursor.execute(
            f"SELECT COALESCE(NULLIF(common_name,''), species) as name, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY species ORDER BY count DESC",
            params,
        )
        species_dist = {}
        unique_species = set()
        for r in cursor.fetchall():
            species_dist[r["name"]] = r["count"]
            unique_species.add(r["name"])

        cursor.execute(
            f"SELECT strftime('%Y-%m-%d', timestamp) as day, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY day ORDER BY day",
            params,
        )
        daily_activity = [{"date": r["day"], "count": r["count"]} for r in cursor.fetchall()]

        # Evenly-distributed scatter sample spanning the full date range.
        # Fetched here (no row limit) so it is not biased by the per-request cap
        # applied to the entity list returned to the table.
        cursor.execute(
            "SELECT timestamp, species, "
            "COALESCE(NULLIF(common_name,''), species) as name, confidence "
            f"FROM entities WHERE {where} ORDER BY timestamp",
            params,
        )
        all_scatter_rows = cursor.fetchall()

        # If a time-of-day window is active, filter the rows and recompute
        # all aggregates in Python. The SQL GROUP BY above has already run
        # but its results are replaced for consistency with the filtered view.
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )
        if apply_time_window:
            filtered_rows = []
            hourly_counts: Dict[int, int] = defaultdict(int)
            daily_counts: Dict[str, int] = defaultdict(int)
            species_counts: Dict[str, int] = defaultdict(int)
            for r in all_scatter_rows:
                ts_str = r["timestamp"]
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if not timestamp_in_window(ts, start_hhmm, end_hhmm, tz):
                    continue
                filtered_rows.append(r)
                # For hourly activity we use the timestamp's own hour field
                # (same semantics as the legacy SQL GROUP BY, which used UTC).
                hourly_counts[ts.hour] += 1
                daily_counts[ts.date().isoformat()] += 1
                species_counts[r["name"]] += 1
            total = len(filtered_rows)
            hourly_activity = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]
            daily_activity = [
                {"date": d, "count": daily_counts[d]} for d in sorted(daily_counts.keys())
            ]
            species_dist = dict(species_counts)
            unique_species = set(species_counts.keys())
            all_scatter_rows = filtered_rows

        n_scatter = len(all_scatter_rows)
        if n_scatter <= 500:
            scatter_sample = [
                {
                    "timestamp": r["timestamp"],
                    "species_code": r["species"],
                    "common_name": r["name"],
                    "confidence": r["confidence"],
                }
                for r in all_scatter_rows
            ]
        else:
            step = n_scatter / 500
            scatter_sample = [
                {
                    "timestamp": all_scatter_rows[int(i * step)]["timestamp"],
                    "species_code": all_scatter_rows[int(i * step)]["species"],
                    "common_name": all_scatter_rows[int(i * step)]["name"],
                    "confidence": all_scatter_rows[int(i * step)]["confidence"],
                }
                for i in range(500)
            ]

        return {
            "total_count": total,
            "unique_species_count": len(unique_species),
            "hourly_activity": hourly_activity,
            "daily_activity": daily_activity,
            "species_distribution": species_dist,
            "scatter_sample": scatter_sample,
        }
    finally:
        conn.close()


def _empty_stats() -> Dict[str, Any]:
    """Return a zeroed stats object used when aggregation cannot run."""
    return {
        "total_count": 0,
        "unique_species_count": 0,
        "hourly_activity": [{"hour": h, "count": 0} for h in range(24)],
        "daily_activity": [],
        "species_distribution": {},
        "scatter_sample": [],
    }


def _compute_all_species_in_range(
    db: DetectionDB,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> Dict[str, int]:
    """Return species_name -> count for the date range, ignoring filters.

    Used to populate the species-filter dropdown so the full list of species
    available in the range stays visible even after the user narrows the
    selection.
    """
    import sqlite3 as _sqlite3

    conn = _sqlite3.connect(str(db.db_path))
    conn.row_factory = _sqlite3.Row
    try:
        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params: list = []
        if start_time:
            ts = start_time.replace(microsecond=0)
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            where_clauses.append("timestamp >= ?")
            params.append(ts.isoformat())
        if end_time:
            ts = end_time.replace(microsecond=999999)
            if ts.tzinfo is None:
                from datetime import timezone

                ts = ts.replace(tzinfo=timezone.utc)
            where_clauses.append("timestamp <= ?")
            params.append(ts.isoformat())
        where = " AND ".join(where_clauses)
        cursor.execute(
            f"SELECT COALESCE(NULLIF(common_name,''), species) as name, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY species ORDER BY count DESC",
            params,
        )
        return {r["name"]: r["count"] for r in cursor.fetchall()}
    finally:
        conn.close()


def on_entity_event_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle entity event messages from MQTT (orpheus/entities/animal).

    Kept for backward-compatibility: the existing Entities page may still
    display real-time events received via MQTT.  These are now also
    persisted to SQLite by the correlator agent itself.
    """
    # No-op: entities are persisted by the correlator agent directly.
    pass


@router.get("/entities")
def get_entities(
    species: Optional[str] = Query(
        None, description="Filter by species code(s), comma-separated (e.g. 'corvus,crow')"
    ),
    exclude_species: Optional[str] = Query(
        None, description="Exclude species code(s), comma-separated (e.g. 'corvus,crow')"
    ),
    start_date: Optional[str] = Query(None, description="Start date (ISO 8601)"),
    end_date: Optional[str] = Query(None, description="End date (ISO 8601)"),
    start_time: Optional[str] = Query(
        None, description="Time-of-day start, HH:MM in the tz given by `tz`."
    ),
    end_time: Optional[str] = Query(
        None, description="Time-of-day end, HH:MM. If start > end the window wraps midnight."
    ),
    tz: Optional[str] = Query(
        None, description="IANA timezone for interpreting start_time/end_time."
    ),
    limit: int = Query(2000, description="Maximum results"),
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Get entity events from the database.

    Supports filtering by species, exclude_species, date range, and an optional
    time-of-day window.
    """
    try:
        db = _get_db()

        start_dt: Optional[datetime] = None
        end_dt: Optional[datetime] = None

        if start_date:
            try:
                start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
                if start_dt.tzinfo is None:
                    start_dt = start_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid start_date format")
        if end_date:
            try:
                end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
                if end_dt.tzinfo is None:
                    end_dt = end_dt.replace(tzinfo=timezone.utc)
                # Set to end of day (23:59:59.999999) to include all events on end_date
                end_dt = end_dt.replace(hour=23, minute=59, second=59, microsecond=999999)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid end_date format")

        start_hhmm = parse_hhmm(start_time)
        end_hhmm = parse_hhmm(end_time)
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )

        entities = db.get_entities(
            species=species,
            exclude_species=exclude_species,
            start_time=start_dt,
            end_time=end_dt,
            limit=limit,
        )

        # Collect all unique event_ids from evidence to look up detection metadata
        event_ids = set()
        for ent in entities:
            for ev in ent.evidence:
                event_ids.add(ev.event_id)

        # Fetch detection metadata for all evidence in a single query
        detection_metadata = _fetch_detection_metadata(db, list(event_ids))

        # Serialize to dicts for JSON response using the wire-format
        # keys expected by the frontend (species_code, common_name).
        # Enrich each entity with aggregated metadata from its evidence.
        entity_dicts: List[Dict[str, Any]] = []
        for ent in entities:
            if apply_time_window:
                ts = ent.timestamp if isinstance(ent.timestamp, datetime) else None
                if ts is None:
                    try:
                        ts = datetime.fromisoformat(str(ent.timestamp).replace("Z", "+00:00"))
                    except Exception:
                        ts = None
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if not timestamp_in_window(ts, start_hhmm, end_hhmm, tz):
                    continue

            # Aggregate metadata from all evidence detections
            metadata_agg = _aggregate_evidence_metadata(ent, detection_metadata)

            entity_dicts.append(
                {
                    "entity_id": ent.entity_id,
                    "timestamp": ent.timestamp.isoformat()
                    if isinstance(ent.timestamp, datetime)
                    else ent.timestamp,
                    "species_code": ent.species,
                    "common_name": ent.common_name,
                    "confidence": ent.confidence,
                    "evidence": [e.model_dump(mode="json") for e in ent.evidence],
                    "context": ent.context,
                    "metadata_aggregate": metadata_agg,
                }
            )

        # Compute aggregated stats for charts (runs over full date range, no row limit).
        # Pass species + time filters so stats and scatter_sample match the filtered view.
        try:
            stats = _compute_entity_stats(
                db,
                start_dt,
                end_dt,
                species=species,
                exclude_species=exclude_species,
                start_hhmm=start_hhmm if apply_time_window else None,
                end_hhmm=end_hhmm if apply_time_window else None,
                tz=tz if apply_time_window else None,
            )
        except Exception as stats_err:
            logger.warning("Failed to compute entity stats", error=str(stats_err))
            stats = _empty_stats()

        # Always include the unfiltered species distribution so the frontend
        # dropdown stays fully populated even after the user narrows the selection.
        try:
            stats["all_species"] = _compute_all_species_in_range(db, start_dt, end_dt)
        except Exception as all_species_err:
            logger.warning("Failed to compute all_species", error=str(all_species_err))
            stats.setdefault("all_species", {})

        # scatter_sample comes from _compute_entity_stats which queries the full
        # date range without the per-request row cap, so it spans all dates.
        scatter_sample = stats.get("scatter_sample", [])

        return {
            "entities": entity_dicts,
            "count": len(entity_dicts),
            "scatter_sample": scatter_sample,
            "stats": stats,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get entities", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get entities: {e}")


def _fetch_detection_metadata(db: DetectionDB, event_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch detection metadata for a list of event IDs.

    Args:
        db: DetectionDB instance
        event_ids: List of detection event IDs

    Returns:
        Dictionary mapping event_id to detection metadata dict
    """
    if not event_ids:
        return {}

    # Use raw SQL to efficiently fetch detections by event_id IN (...)
    conn = sqlite3.connect(str(db.db_path))
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(event_ids))
        query = f"SELECT event_id, metadata FROM detections WHERE event_id IN ({placeholders})"
        cursor = conn.cursor()
        cursor.execute(query, event_ids)
        rows = cursor.fetchall()

        result = {}
        for row in rows:
            import json

            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            result[row["event_id"]] = metadata
        return result
    finally:
        conn.close()


def _aggregate_evidence_metadata(
    entity: Any, detection_metadata: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Aggregate metadata from all evidence detections for an entity.

    Extracts call_type, age, and other attributes from each detection
    and computes averages/distributions for the entity.

    Args:
        entity: Entity object with evidence list
        detection_metadata: Mapping of event_id -> detection metadata

    Returns:
        Aggregated metadata dict with call_types, ages, etc.
    """
    call_types: List[str] = []
    ages: List[str] = []
    behaviors: Dict[str, List[float]] = defaultdict(list)

    for ev in entity.evidence:
        meta = detection_metadata.get(ev.event_id, {})

        # Extract call_type
        call_type = meta.get("call_type")
        if call_type:
            call_types.append(call_type)

        # Extract age from attributes
        attributes = meta.get("attributes", {})
        if isinstance(attributes, dict):
            age = attributes.get("age")
            if age:
                ages.append(age)

            # Collect behavior probabilities for averaging
            for behavior_key in ["alert", "begging", "soft_song", "rattle", "mob"]:
                value = attributes.get(behavior_key)
                if isinstance(value, (int, float)):
                    behaviors[behavior_key].append(float(value))

    # Compute average behaviors
    avg_behaviors = {}
    for behavior, values in behaviors.items():
        if values:
            avg_behaviors[behavior] = sum(values) / len(values)

    return {
        "call_types": call_types,  # List of all call types from evidence
        "ages": ages,  # List of all ages from evidence
        "avg_behaviors": avg_behaviors,  # Average behavior probabilities
        "evidence_count": len(entity.evidence),
    }


@router.get("/entities/{entity_id}")
def get_entity_by_id(
    entity_id: str,
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Get a specific entity event by its ID."""
    try:
        db = _get_db()
        # Query all entities with no filters and look for the matching ID
        # (a dedicated get_entity_by_id on the DB would be more efficient
        # but this keeps changes minimal).
        entities = db.get_entities(limit=5000)
        for ent in entities:
            if ent.entity_id == entity_id:
                # Fetch metadata for this entity's evidence
                event_ids = [ev.event_id for ev in ent.evidence]
                detection_metadata = _fetch_detection_metadata(db, event_ids)
                metadata_agg = _aggregate_evidence_metadata(ent, detection_metadata)

                return {
                    "entity_id": ent.entity_id,
                    "timestamp": ent.timestamp.isoformat()
                    if isinstance(ent.timestamp, datetime)
                    else ent.timestamp,
                    "species_code": ent.species,
                    "common_name": ent.common_name,
                    "confidence": ent.confidence,
                    "evidence": [e.model_dump(mode="json") for e in ent.evidence],
                    "context": ent.context,
                    "metadata_aggregate": metadata_agg,
                }
        raise HTTPException(status_code=404, detail="Entity not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get entity", entity_id=entity_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get entity: {e}")
