"""Main entry point for the event correlator agent."""

from __future__ import annotations

import asyncio
import contextlib
import time
from datetime import datetime, timezone
from typing import Any

from orpheus_common import OrpheusConfig, StateSpaceMemory
from orpheus_common.actor import Actor, build_operational_health
from orpheus_common.detection import (
    Detection,
    DetectionDB,
    Entity,
    TaxonomyEquivalenceDB,
    discover_equivalences,
    same_source,
)
from orpheus_common.detection.entity_taxonomy import load_taxonomy
from orpheus_common.events import WeatherReading
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.weather import WeatherDB
from pydantic import ValidationError

from .cluster_manager import ClusterManager, Observation
from .corollary_discharge import PLAYBACK_TOPIC, CorollaryDischargeFilter

logger = get_logger(__name__)

# Detection types to ignore (raw triggers, not entities)
IGNORED_DETECTION_TYPES = {"audio.motion"}

# Detection types to process
PROCESSED_DETECTION_TYPES = {"species.detected", "crow.analyzed", "audio.classified"}

# Late-arrival enrichment updates publish here — deliberately a SIBLING root
# outside orpheus/entities/ so no entity-create wildcard (orpheus/entities/#)
# can catch an update and double-count. The primary consumer (the UI) reads the
# in-place-updated SQLite row; this topic is for streaming consumers that want
# update events explicitly.
ENTITY_UPDATED_TOPIC = "orpheus/entity-updates/animal"


