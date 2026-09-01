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
    "EntityEvent",
    "InferenceEvent",
    "OrpheusBaseEvent",
    "SpatiotemporalContext",
    "WeatherReading",
]


class WeatherReading(BaseModel):
    """Environmental conditions at a point in time ([FEATURE] Ecowitt Weather
    Station Integration). Units are SI by contract — temperature in Celsius,
    pressure in hectopascals, wind speed in metres/second, rainfall in mm — so a
    provider mapping a vendor API (e.g. Ecowitt's imperial local feed) owns the
    conversion. All fields are optional so a partial reading (a sensor offline)
    is representable rather than dropped.

    Defined ABOVE ``SpatiotemporalContext`` on purpose: this module uses
    ``from __future__ import annotations``, so the ``weather`` forward-ref below
    only resolves if ``WeatherReading`` is already in this module's namespace.
    """

    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    pressure_hpa: Optional[float] = None
    wind_speed_mps: Optional[float] = None
    wind_direction_deg: Optional[int] = None
    rainfall_mm: Optional[float] = None
    timestamp: str = ""  # ISO-8601 string, like the EntityEvent emit dict

    # extra="ignore" is pydantic's default, but set explicitly so a future field
    # added here stays readable by an older binary (reversibility, made durable
    # against a global extra="forbid").
    model_config = {"frozen": False, "extra": "ignore"}


class SpatiotemporalContext(BaseModel):
    """Spatiotemporal context for an event (location + time + sensor)."""

    lat: Optional[float] = None
    lon: Optional[float] = None
    elevation: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sensor_id: str = ""
    # Additive, optional, nullable: ambient weather at the event, when a weather
    # provider is configured. Old context blobs lack it (-> None); old binaries
    # drop it via the explicit extra="ignore" below. Nested dict rehydrates to a
    # typed WeatherReading automatically on SpatiotemporalContext(**blob).
    weather: Optional[WeatherReading] = None

    # Explicit extra="ignore" (pydantic's default) so an OLD binary reading a NEW
    # context blob with a 'weather' key silently drops it instead of erroring —
    # the load-bearing reversibility guarantee for this added field.
    model_config = {"frozen": False, "extra": "ignore"}


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


class EntityEvent(BaseModel):
    """Typed view of the correlator's EntityEvent — the dict emitted by
    ``ClusterManager._build_one_entity`` and published on
    ``orpheus/entities/animal`` ([ARCH] Generalize the EntityEvent State Space
    Taxonomy).

    Deliberately STANDALONE (not an ``OrpheusBaseEvent`` subclass): the emit
    dict is flat and uses ``entity_id``/``timestamp``/dict-``context``, which
    would collide with the base's ``event_id``/``event_timestamp``/model-
    ``context``. This mirrors the EMIT dict (keys ``species_code``/
    ``common_name``/...), NOT ``Entity.to_dict`` (which uses ``species``).

    ``entity_type`` is ADDITIVE, DERIVED, and nullable — a coarse projection of
    the per-evidence ``taxonomy`` (the real source of truth), never authoritative
    over it. ``to_dict()`` returns the exact legacy emit keys plus
    ``entity_type``, so legacy consumers see an unchanged-shape dict with one
    extra ignorable field.
    """

    entity_id: str
    timestamp: str = ""  # ISO-8601 string (the emit dict stores ISO, not datetime)
    species_code: str = ""
    common_name: str = ""
    confidence: float = 0.0
    entity_type: Optional[str] = None  # derived; None when nothing resolves
    context: Optional[dict] = None
    evidence: list = Field(default_factory=list)
    also_detected: list = Field(default_factory=list)
    event_signature: Optional[dict] = None
    is_self_generated: bool = False

    model_config = {"frozen": False}

    @classmethod
    def from_dict(cls, data: dict) -> EntityEvent:
        """Build from a (possibly legacy / partial) emit dict; unknown keys are
        ignored and missing keys take field defaults (so a pre-entity_type dict
        yields ``entity_type is None``)."""
        return cls(**{k: v for k, v in data.items() if k in cls.model_fields})

    def to_dict(self) -> dict:
        """The emit-dict shape: every legacy key plus ``entity_type``."""
        return self.model_dump()


# Backward-compatible alias — existing imports continue to work.
InferenceEvent = OrpheusBaseEvent
