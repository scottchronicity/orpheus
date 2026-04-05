"""
Base event system for Orpheus Event-Driven Architecture.

Provides foundational event models with spatiotemporal context
that all signal events (Audio, Video, Detection, Entity) inherit from.

Example:
    from orpheus_common.events import OrpheusBaseEvent, SpatiotemporalContext

    ctx = SpatiotemporalContext(
        lat=47.6062, lon=-122.3321,
        sensor_id="mic-01",
    )
    event = OrpheusBaseEvent(context=ctx)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

__all__ = [
    "InferenceEvent",
    "OrpheusBaseEvent",
    "SpatiotemporalContext",
]


class SpatiotemporalContext(BaseModel):
    """Spatiotemporal context for an event (location + time + sensor)."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str = ""

    model_config = {"frozen": False}


class OrpheusBaseEvent(BaseModel):
    """
    Base event for all Orpheus events.

    Provides common fields: event_id, event_timestamp, optional
    spatiotemporal context, and optional source_event_id for causal
    lineage tracking.  Every event in the system (Detection, EntityEvent,
    etc.) inherits from this base.
    """

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: Optional[SpatiotemporalContext] = None
    source_event_id: Optional[str] = None

    model_config = {"frozen": False}


# Backward-compatible alias — existing imports continue to work.
InferenceEvent = OrpheusBaseEvent
