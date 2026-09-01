"""Entity event API endpoints.

Provides endpoints for viewing correlated animal entity events
persisted to SQLite by the event correlator agent.

The ``on_entity_event_message`` MQTT callback is retained so that the
Entities page can still display real-time events before they are flushed
to disk by the correlator.  The primary ``GET /api/entities`` endpoint
reads from the database and supports filtering by species and date range.
"""

import json
import os
import sqlite3
import threading
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from orpheus_common.actor import HEALTH_STALE_AFTER_SECONDS
from orpheus_common.detection import (
    DetectionDB,
    TaxonomyEquivalenceDB,
    TaxonomyRef,
    diagnose_equivalences,
    discover_equivalences,
    expand_species_filter,
    iso_lower_bound,
    iso_upper_bound,
    open_connection,
)
from orpheus_common.logging import get_logger
from orpheus_common.storage import get_audio_clip_path
from orpheus_common.utils.time import is_full_day, parse_hhmm, timestamp_in_window

from orpheus_ui.api._date_range import resolve_date_range
from orpheus_ui.api._responses import even_sample, paginate, set_cache_control
from orpheus_ui.auth.backend import current_active_user, require_role
from orpheus_ui.auth.models import User
from orpheus_ui.db import get_detection_db

logger = get_logger(__name__)


def _evidence_clip_available(sensor_id: str, clip_path: Optional[str]) -> bool:
    """Does the audio clip backing this evidence still exist on disk?

    The Entity/Detection tables outlive the on-disk audio clips: clips roll
    off after the storage-retention size cap while the DB rows persist
    forever. When the file is gone, Play/Download 404s and the UI shows only
    a console error. Precompute availability so the frontend can render a
    "Clip expired" state without firing a doomed request — this mirrors how
    ``GET /api/audio/clips/{channel}/{filename}`` resolves the path (see
    ``api/diagnostics.get_audio_clip``), so the flag matches what a real
    fetch would do.

    Fails OPEN: any resolution error returns True so we never wrongly hide a
    playable clip. The frontend's HEAD-probe-on-error fallback still catches
    a genuine 404.
    """
    if not clip_path:
        # No clip recorded → ClipActions renders "No clip", not "expired".
        return True
    try:
        filename = os.path.basename(clip_path)
        # Mirror the frontend EXACTLY: ClipActions.getClipUrl falls back to
        # channel "1" for a blank channelId (`channelId || '1'`), so a piece
        # of evidence with an empty sensor_id (the model default when a
        # Detection had no context) is actually fetched from channel 1. Using
        # the same fallback here keeps the flag and the real request on the
        # same path — otherwise sensor_id="" collapses to a channel-less path
        # that never exists and we'd wrongly hide a playable clip.
        resolved = get_audio_clip_path(
            category="audio_motion", sensor_id=sensor_id or "1", filename=filename
        )
        return resolved.exists()
    except Exception:  # noqa: BLE001 - never block playback on a path error
        return True


def _serialize_evidence(
    evidence: list, *, with_availability: bool = True
) -> List[Dict[str, Any]]:
    """``model_dump`` each evidence row, optionally annotating ``clip_available``.

    ``clip_available`` is COMPUTED at serialization time, not stored — so it
    adds no DB column and is fully reversible. It costs one ``os.path.exists``
    per evidence row, so we only compute it when the result is actually
    consumed: the bounded paths (a single entity, or a paginated page) that
    feed the evidence drawer. ``with_availability=False`` skips it for the
    legacy non-paginated species path (e.g. CrowEntitySection's 30s poll),
    which serialises the entire filtered set and never renders ClipActions —
    paying a stat per row there would add unbounded syscalls to a hot,
    DB-contended endpoint for a field nobody reads.
    """
    out: List[Dict[str, Any]] = []
    for e in evidence:
        d = e.model_dump(mode="json")
        if with_availability:
            d["clip_available"] = _evidence_clip_available(
                d.get("sensor_id", ""), d.get("clip_path")
            )
        out.append(d)
    return out

router = APIRouter(prefix="/api", tags=["entities"])


def _entity_matches_species_filter(
    ent_species: str,
    ent_evidence: list,
    legacy_terms: set[str],
    taxa_pairs: set[tuple[str, str]],
    ent_common_name: Optional[str] = None,
) -> bool:
    """In-Python predicate: does this entity match the expanded filter?

    Used after the DB-level coarse query (Entity.species IN (...)) to
    also accept entities whose ONLY match is in evidence — needed because
    Layer 2's clustering means Entity.species may be from a different
    classifier than what the user is searching for.

    The ``species`` filter dropdown is populated from
    ``_compute_all_species_in_range``, which uses
    ``COALESCE(NULLIF(common_name,''), species)`` — so the dropdown
    values can be EITHER common names (``"American Robin"``) or slugs
    (``"amerob"``). The filter must accept whichever the user picked,
    matching against the Entity's ``species`` (slug column),
    ``common_name``, AND each evidence row's species_code/species_common.
    Legacy entities (pre-Layer 2) have evidence rows without
    per-evidence species_common; the ``ent_common_name`` fallback is
    how those still match.
    """
    if not legacy_terms and not taxa_pairs:
        return True  # no filter = match all
    legacy_lc = {t.lower() for t in legacy_terms}
    if ent_species and ent_species.lower() in legacy_lc:
        return True
    if ent_common_name and ent_common_name.lower() in legacy_lc:
        return True
    for ev in ent_evidence:
        if hasattr(ev, "model_dump"):
            d = ev.model_dump(mode="json")
        else:
            d = dict(ev)
        if (d.get("species_code") or "").lower() in legacy_lc:
            return True
        if (d.get("species_common") or "").lower() in legacy_lc:
            return True
        tax = d.get("taxonomy")
        if tax and (tax.get("namespace"), tax.get("id")) in taxa_pairs:
            return True
    return False


def _get_db() -> DetectionDB:
    """Return the shared process-wide DetectionDB instance.

    Delegates to ``orpheus_ui.db.get_detection_db`` so this module and
    ``api/diagnostics`` share a single cached instance (one schema migration per
    process, not per request). Kept as a thin shim because the endpoints here —
    and the test suite — reference ``_get_db`` directly.
    """
    return get_detection_db()


# One warning per process for the read-path equivalence-store degrade — the
# species-filter expansion runs on every filtered /entities poll, so a dead
# store must not turn the log into a firehose.
_EQ_STORE_WARNED = False


def _equivalence_db_or_none() -> Optional[TaxonomyEquivalenceDB]:
    """Open the taxonomy-equivalence store for read-path filter expansion,
    degrading to ``None`` when it can't be opened (e.g. an unwritable data root
    — the constructor mkdirs + writes schema). ``expand_species_filter`` treats
    ``None`` as "no graph": the filter still applies, just unexpanded. GET
    endpoints must degrade this way rather than 500 (real incident: a
    read-only data root blanked the Birds page); writes still fail loud.
    Warns once per process so the degrade is visible without flooding."""
    global _EQ_STORE_WARNED
    try:
        return TaxonomyEquivalenceDB()
    except Exception as e:  # noqa: BLE001 - any open failure -> unexpanded filter
        if not _EQ_STORE_WARNED:
            logger.warning(
                "Taxonomy equivalence store unavailable; species filters will "
                "not be equivalence-expanded",
                error=str(e),
            )
            _EQ_STORE_WARNED = True
        return None


