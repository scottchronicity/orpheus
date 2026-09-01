"""Coarsening helpers for the public projection — fail-closed by design.

Pure functions, config-driven, with no guessed thresholds. Time buckets to the day
by default (maximally safe v1); location renders a coarse owner-supplied label and
NEVER a real coordinate. Anything unrecognized falls closed to the safest output.
"""

from __future__ import annotations

from datetime import datetime

# Rendered whenever a real region label isn't configured — never a coordinate.
LOCATION_PLACEHOLDER = "undisclosed"


def coarsen_time(ts: datetime, granularity: str = "day") -> str:
    """Bucket a timestamp to ``granularity``. ``"day"`` (default + fall-closed) →
    ``YYYY-MM-DD``; ``"hour"`` → ``YYYY-MM-DDTHH:00``. Never second-precision."""
    if granularity == "hour":
        return ts.strftime("%Y-%m-%dT%H:00")
    return ts.strftime("%Y-%m-%d")


def coarsen_location(*, mode: str = "site_label", site_label: str = "") -> str:
    """Coarsen location to a publishable label. v1 supports only ``"site_label"``:
    a single coarse owner-supplied string. **Fail-closed:** an unset label — or any
    unsupported mode (e.g. a future ``"grid"`` before its hard min-grid-size floor
    ships) — renders ``LOCATION_PLACEHOLDER``, never a real coordinate. Note this
    takes no lat/lon: v1 cannot emit coordinates at all."""
    if mode == "site_label" and site_label:
        return site_label
    return LOCATION_PLACEHOLDER
