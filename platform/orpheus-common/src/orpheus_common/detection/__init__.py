"""
Detection data models and database access for Orpheus.

This module provides:
- Detection data model for all detection events
- SQLite database wrapper for /data/orpheus/detections/orpheus.db
- Query and storage APIs
- Schema migration via ensure_schema_updates

Example:
    from orpheus_common.detection import DetectionDB, Detection

    db = DetectionDB()

    # Store detection
    detection = Detection(
        event_id="bird_det_123",
        timestamp=datetime.now(timezone.utc),
        detection_type="species.detected",
        species_code="amecro",
        species_common="American Crow",
        confidence=0.95,
        channel=1
    )
    db.save(detection)

    # Query detections
    results = db.query(
        species_code="amecro",
        start_time=datetime.now(timezone.utc) - timedelta(hours=24),
        min_confidence=0.8
    )
"""

from .database import DetectionDB, ensure_schema_updates
from .models import Detection, Entity, EntityEvidence
from .species import CORVID_SPECIES, CROW_UI_CODES

__all__ = [
    "CORVID_SPECIES",
    "CROW_UI_CODES",
    "Detection",
    "DetectionDB",
    "Entity",
    "EntityEvidence",
    "ensure_schema_updates",
]