def _compute_entity_stats(
    db: DetectionDB,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    species: Optional[str] = None,
    exclude_species: Optional[str] = None,
    start_hhmm: Optional[tuple] = None,
    end_hhmm: Optional[tuple] = None,
    tz: Optional[str] = None,
    matched_entity_ids: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """Compute aggregated chart stats for all entities in the date range (no limit).

    Also returns an evenly-distributed scatter_sample (up to 500 points) spanning
    the full date range so charts are not biased by the per-request row cap.

    ``matched_entity_ids`` lets the caller pre-resolve which entities
    pass the equivalence-expanded species filter (which SQL alone can't
    express — it needs evidence-row introspection). When supplied,
    stats are restricted to that set and the ``species`` SQL clause is
    skipped. Without it, stats can diverge from the entity-list count
    whenever equivalence expansion picks up entities that don't match
    the literal species/common_name predicate.
    """
    import sqlite3 as _sqlite3

    if matched_entity_ids is not None and not matched_entity_ids:
        return _empty_stats()

    conn = open_connection(db.db_path, read_only=db.read_only)
    conn.row_factory = _sqlite3.Row
    try:
        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params: list = []
        # The SAME bound shapes DetectionDB's own query paths use — list vs
        # stats must never compare differently-normalized strings against the
        # UTC-stored column (an offset-bearing bound would sort differently).
        if start_time:
            where_clauses.append("timestamp >= ?")
            params.append(iso_lower_bound(start_time))
        if end_time:
            where_clauses.append("timestamp <= ?")
            params.append(iso_upper_bound(end_time))
        if matched_entity_ids is not None:
            # Caller supplied the post-equivalence-expansion entity set —
            # filter to those IDs and skip the SQL species clause.
            # SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999 on
            # ancient builds and 32766 on modern; we chunk by 500 to be
            # well under either limit.
            ids_list = list(matched_entity_ids)
            chunk_size = 500
            id_chunks = [
                ids_list[i : i + chunk_size]
                for i in range(0, len(ids_list), chunk_size)
            ]
            chunk_clauses = []
            for chunk in id_chunks:
                placeholders = ",".join("?" for _ in chunk)
                chunk_clauses.append(f"entity_id IN ({placeholders})")
                params.extend(chunk)
            where_clauses.append("(" + " OR ".join(chunk_clauses) + ")")
        elif species:
            species_list = [s.strip() for s in species.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in species_list)
            # Match against EITHER the species (slug) column OR the
            # common_name column — the dropdown shows
            # COALESCE(NULLIF(common_name,''), species) values, so the
            # filter may carry either form. A pure species-column WHERE
            # used to silently zero-out any common-name selection
            # (the user-reported "filter shows nothing" bug).
            where_clauses.append(
                f"(species IN ({placeholders}) OR common_name IN ({placeholders}))"
            )
            params.extend(species_list)
            params.extend(species_list)
        if exclude_species:
            exclude_list = [s.strip() for s in exclude_species.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in exclude_list)
            # Mirror the species-include change: exclude on EITHER
            # species (slug) OR common_name so dropdown common-name
            # values exclude correctly.
            where_clauses.append(
                f"(species NOT IN ({placeholders}) "
                f"AND (common_name IS NULL OR common_name NOT IN ({placeholders})))"
            )
            params.extend(exclude_list)
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
        species_dist: Dict[str, int] = {}
        unique_species = set()
        for r in cursor.fetchall():
            # SUM into the name-keyed dict: GROUP BY species can produce
            # multiple rows whose COALESCE(common_name, species)
            # projection collapses to the same display name (two
            # distinct slugs sharing a common name). A naive assignment
            # would silently drop one count.
            species_dist[r["name"]] = species_dist.get(r["name"], 0) + r["count"]
            unique_species.add(r["name"])

        cursor.execute(
            f"SELECT strftime('%Y-%m-%d', timestamp) as day, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY day ORDER BY day",
            params,
        )
        daily_activity = [{"date": r["day"], "count": r["count"]} for r in cursor.fetchall()]

        # Evenly-distributed scatter sample spanning the full date range.
        # When a time-of-day window is active we need EVERY row in range (all
        # aggregates are recomputed in Python after the window filter), so
        # only the full-day path may sample server-side.
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )
        scatter_projection = (
            "SELECT timestamp, species, "
            "COALESCE(NULLIF(common_name,''), species) as name, confidence "
        )
        if not apply_time_window and total > 500:
            # Server-side even sample: pick the SAME row positions
            # even_sample() would (rows[int(i * step)], n=500, including its
            # documented off-by-one), but let SQLite do the striding so only
            # ~500 rows cross into Python instead of the whole range — row
            # materialisation dominates wide-window cost. ROW_NUMBER numbers
            # the same ascending-timestamp order the unsampled query uses;
            # the trailing even_sample() call then passes the <=500 rows
            # through unchanged.
            step = total / 500
            picks = [int(i * step) for i in range(500)]
            pick_placeholders = ",".join("?" for _ in picks)
            cursor.execute(
                "SELECT timestamp, species, name, confidence FROM ("
                f"{scatter_projection}, "
                "ROW_NUMBER() OVER (ORDER BY timestamp) - 1 AS rn "
                f"FROM entities WHERE {where}"
                f") WHERE rn IN ({pick_placeholders}) ORDER BY rn",
                [*params, *picks],
            )
        else:
            # Full fetch (no row limit) so the sample is not biased by the
            # per-request cap applied to the entity list returned to the table.
            cursor.execute(
                f"{scatter_projection}FROM entities WHERE {where} ORDER BY timestamp",
                params,
            )
        all_scatter_rows = cursor.fetchall()

        # If a time-of-day window is active, filter the rows and recompute
        # all aggregates in Python. The SQL GROUP BY above has already run
        # but its results are replaced for consistency with the filtered view.
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

        scatter_sample = [
            {
                "timestamp": r["timestamp"],
                "species_code": r["species"],
                "common_name": r["name"],
                "confidence": r["confidence"],
            }
            for r in even_sample(all_scatter_rows)
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

    conn = open_connection(db.db_path, read_only=db.read_only)
    conn.row_factory = _sqlite3.Row
    try:
        cursor = conn.cursor()
        where_clauses = ["1=1"]
        params: list = []
        # The SAME bound shapes DetectionDB's own query paths use — list vs
        # stats must never compare differently-normalized strings against the
        # UTC-stored column (an offset-bearing bound would sort differently).
        if start_time:
            where_clauses.append("timestamp >= ?")
            params.append(iso_lower_bound(start_time))
        if end_time:
            where_clauses.append("timestamp <= ?")
            params.append(iso_upper_bound(end_time))
        where = " AND ".join(where_clauses)
        cursor.execute(
            f"SELECT COALESCE(NULLIF(common_name,''), species) as name, COUNT(*) as count "
            f"FROM entities WHERE {where} GROUP BY species ORDER BY count DESC",
            params,
        )
        # Sum-by-name (don't assign): two distinct ``species`` slugs
        # whose COALESCE(common_name, species) projection happens to
        # collapse to the same display name must add — naive dict-
        # assignment from the fetchall iterator silently drops the
        # second row's count.
        out: Dict[str, int] = {}
        for r in cursor.fetchall():
            out[r["name"]] = out.get(r["name"], 0) + r["count"]
        return out
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


# Layer 3 — auto-discovery worker health cache. Holds the latest scan
# summary published by the correlator on
# ``orpheus/system/auto-discovery/health``. Read by
# /api/auto-discovery/status.
#
# **Caveats**: (1) Per-worker scope. Module globals don't cross
# gunicorn / uvicorn worker processes — when running multi-worker, only
# the worker whose MQTT subscriber received the heartbeat sees this.
# Run the UI backend single-worker (or behind a single coordinator) if
# health visibility matters. (2) Staleness. The cache holds the LAST
# heartbeat indefinitely — if the agent crashes, the UI reports the
# pre-crash payload until the UI backend restarts. The read endpoints
# add a ``received_age_seconds`` field + ``stale`` flag so consumers
# can detect this.
LATEST_AUTO_DISCOVERY_HEALTH: Optional[Dict[str, Any]] = None
LATEST_AUTO_DISCOVERY_HEALTH_AT: float = 0.0  # monotonic time of last receive

# Audio-events agent health cache. Same caveats as above.
LATEST_AUDIO_EVENTS_HEALTH: Optional[Dict[str, Any]] = None
LATEST_AUDIO_EVENTS_HEALTH_AT: float = 0.0  # monotonic time of last receive

# A single lock guards both health caches. Each cache is a pair of
# globals (payload + monotonic-time-of-receive) that must be written
# and read atomically together — without the lock, a reader can
# observe a fresh payload paired with a stale timestamp (or vice
# versa) while the MQTT subscriber thread is mid-update, making the
# ``stale`` flag and ``received_age_seconds`` field incoherent. The
# critical sections are tiny so a single lock is fine.
_HEALTH_LOCK = threading.Lock()

# Heartbeat is published every 30s by spec; we flag stale after 90s
# (3 missed heartbeats) — long enough to ride out a single network
# blip but short enough to surface a real outage.
# HEALTH_STALE_AFTER_SECONDS is imported at module top from
# orpheus_common.actor — the writer's contract, shared with the KV consumer.


def _serve_health_from_kv() -> bool:
    """True iff the UI is PROMOTED to serve operational health from the KV plane
    (§11 Phase 3: ``ui.health_source == "kv"``). ``"bus"`` (default) and ``"both"``
    (Phase-2 shadow: read KV but still serve from the bus) both serve from the bus —
    so promotion is a single config flip, instantly reversible, no redeploy. Any error
    resolving config falls back to ``"bus"`` so a config hiccup never breaks the view.

    Config alone is not enough: the KV consumer must have actually started feeding
    the cache (``health_kv.CONSUMER_ACTIVE``, set by main.py's lifespan / re-snapshot
    loop). Without that guard, ``health_source="kv"`` on an mqtt backend — or a
    broker outage at UI boot — would serve a never-fed empty cache (every agent
    "never_seen") with no fallback."""
    from orpheus_common.config import OrpheusConfig  # noqa: PLC0415

    from orpheus_ui import health_kv  # noqa: PLC0415

    if not health_kv.CONSUMER_ACTIVE:
        return False  # KV consumer never fed the cache -> keep serving from the bus
    try:
        return getattr(OrpheusConfig.get_instance().ui, "health_source", "bus") == "kv"
    except Exception:
        return False  # config unavailable -> serve from the bus (safe default)


# Cross-agent error feed — ring buffer of the last N agent errors,
# populated from MQTT health publishes whose payload includes a
# `last_error` or `errors_count` field. Bounded memory; the backend
# only keeps the most recent entries.
#
# **Concurrency**: writes come from the MQTT subscriber callback (which
# runs on paho's loop thread), reads come from FastAPI worker threads
# serving /api/errors/recent. The composite dedup-iterate + append +
# trim is not naturally atomic under the GIL, so we guard the whole
# critical section with a Lock. Readers also briefly hold it to take a
# consistent snapshot.
#
# **Per-worker scope (multi-worker caveat)**: this is a module-level
# list, so under gunicorn/uvicorn with workers > 1 each worker has its
# own ERROR_FEED. The endpoint will only show errors observed by the
# worker handling the request — fine for single-worker deployments
# (the default), surprising for multi-worker setups. If multi-worker
# becomes the norm, move this to a shared backing store (Redis, the
# SQLite DB, etc.).
ERROR_FEED_MAX: int = 200
ERROR_FEED: List[Dict[str, Any]] = []
_ERROR_FEED_LOCK = threading.Lock()
# Dedup window — repeated identical errors within this many seconds
# from the same agent get coalesced into one feed entry with a
# bumped count, so a tight error loop doesn't blow out the ring.
ERROR_FEED_DEDUP_SECONDS = 60.0


def _agent_from_health_topic(topic: str) -> Optional[str]:
    """Extract the agent name from a health topic like
    ``orpheus/system/audio-events/health`` → ``"audio-events"``."""
    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == "orpheus" and parts[-1] == "health":
        return parts[-2]
    return None


def _record_agent_error(agent: str, error_message: str, errors_count: int) -> None:
    """Append to the ring buffer with dedup. Updates the count on a
    matching recent entry instead of duplicating.

    Thread-safe — holds ``_ERROR_FEED_LOCK`` for the whole
    dedup + append + trim composite, so concurrent MQTT-thread writes
    and FastAPI-thread reads see a consistent ring state.
    """
    if not error_message:
        return
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    with _ERROR_FEED_LOCK:
        # Look for a recent entry with the same agent + message.
        for entry in reversed(ERROR_FEED[-30:]):
            if entry["agent"] != agent or entry["message"] != error_message:
                continue
            try:
                last_seen = datetime.fromisoformat(entry["last_seen"])
            except Exception:
                continue
            if (now - last_seen).total_seconds() <= ERROR_FEED_DEDUP_SECONDS:
                entry["last_seen"] = now_iso
                entry["count"] = entry.get("count", 1) + 1
                entry["errors_count"] = errors_count
                return

        ERROR_FEED.append(
            {
                "agent": agent,
                "message": error_message,
                "first_seen": now_iso,
                "last_seen": now_iso,
                "count": 1,
                "errors_count": errors_count,
            }
        )
        # Trim ring buffer.
        if len(ERROR_FEED) > ERROR_FEED_MAX:
            del ERROR_FEED[: len(ERROR_FEED) - ERROR_FEED_MAX]


def on_agent_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Subscribed to ``orpheus/system/+/health``. Harvests any agent
    errors out of the payload and feeds the cross-agent error ring.

    Agents that publish ``last_error`` (non-empty string) and/or
    ``errors_count`` get represented in the feed. Agents that don't
    publish these fields are simply silent here — no breakage."""
    agent = _agent_from_health_topic(topic)
    if not agent:
        return
    last_error = payload.get("last_error") if isinstance(payload, dict) else None
    if not last_error:
        return
    errors_count = (
        int(payload.get("errors_count", 0))
        if isinstance(payload, dict)
        else 0
    )
    _record_agent_error(agent, str(last_error), errors_count)


@router.get("/errors/recent")
def get_recent_errors(
    limit: int = Query(50, ge=1, le=200, description="Max entries returned"),
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Recent agent errors, most-recent-first. Sourced from the
    ring buffer that captures `last_error` fields on agent health
    publishes.

    Bounded memory — the backend keeps at most
    ``ERROR_FEED_MAX`` entries, dedup'd by (agent, message) within
    a 60s window.

    NB: ring buffer is per-worker. Under multi-worker gunicorn/uvicorn,
    each worker has its own ERROR_FEED and this endpoint only shows the
    errors the request-handling worker observed.
    """
    # §11 Phase 3: when promoted to serve from KV, project the cross-agent error feed
    # from the KV last-values (each agent's current last_error). This is LOSSIER than
    # the bus ring buffer — a sub-heartbeat error that clears is invisible to a
    # last-value projection (the accepted fidelity trade; see the determinism design).
    if _serve_health_from_kv():
        from orpheus_ui import health_kv  # noqa: PLC0415

        errors = []
        for key, env in health_kv.HEALTH_KV_CACHE.snapshot().items():
            last_error = env.get("last_error")
            if last_error:
                # A last-value projection has no dedup history, so first/last seen
                # both come from the envelope's emitted_at and count is 1 — but the
                # entry must carry EVERY key the bus-path entries carry (agent,
                # message, first_seen, last_seen, count, errors_count): the
                # RecentErrorsPanel dereferences last_seen/count unconditionally,
                # so omitting them crashes the panel on promotion.
                emitted_at = str(env.get("emitted_at", "") or "")
                errors.append(
                    {
                        "agent": env.get("agent", key),
                        "message": str(last_error),
                        "first_seen": emitted_at,
                        "last_seen": emitted_at,
                        "count": 1,
                        "errors_count": int(env.get("errors_count", 0) or 0),
                        "source": "kv",
                    }
                )
        return {"errors": errors[:limit], "total": len(errors), "buffer_max": ERROR_FEED_MAX}

    # Hold the lock briefly to take a consistent snapshot — concurrent
    # MQTT writes can otherwise observe a slice mid-mutation.
    with _ERROR_FEED_LOCK:
        snapshot = list(reversed(ERROR_FEED[-limit:]))
        total = len(ERROR_FEED)
    return {
        "errors": snapshot,
        "total": total,
        "buffer_max": ERROR_FEED_MAX,
    }


def on_audio_events_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Cache the latest audio-events agent heartbeat so the UI can
    surface PANNs liveness, latency stats, and error counts without
    polling the agent directly."""
    global LATEST_AUDIO_EVENTS_HEALTH
    global LATEST_AUDIO_EVENTS_HEALTH_AT
    import time as _time  # noqa: PLC0415

    with _HEALTH_LOCK:
        LATEST_AUDIO_EVENTS_HEALTH = payload
        LATEST_AUDIO_EVENTS_HEALTH_AT = _time.monotonic()


@router.get("/audio-events/health")
def get_audio_events_health(
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Return the most recent audio-events heartbeat.

    Returns ``{"status": "never_seen"}`` when no heartbeat has been
    observed since the UI backend started (e.g. agent not running yet,
    or just-started agent before its first heartbeat). Adds a
    ``received_age_seconds`` field + a ``stale`` flag so the UI can
    distinguish a live agent from one that crashed N minutes ago.
    """
    import time as _time  # noqa: PLC0415

    if _serve_health_from_kv():  # §11 Phase 3: serve from the KV plane
        from orpheus_ui import health_kv  # noqa: PLC0415

        view = health_kv.HEALTH_KV_CACHE.view("audio-events")
        return view if view is not None else {"status": "never_seen"}

    with _HEALTH_LOCK:
        payload = LATEST_AUDIO_EVENTS_HEALTH
        ts = LATEST_AUDIO_EVENTS_HEALTH_AT
    if payload is None:
        return {"status": "never_seen"}
    age = _time.monotonic() - ts
    out = dict(payload)
    out["received_age_seconds"] = round(age, 1)
    out["stale"] = age > HEALTH_STALE_AFTER_SECONDS
    return out


def on_auto_discovery_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Cache the latest auto-discovery scan summary so the UI can show
    'last scan ran X ago' without polling the DB or hitting the
    correlator directly."""
    global LATEST_AUTO_DISCOVERY_HEALTH
    global LATEST_AUTO_DISCOVERY_HEALTH_AT
    import time as _time  # noqa: PLC0415

    with _HEALTH_LOCK:
        LATEST_AUTO_DISCOVERY_HEALTH = payload
        LATEST_AUTO_DISCOVERY_HEALTH_AT = _time.monotonic()


@router.get("/auto-discovery/status")
def get_auto_discovery_status(
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Return the most recent auto-discovery scan summary, if any.

    The correlator publishes one of these to MQTT after every periodic
    scan (and also surfaces lifetime stats). Returns 200 with
    ``{"status": "never_run"}`` when no scan has been observed since
    the UI backend started.

    Adds ``received_age_seconds`` + ``stale`` so the UI can render
    "last scan: 6h ago, agent healthy" vs "last scan: 2h ago, agent
    offline". Stale threshold is the same 90s window as the audio-events
    heartbeat — the auto-discovery worker pulses its own heartbeat
    inside the correlator process at the same cadence.
    """
    import time as _time  # noqa: PLC0415

    if _serve_health_from_kv():  # §11 Phase 3: serve from the KV plane
        from orpheus_ui import health_kv  # noqa: PLC0415

        view = health_kv.HEALTH_KV_CACHE.view("auto-discovery")
        return view if view is not None else {"status": "never_run"}

    with _HEALTH_LOCK:
        payload = LATEST_AUTO_DISCOVERY_HEALTH
        ts = LATEST_AUTO_DISCOVERY_HEALTH_AT
    if payload is None:
        return {"status": "never_run"}
    age = _time.monotonic() - ts
    out = dict(payload)
    out["received_age_seconds"] = round(age, 1)
    out["stale"] = age > HEALTH_STALE_AFTER_SECONDS
    return out


@router.get("/diagnostics/health-source-diff")
def get_health_source_diff(
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Phase-2 equivalence oracle for the health-off-bus migration (§11): compare the
    bus health caches the UI serves from today against the shadow KV cache, per field
    (value, bus-only, kv-only, both-absent). ``equivalent: true`` over a soak window
    is the evidence that promoting serving to KV (Phase 3) won't regress the view.
    Diagnostic only — changes no serving path. ``bus_only`` is the worst divergence (a
    source the UI reads that KV is missing); ``kv_only`` is expected new coverage (KV
    holds every agent, not just the two with bus caches)."""
    from orpheus_ui import health_kv  # noqa: PLC0415 — avoid an import cycle at load

    with _HEALTH_LOCK:
        bus = {
            "audio-events": LATEST_AUDIO_EVENTS_HEALTH,
            "auto-discovery": LATEST_AUTO_DISCOVERY_HEALTH,
        }
    kv = {
        "audio-events": health_kv.HEALTH_KV_CACHE.get("audio-events"),
        "auto-discovery": health_kv.HEALTH_KV_CACHE.get("auto-discovery"),
    }
    result = health_kv.compute_health_source_diff(bus, kv)
    # The full KV key set — the coverage gain beyond the two bus per-agent caches
    # (the other agents only fed the cross-agent error feed on the bus side).
    result["kv_keys"] = health_kv.HEALTH_KV_CACHE.keys()
    return result


# Cache-Control + ``Vary: Authorization`` was lifted verbatim into the shared
# api/_responses module so diagnostics + system consume the same header logic.
# Kept as a thin alias for the historical private name / any in-module callers.
_set_cache_control = set_cache_control


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
    limit: int = Query(
        2000,
        ge=1,
        le=2000,
        description=(
            "Legacy unpaginated cap (max 2000). Use page/page_size for "
            "proper server-side pagination instead."
        ),
    ),
    page: Optional[int] = Query(
        None,
        ge=1,
        description=(
            "1-indexed page number. Pass with page_size for server-side "
            "pagination (recommended; bypasses the legacy 2000-row cap)."
        ),
    ),
    page_size: Optional[int] = Query(
        None,
        ge=1,
        le=1000,
        description="Rows per page. Required with page. Max 1000.",
    ),
    response: Response = None,  # type: ignore[assignment]
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Get entity events from the database.

    Supports filtering by species, exclude_species, date range, and an optional
    time-of-day window.

    Pagination: pass ``page`` and ``page_size`` together to get a specific
    slice with ``total_pages`` + ``count`` in the response. Without those,
    falls back to the legacy 2000-row cap (kept for backward compat).
    """
    try:
        db = _get_db()

        # Shared with the diagnostics history endpoints. ``default_days=None``
        # means no rolling fallback: absent start_date/end_date stay None
        # (leaving that side of the query unbounded), matching the original
        # inline behaviour here. Bad input -> HTTPException(400).
        start_dt, end_dt = resolve_date_range(
            None, start_date, end_date, default_days=None
        )

        start_hhmm = parse_hhmm(start_time)
        end_hhmm = parse_hhmm(end_time)
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )

        # Determine the effective fetch cap. When the caller passes
        # page+page_size, we need to fetch enough rows to know the
        # total count (so we can compute total_pages) — use a big cap.
        # Without paging params, honour the legacy ``limit`` for
        # back-compat. ``isinstance`` check because existing unit
        # tests call this function directly without FastAPI's
        # dependency injection, so Query() defaults arrive as Query
        # objects rather than None — those should fall through to the
        # legacy path.
        paginating = isinstance(page, int) and isinstance(page_size, int)

        # Cross-classifier-identity §5: if a species filter is provided,
        # expand it through the equivalence graph + evidence-level matching
        # so a search for "American Crow" hits Entities where the legacy
        # species column says "corvus" AND Entities where only an evidence
        # row has the matching TaxonomyRef. We fetch a broader candidate
        # set from the DB (no DB-level species filter when the expansion
        # is active) and apply the predicate in Python.
        legacy_terms: set[str] = set()
        taxa_pairs: set[tuple[str, str]] = set()
        if species:
            # The store handle is opened here (not left to expand_species_filter's
            # internal default) so an unopenable store logs a once-per-process
            # warning instead of degrading silently; eq_db=None ⇒ the filter
            # still applies, just without equivalence expansion (never a 500).
            legacy_terms, taxa_pairs = expand_species_filter(
                species, eq_db=_equivalence_db_or_none()
            )

        # When a species filter is active we must fetch a broader set from
        # the DB (no DB-level species predicate, because we filter in Python
        # after equivalence expansion). The legacy 2000-row default is far
        # too small for that case — non-paginated callers with a species
        # filter (e.g. CrowEntitySection.tsx) would silently miss species
        # matches sitting outside the most-recent 2000 of ALL species.
        # Bump to the paginated cap (100k) when species expansion is in
        # play, regardless of pagination mode.
        has_species_expansion = bool(legacy_terms or taxa_pairs)
        fetch_limit = (
            100_000
            if (paginating or has_species_expansion)
            else (limit if isinstance(limit, int) else 2000)
        )

        if has_species_expansion:
            # Skip DB-level species filter; we'll apply the broader
            # predicate in Python.
            entities = db.get_entities(
                exclude_species=exclude_species,
                start_time=start_dt,
                end_time=end_dt,
                limit=fetch_limit,
            )
            entities = [
                e for e in entities
                if _entity_matches_species_filter(
                    e.species,
                    e.evidence,
                    legacy_terms,
                    taxa_pairs,
                    ent_common_name=e.common_name,
                )
            ]
        else:
            entities = db.get_entities(
                exclude_species=exclude_species,
                start_time=start_dt,
                end_time=end_dt,
                limit=fetch_limit,
            )

        # Apply the time-window filter UP FRONT (separate pass) so that
        # pagination math sees the post-filter count. Previously the
        # filter was applied inline with the dict-building loop, which
        # meant pagination over a filtered subset double-counted skips.
        if apply_time_window:
            filtered_entities = []
            for ent in entities:
                ts = ent.timestamp if isinstance(ent.timestamp, datetime) else None
                if ts is None:
                    try:
                        ts = datetime.fromisoformat(
                            str(ent.timestamp).replace("Z", "+00:00")
                        )
                    except Exception:
                        ts = None
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if not timestamp_in_window(ts, start_hhmm, end_hhmm, tz):
                    continue
                filtered_entities.append(ent)
            entities = filtered_entities

        total_count = len(entities)
        # Capture the full filtered set's entity_ids BEFORE pagination
        # slices ``entities`` below. Stats must reflect every entity that
        # passed the equivalence-expanded predicate, not just the page
        # the user is looking at — without this snapshot the stats panels
        # silently disagree with the table.
        matched_entity_ids: Optional[set[str]] = (
            {e.entity_id for e in entities} if has_species_expansion else None
        )

        # Server-side pagination: slice to the requested page BEFORE we
        # do the expensive per-evidence metadata fetch. Without
        # page+page_size, return everything we fetched (legacy
        # behaviour).
        total_pages: Optional[int] = None
        if paginating:
            entities, _, _, total_pages = paginate(entities, page, page_size)

        # Collect event_ids only for the entities we'll actually return.
        # Previously this fetched metadata for ALL filtered entities even
        # though only a slice was serialised — wasted work when paging.
        event_ids = set()
        for ent in entities:
            for ev in ent.evidence:
                event_ids.add(ev.event_id)
        detection_metadata = _fetch_detection_metadata(db, list(event_ids))

        # Serialize to dicts for JSON response using the wire-format
        # keys expected by the frontend (species_code, common_name).
        # Enrich each entity with aggregated metadata from its evidence.
        entity_dicts: List[Dict[str, Any]] = []
        for ent in entities:
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
                    # Layer 2: evidence carries per-classifier species + taxonomy
                    # + detection_type. Serialised via model_dump so the new
                    # fields appear automatically. See cross-classifier-identity §4.
                    # clip_available (computed) lets the UI pre-render "Clip
                    # expired" for evidence whose audio rolled off retention —
                    # only on the bounded paginated path (the drawer's source);
                    # skipped on the unbounded species path that never renders
                    # ClipActions, to avoid a stat() per row on a hot endpoint.
                    "evidence": _serialize_evidence(
                        ent.evidence, with_availability=paginating
                    ),
                    "context": ent.context,
                    "metadata_aggregate": metadata_agg,
                    # Layer 2: traceability metadata describing how this
                    # Entity was assembled (audio.motion source_ids, mics
                    # that contributed, time span). None for legacy rows.
                    "event_signature": ent.event_signature,
                    # Corollary discharge — True when this entity overlapped our
                    # own audio playback (the system hearing itself).
                    "is_self_generated": ent.is_self_generated,
                    # Coarse state-space type (e.g. "Animal.Bird.Crow"); None for
                    # legacy/unresolved entities ([ARCH] entity taxonomy).
                    "entity_type": ent.entity_type,
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
                matched_entity_ids=matched_entity_ids,
            )
        except Exception as stats_err:
            logger.warning("Failed to compute entity stats", error=str(stats_err))
            stats = _empty_stats()

        # Always include the unfiltered species distribution so the
        # frontend dropdown stays fully populated even after the user
        # narrows the selection.
        #
        # Fast path: when the user has NO species/exclude filter AND
        # no time-of-day window, the stats we just computed already
        # span the full date range — the species_distribution dict IS
        # the all-species view, so reuse it instead of issuing a
        # second full-range GROUP BY scan. With 30s polling on
        # Entities this saves one scan per poll on the common no-
        # filter path.
        #
        # ``apply_time_window`` must be false too: when the user picks
        # a time-of-day window, ``_compute_entity_stats`` rebuilds
        # species_dist from the filtered row subset and the dropdown
        # would silently lose species that occur in the date range
        # but outside the time window.
        #
        # Fallback: if ``_compute_entity_stats`` raised (try/except
        # above caught and set ``stats = _empty_stats()``),
        # species_distribution is ``{}``. Don't lock the dropdown to
        # empty — fall through to ``_compute_all_species_in_range``
        # which is independent and may succeed.
        species_dist = stats.get("species_distribution", {})
        can_reuse_distribution = (
            not species
            and not exclude_species
            and not apply_time_window
            and species_dist  # not empty → stats path succeeded
        )
        if can_reuse_distribution:
            stats["all_species"] = dict(species_dist)
        else:
            try:
                stats["all_species"] = _compute_all_species_in_range(db, start_dt, end_dt)
            except Exception as all_species_err:
                logger.warning("Failed to compute all_species", error=str(all_species_err))
                stats.setdefault("all_species", {})

        # scatter_sample comes from _compute_entity_stats which queries the full
        # date range without the per-request row cap, so it spans all dates.
        scatter_sample = stats.get("scatter_sample", [])

        result: Dict[str, Any] = {
            "entities": entity_dicts,
            "count": total_count,  # full filtered count, not the page size
            "scatter_sample": scatter_sample,
            "stats": stats,
        }
        if paginating:
            result["page"] = max(1, int(page))
            result["page_size"] = max(1, min(int(page_size), 1000))
            result["total_pages"] = total_pages
        # 5 second browser cache — combined with 30s react-query polling
        # this makes a tab-switch or quick refetch hit the disk cache
        # instead of re-running the expanded-species megaquery.
        # ``response`` is None when the function is called directly from
        # Python (tests), but FastAPI always injects it at request time.
        if response is not None:
            set_cache_control(response, max_age=5)
        return result
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
    conn = open_connection(db.db_path, read_only=db.read_only)
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