class EventCorrelatorAgent(Actor):
    """Event correlator agent that fuses detection events into EntityEvents.

    Lifecycle comes from ``Actor``; this fills the hooks. ``self.bus`` is the
    EventBus, ``self.orpheus_config`` the loaded config (set by the base)."""

    def __init__(
        self,
        window_seconds: float | None = None,
        max_cluster_duration_seconds: float | None = None,
        config_path: str | None = None,
        *,
        auto_discovery_enabled: bool | None = None,
        auto_discovery_interval_seconds: float | None = None,
        auto_discovery_lookback_days: int | None = None,
        late_enrichment_enabled: bool | None = None,
        late_enrichment_ttl_seconds: float | None = None,
        late_enrichment_max_tracked_roots: int | None = None,
    ) -> None:
        """Initialize event correlator agent.

        Any constructor argument left as None inherits its value from
        the ``correlation`` section of ``orpheus.yaml``. Constructor
        arguments override config (useful for tests).
        """
        super().__init__("event-correlator", OrpheusConfig.get_instance(config_path=config_path))
        corr_cfg = self.orpheus_config.correlation

        self.window_seconds = (
            window_seconds if window_seconds is not None else corr_cfg.window_seconds
        )
        self.max_cluster_duration_seconds = (
            max_cluster_duration_seconds
            if max_cluster_duration_seconds is not None
            else corr_cfg.max_cluster_duration_seconds
        )
        # Off-by-default: ALSO publish each EntityEvent on its entity_type-routed
        # topic (in addition to the always-on legacy orpheus/entities/animal).
        self.publish_entity_type_topics = corr_cfg.publish_entity_type_topics
        # Off-by-default: record finalised entities into the persisted
        # state-space memory so the system learns temporal patterns. Pure
        # enrichment (a write to a separate DB); created in start() when on.
        self.state_space_memory_enabled = corr_cfg.state_space_memory_enabled

        # Off-by-default: fold late-arriving detections into the recently-
        # emitted entity for the same acoustic moment instead of spawning a
        # duplicate (cross-classifier-identity §1 "enrich existing event").
        le_cfg = corr_cfg.late_enrichment
        self.late_enrichment_enabled = (
            late_enrichment_enabled
            if late_enrichment_enabled is not None
            else le_cfg.enabled
        )
        self.late_enrichment_ttl_seconds = (
            late_enrichment_ttl_seconds
            if late_enrichment_ttl_seconds is not None
            else le_cfg.ttl_seconds
        )
        self.late_enrichment_max_tracked_roots = (
            late_enrichment_max_tracked_roots
            if late_enrichment_max_tracked_roots is not None
            else le_cfg.max_tracked_roots
        )

        # Ambient-weather context join (the Ecowitt DoD's Scenario 2): when the
        # weather ingestor is on, attach the freshest reading to each emitted
        # entity's context so "do crows visit before a storm?" is answerable
        # from the entities table. DELIBERATELY rides the EXISTING
        # weather.enabled ingestor knob rather than a dedicated correlation
        # flag: without the ingestor there is nothing to attach, and with it
        # on the join is the feature's whole point — one knob, no dead
        # combination. (Documented decision; a correlation-side opt-out would
        # be a new additive+defaulted key if ever needed.) No reading is ever
        # attached when the ingestor is off (default).
        weather_cfg = getattr(self.orpheus_config, "weather", None)
        # `is True`: the real config layer yields a strict bool; anything else
        # (absent section, bare-Mock configs in older tests) means OFF.
        self.weather_enabled = getattr(weather_cfg, "enabled", False) is True
        # A reading older than 2x the poll interval means the ingestor is
        # down/stale — attaching it would claim weather we don't know.
        try:
            self._weather_max_age_seconds = 2.0 * float(
                getattr(weather_cfg, "poll_interval_seconds", 300.0)
            )
        except (TypeError, ValueError):
            self._weather_max_age_seconds = 600.0
        self._weather_db: WeatherDB | None = None
        # (monotonic_read_at, reading, recorded_at) — readings change every
        # poll_interval, so memoize briefly rather than hitting SQLite per
        # entity in a chorus. recorded_at is the ingest-side freshness
        # fallback, fetched only when the reading has no usable timestamp.
        self._weather_cache: tuple[float, WeatherReading | None, str | None] | None = None
        # Monotonic time of the last stale/unprovable-freshness warning —
        # rate-limited so a dead join is visible without log spam per entity.
        # None (not 0.0): time.monotonic() can start near zero at process
        # start, and the FIRST rejection must always warn.
        self._weather_reject_warned_at: float | None = None
        self.entities_weather_tagged = 0

        # Layer 3 auto-discovery worker config — runs periodically, scans
        # recent detections for co-occurring TaxonomyRefs, proposes
        # equivalences above the Jaccard thresholds. See
        # docs/designs/cross-classifier-identity.md §5.
        ad_cfg = corr_cfg.auto_discovery
        self.auto_discovery_enabled = (
            auto_discovery_enabled
            if auto_discovery_enabled is not None
            else ad_cfg.enabled
        )
        self.auto_discovery_interval_seconds = (
            auto_discovery_interval_seconds
            if auto_discovery_interval_seconds is not None
            else ad_cfg.interval_seconds
        )
        self.auto_discovery_lookback_days = (
            auto_discovery_lookback_days
            if auto_discovery_lookback_days is not None
            else ad_cfg.lookback_days
        )
        self.auto_discovery_propose_threshold = ad_cfg.propose_threshold
        self.auto_discovery_accept_threshold = ad_cfg.accept_threshold
        self.auto_discovery_min_cooccurrences = ad_cfg.min_cooccurrences
        self.auto_discovery_cross_namespace_accept_only = (
            ad_cfg.cross_namespace_accept_only
        )

        # Corollary discharge ("echo problem"): tag detections that overlap
        # our own audio playback. Fed by playback events on PLAYBACK_TOPIC.
        # Off by default per the Reversibility Contract: when disabled the
        # agent neither subscribes to PLAYBACK_TOPIC nor recomputes the tag —
        # entities keep the is_self_generated=False that _build_one_entity
        # emits. The filter itself is still constructed (cheap, stateless
        # until fed) so flag-off code paths never null-check it.
        cd_cfg = self.orpheus_config.corollary_discharge
        # `is True`: the real config layer yields a strict bool; anything else
        # (absent section, bare-Mock configs in older tests) means OFF.
        self.corollary_discharge_enabled = getattr(cd_cfg, "enabled", False) is True
        self.corollary_discharge = CorollaryDischargeFilter(
            buffer_seconds=cd_cfg.buffer_seconds
        )

        self.cluster_manager: ClusterManager | None = None
        self.db: DetectionDB | None = None
        self.eq_db: TaxonomyEquivalenceDB | None = None
        self.state_space: StateSpaceMemory | None = None
        self._auto_discovery_task: asyncio.Task | None = None
        # Event loop, captured at start(), so MQTT-thread callbacks can marshal
        # work onto it (the corollary-discharge window buffer is not thread-safe).
        self._loop: asyncio.AbstractEventLoop | None = None

        # Statistics
        self.events_received = 0
        self.events_ignored = 0
        self.entities_emitted = 0
        # Late-arrival enrichments applied (only moves when the flag is on).
        self.entities_enriched = 0
        # State-space memory enrichment counters (only move when the flag is on).
        self.state_space_recorded = 0
        self.state_space_errors = 0
        self.auto_discovery_runs = 0
        self.auto_discovery_proposals = 0
        # Error tracking for the UI's cross-agent error feed.
        self.errors_count = 0
        self.last_error: str | None = None

    async def on_setup(self) -> None:
        """Open the entity DB + equivalence graph (+ optional state-space) and
        build the cluster manager bound to the running loop."""
        setup_logging("orpheus-agent-event-correlator", level="INFO")
        logger.info("Starting Event Correlator Agent", window_seconds=self.window_seconds)

        # Entity persistence + the equivalence graph the auto-discovery writes into.
        self.db = DetectionDB()
        self.eq_db = TaxonomyEquivalenceDB()
        logger.info("Initialized entity database", db_path=str(self.db.db_path))

        # State-space latent memory (off by default) — learns temporal patterns.
        if self.state_space_memory_enabled:
            self.state_space = StateSpaceMemory()
            logger.info("State-space memory enabled")

        # Weather-context join (off unless the ingestor is on). Constructed ONCE:
        # WeatherDB.__init__ runs an ensure-schema write against the shared
        # detections DB — never per-entity (the StorageHistoryDB contention lesson).
        if self.weather_enabled:
            self._weather_db = WeatherDB()
            logger.info(
                "Weather-context join enabled",
                max_age_seconds=self._weather_max_age_seconds,
            )

        loop = asyncio.get_running_loop()
        self._loop = loop
        self.cluster_manager = ClusterManager(
            window_seconds=self.window_seconds,
            max_cluster_duration_seconds=self.max_cluster_duration_seconds,
            on_entity_ready=self._on_entity_ready,
            # Merge observations whose labels denote the same real-world source.
            # The static same_source bridge gives the obvious cross-classifier /
            # cross-modal merges (PANNs Crow ≡ BirdNET American Crow); the learned
            # equivalence graph is the long-tail fallback.
            is_equivalent=lambda a, b: same_source(a, b) or self.eq_db.is_equivalent(a, b),
            enrich_late_arrivals=self.late_enrichment_enabled,
            late_ttl_seconds=self.late_enrichment_ttl_seconds,
            late_max_tracked_roots=self.late_enrichment_max_tracked_roots,
            on_entity_enrich=self._on_entity_enrich,
        )
        self.cluster_manager.set_loop(loop)

    def subscriptions(self) -> list[tuple[str, Any]]:
        # Detection topics from config + our own audio-playback windows (corollary
        # discharge: tag self-generated detections — only when the flag is on;
        # off means no playback subscription and no tagging).
        subs = [
            (topic, self._on_detection_event)
            for topic in self.orpheus_config.correlation.input_topics
        ]
        if self.corollary_discharge_enabled:
            subs.append((PLAYBACK_TOPIC, self._on_playback_event))
        return subs

    def health_payload(self, phase: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        if phase == "startup":
            return {
                "status": "online",
                "window_seconds": self.window_seconds,
                "auto_discovery_enabled": self.auto_discovery_enabled,
                "late_enrichment_enabled": self.late_enrichment_enabled,
                "weather_join_enabled": self.weather_enabled,
                "corollary_discharge_enabled": self.corollary_discharge_enabled,
                "timestamp": now,
                "events_received": self.events_received,
                "entities_emitted": self.entities_emitted,
                "entities_enriched": self.entities_enriched,
                "entities_weather_tagged": self.entities_weather_tagged,
                "state_space_recorded": self.state_space_recorded,
                "state_space_errors": self.state_space_errors,
                "errors_count": self.errors_count,
                "last_error": self.last_error,
                "cluster_expire_errors": self._cluster_expire_errors(),
            }
        if phase == "shutdown":
            return {
                "status": "offline",
                "events_received": self.events_received,
                "entities_emitted": self.entities_emitted,
                "timestamp": now,
            }
        return {
            "status": "online",
            "timestamp": now,
            "events_received": self.events_received,
            "entities_emitted": self.entities_emitted,
            "entities_enriched": self.entities_enriched,
            "entities_weather_tagged": self.entities_weather_tagged,
            "state_space_recorded": self.state_space_recorded,
            "state_space_errors": self.state_space_errors,
            "errors_count": self.errors_count,
            "last_error": self.last_error,
            "cluster_expire_errors": self._cluster_expire_errors(),
        }


    def _cluster_expire_errors(self) -> int:
        """Expiry-path failures counted by the ClusterManager (0 before it exists)."""
        manager = getattr(self, "cluster_manager", None)
        return getattr(manager, "expire_errors", 0) if manager is not None else 0

    async def on_started(self) -> None:
        # Layer 3 auto-discovery worker (off by default).
        if self.auto_discovery_enabled:
            self._auto_discovery_task = asyncio.create_task(self._run_auto_discovery_loop())

    async def _run_auto_discovery_loop(self) -> None:
        """Periodic background task: scan for co-occurring TaxonomyRefs and
        propose equivalences. Runs every ``auto_discovery_interval_seconds``.

        Safe to cancel — between runs it's just sleeping; mid-run cancellation
        is handled by asyncio at the next await point in discover_equivalences
        (which is purely synchronous DB work, so cancellation is clean).
        """
        logger.info(
            "Auto-discovery worker started",
            interval_seconds=self.auto_discovery_interval_seconds,
            lookback_days=self.auto_discovery_lookback_days,
        )
        try:
            while True:
                # First sleep, then run — lets the system stabilise after
                # startup before scanning. Avoids hammering the DB during
                # boot-storms or migration windows.
                await asyncio.sleep(self.auto_discovery_interval_seconds)
                await self._run_auto_discovery_once()
        except asyncio.CancelledError:
            logger.info(
                "Auto-discovery worker stopped",
                runs=self.auto_discovery_runs,
                proposals=self.auto_discovery_proposals,
            )
            raise

    async def _run_auto_discovery_once(self) -> None:
        """One scan pass. Logs proposals; equivalences are written by
        ``discover_equivalences`` directly into ``self.eq_db``."""
        if self.db is None or self.eq_db is None:
            return
        try:
            # Pure-Python DB work — run in a thread to keep the event loop
            # responsive to MQTT callbacks during the scan.
            proposals = await asyncio.to_thread(
                discover_equivalences,
                self.db,
                self.eq_db,
                lookback_days=self.auto_discovery_lookback_days,
                propose_threshold=self.auto_discovery_propose_threshold,
                accept_threshold=self.auto_discovery_accept_threshold,
                min_cooccurrences=self.auto_discovery_min_cooccurrences,
                cross_namespace_accept_only=(
                    self.auto_discovery_cross_namespace_accept_only
                ),
            )
        except Exception as exc:
            self.errors_count += 1
            self.last_error = f"{type(exc).__name__}: {str(exc)[:200]}"
            logger.exception("Auto-discovery run failed; continuing")
            return

        self.auto_discovery_runs += 1
        recorded = [p for p in proposals if p["action"] == "recorded"]
        promoted = [p for p in proposals if p["action"] == "promoted"]
        # Both "recorded" (new) and "promoted" (pending → accepted on
        # stronger evidence) represent real new state in the equivalence
        # table — count both toward lifetime_proposals so ops can
        # actually see auto-discovery making progress over time.
        self.auto_discovery_proposals += len(recorded) + len(promoted)

        scan_summary = {
            "status": "ok",
            "ran_at": datetime.now(timezone.utc).isoformat(),
            "total_proposals": len(proposals),
            "recorded": len(recorded),
            "promoted": len(promoted),
            "skipped_existing": sum(
                1 for p in proposals if p["action"] == "skipped_existing"
            ),
            "skipped_blocked": sum(
                1 for p in proposals if p["action"] == "skipped_blocked"
            ),
            "lifetime_runs": self.auto_discovery_runs,
            "lifetime_proposals": self.auto_discovery_proposals,
        }

        # Publish health event so the UI (and ops monitoring) can show
        # auto-discovery liveness without polling the DB.
        if self.bus is not None:
            try:
                self.bus.publish(
                    "orpheus/system/auto-discovery/health", scan_summary
                )
            except Exception:  # pylint: disable=broad-except
                logger.exception("Failed to publish auto-discovery health")
            # §11 Phase 1b: dual-write the scan summary to the operational KV plane
            # (key "auto-discovery") IN ADDITION to the bus publish, when enabled. The
            # scan callback (hours apart) is the writer — NOT folded into the 30s
            # heartbeat. None ⇒ no-op (default; bus publish unchanged).
            op_health = build_operational_health(self.bus, self.orpheus_config)
            if op_health is not None:
                try:
                    op_health.publish("auto-discovery", scan_summary, phase="scan")
                except Exception:  # pylint: disable=broad-except
                    logger.exception("Failed to dual-write auto-discovery health to KV")

        if proposals:
            logger.info("Auto-discovery scan complete", **scan_summary)
            for p in recorded + promoted:
                logger.info(
                    "Equivalence proposed" if p["action"] == "recorded"
                    else "Equivalence promoted",
                    a=f"{p['a']['namespace']}:{p['a']['id']}",
                    b=f"{p['b']['namespace']}:{p['b']['id']}",
                    jaccard=f"{p['jaccard']:.3f}",
                    status=p["status"],
                    cooccurrence=p["cooccurrence"],
                )

    async def on_stopping(self) -> None:
        """Pre-disconnect: stop the discovery worker, then FLUSH open clusters
        (which publishes their entities) while the bus is still connected — so the
        most-recent cluster isn't lost across a restart."""
        if self._auto_discovery_task is not None:
            self._auto_discovery_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._auto_discovery_task
            self._auto_discovery_task = None

        # Route through _on_entity_ready so the open cluster is both persisted AND
        # published (flush_all alone returns events without firing the handler).
        if self.cluster_manager is not None:
            for entity_event in self.cluster_manager.flush_all():
                self._on_entity_ready(entity_event)

    async def on_shutdown(self) -> None:
        logger.info(
            "Agent shutdown complete",
            events_received=self.events_received,
            events_ignored=self.events_ignored,
            entities_emitted=self.entities_emitted,
        )

    def _on_detection_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Handle incoming detection event from MQTT."""
        self.events_received += 1

        logger.info(
            "Received detection event",
            topic=topic,
            event_id=payload.get("event_id"),
            detection_type=payload.get("detection_type"),
        )

        # Parse the detection
        try:
            detection = Detection.model_validate(payload)
        except ValidationError:
            # Try from_dict for backward compat
            try:
                detection = Detection.from_dict(payload)
            except Exception as e:
                logger.warning(
                    "Failed to parse detection event",
                    topic=topic,
                    event_id=payload.get("event_id"),
                    error=e,
                    payload=payload,
                )
                self.events_ignored += 1
                return

        # Filter by detection type
        if detection.detection_type in IGNORED_DETECTION_TYPES:
            self.events_ignored += 1
            return

        if detection.detection_type not in PROCESSED_DETECTION_TYPES:
            self.events_ignored += 1
            return

        # Extract context as dict for storage
        context_dict = None
        if detection.context is not None:
            context_dict = detection.context.model_dump(mode="json")

        # Extract sensor_id
        sensor_id = ""
        if detection.context is not None:
            sensor_id = detection.context.sensor_id

        # Unpack observations, passing raw payload for legacy schema support
        try:
            observations = self._unpack_observations(
                detection,
                sensor_id,
                context_dict,
                raw_payload=payload,
            )
        except Exception as e:
            logger.error(
                "Error unpacking observations from detection",
                event_id=detection.event_id,
                error=str(e),
                exc_info=True,
            )
            self.events_ignored += 1
            return

        for obs in observations:
            if self.cluster_manager is not None:
                self.cluster_manager.process_observation(obs)

    def _unpack_observations(
        self,
        detection: Detection,
        sensor_id: str,
        context_dict: dict[str, Any] | None,
        raw_payload: dict[str, Any] | None = None,
    ) -> list[Observation]:
        """Unpack a Detection into individual Observations.

        Checks for sub-detections in two places to support both V2 and legacy
        schemas:
          1. ``detection.metadata["detections"]`` — V2 standard
          2. ``raw_payload["detections"]`` — Legacy BirdNET (root-level list)

        If neither contains sub-detections, the top-level species_code is used
        as a single Observation.
        """
        observations = []

        # V2 schema: detections nested under metadata
        sub_detections = detection.metadata.get("detections")

        # Legacy BirdNET schema: detections at root level of the raw payload
        if (not sub_detections or not isinstance(sub_detections, list)) and raw_payload:
            legacy = raw_payload.get("detections")
            if legacy and isinstance(legacy, list):
                sub_detections = legacy

        if sub_detections and isinstance(sub_detections, list):
            # BirdNET / multi-detection style: iterate sub-detections
            for sub in sub_detections:
                species_code = sub.get("species_code", "")
                common_name = sub.get("species_common", "")
                confidence = float(sub.get("confidence", 0.0))

                if not species_code:
                    continue

                # ADR 0011: pass per-sub-detection windows through as
                # interval dicts. Fall back to the parent Detection's
                # intervals when the sub-dict has none.
                sub_intervals = self._extract_sub_intervals(sub) or self._extract_intervals(
                    detection
                )

                obs = Observation(
                    species_code=species_code,
                    common_name=common_name,
                    confidence=confidence,
                    event_id=detection.event_id,
                    source_event_id=detection.source_event_id,
                    root_event_id=detection.root_event_id,
                    sensor_id=sensor_id,
                    clip_path=detection.audio_clip_path,
                    context=context_dict,
                    intervals=sub_intervals,
                    taxonomy=self._extract_taxonomy_for_sub(sub, detection),
                    detection_type=detection.detection_type,
                    # Pass the source detection's timestamp so the
                    # Entity's event_signature spans reflect WHEN the
                    # event happened, not when this agent got around to
                    # processing it. Aligns with /api/correlator/health
                    # which uses detection timestamps.
                    timestamp=detection.timestamp,
                )
                observations.append(obs)
        # Single detection style (e.g., crow.analyzed, audio.classified)
        elif detection.species_code:
            obs = Observation(
                species_code=detection.species_code,
                common_name=detection.species_common or "",
                confidence=float(detection.confidence or 0.0),
                event_id=detection.event_id,
                source_event_id=detection.source_event_id,
                root_event_id=detection.root_event_id,
                sensor_id=sensor_id,
                clip_path=detection.audio_clip_path,
                context=context_dict,
                intervals=self._extract_intervals(detection),
                taxonomy=(
                    detection.taxonomy.model_dump(mode="json")
                    if detection.taxonomy
                    else None
                ),
                detection_type=detection.detection_type,
                timestamp=detection.timestamp,
            )
            observations.append(obs)

        return observations

    @staticmethod
    def _extract_taxonomy_for_sub(
        sub: dict[str, Any], detection: Detection
    ) -> dict[str, Any] | None:
        """Extract a per-sub-detection TaxonomyRef as a serialised dict.

        BirdNET-style payloads carry the species-level scientific name in
        the sub-detection (``species_scientific``). Build an IOC
        TaxonomyRef from it. Fall back to the parent Detection's
        ``taxonomy`` field if the sub-dict doesn't have a scientific name
        (legacy payloads).

        Returns None if no taxonomy info is available — Layer 3 falls
        back to free-form species_code on equivalence lookup.
        """
        scientific = sub.get("species_scientific")
        if scientific:
            common = sub.get("species_common")
            return {
                "namespace": "ioc",
                "id": scientific,
                "common_name": common or None,
            }
        if detection.taxonomy is not None:
            return detection.taxonomy.model_dump(mode="json")
        return None

    @staticmethod
    def _extract_intervals(detection: Detection) -> list[dict[str, Any]] | None:
        """Extract intervals from a Detection model as a list of plain dicts.

        Returns ``None`` if the Detection has no localisation data — preserves
        the "no data" signal end-to-end through to the EntityEvent evidence.
        """
        if detection.intervals is None:
            return None
        return [iv.model_dump(mode="json") for iv in detection.intervals]

    @staticmethod
    def _extract_sub_intervals(
        sub: dict[str, Any],
    ) -> list[dict[str, Any]] | None:
        """Extract per-sub-detection intervals from a BirdNET-style sub-dict.

        BirdNET embeds per-window data under ``windows: [...]`` in each
        sub-detection (added in the bird-detection commit per ADR 0011 §4.5).
        Convert those to interval dicts. Returns ``None`` when the sub-dict
        has no windows.
        """
        windows = sub.get("windows")
        if not windows or not isinstance(windows, list):
            return None
        intervals: list[dict[str, Any]] = []
        for w in windows:
            if "start_time" not in w or "end_time" not in w:
                continue
            intervals.append(
                {
                    "start_seconds": float(w["start_time"]),
                    "end_seconds": float(w["end_time"]),
                    "confidence": (
                        float(w["confidence"]) if w.get("confidence") is not None else None
                    ),
                }
            )
        return intervals or None

    def _on_playback_event(self, _topic: str, payload: dict[str, Any]) -> None:
        """Register an audio-playback window for corollary discharge.

        Runs on the MQTT network thread, so marshal the window write onto the
        event loop (mirroring ``cluster_manager.process_observation``): the
        window deque is read/evicted by the timer-driven ``_on_entity_ready`` on
        the loop thread, and the deque is not thread-safe.
        """
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.corollary_discharge.register_from_event, payload)
        else:
            self.corollary_discharge.register_from_event(payload)

    @staticmethod
    def _parse_weather_ts(value: str | None) -> datetime | None:
        """Best-effort ISO parse to a UTC-aware datetime; None on empty or
        unparseable input (never raises — freshness falls back instead)."""
        if not value:
            return None
        try:
            ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


    def _warn_weather_rejected(self, reason: str, **kw: Any) -> None:
        """Rate-limited (5 min) warning when a reading is rejected — makes a
        dead weather join visible on Diagnostics without per-entity log spam."""
        now = time.monotonic()
        last = self._weather_reject_warned_at
        if last is None or now - last >= 300.0:
            self._weather_reject_warned_at = now
            logger.warning(
                "Weather reading rejected; entities emitted without weather",
                reason=reason,
                **kw,
            )

    def _ambient_weather(self) -> dict[str, Any] | None:
        """The freshest weather reading as a context-ready dict, or None.

        None when the join is off, no reading exists yet, the latest reading is
        stale (ingestor down — attaching it would claim weather we don't know),
        or the read fails (best-effort: weather must never block an entity).
        Freshness keys on the provider-reported ``reading.timestamp`` when it
        parses, else on the ingest-side ``recorded_at`` (partial readings have
        an empty timestamp by contract). Rejections warn (rate-limited).
        Memoized for 60s — readings only change every poll interval."""
        if self._weather_db is None:
            return None
        now = time.monotonic()
        if self._weather_cache is not None and (now - self._weather_cache[0]) < 60.0:
            _, reading, recorded_at = self._weather_cache
        else:
            try:
                latest = self._weather_db.latest_row()
            except Exception as e:
                logger.warning("Weather read failed; entity emitted without weather", error=str(e))
                latest = None
            reading = latest[0] if latest is not None else None
            recorded_at = latest[1] if latest is not None else None
            self._weather_cache = (now, reading, recorded_at)
        if reading is None:
            return None
        ts = self._parse_weather_ts(reading.timestamp) or self._parse_weather_ts(recorded_at)
        if ts is None:
            # Neither the provider timestamp nor the ingest stamp is usable —
            # can't prove freshness, so don't claim weather we don't know.
            self._warn_weather_rejected("no provable freshness (timestamp + recorded_at unusable)")
            return None
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        if age > self._weather_max_age_seconds:
            self._warn_weather_rejected(
                "stale reading (ingestor down?)",
                age_seconds=round(age, 1),
                max_age_seconds=self._weather_max_age_seconds,
            )
            return None
        return reading.model_dump(mode="json")

    def _on_entity_ready(self, entity_event: dict[str, Any]) -> None:
        """Callback invoked when a cluster expires and an EntityEvent is ready."""
        # Corollary discharge: tag (don't drop) entities that overlapped our own
        # audio playback, so the system doesn't count hearing itself as wildlife.
        # Flag off (the default): the verdict is never recomputed — the field
        # stays exactly as _build_one_entity emitted it (False; setdefault only
        # backfills the key for hand-built dicts), and no playback subscription
        # exists to feed the filter anyway.
        if self.corollary_discharge_enabled:
            entity_event["is_self_generated"] = self.corollary_discharge.is_self_generated(
                entity_event
            )
        else:
            entity_event.setdefault("is_self_generated", False)
        # Ambient-weather join (Ecowitt Scenario 2): additive context key; old
        # binaries drop it via SpatiotemporalContext's extra="ignore".
        weather = self._ambient_weather()
        if weather is not None:
            entity_event.setdefault("context", {})["weather"] = weather
            self.entities_weather_tagged += 1
        if entity_event["is_self_generated"]:
            logger.info(
                "Tagged entity as self-generated (corollary discharge)",
                entity_id=entity_event.get("entity_id"),
            )
        self._persist_entity(entity_event)
        self._record_state_space(entity_event)
        self._publish_entity(entity_event)

    def _on_entity_enrich(self, enriched: dict[str, Any], obs: Observation) -> bool:
        """Persist + publish a late-arrival enrichment of an already-emitted
        entity (the I/O half; the merge already happened in cluster_manager).

        Deliberately NOT the create pipeline: no corollary-discharge re-check
        (the emit-time verdict is preserved — a widened span must not flip
        wildlife to self-generated), no state-space record (the acoustic moment
        was counted at first emit), no legacy/typed create-topic publish (create
        consumers must not double-count) — updates go out on
        ENTITY_UPDATED_TOPIC only, and the UI reads the updated SQLite row.

        Returns True only when the update was actually persisted. False on a
        missing row (aged out of the DB) AND on any persist error: in both
        cases the caller drops the (possibly merged, now-discarded) in-memory
        record and falls back to normal clustering, so the observation
        survives as a duplicate entity — exactly the flag-off baseline, and
        strictly safer than consuming it while the DB kept the old row (the
        merged in-memory record would also block a QoS-1 redelivery via the
        dedup check, making the loss unrepairable)."""
        try:
            entity = Entity.from_entity_event(enriched)
            persisted = self.db is not None and self.db.update_entity(entity)
        except Exception as e:
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning(
                "Failed to persist entity enrichment; clustering instead",
                entity_id=enriched.get("entity_id"),
                error=str(e),
            )
            return False
        if not persisted:
            logger.warning(
                "Late-arrival target entity missing from DB; clustering instead",
                entity_id=enriched.get("entity_id"),
            )
            return False
        self.entities_enriched += 1
        logger.info(
            "Enriched recently-emitted entity with late arrival",
            entity_id=enriched.get("entity_id"),
            late_event_id=obs.event_id,
            detection_type=obs.detection_type,
            evidence_count=len(enriched.get("evidence", [])),
        )
        # Publish is best-effort AFTER the row is safely updated — a bus hiccup
        # must not trigger the clustering fallback (that would duplicate an
        # entity whose update already persisted; the UI reads the row anyway).
        try:
            if self.bus is not None:
                self.bus.publish(ENTITY_UPDATED_TOPIC, enriched)
        except Exception as e:
            self.errors_count += 1
            self.last_error = f"{type(e).__name__}: {str(e)[:200]}"
            logger.warning(
                "Failed to publish entity update (row persisted)",
                entity_id=enriched.get("entity_id"),
                error=str(e),
            )
        return True

    def _record_state_space(self, entity_event: dict[str, Any]) -> None:
        """Record a finalised entity into the temporal state-space memory.

        No-op unless enabled. Self-generated entities (our own audio playback,
        flagged by corollary discharge) are skipped — learning from them would
        teach the system that animals appear whenever it plays their calls."""
        if self.state_space is None or entity_event.get("is_self_generated"):
            return
        try:
            self.state_space.record_event(entity_event)
            self.state_space_recorded += 1
        except Exception as e:
            self.state_space_errors += 1
            logger.warning(
                "Failed to record entity into state-space memory",
                entity_id=entity_event.get("entity_id"),
                error=str(e),
            )

    def _persist_entity(self, entity_event: dict[str, Any]) -> None:
        """Save an EntityEvent to the local SQLite database."""
        if self.db is None:
            return
        try:
            entity = Entity.from_entity_event(entity_event)
            self.db.save_entity(entity)
            logger.debug(
                "Persisted entity to DB",
                entity_id=entity.entity_id,
            )
        except Exception as e:
            logger.warning(
                "Failed to persist entity to DB",
                entity_id=entity_event.get("entity_id"),
                error=str(e),
            )

    def _publish_entity(self, entity_event: dict[str, Any]) -> None:
        """Publish an EntityEvent to MQTT."""
        self.entities_emitted += 1

        logger.info(
            "Publishing EntityEvent",
            entity_id=entity_event["entity_id"],
            species_code=entity_event["species_code"],
            common_name=entity_event["common_name"],
            confidence=entity_event["confidence"],
            evidence_count=len(entity_event["evidence"]),
        )

        if self.bus is not None:
            # Legacy topic — ALWAYS published (the backward-compat anchor).
            self.bus.publish(
                "orpheus/entities/animal",
                entity_event,
            )
            # Additive entity_type-routed topic, off by default. The legacy
            # topic above is never removed, so existing consumers are unaffected.
            entity_type = entity_event.get("entity_type")
            if entity_type and self.publish_entity_type_topics:
                try:
                    topic = load_taxonomy().topic_for(entity_type)
                    self.bus.publish(topic, entity_event)
                except Exception:
                    logger.exception(
                        "Failed to publish entity_type-routed topic",
                        entity_type=entity_type,
                    )


def main() -> None:
    """Main entry point."""
    agent = EventCorrelatorAgent()
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
