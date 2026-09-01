"""The public/private chokepoint — the single, audited place an Entity becomes
publishable. See docs/designs/read-only-portal.md §2.

``PublicProjection.project_entity`` is the ONLY constructor of
``PublicEntityRecord``. It is an **allow-list builder**: it names each field it
copies and never calls ``entity.to_dict()`` / ``model_dump()``. A sensitive field
added to ``Entity`` next month flows nowhere — it is simply never referenced. This
inverts the deny-list ("strip the bad fields") failure mode, where any
newly-added sensitive field leaks by default.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .coarsen import coarsen_location, coarsen_time
from .records import PublicEntityRecord

if TYPE_CHECKING:
    from orpheus_common.config import PublicProjectionConfig
    from orpheus_common.detection.models import Entity

# Every field that must NEVER reach a public artifact. The artifact-scanning test
# (Epic 7) greps emitted files for these; the allow-list record already has no slot
# for them — this is the belt-and-braces enumeration for the scan.
SENSITIVE_FIELDS = frozenset(
    {
        "context",
        "lat",
        "lon",
        "elevation",
        "sensor_id",
        "clip_path",
        "audio_clip_path",
        "video_clip_path",
        "timestamp",
        "event_signature",
        "metadata",
        "evidence",
        "is_self_generated",
        "source_event_id",
        "root_event_id",
    }
)


def _confidence_band(
    confidence: float, bands: dict[str, float]
) -> Optional[str]:
    """Map a confidence to its configured band label, or ``None`` if no bands are
    configured (the band is then omitted, never guessed). Picks the
    highest-threshold band the confidence meets."""
    chosen: Optional[str] = None
    best = -1.0
    for label, threshold in bands.items():
        if confidence >= threshold and threshold >= best:
            chosen, best = label, threshold
    return chosen


class PublicProjection:
    """Wraps a ``PublicProjectionConfig`` and projects Entities to public records."""

    def __init__(self, config: PublicProjectionConfig) -> None:
        self._cfg = config

    def project_entity(self, entity: Entity) -> PublicEntityRecord:
        """The chokepoint. Allow-list copy — only the six safe fields, coarsened.
        Drops context/coords, clips, evidence, exact time, metadata, signature."""
        cfg = self._cfg
        return PublicEntityRecord(
            species_code=entity.species,
            common_name=entity.common_name,
            entity_type=entity.entity_type,
            confidence_band=_confidence_band(entity.confidence, cfg.confidence_bands),
            date_bucket=coarsen_time(entity.timestamp, cfg.time_granularity),
            region_label=coarsen_location(
                mode=cfg.location_mode, site_label=cfg.site_label
            ),
        )