@router.get("/correlator/health")
def get_correlator_health(
    lookback_hours: int = Query(
        24, description="Look at root_event_ids seen in the last N hours."
    ),
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Correlator health — late-arrival detection + window-tuning signal.

    The healthy state is one Entity per audio.motion root_event_id. If
    PANNs / crow-tools / etc. take longer than `correlation.window_seconds`
    to process, their Detection arrives after the cluster closed and we
    end up with multiple Entities for the same root. This endpoint
    surfaces that pathology so ops can tune `window_seconds` or
    investigate the slow downstream agent.

    Returns:
        - `entities_per_root_histogram`: {"1": N, "2": M, "3+": K} — how
          many Entities exist per root_event_id in the lookback window.
          Healthy = mostly 1s.
        - `late_arrival_examples`: up to 10 specific root_event_ids that
          have > 1 Entity, with the entity_ids and timestamps.
        - `chain_completion_ms_p50` / `p95`: time from audio.motion to
          last Detection in the chain — drives window_seconds tuning.
        - `roots_examined`: total roots in the lookback window.
        - `multi_entity_root_count`: roots where > 1 Entity exists.
        - `multi_entity_root_pct`: share — > 5% is a real signal to
          widen the window.
    """
    try:
        db = _get_db()
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=lookback_hours)

        conn = open_connection(db.db_path, read_only=db.read_only)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            # event_signature is an additive column. On a read-only DB that
            # predates it (the replica path, or the degrade-to-read-only
            # fallback pointed at an un-migrated DB) it won't exist and the
            # query below would raise "no such column". Treat a legacy DB as
            # having no signatures yet rather than 500ing.
            cur.execute("PRAGMA table_info(entities)")
            entity_cols = {r[1] for r in cur.fetchall()}
            if "event_signature" not in entity_cols:
                entity_rows = []
            else:
                # Count Entities grouped by root_event_id (parsed from
                # event_signature JSON). NULL event_signature = legacy row, skip.
                cur.execute(
                    """
                    SELECT entity_id, timestamp, event_signature
                    FROM entities
                    WHERE event_signature IS NOT NULL
                      AND timestamp >= ?
                      AND timestamp <= ?
                    """,
                    (start.replace(microsecond=0).isoformat(),
                     now.replace(microsecond=999999).isoformat()),
                )
                entity_rows = cur.fetchall()

            roots_to_entities: Dict[str, list] = defaultdict(list)
            for row in entity_rows:
                try:
                    sig = json.loads(row["event_signature"])
                except (TypeError, json.JSONDecodeError):
                    continue
                for root in sig.get("audio_motion_source_ids", []) or []:
                    roots_to_entities[root].append(
                        {
                            "entity_id": row["entity_id"],
                            "timestamp": row["timestamp"],
                        }
                    )

            histogram = {"1": 0, "2": 0, "3+": 0}
            late_arrivals: list = []
            for root, ents in roots_to_entities.items():
                n = len(ents)
                if n == 1:
                    histogram["1"] += 1
                elif n == 2:
                    histogram["2"] += 1
                else:
                    histogram["3+"] += 1
                if n > 1 and len(late_arrivals) < 10:
                    late_arrivals.append(
                        {
                            "root_event_id": root,
                            "entity_count": n,
                            "entities": ents,
                        }
                    )

            # Chain-completion latency: for each root, time gap between
            # the audio.motion timestamp and the LAST detection in the
            # chain. Drives window_seconds tuning — if p95 > current
            # window_seconds, downstream agents are routinely missing
            # the cluster.
            #
            # Batched: previously this loop issued ONE SELECT MIN/MAX
            # per root_event_id (up to 500 round-trips per /api/
            # correlator/health hit, which Diagnostics polls every
            # 60s — see Diagnostics.tsx). Now we do a single GROUP BY
            # in chunks, served from idx_root_event_id_ts as O(1) per
            # group via index extremes.
            chain_gaps_ms: list[float] = []
            roots_for_chain = list(roots_to_entities.keys())[:500]  # cap for perf
            # SQLite's default SQLITE_MAX_VARIABLE_NUMBER is 999 on old
            # builds; chunk at 500 to stay well below either limit.
            chunk_size = 500
            for i in range(0, len(roots_for_chain), chunk_size):
                chunk = roots_for_chain[i : i + chunk_size]
                if not chunk:
                    continue
                placeholders = ",".join("?" for _ in chunk)
                cur.execute(
                    f"""
                    SELECT root_event_id,
                           MIN(timestamp) AS start_ts,
                           MAX(timestamp) AS end_ts
                    FROM detections
                    WHERE root_event_id IN ({placeholders})
                    GROUP BY root_event_id
                    """,
                    chunk,
                )
                for ts_row in cur.fetchall():
                    if not ts_row["start_ts"] or not ts_row["end_ts"]:
                        continue
                    try:
                        start_dt = datetime.fromisoformat(ts_row["start_ts"])
                        end_dt = datetime.fromisoformat(ts_row["end_ts"])
                        gap_ms = (end_dt - start_dt).total_seconds() * 1000
                        if gap_ms >= 0:
                            chain_gaps_ms.append(gap_ms)
                    except (ValueError, TypeError):
                        continue

            def _pct(values: list[float], p: float) -> float:
                if not values:
                    return 0.0
                s = sorted(values)
                k = (len(s) - 1) * p
                f = int(k)
                c = min(f + 1, len(s) - 1)
                if f == c:
                    return s[f]
                return s[f] + (k - f) * (s[c] - s[f])

            total_roots = len(roots_to_entities)
            multi_count = histogram["2"] + histogram["3+"]
            return {
                "lookback_hours": lookback_hours,
                "ran_at": now.isoformat(),
                "roots_examined": total_roots,
                "multi_entity_root_count": multi_count,
                "multi_entity_root_pct": (
                    round(100.0 * multi_count / total_roots, 2)
                    if total_roots > 0 else 0.0
                ),
                "entities_per_root_histogram": histogram,
                "late_arrival_examples": late_arrivals,
                "chain_completion_ms": {
                    "samples": len(chain_gaps_ms),
                    "p50": round(_pct(chain_gaps_ms, 0.5), 1),
                    "p95": round(_pct(chain_gaps_ms, 0.95), 1),
                    "max": round(max(chain_gaps_ms) if chain_gaps_ms else 0.0, 1),
                },
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to compute correlator health", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compute correlator health: {e}",
        )


@router.get("/equivalences")
def list_equivalences(
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """List the current state of the taxonomy equivalence graph.

    Returns accepted rows + pending_review rows + non-equivalence
    assertions, all deduplicated to one row per pair (the underlying
    table stores both directions for query efficiency).

    Used by the UI's equivalence review page to surface what
    auto-discovery has learned and what's awaiting human approval.

    A store that can't be OPENED (the constructor mkdirs + writes schema, so an
    unwritable data root raises) degrades to an empty listing + a warning — a
    read endpoint must not 500 the review page over a store that plainly has
    nothing in it (real CI incident). The accept/reject/scan WRITE endpoints
    below still fail loud.

    Cross-classifier-identity §5.
    """
    try:
        eq_db = TaxonomyEquivalenceDB()
    except Exception as e:  # noqa: BLE001 - unopenable store -> empty listing
        logger.warning(
            "Taxonomy equivalence store unavailable; serving empty equivalence "
            "list",
            error=str(e),
        )
        return {
            "accepted": [],
            "pending_review": [],
            "non_equivalences": [],
            "counts": {"accepted": 0, "pending_review": 0, "non_equivalences": 0},
            "degraded": True,
        }
    try:
        conn = open_connection(eq_db.db_path)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            # Equivalence rows — dedupe to one per canonical pair.
            cur.execute(
                """
                SELECT namespace_a, id_a, namespace_b, id_b,
                       confidence, source, status, created_at, notes
                FROM taxonomy_equivalence
                """
            )
            seen: set = set()
            accepted: List[Dict[str, Any]] = []
            pending: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                pair = tuple(
                    sorted([(row["namespace_a"], row["id_a"]),
                            (row["namespace_b"], row["id_b"])])
                )
                if pair in seen:
                    continue
                seen.add(pair)
                entry = {
                    "a": {"namespace": pair[0][0], "id": pair[0][1]},
                    "b": {"namespace": pair[1][0], "id": pair[1][1]},
                    "confidence": row["confidence"],
                    "source": row["source"],
                    "status": row["status"],
                    "created_at": row["created_at"],
                    "notes": row["notes"],
                }
                if row["status"] == "pending_review":
                    pending.append(entry)
                else:
                    accepted.append(entry)

            # Non-equivalence rows.
            cur.execute(
                """
                SELECT namespace_a, id_a, namespace_b, id_b,
                       source, notes, created_at
                FROM taxonomy_non_equivalence
                """
            )
            seen_neq: set = set()
            non_equivalences: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                pair = tuple(
                    sorted([(row["namespace_a"], row["id_a"]),
                            (row["namespace_b"], row["id_b"])])
                )
                if pair in seen_neq:
                    continue
                seen_neq.add(pair)
                non_equivalences.append(
                    {
                        "a": {"namespace": pair[0][0], "id": pair[0][1]},
                        "b": {"namespace": pair[1][0], "id": pair[1][1]},
                        "source": row["source"],
                        "notes": row["notes"],
                        "created_at": row["created_at"],
                    }
                )

            return {
                "accepted": accepted,
                "pending_review": pending,
                "non_equivalences": non_equivalences,
                "counts": {
                    "accepted": len(accepted),
                    "pending_review": len(pending),
                    "non_equivalences": len(non_equivalences),
                },
            }
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to list equivalences", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to list equivalences: {e}"
        )


@router.post("/equivalences/accept")
def accept_equivalence(
    payload: Dict[str, Any],
    user: User = Depends(require_role("admin")),
) -> Dict[str, Any]:
    """Promote a pending_review equivalence to accepted.

    POST body shape:
        {
          "a": {"namespace": "ioc", "id": "Corvus brachyrhynchos"},
          "b": {"namespace": "audioset", "id": "/m/04s8yn"}
        }
    """
    try:
        a = TaxonomyRef(
            namespace=payload["a"]["namespace"], id=payload["a"]["id"]
        )
        b = TaxonomyRef(
            namespace=payload["b"]["namespace"], id=payload["b"]["id"]
        )
        eq_db = TaxonomyEquivalenceDB()
        eq_db.accept_pending(a, b)
        # Bust the bird-like cache so the Bird Correlation dashboard
        # picks up the new edge on the next request.
        try:
            from orpheus_ui.api import diagnostics  # noqa: PLC0415

            diagnostics.reset_bird_like_audioset_cache()
        except Exception:
            pass
        return {"status": "accepted", "a": payload["a"], "b": payload["b"]}
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e}")
    except Exception as e:
        logger.error("Failed to accept equivalence", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to accept equivalence: {e}"
        )


@router.post("/equivalences/reject")
def reject_equivalence(
    payload: Dict[str, Any],
    user: User = Depends(require_role("admin")),
) -> Dict[str, Any]:
    """Record a non-equivalence — these refs are NOT the same thing.

    Blocks the auto-discovery worker from re-proposing the pair.

    POST body same shape as ``accept_equivalence`` plus optional
    ``notes``.
    """
    try:
        a = TaxonomyRef(
            namespace=payload["a"]["namespace"], id=payload["a"]["id"]
        )
        b = TaxonomyRef(
            namespace=payload["b"]["namespace"], id=payload["b"]["id"]
        )
        notes = payload.get("notes", "")
        eq_db = TaxonomyEquivalenceDB()
        eq_db.record_non_equivalence(a, b, source="manual", notes=notes)
        try:
            from orpheus_ui.api import diagnostics  # noqa: PLC0415

            diagnostics.reset_bird_like_audioset_cache()
        except Exception:
            pass
        return {
            "status": "rejected",
            "a": payload["a"],
            "b": payload["b"],
            "notes": notes,
        }
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"Missing field: {e}")
    except Exception as e:
        logger.error("Failed to reject equivalence", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to reject equivalence: {e}"
        )


@router.get("/equivalences/diagnose")
def diagnose_auto_discovery(
    lookback_days: int = Query(7, description="Lookback window in days."),
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Read-only debug view of auto-discovery state.

    Shows what auto-discovery WOULD propose at lower thresholds, what
    taxa are firing in the lookback window, and which pairs are near
    misses. Lets ops decide whether the thresholds are too strict.

    Doesn't write anything to the equivalence graph.
    """
    try:
        from orpheus_common import OrpheusConfig  # noqa: PLC0415

        ad_cfg = OrpheusConfig.get_instance().correlation.auto_discovery
        result = diagnose_equivalences(
            _get_db(),
            TaxonomyEquivalenceDB(),
            lookback_days=lookback_days,
            propose_threshold=ad_cfg.propose_threshold,
            min_cooccurrences=ad_cfg.min_cooccurrences,
        )
        return result
    except Exception as e:
        logger.error("Failed to run auto-discovery diagnose", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to diagnose: {e}"
        )


