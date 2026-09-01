"""The public-facing record shape — the only thing a public path may emit.

See docs/designs/read-only-portal.md §2. ``PublicEntityRecord`` has NO slot for a
clip, a coordinate, an exact timestamp, evidence, sensor id, or metadata, so the
public site / export physically cannot leak them — even by a coding mistake.
Privacy is enforced by the *shape*, not by a redactor that strips fields.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

# The complete set of keys a public artifact is allowed to contain. The
# artifact-scanning test (the public generator, Epic 7) asserts emitted JSON keys
# are a subset of this — so adding a leaky field to the record fails the build.
PUBLIC_ALLOWED_KEYS = frozenset(
    {
        "species_code",
        "common_name",
        "entity_type",
        "confidence_band",
        "date_bucket",
        "region_label",
    }
)


class PublicEntityRecord(BaseModel):
    """An entity, coarsened for public consumption. Built ONLY by
    ``PublicProjection.project_entity`` (an allow-list builder). Frozen: a terminal
    leaf type with no place to attach sensitive data."""

    model_config = ConfigDict(frozen=True)

    species_code: str
    common_name: str = ""
    entity_type: Optional[str] = None  # coarse clade, e.g. "Animal.Bird.Crow"
    confidence_band: Optional[str] = None  # "high"/"medium"/…; omitted if unconfigured
    date_bucket: str = ""  # coarsened time — never second-precision
    region_label: str = ""  # coarsened location — never raw lat/lon
