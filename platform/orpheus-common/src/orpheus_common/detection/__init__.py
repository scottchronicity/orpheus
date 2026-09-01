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

from .audioset_birds import BIRD_LIKE_AUDIOSET_MIDS, is_bird_like_audioset_mid
from .backfill import backfill_root_event_ids
from .database import (
    DetectionDB,
    ensure_schema_updates,
    iso_lower_bound,
    iso_upper_bound,
    open_connection,
)
from .entity_type_backfill import backfill_entity_types
from .equivalence import (
    TaxonomyEquivalenceDB,
    equivalent_taxa,
    expand_species_filter,
    is_equivalent,
    record_equivalence,
    record_non_equivalence,
)
from .equivalence_discovery import diagnose_equivalences, discover_equivalences
from .models import Detection, Entity, EntityEvidence, TaxonomyRef, TemporalInterval
from .namespaces import KNOWN_NAMESPACES, validate_namespace
from .species import (
    CORVID_SPECIES,
    CORVIDAE_GENERA,
    CROW_UI_CODES,
    is_corvid,
    is_corvid_species_code,
    is_corvidae,
)
from .taxonomy_bridge import same_source

__all__ = [
    "BIRD_LIKE_AUDIOSET_MIDS",
    "CORVID_SPECIES",
    "CORVIDAE_GENERA",
    "CROW_UI_CODES",
    "Detection",
    "DetectionDB",
    "Entity",
    "EntityEvidence",
    "KNOWN_NAMESPACES",
    "TaxonomyEquivalenceDB",
    "TaxonomyRef",
    "TemporalInterval",
    "backfill_root_event_ids",
    "backfill_entity_types",
    "diagnose_equivalences",
    "discover_equivalences",
    "ensure_schema_updates",
    "equivalent_taxa",
    "expand_species_filter",
    "is_bird_like_audioset_mid",
    "is_corvid",
    "is_corvid_species_code",
    "is_corvidae",
    "is_equivalent",
    "iso_lower_bound",
    "iso_upper_bound",
    "open_connection",
    "record_equivalence",
    "record_non_equivalence",
    "same_source",
    "validate_namespace",
]