@router.post("/equivalences/scan")
def scan_equivalences_now(
    payload: Optional[Dict[str, Any]] = None,
    user: User = Depends(require_role("admin")),
) -> Dict[str, Any]:
    """Trigger an auto-discovery scan immediately.

    The correlator runs auto-discovery on a 6h schedule by default;
    this endpoint lets ops/UI kick off an on-demand scan without
    waiting (useful right after a fresh deployment, or for sanity
    checking on the Equivalences page).

    Optional POST body:
        {
          "lookback_days": 7,
          "propose_threshold": 0.6,
          "accept_threshold": 0.9,
          "min_cooccurrences": 5,
          "cross_namespace_accept_only": false
        }
    Any field can be omitted to use the orpheus.yaml default.
    """
    try:
        payload = payload or {}
        # Defer to OrpheusConfig for the defaults so the operator's
        # tuned values are honoured.
        from orpheus_common import OrpheusConfig  # noqa: PLC0415

        ad_cfg = OrpheusConfig.get_instance().correlation.auto_discovery
        proposals = discover_equivalences(
            _get_db(),
            TaxonomyEquivalenceDB(),
            lookback_days=int(
                payload.get("lookback_days", ad_cfg.lookback_days)
            ),
            propose_threshold=float(
                payload.get("propose_threshold", ad_cfg.propose_threshold)
            ),
            accept_threshold=float(
                payload.get("accept_threshold", ad_cfg.accept_threshold)
            ),
            min_cooccurrences=int(
                payload.get("min_cooccurrences", ad_cfg.min_cooccurrences)
            ),
            cross_namespace_accept_only=bool(
                payload.get(
                    "cross_namespace_accept_only",
                    ad_cfg.cross_namespace_accept_only,
                )
            ),
        )
        # The scan may have added new equivalences — bust the bird-like
        # cache so the Bird Correlation dashboard picks them up.
        try:
            from orpheus_ui.api import diagnostics  # noqa: PLC0415

            diagnostics.reset_bird_like_audioset_cache()
        except Exception:
            pass
        return {
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "total_proposals": len(proposals),
            "recorded": sum(1 for p in proposals if p["action"] == "recorded"),
            "promoted": sum(1 for p in proposals if p["action"] == "promoted"),
            "skipped_existing": sum(
                1 for p in proposals if p["action"] == "skipped_existing"
            ),
            "skipped_blocked": sum(
                1 for p in proposals if p["action"] == "skipped_blocked"
            ),
            "proposals": proposals,
        }
    except Exception as e:
        logger.error("Failed to run auto-discovery scan", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to run auto-discovery scan: {e}"
        )


