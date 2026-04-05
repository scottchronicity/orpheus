"""Detection data models for Orpheus."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from orpheus_common.events import OrpheusBaseEvent, SpatiotemporalContext


class EntityEvidence(BaseModel):
    """A single piece of evidence linking an Entity to a source Detection."""

    event_id: str
    source_event_id: Optional[str] = None
    sensor_id: str = ""
    clip_path: Optional[str] = None
    confidence: float = 0.0


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
    species: str
    common_name: str = ""
    confidence: float = 0.0
    evidence: list[EntityEvidence] = Field(default_factory=list)
    context: Optional[dict[str, Any]] = None

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
        }

    @classmethod
    def from_entity_event(cls, event: dict[str, Any]) -> Entity:
        """Create Entity from an EntityEvent dict (as emitted by ClusterManager).

        Maps ``species_code`` → ``species`` for DB storage.
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
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Detection:
        """Create Detection from dictionary.

        Backward compatible: missing event_id or context fields
        are auto-generated with defaults.
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
        }

        if "event_id" in data and data["event_id"] is not None:
            kwargs["event_id"] = data["event_id"]

        # Parse context if present
        context_data = data.get("context")
        if isinstance(context_data, dict):
            kwargs["context"] = SpatiotemporalContext(**context_data)
        elif context_data is not None:
            kwargs["context"] = context_data

        return cls(**kwargs)
