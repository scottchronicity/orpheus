"""Read-only public portal projection (docs/designs/read-only-portal.md).

The privacy chokepoint for any public-facing read of Orpheus data: the public site,
a future read-only MCP, citizen-science export. ``PublicProjection`` turns an
``Entity`` into a ``PublicEntityRecord`` that structurally cannot carry clips,
coordinates, exact timestamps, evidence, or metadata. Everything here is inert
until a consumer (Epic 7) wires it up; the projection config defaults disabled +
fail-closed.
"""

from .coarsen import LOCATION_PLACEHOLDER, coarsen_location, coarsen_time
from .export import export_public_site
from .projection import SENSITIVE_FIELDS, PublicProjection
from .read_model import ReadModel
from .records import PUBLIC_ALLOWED_KEYS, PublicEntityRecord

__all__ = [
    "LOCATION_PLACEHOLDER",
    "PUBLIC_ALLOWED_KEYS",
    "PublicEntityRecord",
    "PublicProjection",
    "ReadModel",
    "SENSITIVE_FIELDS",
    "coarsen_location",
    "coarsen_time",
    "export_public_site",
]
