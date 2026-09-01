"""Cluster manager for temporal correlation of detection events.

Layer 2 of cross-classifier identity
(``docs/designs/cross-classifier-identity.md`` §4): clusters all
Observations within ``window_seconds`` of each other into a single
TemporalCluster regardless of species. One Entity = one acoustic moment,
with all classifier opinions (heterogeneous species) as evidence.

Cluster key is the implicit "currently-open cluster" (at most one open
at any time). Multi-mic, multi-species, multi-classifier all merge
naturally because they're temporally co-located.

The Entity's ``species`` / ``common_name`` fields are LEGACY display
labels populated from the highest-confidence observation. The
authoritative species info lives in ``evidence[i]``: each piece of
evidence carries its own native species_code/common_name AND a
canonical TaxonomyRef (where the source classifier provided one).
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from orpheus_common.detection import TaxonomyRef
from orpheus_common.detection.entity_taxonomy import derive_entity_type
from orpheus_common.events import EntityEvent
from orpheus_common.logging import get_logger

from orpheus_agent_event_correlator.corollary_discharge import _utc

logger = get_logger(__name__)


class Observation:
    """A single observation extracted from a Detection event.

    Layer 2 (cross-classifier identity §4): carries per-evidence taxonomy
    + detection_type so the emitted Entity preserves what each classifier
    actually said. The cluster key never touches species — Observations
    merge by time-window only.
    """

    def __init__(
        self,
        species_code: str,
        common_name: str,
        confidence: float,
        event_id: str,
        source_event_id: str | None,
        sensor_id: str,
        clip_path: str | None,
        context: dict[str, Any] | None,
        intervals: list[dict[str, Any]] | None = None,
        taxonomy: dict[str, Any] | None = None,
        detection_type: str = "",
        root_event_id: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        self.species_code = species_code
        self.common_name = common_name
        self.confidence = confidence
        self.event_id = event_id
        self.source_event_id = source_event_id
        # Chain root — the audio.motion event_id this observation traces
        # back to. Layer 1.5 (see cross-classifier-identity §1.1). The
        # Entity's event_signature collects these to record which physical
        # events the cluster combined.
        self.root_event_id = root_event_id
        self.sensor_id = sensor_id
        self.clip_path = clip_path
        self.context = context
        # Prefer the SOURCE Detection's timestamp (when the acoustic
        # event actually happened) over the time this Observation was
        # constructed (when the agent got around to processing). The
        # latter is "processing time" and creates a misleading
        # divergence from /api/correlator/health (which uses the
        # detection's own timestamp). Callers passing the parent
        # Detection.timestamp get the correct semantics; callers that
        # don't pass anything fall back to now-UTC for back-compat with
        # legacy code paths.
        # Normalized to aware-UTC: cluster time math (min/max over mixed
        # observations) raises on a naive-vs-aware mix, and producers are not
        # trusted to always send an offset.
        self.timestamp = (
            _utc(timestamp) if timestamp is not None else datetime.now(timezone.utc)
        )
        self.intervals = intervals
        # ``taxonomy`` is the serialised TaxonomyRef dict from the source
        # Detection. May be None for classifiers that don't make species
        # claims (e.g. crow-tools, see design doc §3).
        self.taxonomy = taxonomy
        # Which Orpheus detection_type emitted this observation. Lets
        # consumers tell BirdNET evidence apart from PANNs evidence even
        # when their TaxonomyRefs are equivalent under Layer 3.
        self.detection_type = detection_type


def intervals_overlap(a: Observation, b: Observation, tol: float = 0.5) -> bool:
    """Do two observations overlap in time within the clip?

    Co-occurrence is NOT identity, but temporal *separation* is a strong
    DIS-qualifier: a loon at 13.5-16.5 s and an insect at 0-9.6 s in the
    same clip are clearly different sources. Intervals are clip-relative
    (ADR 0011), so the offsets only share a t=0 origin WITHIN ONE CLIP
    (chain root). A single time-window cluster legitimately holds
    observations from different roots (different mics/triggers, each clip
    with its own t=0); comparing their offsets as if aligned would both
    false-split (the same crow at 0-3 s of clip A and 13-16 s of clip B) and
    false-merge. So only compare offsets when the two observations share a
    clip origin; across roots, fall back to co-location (absolute-time
    mapping is the future refinement — see the design doc).

    Missing interval data, or cross-clip observations → return True (can't
    disprove co-location; don't over-split legacy/interval-less or
    independently-clocked observations).
    """
    ia, ib = a.intervals, b.intervals
    if not ia or not ib:
        return True
    # Clip-relative offsets are only comparable within one clip. Key on the
    # chain root (mirrors build_entity_event's ``root_event_id or
    # source_event_id``); across roots the offsets share no origin.
    if (a.root_event_id or a.source_event_id) != (b.root_event_id or b.source_event_id):
        return True
    for x in ia:
        for y in ib:
            xs, xe = float(x.get("start_seconds", 0)), float(x.get("end_seconds", 0))
            ys, ye = float(y.get("start_seconds", 0)), float(y.get("end_seconds", 0))
            if (xs - tol) <= ye and (ys - tol) <= xe:
                return True
    return False


def label_compatible(
    a: Observation, b: Observation, is_equivalent: Callable[[Any, Any], bool] | None = None
) -> bool:
    """Are two observations plausibly the SAME animal/source?

    True when they share a species_code, a common_name, an exact
    taxonomy ref, OR a Layer-3 equivalence links their taxonomies
    (BirdNET ``Crow`` ≡ PANNs ``Crow``). Cross-modal-ready: a video
    "American Robin" and an audio "American Robin" match on name/taxon
    with nothing audio-specific.
    """
    if a.species_code and a.species_code.lower() == (b.species_code or "").lower():
        return True
    if a.common_name and a.common_name.lower() == (b.common_name or "").lower():
        return True
    ta, tb = a.taxonomy or {}, b.taxonomy or {}
    if ta.get("id") and ta.get("namespace") and ta == tb:
        return True
    if is_equivalent and ta.get("id") and tb.get("id"):
        try:
            ra = TaxonomyRef(namespace=ta["namespace"], id=ta["id"])
            rb = TaxonomyRef(namespace=tb["namespace"], id=tb["id"])
            if is_equivalent(ra, rb):
                return True
        except Exception:  # noqa: S110 - equivalence lookup is best-effort
            pass
    return False


def observations_same_source(
    a: Observation, b: Observation, is_equivalent: Callable[[Any, Any], bool] | None = None
) -> bool:
    """The ONE same-source identity predicate: two observations are the same
    source iff they overlap in time AND their labels are compatible.
    Co-occurring-but-different and same-label-but-disjoint-in-time both
    correctly stay separate. Shared by in-window clustering
    (``TemporalCluster._same_source``) and late-arrival enrichment
    (``ClusterManager._try_enrich``) so the two paths can never drift."""
    return intervals_overlap(a, b) and label_compatible(a, b, is_equivalent)


class TemporalCluster:
    """A cluster of observations within a single time window.

    Species-agnostic — observations of different species, from different
    classifiers, from different mics all live in one cluster as long as
    they're within ``window_seconds`` of each other.
    """

    def __init__(
        self,
        window_seconds: float = 3.0,
        is_equivalent: Callable[[Any, Any], bool] | None = None,
    ) -> None:
        self.window_seconds = window_seconds
        self.observations: list[Observation] = []
        self.created_at = datetime.now(timezone.utc)
        self.last_updated = datetime.now(timezone.utc)
        self._timer_handle: asyncio.TimerHandle | None = None
        # Optional callable(TaxonomyRef, TaxonomyRef) -> bool used to merge
        # cross-classifier labels a Layer-3 equivalence has linked (e.g.
        # BirdNET ioc:Corvus brachyrhynchos ≡ PANNs audioset:/m/04s8yn).
        # None → identity is name/code/taxonomy match only.
        self._is_equivalent = is_equivalent

    def add_observation(self, obs: Observation) -> None:
        """Add an observation and refresh the last-updated timestamp.

        Timer rescheduling happens in ClusterManager._schedule_expiration —
        this method just bookkeeps the cluster's state.
        """
        self.observations.append(obs)
        self.last_updated = datetime.now(timezone.utc)

    @property
    def max_confidence(self) -> float:
        """Highest confidence across all observations in the cluster."""
        if not self.observations:
            return 0.0
        return max(obs.confidence for obs in self.observations)

    @property
    def display_observation(self) -> Observation | None:
        """The observation used to populate Entity's LEGACY display
        fields (species, common_name). Picked as the highest-confidence
        observation that has a non-empty species_code.

        Not authoritative — the full evidence list is the source of
        truth. This just gives table/list views something to show.
        """
        candidates = [
            obs for obs in self.observations if obs.species_code
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda o: o.confidence)

    @staticmethod
    def _intervals_overlap(a: Observation, b: Observation, tol: float = 0.5) -> bool:
        """Delegates to the module-level :func:`intervals_overlap` (lifted so
        late-arrival enrichment shares the identical predicate)."""
        return intervals_overlap(a, b, tol)

    def _label_compatible(self, a: Observation, b: Observation) -> bool:
        """Delegates to the module-level :func:`label_compatible` with this
        cluster's equivalence checker."""
        return label_compatible(a, b, self._is_equivalent)

    def _same_source(self, a: Observation, b: Observation) -> bool:
        """Two observations are the same source iff they overlap in time
        AND their labels are compatible. Co-occurring-but-different and
        same-label-but-disjoint-in-time both correctly stay separate.
        Delegates to :func:`observations_same_source`."""
        return observations_same_source(a, b, self._is_equivalent)

    def _group_by_source(self) -> list[list[Observation]]:
        """Partition observations into same-source groups (connected
        components under ``_same_source``), preserving first-seen order."""
        obs = self.observations
        n = len(obs)
        parent = list(range(n))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if self._same_source(obs[i], obs[j]):
                    parent[find(i)] = find(j)

        groups: dict[int, list[Observation]] = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(obs[i])
        # Order groups by first appearance for deterministic output.
        seen: dict[int, int] = {}
        for i in range(n):
            r = find(i)
            if r not in seen:
                seen[r] = len(seen)
        return [g for _, g in sorted(groups.items(), key=lambda kv: seen[kv[0]])]

    @staticmethod
    def _group_display(observations: list[Observation]) -> Observation | None:
        """Highest-confidence observation in a group that has a species
        code — used for the group's display label."""
        candidates = [o for o in observations if o.species_code]
        if not candidates:
            return None
        return max(candidates, key=lambda o: o.confidence)

    def build_entity_events(self) -> list[dict[str, Any]]:
        """Build one EntityEvent per SAME-SOURCE group in this cluster.

        A 30 s clip that caught a cricket, a nuthatch and a loon yields
        three Entities — each with only its own evidence. The other groups
        in the same window are attached as ``also_detected`` context so
        nothing is hidden ("also detected at this time"), without pretending
        they're evidence for this Entity's label.
        """
        groups = self._group_by_source()

        # One-line summary of every group, for cross-referencing as the
        # "also detected at this time" context on each sibling Entity.
        summaries: list[dict[str, Any]] = []
        for g in groups:
            disp = self._group_display(g)
            summaries.append(
                {
                    "species_code": disp.species_code if disp else "",
                    "species_common": disp.common_name if disp else "",
                    "confidence": max((o.confidence for o in g), default=0.0),
                    "detection_type": disp.detection_type if disp else "",
                }
            )

        events: list[dict[str, Any]] = []
        for idx, g in enumerate(groups):
            also = [s for j, s in enumerate(summaries) if j != idx]
            events.append(self._build_one_entity(g, also))
        return events

    def build_entity_event(self) -> dict[str, Any] | None:
        """Back-compat: the first same-source Entity, or None if empty.

        New code should use ``build_entity_events()`` — a cluster can now
        produce multiple Entities.
        """
        events = self.build_entity_events()
        return events[0] if events else None

    def _build_one_entity(
        self, observations: list[Observation], also_detected: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Build a single Entity from one same-source group of observations."""
        lats: list[float] = []
        lons: list[float] = []
        sensor_ids: list[str] = []
        source_ids: list[str] = []
        timestamps: list[datetime] = []
        evidence: list[dict[str, Any]] = []

        for obs in observations:
            if obs.context:
                lat = obs.context.get("lat")
                lon = obs.context.get("lon")
                if lat is not None:
                    lats.append(lat)
                if lon is not None:
                    lons.append(lon)
            # Distinct sensors that observed THIS source (the honest
            # "# sensors" — mics now, "+1 camera" once video lands).
            if obs.sensor_id and obs.sensor_id not in sensor_ids:
                sensor_ids.append(obs.sensor_id)
            # Chain root (audio.motion event) — prefer root_event_id.
            root = obs.root_event_id or obs.source_event_id
            if root and root not in source_ids:
                source_ids.append(root)
            timestamps.append(obs.timestamp)
            evidence.append(
                {
                    "event_id": obs.event_id,
                    "source_event_id": obs.source_event_id,
                    "sensor_id": obs.sensor_id,
                    "clip_path": obs.clip_path,
                    "confidence": obs.confidence,
                    "intervals": obs.intervals,
                    "species_code": obs.species_code,
                    "species_common": obs.common_name,
                    "taxonomy": obs.taxonomy,
                    "detection_type": obs.detection_type,
                }
            )

        context: dict[str, Any] = {}
        if lats:
            context["lat"] = sum(lats) / len(lats)
        if lons:
            context["lon"] = sum(lons) / len(lons)
        context["timestamp"] = datetime.now(timezone.utc).isoformat()

        display = self._group_display(observations)
        start = min(timestamps) if timestamps else self.created_at
        end = max(timestamps) if timestamps else self.last_updated

        # Coarse entity_type, derived from the SAME display observation that sets
        # species_code (so the two stay consistent). Nullable — unresolvable
        # detections leave it None. See entity_taxonomy.derive_entity_type.
        entity_type = None
        if display is not None:
            entity_type = derive_entity_type(
                taxonomy=display.taxonomy,
                species_code=display.species_code,
                common_name=display.common_name,
                detection_type=display.detection_type,
            )

        # Build through the typed EntityEvent so the model is the single source
        # of the wire shape (additive superset of the legacy emit dict). The
        # agent still overrides is_self_generated in _on_entity_ready.
        return EntityEvent.from_dict(
            {
                "entity_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "species_code": display.species_code if display else "",
                "common_name": display.common_name if display else "",
                "confidence": max((o.confidence for o in observations), default=0.0),
                "entity_type": entity_type,
                "context": context,
                "evidence": evidence,
                # Co-occurring OTHER sources in the same window — context, not
                # evidence for this Entity's label. Also nested in
                # event_signature so it survives DB persistence (JSON) with no
                # schema change.
                "also_detected": also_detected,
                "event_signature": {
                    "audio_motion_source_ids": source_ids,
                    "sensor_ids": sensor_ids,
                    "start_time": start.isoformat(),
                    "end_time": end.isoformat(),
                    "also_detected": also_detected,
                },
                "is_self_generated": False,
            }
        ).to_dict()


@dataclass
class _Recent:
    """One recently-emitted entity, enrichable until ``expires_at``.

    ``entity_event`` is the FULL post-``on_entity_ready`` emit-shape dict (the
    same object the agent published — so it carries the authoritative
    ``is_self_generated``, and one in-place enrichment is visible under every
    root it's registered against). ``roots`` lists every map key holding this
    record, for O(roots) removal."""

    entity_event: dict[str, Any]
    expires_at: float  # time.monotonic() deadline; absolute from first emit
    roots: list[str] = field(default_factory=list)


def _evidence_to_observation(ev: dict[str, Any], root_key: str) -> Observation:
    """Adapt one persisted evidence dict back into an Observation so the
    late-arrival gate can run the REAL same-source predicate against every
    piece of evidence (not just the display label).

    Clip-origin handling: evidence dicts don't persist their chain root, only
    ``source_event_id``. We pin ``root_event_id=root_key`` ONLY when the
    evidence provably originates from the lookup root (its source IS the
    root — the direct audio.motion children), so intervals are compared as
    same-clip. For anything else (chained evidence like crow.analyzed, or a
    multi-root entity's other-clip evidence) the adapter keeps the evidence's
    own origin, making :func:`intervals_overlap` take its cross-root fallback
    (True) — exactly the conservative fallback clustering applies when clip
    origins differ. Pinning unconditionally would numerically compare
    clip-A-relative offsets against clip-B observations as if they shared a
    t=0 origin and spuriously reject genuine same-source late arrivals."""
    origin = ev.get("source_event_id")
    return Observation(
        species_code=ev.get("species_code") or "",
        common_name=ev.get("species_common") or "",
        confidence=float(ev.get("confidence") or 0.0),
        event_id=ev.get("event_id") or "",
        source_event_id=origin,
        sensor_id=ev.get("sensor_id") or "",
        clip_path=ev.get("clip_path"),
        context=None,
        intervals=ev.get("intervals"),
        taxonomy=ev.get("taxonomy"),
        detection_type=ev.get("detection_type") or "",
        root_event_id=root_key if origin == root_key else None,
    )


def _parse_iso_or_none(value: Any) -> datetime | None:
    """Best-effort ISO parse for event_signature times; None on any failure
    (a malformed timestamp must not abort an enrichment)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def enrich_entity_event(entity_event: dict[str, Any], obs: Observation) -> bool:
    """Fold a late-arriving observation into an already-emitted entity dict,
    in place. Pure (no I/O) so it's unit-testable in isolation.

    Returns False (and mutates NOTHING) when the observation is a duplicate
    redelivery — same event_id AND the same species identity as an existing
    evidence item. Species identity is the taxonomy id when either side has
    one, falling back to species_common only when both lack a taxonomy.
    species_code alone is NOT sufficient: BirdNET's 6-char code collapses
    ~6,522 labels to ~1,800 codes ('corvus' covers 32 crow/raven species —
    see birdnet.py's "do not use species_code as a primary key" warning), and
    all sub-detections of one clip share the parent event_id — so keying on
    (event_id, species_code) would silently swallow a distinct same-code
    sub-detection (e.g. a Common Raven arriving after an American Crow).

    Deliberately UNCHANGED: ``entity_id`` (stable identity), the top-level
    ``timestamp`` (creation ordering), ``also_detected``, and
    ``is_self_generated`` — the emit-time corollary-discharge verdict is
    preserved verbatim, never recomputed against the widened time span (a
    late arrival must not be able to flip genuine wildlife to
    self-generated)."""
    evidence = entity_event.setdefault("evidence", [])
    obs_tax_id = (obs.taxonomy or {}).get("id")
    for ev in evidence:
        if ev.get("event_id") != obs.event_id:
            continue
        if (ev.get("species_code") or "") != (obs.species_code or ""):
            continue
        ev_tax_id = (ev.get("taxonomy") or {}).get("id")
        if ev_tax_id or obs_tax_id:
            if ev_tax_id == obs_tax_id:
                return False  # true redelivery (same taxon)
            continue  # same code, DIFFERENT taxon — a distinct sub-detection
        if (ev.get("species_common") or "") == (obs.common_name or ""):
            return False  # no taxonomy on either side — dedup on display name

    pre_max = float(entity_event.get("confidence") or 0.0)
    # Display-swap gate: _group_display picks the max over species-CODED
    # observations only, so the gate must scan the same population. Gating on
    # the entity-wide max (pre_max, which includes codeless evidence) diverged
    # whenever a codeless item held the entity max: a coded late arrival that
    # beat every coded item but not the codeless max never swapped, even though
    # a from-scratch rebuild would have displayed it. Computed BEFORE the
    # append so the new evidence can't gate itself.
    pre_display_max = max(
        (
            float(ev.get("confidence") or 0.0)
            for ev in evidence
            if ev.get("species_code")
        ),
        default=0.0,
    )
    evidence.append(
        {
            "event_id": obs.event_id,
            "source_event_id": obs.source_event_id,
            "sensor_id": obs.sensor_id,
            "clip_path": obs.clip_path,
            "confidence": obs.confidence,
            "intervals": obs.intervals,
            "species_code": obs.species_code,
            "species_common": obs.common_name,
            "taxonomy": obs.taxonomy,
            "detection_type": obs.detection_type,
        }
    )
    entity_event["confidence"] = max(pre_max, obs.confidence)

    # Display swap gated on the PRE-merge max over CODED evidence (mirrors
    # _group_display's highest-confidence-wins among species-coded
    # candidates), keeping entity_type consistent with the display label
    # exactly as _build_one_entity does.
    if obs.species_code and obs.confidence > pre_display_max:
        entity_event["species_code"] = obs.species_code
        entity_event["common_name"] = obs.common_name
        entity_event["entity_type"] = derive_entity_type(
            taxonomy=obs.taxonomy,
            species_code=obs.species_code,
            common_name=obs.common_name,
            detection_type=obs.detection_type,
        )

    sig = entity_event.setdefault("event_signature", {})
    sensor_ids = sig.setdefault("sensor_ids", [])
    if obs.sensor_id and obs.sensor_id not in sensor_ids:
        sensor_ids.append(obs.sensor_id)
    root = obs.root_event_id or obs.source_event_id
    source_ids = sig.setdefault("audio_motion_source_ids", [])
    if root and root not in source_ids:
        source_ids.append(root)
    # Widen the span by PARSED datetime comparison (never lexicographic).
    ts = obs.timestamp
    start = _parse_iso_or_none(sig.get("start_time"))
    end = _parse_iso_or_none(sig.get("end_time"))
    try:
        if start is None or ts < start:
            sig["start_time"] = ts.isoformat()
        if end is None or ts > end:
            sig["end_time"] = ts.isoformat()
    except TypeError:
        # Mixed naive/aware timestamps (legacy data) — leave the span as-is
        # rather than aborting the enrichment.
        pass
    return True


class ClusterManager:
    """Manages a single rolling temporal cluster of detection observations.

    At any moment there is at most one OPEN cluster. When an Observation
    arrives:
      - If no open cluster exists OR the open cluster's window has expired,
        emit the existing cluster (if any) and create a new one.
      - Add the Observation to the (now-open) cluster and reset the timer.

    When the timer fires (no new observations for ``window_seconds``):
      - Close the cluster and emit its EntityEvent via
        ``on_entity_ready``.

    **Thread safety**: ``process_observation`` may be called from any
    thread (typically the MQTT callback thread). When ``set_loop()`` has
    been called, all cluster mutations are marshalled to the event-loop
    thread via ``call_soon_threadsafe``, serialising them with the
    timer-driven ``_expire_cluster`` callback. In synchronous-test mode
    (no loop set), mutations happen in-place — safe because no
    concurrent thread exists.

    **Max-duration cap**: Under continuous noise (observations arriving
    faster than ``window_seconds``), the naive timer would never expire
    because every observation reschedules it. ``max_cluster_duration_seconds``
    caps the absolute age of any single cluster — once exceeded, the
    cluster is force-closed and a new one will be opened by the next
    observation. Prevents unbounded memory growth during dawn chorus,
    persistent wind/traffic, etc.
    """

    def __init__(
        self,
        window_seconds: float = 3.0,
        max_cluster_duration_seconds: float = 30.0,
        on_entity_ready: Callable[[dict[str, Any]], None] | None = None,
        is_equivalent: Callable[[Any, Any], bool] | None = None,
        *,
        enrich_late_arrivals: bool = False,
        late_ttl_seconds: float = 300.0,
        late_max_tracked_roots: int = 2000,
        on_entity_enrich: Callable[[dict[str, Any], Observation], bool] | None = None,
    ) -> None:
        self.window_seconds = window_seconds
        self.max_cluster_duration_seconds = max_cluster_duration_seconds
        self.on_entity_ready = on_entity_ready
        # Cross-classifier equivalence checker passed to each cluster so
        # same-source observations from different classifiers merge.
        self._is_equivalent = is_equivalent
        # The one currently-open cluster, if any.
        self._open_cluster: TemporalCluster | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Late-arrival enrichment (off by default — cross-classifier-identity
        # §1 "enrich existing event"). The recent-entities map is touched ONLY
        # from _add_observation (read/evict) and _expire_cluster (populate),
        # both already serialised onto the loop thread via
        # call_soon_threadsafe — same single-owner discipline as
        # _open_cluster, no lock needed. Keyed by chain root; the value is a
        # LIST because one cluster emits one entity PER same-source group and
        # every group of a clip shares the root. Restart amnesia is accepted:
        # the map is in-memory, so for one TTL window after a restart a late
        # arrival duplicates instead of enriching (self-healing, bounded).
        self._enrich_late_arrivals = enrich_late_arrivals
        self._late_ttl_seconds = late_ttl_seconds
        self._late_max_tracked_roots = late_max_tracked_roots
        self.on_entity_enrich = on_entity_enrich
        # Expiry-path failures are surfaced (health payload) rather than lost
        # to the event loop's default exception logging.
        self.expire_errors = 0
        self.last_expire_error: str | None = None
        self._recent: OrderedDict[str, list[_Recent]] = OrderedDict()

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for scheduling timers."""
        self._loop = loop

    def process_observation(self, obs: Observation) -> None:
        """Add an observation to the open cluster, creating one if needed.

        Safe to call from any thread. When a loop has been registered,
        the actual mutation happens on the loop (serialised with timer
        callbacks). In synchronous-test mode, mutation happens inline.
        """
        if self._loop is not None:
            # Marshal to event loop — serialises with _expire_cluster.
            self._loop.call_soon_threadsafe(self._add_observation, obs)
        else:
            # Synchronous mode (tests without a loop). No concurrent
            # thread can race, so direct mutation is safe.
            self._add_observation(obs)

    def _add_observation(self, obs: Observation) -> None:
        """Always runs on the event-loop thread (when loop is set).

        Mutates _open_cluster and schedules the expiration timer.
        Pulled out of process_observation so the mutation is atomic
        with the timer reschedule (no window for a timer callback to
        slip in between).
        """
        # Late-arrival enrichment takes strict priority over the open-cluster
        # path: a late observation whose root matches a recently-emitted
        # entity must enrich it, never be dumped into an unrelated open
        # cluster. Flag off ⇒ the `and` short-circuits and today's code runs
        # unchanged. The map holds only already-EMITTED entities and roots
        # are per-clip unique (a root is either open or emitted, never both),
        # so an observation for the still-open current moment always misses
        # here and joins its open cluster normally.
        if self._enrich_late_arrivals and self._try_enrich(obs):
            return
        if self._open_cluster is None:
            self._open_cluster = TemporalCluster(
                window_seconds=self.window_seconds,
                is_equivalent=self._is_equivalent,
            )
        self._open_cluster.add_observation(obs)
        self._schedule_expiration()

    def _try_enrich(self, obs: Observation) -> bool:
        """Try to fold ``obs`` into a recently-emitted entity. Returns True
        iff the observation was CONSUMED (enriched, or a duplicate
        redelivery); False falls through to normal clustering.

        Contract per outcome:
        - no root / no candidate / no same-source match → False (cluster it);
        - duplicate evidence (merge returns False)      → True (consumed, no publish);
        - merged + on_entity_enrich True (row updated)  → True (consumed);
        - merged + on_entity_enrich False (row gone OR the persist failed) →
          drop the record (discarding the merged-but-unpersisted in-memory
          state with it), False — the observation survives as a new entity,
          the flag-off baseline. Strictly safer than consuming it: a consumed
          observation with an unpersisted merge would leave the DB stale AND
          block a QoS-1 redelivery via the dedup check.
        """
        root_key = obs.root_event_id or obs.source_event_id
        if not root_key:
            return False
        self._evict_recent(time.monotonic())
        rec = self._find_enrichable(root_key, obs)
        if rec is None:
            return False
        changed = enrich_entity_event(rec.entity_event, obs)
        if not changed:
            return True  # duplicate redelivery — consumed, nothing to persist
        if self.on_entity_enrich is None:
            return True  # merged in-memory (sync-test mode, no I/O sink)
        if self.on_entity_enrich(rec.entity_event, obs):
            return True
        # Row gone (aged out of the DB) or the persist failed — this record
        # is no longer trustworthy; drop it (with its merged-but-unpersisted
        # in-memory state) and cluster the observation instead.
        self._drop_recent(rec)
        return False

    def _find_enrichable(self, root_key: str, obs: Observation) -> _Recent | None:
        """First recently-emitted entity under ``root_key`` with ANY evidence
        item that is full-same-source with ``obs`` (interval overlap AND label
        compatibility — the same :func:`observations_same_source` predicate
        clustering uses, with one honest bound: evidence dicts don't persist
        their chain root, so where an item's clip origin can't be proven the
        adapter mirrors clustering's cross-root fallback and skips the interval
        comparison — see :func:`_evidence_to_observation`). Scanning every
        evidence item (not just the display label) is what lets a late
        crow.analyzed match a secondary PANNs 'Crow' item."""
        candidates = self._recent.get(root_key)
        if not candidates:
            return None
        for rec in candidates:
            for ev in rec.entity_event.get("evidence", []):
                adapter = _evidence_to_observation(ev, root_key)
                if observations_same_source(obs, adapter, self._is_equivalent):
                    return rec
        return None

    def _register_recent(self, entity_event: dict[str, Any]) -> None:
        """Track a just-emitted entity as enrichable under every chain root it
        combined. Called AFTER on_entity_ready so the cached dict carries the
        agent's in-place is_self_generated verdict. Loop-thread only."""
        sig = entity_event.get("event_signature") or {}
        roots = [r for r in (sig.get("audio_motion_source_ids") or []) if r]
        if not roots:
            return
        rec = _Recent(
            entity_event=entity_event,
            expires_at=time.monotonic() + self._late_ttl_seconds,
            roots=list(roots),
        )
        for root in roots:
            self._recent.setdefault(root, []).append(rec)
        # FIFO size cap on root keys (oldest-emitted first). A popped root just
        # stops being enrichable; a record shared with a surviving root remains
        # reachable there.
        while len(self._recent) > self._late_max_tracked_roots:
            self._recent.popitem(last=False)

    def _evict_recent(self, now: float) -> None:
        """Drop expired records (absolute monotonic TTL — never refreshed by an
        enrichment, so the window can't slide unbounded). Full scan: the map is
        capped at max_tracked_roots, so this stays trivially cheap."""
        for root in list(self._recent.keys()):
            live = [r for r in self._recent[root] if r.expires_at > now]
            if live:
                self._recent[root] = live
            else:
                del self._recent[root]

    def _drop_recent(self, rec: _Recent) -> None:
        """Remove one record from every root list holding it."""
        for root in rec.roots:
            recs = self._recent.get(root)
            if not recs:
                continue
            recs[:] = [r for r in recs if r is not rec]
            if not recs:
                del self._recent[root]

    def _schedule_expiration(self) -> None:
        """Schedule or reschedule the expiration timer for the open cluster.

        Must run on the event loop thread. Capped by
        ``max_cluster_duration_seconds`` — under continuous noise the
        timer would otherwise be perpetually rescheduled and the cluster
        would never close.
        """
        cluster = self._open_cluster
        if cluster is None:
            return

        if cluster._timer_handle is not None:
            cluster._timer_handle.cancel()

        if self._loop is None:
            return

        # Compute time remaining until the absolute cap. If we're already
        # at or past the cap, expire immediately rather than scheduling
        # a no-op timer.
        elapsed = (datetime.now(timezone.utc) - cluster.created_at).total_seconds()
        remaining_until_cap = self.max_cluster_duration_seconds - elapsed
        if remaining_until_cap <= 0:
            self._expire_cluster()
            return

        delay = min(self.window_seconds, remaining_until_cap)
        cluster._timer_handle = self._loop.call_later(delay, self._expire_cluster)

    def _expire_cluster(self) -> None:
        """Close the open cluster and emit its EntityEvent.

        Always runs on the event-loop thread (called as a timer
        callback or directly from _schedule_expiration on cap).
        """
        cluster = self._open_cluster
        if cluster is None:
            return
        self._open_cluster = None

        # A cluster can now yield multiple Entities (one per same-source
        # group), so emit each. Registration for late-arrival enrichment
        # happens AFTER on_entity_ready: the agent mutates the same dict in
        # place (is_self_generated), so the cached record carries the
        # authoritative emitted state.
        # This runs as a bare timer callback: an uncaught exception would
        # silently destroy the whole cluster (nothing emitted or registered)
        # with only the loop's generic callback log. Fail loud and countable.
        try:
            for entity_event in cluster.build_entity_events():
                if self.on_entity_ready is not None:
                    self.on_entity_ready(entity_event)
                if self._enrich_late_arrivals:
                    self._register_recent(entity_event)
        except Exception as e:
            self.expire_errors += 1
            self.last_expire_error = str(e)
            logger.exception(
                "Cluster expiry failed; cluster dropped",
                observations=len(cluster.observations),
                expire_errors=self.expire_errors,
            )

    def flush_all(self) -> list[dict[str, Any]]:
        """Force-close the open cluster and return its EntityEvent.

        Returns a list (zero or one element) for back-compat with the
        previous multi-cluster API. Useful for graceful shutdown or
        deterministic testing.
        """
        events: list[dict[str, Any]] = []
        if self._open_cluster is not None:
            cluster = self._open_cluster
            self._open_cluster = None
            if cluster._timer_handle is not None:
                cluster._timer_handle.cancel()
            events.extend(cluster.build_entity_events())
        return events

    @property
    def _clusters(self) -> dict[str, TemporalCluster]:
        """Back-compat property for tests that introspect cluster state.

        Returns a dict keyed by the open cluster's display species_code
        (legacy field) — there's at most one entry now. New code should
        check ``_open_cluster`` directly.
        """
        if self._open_cluster is None:
            return {}
        display = self._open_cluster.display_observation
        key = display.species_code if display else ""
        return {key: self._open_cluster}