@router.get("/chain/{root_event_id}")
def get_chain(
    root_event_id: str,
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Return every Detection in the chain rooted at ``root_event_id``.

    The "metadata appended to metadata" view: given an audio.motion
    event_id, you get back the audio.motion + every downstream
    classifier's Detection that traces back to it (bird-detection,
    crow-detection, audio-events, future agents).

    See ``docs/designs/cross-classifier-identity.md`` §1.1.
    """
    try:
        db = _get_db()
        detections = db.get_chain(root_event_id)
        if not detections:
            raise HTTPException(
                status_code=404,
                detail=f"No detections found for root_event_id={root_event_id}",
            )
        return {
            "root_event_id": root_event_id,
            "count": len(detections),
            "chain": [d.to_dict() for d in detections],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to fetch chain", root_event_id=root_event_id, error=str(e)
        )
        raise HTTPException(status_code=500, detail=f"Failed to fetch chain: {e}")


@router.get("/entities/{entity_id}")
def get_entity_by_id(
    entity_id: str,
    user: User = Depends(current_active_user),
) -> Dict[str, Any]:
    """Get a specific entity event by its ID."""
    try:
        db = _get_db()
        # Direct DB-level lookup by entity_id — previously this fetched
        # the most-recent 5000 rows and linear-scanned them, which
        # returned 404 for any entity older than that even though it
        # was right there in the DB.
        ent = db.get_entity_by_id(entity_id)
        if ent is None:
            raise HTTPException(status_code=404, detail="Entity not found")
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
            "evidence": _serialize_evidence(ent.evidence),
            "context": ent.context,
            "metadata_aggregate": metadata_agg,
            "event_signature": ent.event_signature,
            "is_self_generated": ent.is_self_generated,
            "entity_type": ent.entity_type,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get entity", entity_id=entity_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get entity: {e}")
