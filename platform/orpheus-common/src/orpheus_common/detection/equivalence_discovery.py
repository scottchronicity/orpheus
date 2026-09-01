"""Auto-discovery of cross-classifier taxonomy equivalences from real data.

Layer 3 follow-up (see ``docs/designs/cross-classifier-identity.md`` §5):
this worker observes which TaxonomyRefs consistently co-occur on the
same root audio.motion event over time, computes Jaccard similarity
across all such pairs, and proposes equivalence rows above the
configured threshold.

The motivation: hand-curated alias maps are a maintenance burden. With
auto-discovery, when BirdNET emits ``ioc:Corvus brachyrhynchos`` and
PANNs emits ``audioset:/m/04s8yn`` on most of the same audio events
over a week of real operation, the system learns the equivalence
automatically.

Usage:
    db = DetectionDB()
    eq_db = TaxonomyEquivalenceDB()
    proposals = discover_equivalences(db, eq_db, lookback_days=7)
    # proposals: list of {a, b, jaccard, status, cooccurrence, n_a, n_b}

Designed to run periodically (every 1-6 hours is fine — this is not
latency-sensitive). The correlator includes it as a background asyncio
task by default.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from itertools import combinations
from typing import Any, Optional

from .database import DetectionDB
from .equivalence import TaxonomyEquivalenceDB
from .models import TaxonomyRef

# Defaults — tunable via orpheus.yaml (see cross-classifier-identity §9 item 4).
DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_PROPOSE_THRESHOLD = 0.6     # Jaccard >= this → pending_review row
DEFAULT_ACCEPT_THRESHOLD = 0.9      # Jaccard >= this → accepted immediately
DEFAULT_MIN_COOCCURRENCES = 5       # Require at least N joint observations


def _group_taxa_by_root_event(
    detections: list,
) -> dict[str, set[TaxonomyRef]]:
    """Group Detections by their root_event_id (chain root). Each group is
    the set of distinct TaxonomyRefs that fired on that physical event.

    Detections without a taxonomy are skipped (we can't propose equivalences
    for them).  Detections without a root_event_id fall back to
    source_event_id or event_id (treated as their own root — they won't
    co-occur with anything else, which is the correct semantics).
    """
    groups: dict[str, set[TaxonomyRef]] = defaultdict(set)
    for det in detections:
        if det.taxonomy is None:
            continue
        root = det.root_event_id or det.source_event_id or det.event_id
        groups[root].add(det.taxonomy)
    return groups


def _compute_pairwise_stats(
    groups: dict[str, set[TaxonomyRef]],
) -> tuple[dict[TaxonomyRef, int], dict[tuple, int]]:
    """One-pass tally: per-taxa group counts + pairwise cooccurrence counts.

    Returns ``(counts, cooccurrences)`` where:
      - ``counts[ref]`` = number of groups in which ``ref`` appears.
      - ``cooccurrences[(ref_a, ref_b)]`` = number of groups in which
        both refs appear. Keys are always ordered ``(min, max)`` to avoid
        double-counting.
    """
    counts: dict[TaxonomyRef, int] = defaultdict(int)
    cooccurrences: dict[tuple, int] = defaultdict(int)

    for refs in groups.values():
        for ref in refs:
            counts[ref] += 1
        # Pairwise: sorted to canonicalise the key.
        sorted_refs = sorted(refs, key=lambda r: (r.namespace, r.id))
        for a, b in combinations(sorted_refs, 2):
            cooccurrences[(a, b)] += 1

    return counts, cooccurrences


def _jaccard(cooccurrence_ab: int, count_a: int, count_b: int) -> float:
    """|A ∩ B| / |A ∪ B|. Returns 0 if union is empty."""
    union = count_a + count_b - cooccurrence_ab
    if union == 0:
        return 0.0
    return cooccurrence_ab / union


def diagnose_equivalences(
    db: DetectionDB,
    eq_db: TaxonomyEquivalenceDB,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    propose_threshold: float = DEFAULT_PROPOSE_THRESHOLD,
    min_cooccurrences: int = DEFAULT_MIN_COOCCURRENCES,
    near_miss_top_k: int = 20,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Read-only diagnostic view of what auto-discovery WOULD propose +
    what it's filtering out.

    Designed for the Equivalences page's "Debug auto-discovery" panel.
    Doesn't write anything to the equivalence DB; just returns the
    statistics so a human can decide whether to retune the thresholds.

    Returns:
        - ``lookback_days``, ``min_cooccurrences``, ``propose_threshold``:
          the parameters used.
        - ``total_detections``: count of detections in the window.
        - ``total_detections_with_taxonomy``: subset with a TaxonomyRef
          (the only ones auto-discovery can use).
        - ``distinct_taxa_observed``: unique TaxonomyRefs in the window.
        - ``taxa_by_count``: top-K most-frequent TaxonomyRefs (helps
          ops see what's actually firing).
        - ``near_miss_below_min_cooc``: top-K pairs that have high Jaccard
          but didn't clear ``min_cooccurrences``. These are pairs that
          might really be equivalent but didn't co-occur enough yet.
        - ``near_miss_below_propose_threshold``: top-K pairs that
          cleared ``min_cooccurrences`` but didn't reach
          ``propose_threshold``. Lowering the threshold would propose
          these.
    """
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    # Single streaming pass: tally totals + group taxa by root, instead of
    # materialising the whole window (limit=1_000_000) just to len() it. Mirrors
    # _group_taxa_by_root_event's grouping; inlined here because diagnose also
    # needs the detection counts that helper doesn't return.
    total_detections = 0
    detections_with_taxonomy = 0
    groups: dict[str, set[TaxonomyRef]] = defaultdict(set)
    for det in db.iter_query(start_time=start, end_time=end):
        total_detections += 1
        if det.taxonomy is None:
            continue
        detections_with_taxonomy += 1
        root = det.root_event_id or det.source_event_id or det.event_id
        groups[root].add(det.taxonomy)
    counts, cooccurrences = _compute_pairwise_stats(groups)
    existing_eq = _existing_equivalence_pairs(eq_db)
    blocked = _blocked_pairs(eq_db)

    taxa_by_count = sorted(
        ({"namespace": t.namespace, "id": t.id, "count": c} for t, c in counts.items()),
        key=lambda x: -x["count"],
    )[:near_miss_top_k]

    near_miss_below_min_cooc: list[dict[str, Any]] = []
    near_miss_below_propose: list[dict[str, Any]] = []

    for (a, b), cooc in cooccurrences.items():
        n_a = counts[a]
        n_b = counts[b]
        jacc = _jaccard(cooc, n_a, n_b)
        pair_key = _canonical_pair_key(a, b)
        if pair_key in existing_eq or pair_key in blocked:
            continue
        entry = {
            "a": {"namespace": a.namespace, "id": a.id},
            "b": {"namespace": b.namespace, "id": b.id},
            "jaccard": round(jacc, 3),
            "cooccurrence": cooc,
            "n_a": n_a,
            "n_b": n_b,
        }
        if cooc < min_cooccurrences and jacc >= propose_threshold:
            # High Jaccard but too few co-occurrences yet.
            near_miss_below_min_cooc.append(entry)
        elif cooc >= min_cooccurrences and jacc < propose_threshold:
            # Enough co-occurrences but the ratio is too low.
            near_miss_below_propose.append(entry)

    near_miss_below_min_cooc.sort(key=lambda x: -x["jaccard"])
    near_miss_below_propose.sort(key=lambda x: -x["jaccard"])

    return {
        "lookback_days": lookback_days,
        "min_cooccurrences": min_cooccurrences,
        "propose_threshold": propose_threshold,
        "total_detections": total_detections,
        "total_detections_with_taxonomy": detections_with_taxonomy,
        "distinct_taxa_observed": len(counts),
        "taxa_by_count": taxa_by_count,
        "near_miss_below_min_cooc": near_miss_below_min_cooc[:near_miss_top_k],
        "near_miss_below_propose_threshold": near_miss_below_propose[:near_miss_top_k],
    }


