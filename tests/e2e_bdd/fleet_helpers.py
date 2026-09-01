"""Shared helpers for the real-audio fleet e2e (not a test module).

The clip path + the audio.motion stimulus that drives the whole cascade, plus the
topic constants, shared by the cascade and dashboard validations.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

ENTITY_TOPIC = "orpheus/entities/animal"
MOTION_TOPIC = "orpheus/audio/motion/events"
# In-container path (mounted from artifacts/audio-samples by the fleet profile).
CROW_CLIP = "/data/orpheus/clips/American Crow - Corvus_brachyrhynchos_call.ogg"


def audio_motion(clip_path: str = CROW_CLIP, event_id: str | None = None) -> dict:
    """An audio.motion trigger carrying a clip to analyze (audio.motion is its own
    chain root). One of these drives the entire detection cascade."""
    event_id = event_id or ("crow-e2e-" + uuid.uuid4().hex[:8])
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event_id": event_id,
        "event_timestamp": now,
        "timestamp": now,
        "detection_type": "audio.motion",
        "channel": 1,
        "audio_clip_path": clip_path,
        "metadata": {"duration_seconds": 3.0, "peak_energy_db": -25.0},
        "source_event_id": None,
        "root_event_id": event_id,
        "intervals": [{"start_seconds": 0.0, "end_seconds": 3.0, "confidence": None}],
        "taxonomy": None,
    }


def is_corvid_entity(entity: dict) -> bool:
    """True if an EntityEvent (or any dict) reads as a corvid across its identity
    fields — robust to which classifier supplied the name."""
    hay = " ".join(
        str(entity.get(k, ""))
        for k in ("species_code", "species_common", "common_name", "entity_type")
    ).lower()
    return "crow" in hay or "corvus" in hay


def entity_roots(entity: dict) -> list:
    """The audio.motion chain roots an EntityEvent was built from.

    The correlator records them in ``event_signature.audio_motion_source_ids``
    (cross-classifier-identity Layer 2), which is how a test says "this entity
    came from the clip I injected" rather than "an entity appeared".
    """
    sig = entity.get("event_signature") or {}
    return list(sig.get("audio_motion_source_ids") or [])
