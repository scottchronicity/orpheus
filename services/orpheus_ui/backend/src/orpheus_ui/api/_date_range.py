"""Shared date-range resolution for the history / analytics API endpoints.

Several diagnostics endpoints (``/data/birds/history``,
``/data/audio-events/history``, ``/data/audio-events/bird-correlation``,
``/data/crows/stats``, ``/data/audio/history``) plus ``/entities`` all accept
the same ``days`` / ``start_date`` / ``end_date`` trio and resolve it to a
concrete ``(start_dt, end_dt)`` UTC window. That resolution used to be
copy-pasted inline in six places.

Five of those copies parsed the ISO dates with **no** ``try/except``, so a
malformed ``?start_date=garbage`` raised ``ValueError`` — which the endpoint's
bare ``except Exception`` then re-wrapped as an HTTP 500 leaking the raw
exception in ``detail``. The one correct copy (``/entities``) returned a clean
400. This module is the single source of truth so every call site gets the
400 behaviour: unparseable input always maps to ``HTTPException(400)``.

It lives in the UI backend (not ``orpheus_common``) because the 400 translation
is FastAPI-specific — ``orpheus_common`` has no FastAPI dependency.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from fastapi import HTTPException


def _parse_iso(value: str, *, field: str) -> datetime:
    """Parse an ISO-8601 date/datetime into a tz-aware datetime.

    Accepts a trailing ``Z`` (Python 3.9's ``datetime.fromisoformat`` does not)
    and fills UTC for naive inputs while preserving an explicit offset when one
    is present. Raises ``HTTPException(400)`` — never a bare ``ValueError`` that
    would escape to the endpoint's ``except Exception`` and become a 500.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid {field} format")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def resolve_date_range(
    days: Optional[int],
    start_date: Optional[str],
    end_date: Optional[str],
    *,
    default_days: Optional[int] = 7,
) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Resolve the ``days`` / ``start_date`` / ``end_date`` trio to a window.

    Semantics (the historical inline blocks, with three deliberate deviations):

    * An explicit ``start_date`` / ``end_date`` (ISO-8601) wins. ``end_date`` is
      snapped to end-of-day (23:59:59.999999) so the whole day is included.
    * When ``default_days`` is an int, absent bounds fall back to a rolling
      window: ``start_dt`` = now - ``(days or default_days)`` days, ``end_dt`` =
      now. This is the diagnostics-history semantics.
    * When ``default_days`` is ``None`` (the ``/entities`` semantics) there is no
      rolling fallback — an absent ``start_date`` / ``end_date`` stays ``None``,
      leaving the query unbounded on that side.

    Deliberate deviations from the historical inline blocks:

    1. Unparseable input raises ``HTTPException(400)`` (with a trailing ``Z``
       accepted, and an explicit UTC offset preserved rather than overwritten
       with UTC) instead of leaking a ``ValueError`` the caller turned into a
       500 — the reason this module exists.
    2. An ``end_date`` WITHOUT a ``start_date`` is honored (start falls back to
       the rolling window / stays unbounded). The old blocks silently ignored
       it and returned the default window.
    3. An explicit window where ``start_dt > end_dt`` raises
       ``HTTPException(400)`` instead of silently resolving to an
       every-row-excluded query that renders as "no data".

    ``days`` is only consulted when it is a plain ``int``; anything else
    (``None`` or, for functions invoked directly in unit tests without FastAPI's
    dependency injection, an unresolved ``Query`` default) is treated as absent.
    """
    start_dt: Optional[datetime] = None
    end_dt: Optional[datetime] = None

    if start_date:
        start_dt = _parse_iso(start_date, field="start_date")
    if end_date:
        end_dt = _parse_iso(end_date, field="end_date").replace(
            hour=23, minute=59, second=59, microsecond=999999
        )

    # Guard on the EXPLICIT bounds only (before the rolling fallback fills a
    # side): an inverted explicit window is caller error and deserves a 400,
    # but e.g. an old ``end_date`` with no ``start_date`` under the rolling
    # fallback keeps the historical silently-empty result.
    if start_dt is not None and end_dt is not None and start_dt > end_dt:
        raise HTTPException(status_code=400, detail="start_date is after end_date")

    if default_days is not None:
        now = datetime.now(timezone.utc)
        if start_dt is None:
            window_days = (days if isinstance(days, int) else None) or default_days
            start_dt = now - timedelta(days=window_days)
        if end_dt is None:
            end_dt = now

    return start_dt, end_dt