def discover_equivalences(
    db: DetectionDB,
    eq_db: TaxonomyEquivalenceDB,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    propose_threshold: float = DEFAULT_PROPOSE_THRESHOLD,
    accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
    min_cooccurrences: int = DEFAULT_MIN_COOCCURRENCES,
    cross_namespace_accept_only: bool = False,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Scan recent detections and propose cross-classifier equivalences.

    Args:
        db: Detection database to read from.
        eq_db: Equivalence database to write proposals into.
        lookback_days: How far back to look for co-occurrence data.
        propose_threshold: Jaccard ≥ this proposes the pair as
            ``status="pending_review"``.
        accept_threshold: Jaccard ≥ this proposes the pair as
            ``status="accepted"`` (live immediately).
        min_cooccurrences: Require at least this many joint observations
            before considering a proposal. Filters noise from one-off
            chance co-occurrences.
        cross_namespace_accept_only: Safety guard. When True, a same-namespace
            pair that clears ``accept_threshold`` is capped at
            ``status="pending_review"`` (human-reviewed) instead of
            auto-accepted — equivalence means "two classifiers naming the same
            source", never "two same-namespace species that co-occur". Default
            False preserves the historical auto-accept behaviour exactly.
        now: Override the current time (used by tests).

    Returns:
        List of proposal dicts (for logging / dashboard / debugging):
        ``{a, b, jaccard, status, cooccurrence, n_a, n_b, action}``
        where ``action`` is ``"recorded"`` (new), ``"promoted"`` (existing
        ``pending_review`` row updated to ``accepted`` on stronger evidence),
        ``"skipped_existing"`` (no change needed), or ``"skipped_blocked"``.
    """
    end = now or datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)

    # Stream the window instead of materialising up to 1M Detection models at
    # once — the auto-discovery worker is default-on and runs every 6h, so the
    # all-in-memory query was a standing Jetson-OOM risk. Grouping is
    # order-independent, so streaming is behaviour-identical.
    groups = _group_taxa_by_root_event(db.iter_query(start_time=start, end_time=end))
    counts, cooccurrences = _compute_pairwise_stats(groups)

    # Pre-fetch existing equivalence + non-equivalence rows to decide
    # what to do per-pair. existing_eq is a dict pair_key → status so we
    # can distinguish "already accepted, leave alone" from "still
    # pending_review, re-evaluate and maybe promote on stronger
    # evidence."
    existing_eq: dict[tuple, str] = _existing_equivalence_pairs(eq_db)
    blocked_pairs: set[tuple] = _blocked_pairs(eq_db)

    proposals: list[dict[str, Any]] = []

    for (a, b), cooc in cooccurrences.items():
        if cooc < min_cooccurrences:
            continue
        n_a = counts[a]
        n_b = counts[b]
        jacc = _jaccard(cooc, n_a, n_b)
        if jacc < propose_threshold:
            continue

        # Determine action.
        pair_key = _canonical_pair_key(a, b)
        if pair_key in blocked_pairs:
            proposals.append(
                _make_proposal(a, b, jacc, cooc, n_a, n_b, status=None, action="skipped_blocked")
            )
            continue
        # Effective auto-accept decision, with the same-namespace safety guard.
        # (Computed before the prior-status checks so "is this a real change?"
        # is judged against the status we'd actually write.)
        auto_accept = jacc >= accept_threshold
        if auto_accept and cross_namespace_accept_only and a.namespace == b.namespace:
            # Co-occurrence within ONE classifier is not identity: two ioc
            # species that consistently share a clip (dawn chorus, a mated pair,
            # the same dawn window) are not the same source. Cap at
            # pending_review so a human reviews it via the Equivalences queue
            # rather than auto-merging them into a single Entity (the "soup").
            auto_accept = False
        status = "accepted" if auto_accept else "pending_review"

        prior_status = existing_eq.get(pair_key)
        if prior_status == "accepted":
            # Already accepted; nothing to update. record_equivalence is
            # idempotent so we could call it again, but skipping is
            # cheaper and the proposal trail benefits from showing
            # "we noticed this pair is still healthy" only when humans
            # care. (The guard never un-accepts a pre-existing accepted row —
            # it only governs new auto-accepts.)
            proposals.append(
                _make_proposal(
                    a, b, jacc, cooc, n_a, n_b, status=None, action="skipped_existing"
                )
            )
            continue
        if prior_status == "pending_review" and status == "pending_review":
            # Row already exists at pending_review and we're not promoting it
            # (either jacc < accept_threshold, or the guard capped it). Don't
            # re-write — avoids churning notes on every run.
            proposals.append(
                _make_proposal(
                    a, b, jacc, cooc, n_a, n_b, status=None, action="skipped_existing"
                )
            )
            continue
        # Either: never seen (record fresh), or pending_review being PROMOTED
        # to accepted on stronger evidence.
        eq_db.record_equivalence(
            a,
            b,
            confidence=jacc,
            source="auto_discovered",
            status=status,
            notes=f"jaccard={jacc:.3f} cooc={cooc} n_a={n_a} n_b={n_b}",
        )
        # Mark as recorded in-run so subsequent pairs don't re-propose.
        existing_eq[pair_key] = status
        action = "promoted" if prior_status == "pending_review" else "recorded"
        proposals.append(
            _make_proposal(a, b, jacc, cooc, n_a, n_b, status=status, action=action)
        )

    return proposals


# ---------------------------------------------------------------------- #
#  Internal helpers
# ---------------------------------------------------------------------- #
def _canonical_pair_key(a: TaxonomyRef, b: TaxonomyRef) -> tuple:
    """Order-independent key for a TaxonomyRef pair."""
    ka = (a.namespace, a.id)
    kb = (b.namespace, b.id)
    return (min(ka, kb), max(ka, kb))


def _canonical_pair_key_raw(
    ns_a: str, id_a: str, ns_b: str, id_b: str
) -> tuple:
    """Order-independent key for a raw (namespace, id) pair.

    Avoids constructing TaxonomyRef instances for the canonicalisation,
    which would otherwise raise ValueError for rows referencing a
    namespace no longer in KNOWN_NAMESPACES (the registry shrunk after
    the row was written).
    """
    ka = (ns_a, id_a)
    kb = (ns_b, id_b)
    return (min(ka, kb), max(ka, kb))


def _existing_equivalence_pairs(eq_db: TaxonomyEquivalenceDB) -> dict[tuple, str]:
    """All pairs that already have an equivalence row → their current
    status (``"accepted"`` | ``"pending_review"``).

    Returned as a dict so callers can decide what to do per-status:
    accepted pairs should be left alone; pending_review pairs should be
    re-evaluated against fresh evidence so they can be promoted to
    accepted when their Jaccard now exceeds the auto-accept threshold.
    """
    # Use the DB's own connection helper so we inherit its
    # ``busy_timeout`` pragma — otherwise this read fails immediately
    # with "database is locked" when contending with the correlator's
    # auto-discovery writer or the UI's accept/reject mutators.
    conn = eq_db._open_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT namespace_a, id_a, namespace_b, id_b, status "
            "FROM taxonomy_equivalence"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    out: dict[tuple, str] = {}
    for ns_a, id_a, ns_b, id_b, status in rows:
        key = _canonical_pair_key_raw(ns_a, id_a, ns_b, id_b)
        # If both directions exist with different statuses (shouldn't
        # happen given record_equivalence writes both atomically, but
        # belt-and-suspenders), prefer the stronger one.
        prior = out.get(key)
        if prior == "accepted" or status == "accepted":
            out[key] = "accepted"
        else:
            out[key] = status
    return out


def _blocked_pairs(eq_db: TaxonomyEquivalenceDB) -> set[tuple]:
    """All pairs explicitly asserted non-equivalent — auto-discovery
    must not re-propose these."""
    # Use ``_open_conn`` for the same busy_timeout reason as
    # ``_existing_equivalence_pairs`` above.
    conn = eq_db._open_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT namespace_a, id_a, namespace_b, id_b "
            "FROM taxonomy_non_equivalence"
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    return {
        _canonical_pair_key_raw(ns_a, id_a, ns_b, id_b)
        for ns_a, id_a, ns_b, id_b in rows
    }


def _make_proposal(
    a: TaxonomyRef,
    b: TaxonomyRef,
    jacc: float,
    cooc: int,
    n_a: int,
    n_b: int,
    *,
    status: Optional[str],
    action: str,
) -> dict[str, Any]:
    return {
        "a": {"namespace": a.namespace, "id": a.id},
        "b": {"namespace": b.namespace, "id": b.id},
        "jaccard": jacc,
        "cooccurrence": cooc,
        "n_a": n_a,
        "n_b": n_b,
        "status": status,
        "action": action,
    }
