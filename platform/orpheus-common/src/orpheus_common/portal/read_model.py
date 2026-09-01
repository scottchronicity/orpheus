"""The read handle a PUBLIC path holds — it yields only public records.

See docs/designs/read-only-portal.md §1.1. A public consumer (the static-site
generator, a future read-only MCP) constructs a ``ReadModel`` and gets back ONLY
``PublicEntityRecord`` objects, each run through the ``PublicProjection``
chokepoint. It never hands a raw ``Entity`` to a public path, so a public consumer
physically cannot reach unprojected data through it. The underlying DB should be
opened read-only (``DetectionDB(read_only=True)`` over the mirror replica)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator, Optional

from orpheus_common.logging import get_logger

from .projection import PublicProjection
from .records import PublicEntityRecord

if TYPE_CHECKING:
    from orpheus_common.config import PublicProjectionConfig
    from orpheus_common.detection import DetectionDB

logger = get_logger(__name__)


class ReadModel:
    """Public read handle over a (read-only) DetectionDB + a PublicProjection."""

    def __init__(self, db: DetectionDB, config: PublicProjectionConfig) -> None:
        self._db = db
        self._projection = PublicProjection(config)

    def public_entities(
        self, limit: Optional[int] = None, **filters: Any
    ) -> Iterator[PublicEntityRecord]:
        """Yield each matching Entity as its coarsened public record. Reads go
        through the DB (read-only in production); every Entity passes through the
        chokepoint — a raw Entity never escapes.

        ``limit`` is the DB row cap, made explicit here because ``get_entities``
        silently defaults to its UI-page size (500) — far too small for a
        full-replace public dataset. When an explicit limit is hit, a loud
        warning marks the result as truncated (visible on Diagnostics/logs).

        Self-generated (playback-echo) entities are DROPPED here: the internal
        "tag, don't drop" rule is for the private DB; the public dataset must
        never present Orpheus's own crow-call playback as a wildlife observation
        (and the allow-list record has no slot for the flag, so a consumer could
        not filter them out downstream)."""
        if limit is not None:
            filters["limit"] = limit
        entities = self._db.get_entities(**filters)
        if limit is not None and len(entities) >= limit:
            logger.warning(
                "Public read hit its row limit — result is TRUNCATED to the "
                "newest entities; raise the limit to cover the full dataset",
                limit=limit,
            )
        for entity in entities:
            if getattr(entity, "is_self_generated", False):
                continue
            yield self._projection.project_entity(entity)
