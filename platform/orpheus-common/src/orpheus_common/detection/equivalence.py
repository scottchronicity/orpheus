"""TaxonomyRef equivalence — bidirectional, transitive, confidence-weighted.

Layer 3 of the cross-classifier identity stack
(see ``docs/designs/cross-classifier-identity.md`` §5).

This module owns:

  1. The ``taxonomy_equivalence`` and ``taxonomy_non_equivalence`` SQLite
     tables — schema is auto-created idempotently on first use.
  2. The pure-function helpers (``equivalent_taxa``, ``is_equivalent``,
     ``record_equivalence``, ``record_non_equivalence``) that consumers
     across Orpheus call to ask "are these two TaxonomyRefs the same
     real-world thing?"

Consumers include:
  - Entities API filtering ("show me Entities where any evidence is
    equivalent to American Crow")
  - Corollary discharge (future): "is this Detection equivalent to the
    one we just played out the speaker?"
  - The Bird Correlation parity dashboard (replaces the hardcoded
    BIRD_LIKE_AUDIOSET_MIDS set with a query)
  - The auto-discovery worker (writes proposed rows)

Bidirectionality is implemented by storing BOTH directions
(`(a, b)` and `(b, a)`) on every ``record_equivalence`` call. Transitivity
is computed at query time via BFS over the graph. Reflexivity is implicit
(``is_equivalent(a, a)`` returns True without needing a row).

Negative assertions live in ``taxonomy_non_equivalence`` and block
that edge during graph walks — useful when auto-discovery proposes a
bad match.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import deque
from pathlib import Path
from typing import Optional

from orpheus_common.logging import get_logger
from orpheus_common.storage import get_data_root

from .models import TaxonomyRef

logger = get_logger(__name__)


def _safe_taxonomy_ref(namespace: str, id_: str) -> Optional[TaxonomyRef]:
    """Construct a TaxonomyRef, returning ``None`` on validation failure.

    DB rows are written by code that knew the namespace registry at the
    time. If the registry shrinks (a namespace is removed) older rows
    become unconstructable — TaxonomyRef's validator raises ``ValueError``.
    A single bad row would otherwise abort the entire BFS / list query.
    Skip those rows with a warning instead.
    """
    try:
        return TaxonomyRef(namespace=namespace, id=id_)
    except ValueError:
        logger.warning(
            "Skipping equivalence row with unknown namespace",
            namespace=namespace,
            id=id_,
        )
        return None


def _equivalence_db_path() -> Path:
    """Default DB location: same dir as detections DB so a single SQLite
    file can be opened, attached, or backed up together."""
    detections_dir = get_data_root() / "detections"
    detections_dir.mkdir(parents=True, exist_ok=True)
    return detections_dir / "orpheus.db"


class TaxonomyEquivalenceDB:
    """SQLite-backed bidirectional taxonomy equivalence graph.

    Construct with a db_path (or None for the default shared
    ``orpheus.db``). The constructor ensures the schema exists; safe to
    construct repeatedly.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path is not None else _equivalence_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------ #
    #  Schema
    # ------------------------------------------------------------------ #
    def _init_schema(self) -> None:
        conn = self._open_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS taxonomy_equivalence (
                    namespace_a TEXT NOT NULL,
                    id_a        TEXT NOT NULL,
                    namespace_b TEXT NOT NULL,
                    id_b        TEXT NOT NULL,
                    confidence  REAL NOT NULL DEFAULT 1.0,
                    source      TEXT NOT NULL,
                    status      TEXT NOT NULL DEFAULT 'accepted',
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    notes       TEXT,
                    PRIMARY KEY (namespace_a, id_a, namespace_b, id_b)
                )
                """
            )
            cur.execute(
                """CREATE INDEX IF NOT EXISTS idx_taxeq_a
                   ON taxonomy_equivalence (namespace_a, id_a)"""
            )
            cur.execute(
                """CREATE INDEX IF NOT EXISTS idx_taxeq_b
                   ON taxonomy_equivalence (namespace_b, id_b)"""
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS taxonomy_non_equivalence (
                    namespace_a TEXT NOT NULL,
                    id_a        TEXT NOT NULL,
                    namespace_b TEXT NOT NULL,
                    id_b        TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    notes       TEXT,
                    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (namespace_a, id_a, namespace_b, id_b)
                )
                """
            )
            cur.execute(
                """CREATE INDEX IF NOT EXISTS idx_taxneq_a
                   ON taxonomy_non_equivalence (namespace_a, id_a)"""
            )
            cur.execute(
                """CREATE INDEX IF NOT EXISTS idx_taxneq_b
                   ON taxonomy_non_equivalence (namespace_b, id_b)"""
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    #  Writes
    # ------------------------------------------------------------------ #
    def record_equivalence(
        self,
        a: TaxonomyRef,
        b: TaxonomyRef,
        confidence: float = 1.0,
        source: str = "manual",
        status: str = "accepted",
        notes: str = "",
    ) -> None:
        """Record that ``a`` and ``b`` are the same real-world thing.

        Writes BOTH directions to the table so graph queries can walk
        either way without needing a UNION. Idempotent — re-recording
        the same pair updates confidence/source/status/notes.

        Args:
            a, b: The pair. Reflexive case (a == b) is a no-op.
            confidence: In [0, 1]. 1.0 = certain.
            source: ``"manual"`` | ``"auto_discovered"`` |
                ``"ontology_import"`` | ``"seed"`` | ...
            status: ``"accepted"`` (live; affects queries) |
                ``"pending_review"`` (recorded but ignored by
                ``equivalent_taxa()`` until promoted).
            notes: Free-text provenance.
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1]; got {confidence}")
        if status not in {"accepted", "pending_review"}:
            raise ValueError(
                f"status must be 'accepted' or 'pending_review'; got {status!r}"
            )
        if a.namespace == b.namespace and a.id == b.id:
            return  # reflexive — no row needed

        conn = self._open_conn()
        try:
            cur = conn.cursor()
            for ns_a, id_a, ns_b, id_b in (
                (a.namespace, a.id, b.namespace, b.id),
                (b.namespace, b.id, a.namespace, a.id),
            ):
                cur.execute(
                    """
                    INSERT INTO taxonomy_equivalence
                        (namespace_a, id_a, namespace_b, id_b,
                         confidence, source, status, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (namespace_a, id_a, namespace_b, id_b) DO UPDATE SET
                        confidence = excluded.confidence,
                        source     = excluded.source,
                        status     = excluded.status,
                        notes      = excluded.notes
                    """,
                    (ns_a, id_a, ns_b, id_b, confidence, source, status, notes),
                )
            conn.commit()
        finally:
            conn.close()

    def record_non_equivalence(
        self,
        a: TaxonomyRef,
        b: TaxonomyRef,
        source: str = "manual",
        notes: str = "",
    ) -> None:
        """Record that ``a`` and ``b`` are explicitly NOT the same.

        Blocks the auto-discovery worker from re-proposing the pair,
        and blocks ``equivalent_taxa()`` from walking the edge even if
        another row exists (negative assertions trump positive ones).

        Stores both directions, same as record_equivalence.
        """
        if a.namespace == b.namespace and a.id == b.id:
            raise ValueError("Cannot assert non-equivalence between a ref and itself")

        conn = self._open_conn()
        try:
            cur = conn.cursor()
            for ns_a, id_a, ns_b, id_b in (
                (a.namespace, a.id, b.namespace, b.id),
                (b.namespace, b.id, a.namespace, a.id),
            ):
                cur.execute(
                    """
                    INSERT INTO taxonomy_non_equivalence
                        (namespace_a, id_a, namespace_b, id_b, source, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (namespace_a, id_a, namespace_b, id_b) DO UPDATE SET
                        source = excluded.source,
                        notes  = excluded.notes
                    """,
                    (ns_a, id_a, ns_b, id_b, source, notes),
                )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ #
    #  Reads
    # ------------------------------------------------------------------ #
    def _open_conn(self) -> sqlite3.Connection:
        """Open a fresh sqlite connection with project-standard pragmas
        (WAL + busy_timeout + synchronous=NORMAL).

        Delegates to ``database.open_connection`` so the equivalence DB
        gets WAL mode too — under the default rollback journal a single
        auto-discovery writer would block every concurrent UI read of
        /api/equivalences.
        """
        # Local import to avoid a circular import at module-load time
        # (database.py also lives in this package).
        from .database import open_connection

        return open_connection(self.db_path)

    def _neighbors(
        self,
        ref: TaxonomyRef,
        min_confidence: float,
        blocked: set,
        conn: Optional[sqlite3.Connection] = None,
    ) -> list:
        """Return TaxonomyRefs directly equivalent to ``ref`` above the
        confidence threshold, skipping edges blocked by non-equivalence.

        Accepts an optional already-open ``conn`` so BFS callers can
        reuse one connection across the whole walk instead of opening
        N connections (one per BFS step). When ``conn`` is None we open
        + close a connection ourselves for backward-compat with any
        external callers that hit this directly.
        """
        own_conn = conn is None
        if own_conn:
            conn = self._open_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT namespace_b, id_b
                FROM taxonomy_equivalence
                WHERE namespace_a = ?
                  AND id_a = ?
                  AND confidence >= ?
                  AND status = 'accepted'
                """,
                (ref.namespace, ref.id, min_confidence),
            )
            rows = cur.fetchall()
        finally:
            if own_conn:
                conn.close()

        out: list[TaxonomyRef] = []
        for ns, rid in rows:
            if (ref.namespace, ref.id, ns, rid) in blocked:
                continue
            nbr = _safe_taxonomy_ref(ns, rid)
            if nbr is not None:
                out.append(nbr)
        return out

    def _blocked_edges(
        self, conn: Optional[sqlite3.Connection] = None
    ) -> set:
        """Read the non-equivalence table once per query as a set of
        ``(ns_a, id_a, ns_b, id_b)`` tuples that ``_neighbors`` must skip.

        Accepts an optional already-open ``conn`` (see ``_neighbors``).
        """
        own_conn = conn is None
        if own_conn:
            conn = self._open_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT namespace_a, id_a, namespace_b, id_b "
                "FROM taxonomy_non_equivalence"
            )
            return set(cur.fetchall())
        finally:
            if own_conn:
                conn.close()

    def equivalent_taxa(
        self, ref: TaxonomyRef, *, min_confidence: float = 0.5
    ) -> set:
        """All TaxonomyRefs equivalent to ``ref`` (transitively).

        BFS over the equivalence graph, respecting non-equivalence as
        blocked edges and a global confidence threshold. The result
        always includes ``ref`` itself (reflexivity).

        Args:
            ref: The starting point.
            min_confidence: Edges with ``confidence < min_confidence``
                or ``status != 'accepted'`` are not walked.

        Returns:
            A set of TaxonomyRefs (including ``ref``). Each element is a
            frozen-by-convention TaxonomyRef; use ``(t.namespace, t.id)``
            tuples for hashing / set membership.
        """
        # Hold ONE connection for the whole walk: a per-BFS-step connection
        # would mean N+1 short-lived connections per equivalent_taxa() call
        # — a perf foot-gun under load and an amplifier of lock contention
        # with auto-discovery
        # writes.
        conn = self._open_conn()
        try:
            blocked = self._blocked_edges(conn=conn)
            seen: set = {(ref.namespace, ref.id)}
            result: set = set()
            result.add(_ref_to_tuple(ref))

            queue = deque([ref])
            while queue:
                current = queue.popleft()
                for nbr in self._neighbors(
                    current, min_confidence, blocked, conn=conn
                ):
                    key = (nbr.namespace, nbr.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    result.add(key)
                    queue.append(nbr)
        finally:
            conn.close()

        # Honor recorded non-equivalence transitively: even if the BFS
        # walked a→c→b via two unrelated edges, drop ``b`` from the
        # result if (ref, b) was explicitly rejected by the operator
        # via record_non_equivalence. The "blocked" set above only
        # filters DIRECT edges during the walk; this post-filter makes
        # the docstring promise "negative assertions trump positive
        # ones" true for transitive paths too.
        seed_key = _ref_to_tuple(ref)
        result = {
            cand
            for cand in result
            if cand == seed_key
            or (seed_key[0], seed_key[1], cand[0], cand[1]) not in blocked
        }

        # Reconstruct TaxonomyRefs from the tuples.
        return {TaxonomyRef(namespace=ns, id=rid) for ns, rid in result}

    def is_equivalent(
        self, a: TaxonomyRef, b: TaxonomyRef, *, min_confidence: float = 0.5
    ) -> bool:
        """True iff ``a`` and ``b`` are in the same equivalence class.

        Reflexive ``a == b`` returns True without a query.
        """
        if a.namespace == b.namespace and a.id == b.id:
            return True
        return _ref_to_tuple(b) in {
            (t.namespace, t.id)
            for t in self.equivalent_taxa(a, min_confidence=min_confidence)
        }

    def list_pending_review(self) -> list:
        """Return all pending_review rows (one direction each — we
        de-duplicate the bidirectional storage here for human-review UIs)."""
        conn = self._open_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT namespace_a, id_a, namespace_b, id_b,
                       confidence, source, created_at, notes
                FROM taxonomy_equivalence
                WHERE status = 'pending_review'
                """
            )
            rows = cur.fetchall()
        finally:
            conn.close()

        # Deduplicate by canonicalising the pair to (lesser-tuple, greater-tuple).
        seen: set = set()
        out = []
        for ns_a, id_a, ns_b, id_b, conf, src, created, notes in rows:
            pair = tuple(sorted([(ns_a, id_a), (ns_b, id_b)]))
            if pair in seen:
                continue
            seen.add(pair)
            ref_a = _safe_taxonomy_ref(pair[0][0], pair[0][1])
            ref_b = _safe_taxonomy_ref(pair[1][0], pair[1][1])
            if ref_a is None or ref_b is None:
                continue
            out.append(
                {
                    "a": ref_a,
                    "b": ref_b,
                    "confidence": conf,
                    "source": src,
                    "created_at": created,
                    "notes": notes,
                }
            )
        return out

    def accept_pending(self, a: TaxonomyRef, b: TaxonomyRef) -> None:
        """Promote a pending_review row to accepted (live)."""
        conn = self._open_conn()
        try:
            cur = conn.cursor()
            for ns_a, id_a, ns_b, id_b in (
                (a.namespace, a.id, b.namespace, b.id),
                (b.namespace, b.id, a.namespace, a.id),
            ):
                cur.execute(
                    """
                    UPDATE taxonomy_equivalence
                    SET status = 'accepted'
                    WHERE namespace_a = ?
                      AND id_a = ?
                      AND namespace_b = ?
                      AND id_b = ?
                    """,
                    (ns_a, id_a, ns_b, id_b),
                )
            conn.commit()
        finally:
            conn.close()


# ---------------------------------------------------------------------- #
#  Module-level convenience (uses a default DB instance)
# ---------------------------------------------------------------------- #
_default_db: Optional[TaxonomyEquivalenceDB] = None
_default_db_lock = threading.Lock()


def _default() -> TaxonomyEquivalenceDB:
    global _default_db  # noqa: PLW0603
    # Double-checked locking: the fast path (already-initialised)
    # is a single attribute read under the GIL; only the first-init
    # window contends. Without the lock, two threads racing
    # initialisation each run TaxonomyEquivalenceDB(), which executes
    # CREATE TABLE IF NOT EXISTS under a 5s busy_timeout — one of them
    # can fail with "database is locked" if the loser falls outside
    # the timeout window.
    if _default_db is None:
        with _default_db_lock:
            if _default_db is None:
                _default_db = TaxonomyEquivalenceDB()
    return _default_db


def reset_default_db() -> None:
    """Force re-initialisation of the default DB instance. Used by tests."""
    global _default_db  # noqa: PLW0603
    with _default_db_lock:
        _default_db = None


def equivalent_taxa(ref: TaxonomyRef, *, min_confidence: float = 0.5) -> set:
    """Module-level convenience: see ``TaxonomyEquivalenceDB.equivalent_taxa``."""
    return _default().equivalent_taxa(ref, min_confidence=min_confidence)


def is_equivalent(
    a: TaxonomyRef, b: TaxonomyRef, *, min_confidence: float = 0.5
) -> bool:
    """Module-level convenience: see ``TaxonomyEquivalenceDB.is_equivalent``."""
    return _default().is_equivalent(a, b, min_confidence=min_confidence)


def record_equivalence(
    a: TaxonomyRef,
    b: TaxonomyRef,
    confidence: float = 1.0,
    source: str = "manual",
    status: str = "accepted",
    notes: str = "",
) -> None:
    """Module-level convenience: see ``TaxonomyEquivalenceDB.record_equivalence``."""
    _default().record_equivalence(a, b, confidence, source, status, notes)


def record_non_equivalence(
    a: TaxonomyRef, b: TaxonomyRef, source: str = "manual", notes: str = ""
) -> None:
    """Module-level convenience: see ``TaxonomyEquivalenceDB.record_non_equivalence``."""
    _default().record_non_equivalence(a, b, source, notes)


def expand_species_filter(
    raw_filter: str, *, eq_db: Optional[TaxonomyEquivalenceDB] = None
) -> tuple[set[str], set[tuple[str, str]]]:
    """Expand a free-form species filter using the equivalence graph.

    Cross-classifier-identity §5: a user typing "Corvus brachyrhynchos" (or
    "amecro", or "/m/04s8yn") should find every Entity whose evidence has a
    TaxonomyRef in any equivalent class — not just rows that happen to use the
    same literal string.

    Lifted here from the UI backend so every read-only embodiment (the dashboard,
    the public site, export) expands species the SAME audited way. This is
    privacy-load-bearing: a species the owner later suppresses must not reappear
    publicly via an equivalence that the public generator expands but a
    suppression list computed by a different path doesn't cover.

    Args:
        raw_filter: comma-separated terms; each may be a free-form species_code, a
            common name, a ``namespace:id`` pair, or an AudioSet machine_id.
        eq_db: equivalence DB to walk; defaults to ``TaxonomyEquivalenceDB()`` (the
            live equivalence DB), constructed defensively. Injectable so a
            read-only/replica consumer can pass its own handle.

    Returns:
        ``(legacy_species_codes, taxonomy_pairs)`` — bare strings to match against
        ``Entity.species`` / evidence ``species_code`` / ``species_common``
        (case-insensitive comparison is the caller's job), and ``(namespace, id)``
        tuples walked through the equivalence graph for cross-namespace identity.
    """
    raw_terms = [t.strip() for t in raw_filter.split(",") if t.strip()]
    legacy: set[str] = set()
    taxa: set[tuple[str, str]] = set()

    if eq_db is None:
        try:
            eq_db = TaxonomyEquivalenceDB()
        except Exception:  # noqa: BLE001 - equivalence is best-effort enrichment
            eq_db = None

    for term in raw_terms:
        legacy.add(term)
        # Did the caller pass a namespace:id pair?
        if ":" in term:
            ns, _, ref_id = term.partition(":")
            if ns and ref_id:
                try:
                    ref = TaxonomyRef(namespace=ns, id=ref_id)
                    if eq_db is not None:
                        for eq in eq_db.equivalent_taxa(ref):
                            taxa.add((eq.namespace, eq.id))
                    else:
                        taxa.add((ns, ref_id))
                except Exception:  # noqa: BLE001 - unknown ns -> legacy-string path
                    pass

        # Walk the equivalence graph for any free-form term that happens to be the
        # id-part of an existing TaxonomyRef (e.g. "Corvus brachyrhynchos" -> all
        # equivalent refs).
        if eq_db is not None:
            for ns_candidate in ("ioc", "audioset", "ebird", "inaturalist", "itis"):
                try:
                    ref = TaxonomyRef(namespace=ns_candidate, id=term)
                    equiv = eq_db.equivalent_taxa(ref)
                    if len(equiv) > 1:  # >1 means real edges, not just self
                        for eq in equiv:
                            taxa.add((eq.namespace, eq.id))
                except Exception:  # noqa: BLE001 - best-effort per candidate ns
                    continue

    return legacy, taxa


# ---------------------------------------------------------------------- #
#  Internal helpers
# ---------------------------------------------------------------------- #
def _ref_to_tuple(ref: TaxonomyRef):
    return (ref.namespace, ref.id)
