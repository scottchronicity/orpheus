"""Shared response helpers for the history / analytics API endpoints.

Three small building blocks were copy-pasted across the diagnostics, entities
and system endpoints. This module is the single source of truth so every call
site stays byte-identical:

* ``even_sample`` — the evenly-distributed max-N scatter downsample (was inline
  in ``/data/birds/history``, ``/data/audio-events/history``,
  ``/data/crows/stats`` and ``_compute_entity_stats``).
* ``paginate`` — the page clamp + slice + total-pages math (was inline in the
  three diagnostics history endpoints and ``/entities``).
* ``set_cache_control`` — the ``private`` browser-cache + ``Vary: Authorization``
  header pair (was a private helper in ``entities`` and hand-written inline in
  diagnostics and system).

It lives in the UI backend (next to ``_date_range``) rather than
``orpheus_common`` because ``set_cache_control`` depends on FastAPI's
``Response`` — and ``orpheus_common`` has no FastAPI dependency.
"""

from __future__ import annotations

from typing import List, NamedTuple, Optional, Sequence, TypeVar

from fastapi import Response

T = TypeVar("T")


def even_sample(rows: Sequence[T], n: int = 500) -> List[T]:
    """Down-sample ``rows`` to at most ``n`` items, evenly spread across the range.

    When ``len(rows) <= n`` every row is returned in its original order.
    Otherwise ``n`` rows are picked at a constant stride ``len(rows) / n``:
    ``rows[int(i * step)]`` for ``i`` in ``range(n)``.

    NOTE (shared off-by-one, preserved deliberately): the stride starts at
    index 0 and the last picked index is ``int((n - 1) * step)``, which is
    strictly below ``len(rows) - 1``. So the newest row (the last element, when
    the input is sorted ascending by timestamp) is **not** in the sample by
    design — this is a distribution/scatter view, not a live tail. Every
    history endpoint relies on this exact selection; don't "fix" the off-by-one
    without updating all call sites and their tests.

    Returns the selected rows unchanged; each call site projects them into its
    own wire-format dict (the endpoints use different key sets).
    """
    total = len(rows)
    if total <= n:
        return list(rows)
    step = total / n
    return [rows[int(i * step)] for i in range(n)]


class Page(NamedTuple):
    """Result of :func:`paginate`: the requested slice plus the clamped inputs.

    ``page`` / ``page_size`` are echoed back *after clamping* so callers can put
    the effective values in the response body; ``total_pages`` is computed from
    the pre-slice item count.
    """

    items: list
    page: int
    page_size: int
    total_pages: int


def paginate(items: Sequence[T], page: int, page_size: int) -> Page:
    """Clamp ``page`` / ``page_size``, slice ``items`` to that page, count pages.

    Clamping matches the historical inline blocks exactly:

    * ``page`` is clamped to a floor of 1.
    * ``page_size`` is clamped to ``[1, 1000]`` (the magic 1000 cap the history
      endpoints have always enforced).
    * ``total_pages`` is ``max(1, ceil(total / page_size))`` over the full
      (pre-slice) item count, so an empty list still reports one page and an
      over-range ``page`` simply yields an empty slice.
    """
    p = max(1, int(page))
    ps = max(1, min(int(page_size), 1000))
    total_pages = max(1, (len(items) + ps - 1) // ps)
    start_idx = (p - 1) * ps
    return Page(list(items[start_idx : start_idx + ps]), p, ps, total_pages)


def set_cache_control(
    response: Response, max_age: int, *, stale_while_revalidate: Optional[int] = None
) -> None:
    """Attach a private-cache header so the browser short-circuits
    identical polls within the window. Heavy aggregation endpoints
    benefit most — a 30s react-query refetchInterval combined with
    this 5-10s window means the second poll is served from disk cache
    without touching uvicorn.

    ``stale_while_revalidate`` defaults to ``max_age * 3`` (the ratio the
    entities + diagnostics history endpoints use); the system storage-history
    endpoint passes an explicit value so its ``max-age=30, swr=60`` output stays
    byte-identical rather than being widened to the default ``90``.

    ``Vary: Authorization`` is essential: ``private`` only excludes
    SHARED caches (proxies, CDNs); the browser's own per-profile cache
    still keys on URL+method by default. Without ``Vary: Authorization``,
    a logout-then-login-as-someone-else flow inside the cache window
    could serve user A's response to user B from the local disk cache.
    """
    swr = max_age * 3 if stale_while_revalidate is None else stale_while_revalidate
    response.headers["Cache-Control"] = (
        f"private, max-age={max_age}, stale-while-revalidate={swr}"
    )
    response.headers["Vary"] = "Authorization"
