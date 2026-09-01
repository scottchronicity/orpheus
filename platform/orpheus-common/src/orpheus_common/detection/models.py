"""Detection data models for Orpheus."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from orpheus_common.events import OrpheusBaseEvent, SpatiotemporalContext

from .namespaces import validate_namespace


class TemporalInterval(BaseModel):
    """A contiguous time range within a source audio clip where a detection's
    signal was observed.

    Used to express *when* in a clip a labelled sound occurred — not just
    *what* was in the clip. Populated by any classifier that has frame-level
    or window-level localisation data (PANNs SED outputs, BirdNET sliding
    windows, audio-motion span, etc.). Consumers (UI clip players,
    correlator, future source-separation experiments) read this to seek to
    the relevant segment.

    See ADR 0011 for the rationale and the cross-cutting design.
    """

    start_seconds: float = Field(
        ...,
        description=(
            "Offset in seconds from the start of audio_clip_path. 0.0 = beginning."
        ),
    )
    end_seconds: float = Field(
        ...,
        description=(
            "Offset in seconds from the start of audio_clip_path. "
            "Must be >= start_seconds."
        ),
    )
    confidence: Optional[float] = Field(
        default=None,
        description=(
            "Optional per-interval confidence in [0, 1]. May differ from the "
            "parent Detection's clip-level confidence."
        ),
    )

    @model_validator(mode="after")
    def _check_ordering(self) -> TemporalInterval:
        """Enforce the start_seconds <= end_seconds invariant.

        Without this, swapped or negative-duration intervals slip through
        (e.g. from a buggy upstream post-processor or a corrupted
        roundtrip), and downstream consumers misbehave silently — UI clip
        players seek past the interval, duration sums for the parity
        dashboard go negative, etc.
        """
        if self.start_seconds < 0:
            raise ValueError(
                f"start_seconds must be >= 0, got {self.start_seconds}"
            )
        if self.end_seconds < self.start_seconds:
            raise ValueError(
                f"end_seconds ({self.end_seconds}) must be >= "
                f"start_seconds ({self.start_seconds})"
            )
        return self


class TaxonomyRef(BaseModel):
    """A reference to a class within a well-known taxonomy.

    Allows multiple classifiers (BirdNET, PANNs/AudioSet, future iNaturalist
    models, etc.) to coexist in the system without colliding on identifier
    semantics. The ``namespace`` field disambiguates which authority owns the
    ``id`` value.

    Conventional namespaces:
      - ``"audioset"``         — Google AudioSet ontology machine_id (e.g. ``"/m/04rlf"``)
      - ``"ebird"``            — eBird species alpha code (e.g. ``"amecro"``)
      - ``"ioc"``              — IOC World Bird List scientific name
      - ``"inaturalist"``      — iNaturalist taxon id

    Value-object semantics: frozen + hashable so that TaxonomyRefs can
    live in sets (used by the equivalence subsystem's BFS walks).

    See ADR 0011 for the rationale.
    """

    model_config = {"frozen": True}

    namespace: str = Field(
        ...,
        description=(
            "Taxonomy authority — must be one of "
            "orpheus_common.detection.namespaces.KNOWN_NAMESPACES."
        ),
    )
    id: str = Field(
        ...,
        description="Identifier within the namespace (e.g. AudioSet machine_id).",
    )
    common_name: Optional[str] = Field(
        default=None,
        description=(
            "Convenience copy of a human-readable label. Not authoritative — "
            "the namespace+id pair is canonical."
        ),
    )

    @field_validator("namespace")
    @classmethod
    def _validate_namespace(cls, value: str) -> str:
        return validate_namespace(value)

    def __eq__(self, other: object) -> bool:
        """Equality is on (namespace, id) only — common_name is a display
        copy and varies between instances of the same canonical ref."""
        if not isinstance(other, TaxonomyRef):
            return NotImplemented
        return self.namespace == other.namespace and self.id == other.id

    def __hash__(self) -> int:
        return hash((self.namespace, self.id))


class EntityEvidence(BaseModel):
    """A single piece of evidence linking an Entity to a source Detection.

    Under Layer 2 (event-based clustering, see
    ``docs/designs/cross-classifier-identity.md`` §4) each piece of
    evidence is self-describing — it carries its own species claim
    (``species_code`` / ``species_common`` / ``taxonomy``) and which
    classifier produced it (``detection_type``). Code that queries
    "what species was this Entity?" walks the evidence list rather than
    reading a single Entity-level species field.

    ``intervals`` (intra-clip TemporalIntervals from the source Detection)
    lets UI clip players highlight per-evidence spans without having to
    refetch the source Detection.

    See ADR 0011 for ``intervals``/``taxonomy`` rationale and the
    cross-classifier-identity design doc for ``species_code``/
    ``detection_type`` on evidence.
    """

    event_id: str
    source_event_id: Optional[str] = None
    sensor_id: str = ""
    clip_path: Optional[str] = None
    confidence: float = 0.0
    intervals: Optional[list[TemporalInterval]] = None
    # Layer 2 — per-evidence species claim (was on the Entity in the
    # species-keyed clustering era; now lives per-evidence so multi-
    # classifier multi-species clusters preserve every opinion).
    species_code: Optional[str] = None
    species_common: Optional[str] = None
    taxonomy: Optional[TaxonomyRef] = None
    # Which Orpheus detection_type emitted this evidence
    # (e.g. ``"species.detected"`` from BirdNET, ``"audio.classified"``
    # from PANNs, ``"crow.analyzed"`` from crow-tools). Lets consumers
    # tell evidence sources apart even when taxonomies are equivalent.
    detection_type: str = ""


class Entity(BaseModel):
    """
    A correlated entity representing a single real-world animal event.

    Produced by the event-correlator agent by fusing multiple Detection
    events from different microphones within a temporal window.

    Fields:
        entity_id: Unique identifier for this entity (UUID).
        timestamp: When this entity was created (cluster expiry time).
        species: Species code (e.g. 'amecro').
        common_name: Human-readable species name.
        confidence: Highest confidence from the contributing detections.
        evidence: List of source detection references.
        context: Optional averaged location context.
    """

    entity_id: str
    timestamp: datetime
    # Legacy display fields under Layer 2 — populated from the highest-
    # confidence observation's species_code/common_name. NOT authoritative;
    # the per-evidence taxonomy is the source of truth. See the cross-
    # classifier-identity design doc.
    species: str
    common_name: str = ""
    confidence: float = 0.0
    evidence: list[EntityEvidence] = Field(default_factory=list)
    context: Optional[dict[str, Any]] = None
    # Layer 2 — traceability metadata describing how the cluster was
    # assembled (source audio.motion event ids, mics that contributed,
    # time span). Not a primary key; not part of any join.
    event_signature: Optional[dict[str, Any]] = None
    # Corollary discharge ("echo problem"): True when this entity overlapped
    # our own audio playback window, so it's the system hearing itself rather
    # than wildlife. Tagged (not dropped) so it stays auditable. Additive;
    # legacy rows / events default False. See the event-correlator's
    # CorollaryDischargeFilter.
    is_self_generated: bool = False
    # Coarse state-space taxonomy (e.g. "Animal.Bird.Crow"). ADDITIVE + DERIVED
    # from the per-evidence taxonomy (never authoritative over it); nullable —
    # legacy rows / unresolvable detections stay None. See entity_taxonomy.py
    # ([ARCH] Generalize the EntityEvent State Space Taxonomy).
    entity_type: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert Entity to dictionary."""
        return {
            "entity_id": self.entity_id,
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else self.timestamp,
            "species": self.species,
            "common_name": self.common_name,
            "confidence": self.confidence,
            "evidence": [e.model_dump(mode="json") for e in self.evidence],
            "context": self.context,
            "event_signature": self.event_signature,
            "is_self_generated": self.is_self_generated,
            "entity_type": self.entity_type,
        }

    @classmethod
    def from_entity_event(cls, event: dict[str, Any]) -> Entity:
        """Create Entity from an EntityEvent dict (as emitted by ClusterManager).

        Maps ``species_code`` → ``species`` for DB storage. Layer 2:
        ``event_signature`` is preserved.
        """
        timestamp = event.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        evidence_list: list[EntityEvidence] = []
        for ev in event.get("evidence", []):
            evidence_list.append(EntityEvidence(**ev))

        return cls(
            entity_id=event["entity_id"],
            timestamp=timestamp,
            species=event.get("species_code", ""),
            common_name=event.get("common_name", ""),
            confidence=event.get("confidence", 0.0),
            evidence=evidence_list,
            context=event.get("context"),
            event_signature=event.get("event_signature"),
            is_self_generated=bool(event.get("is_self_generated", False)),
            entity_type=event.get("entity_type"),
        )


class Detection(OrpheusBaseEvent):
    """
    Represents a detection event in the Orpheus system.

    Inherits from OrpheusBaseEvent, which provides:
    - event_id (UUID v4 default)
    - event_timestamp (UTC default)
    - context (optional SpatiotemporalContext)
    - source_event_id (optional, links to triggering event)

    Supports different detection types:
    - audio.motion: Raw audio motion detected
    - species.detected: Species identified from audio
    - crow.analyzed: Detailed crow behavior analysis
    """

    timestamp: datetime
    detection_type: str
    channel: Optional[int] = None
    species_code: Optional[str] = None
    species_common: Optional[str] = None
    confidence: Optional[float] = None
    audio_clip_path: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # See ADR 0011 — Temporal Localisation and Taxonomy References on Detections.
    intervals: Optional[list[TemporalInterval]] = None
    taxonomy: Optional[TaxonomyRef] = None

    # Cross-classifier identity (cross-classifier-identity.md §1.1): the
    # event_id of the audio.motion event at the root of this Detection's
    # source chain. Denormalised from walking ``source_event_id``
    # repeatedly so consumers can answer "which physical event is this
    # about?" in O(1). The emitting agent sets it as:
    #   - audio.motion (no upstream): self.event_id (or None for
    #     fallback)
    #   - everything downstream: parent.root_event_id ?? parent.event_id
    # Legacy rows have root_event_id=None; consumers fall back to
    # walking source_event_id via DB lookup.
    root_event_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert Detection to dictionary for storage."""
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp.isoformat()
            if isinstance(self.timestamp, datetime)
            else self.timestamp,
            "detection_type": self.detection_type,
            "channel": self.channel,
            "species_code": self.species_code,
            "species_common": self.species_common,
            "confidence": self.confidence,
            "audio_clip_path": self.audio_clip_path,
            "metadata": self.metadata,
            "source_event_id": self.source_event_id,
            "root_event_id": self.root_event_id,
            "intervals": [i.model_dump(mode="json") for i in self.intervals]
            if self.intervals is not None
            else None,
            "taxonomy": self.taxonomy.model_dump(mode="json")
            if self.taxonomy is not None
            else None,
        }

    @staticmethod
    def derive_root_event_id(parent: Detection | None) -> Optional[str]:
        """Compute the ``root_event_id`` for a Detection whose upstream
        triggering event is ``parent``.

        Rule (see ``docs/designs/cross-classifier-identity.md`` §1.1):
        ``self.root_event_id = parent.root_event_id ?? parent.event_id``.
        For audio.motion events (no parent), the agent sets it to
        ``self.event_id`` after construction — they are their own root.

        Returns ``None`` if ``parent`` is ``None`` (the caller is the
        root itself).
        """
        if parent is None:
            return None
        return parent.root_event_id or parent.event_id

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Detection:
        """Create Detection from dictionary.

        Backward compatible: missing event_id, context, intervals, or taxonomy
        fields are accepted (auto-generated defaults or None as appropriate).
        """
        # Parse timestamp if it's a string
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

        # Build kwargs, only include event_id if present (otherwise default UUID)
        kwargs: dict[str, Any] = {
            "timestamp": timestamp,
            "detection_type": data["detection_type"],
            "channel": data.get("channel"),
            "species_code": data.get("species_code"),
            "species_common": data.get("species_common"),
            "confidence": data.get("confidence"),
            "audio_clip_path": data.get("audio_clip_path"),
            "metadata": data.get("metadata", {}),
            "source_event_id": data.get("source_event_id"),
            "root_event_id": data.get("root_event_id"),
        }

        if "event_id" in data and data["event_id"] is not None:
            kwargs["event_id"] = data["event_id"]

        # Parse context if present
        context_data = data.get("context")
        if isinstance(context_data, dict):
            kwargs["context"] = SpatiotemporalContext(**context_data)
        elif context_data is not None:
            kwargs["context"] = context_data

        # Parse intervals if present (list of dicts → list of TemporalInterval)
        intervals_data = data.get("intervals")
        if intervals_data is not None:
            kwargs["intervals"] = [
                TemporalInterval(**i) if isinstance(i, dict) else i
                for i in intervals_data
            ]

        # Parse taxonomy if present (dict → TaxonomyRef)
        taxonomy_data = data.get("taxonomy")
        if isinstance(taxonomy_data, dict):
            kwargs["taxonomy"] = TaxonomyRef(**taxonomy_data)
        elif taxonomy_data is not None:
            kwargs["taxonomy"] = taxonomy_data

        return cls(**kwargs)
