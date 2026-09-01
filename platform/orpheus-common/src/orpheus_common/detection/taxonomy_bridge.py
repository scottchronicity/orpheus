"""Deterministic cross-classifier / cross-modal identity bridge.

``same_source(a, b)`` answers one question — *"do these two TaxonomyRefs,
emitted by two different classifiers or modalities, name the same
real-world source?"* — with a **static, deterministic** rule. The source
can be an animal, a vehicle, anything two detectors might both perceive.
No database, no learning, no human-in-the-loop: the same code gives the
same answer on a laptop and on the Jetson, today and next year.

This is the out-of-the-box complement to the *learned* equivalence graph
in :mod:`orpheus_common.detection.equivalence`. The event-correlator asks
``same_source(a, b) or eq_db.is_equivalent(a, b)`` so the obvious bridges
work immediately while auto-discovery can still add long-tail ones.

Two kinds of bridge, one question
---------------------------------
1. **Membership bridge** — a *coarse* label names a group, a *specific*
   label names one member, and they match when the member is inside the
   group. Today: AudioSet clade labels (``Crow``, ``/m/04s8yn``) ↔ IOC
   species (``Corvus brachyrhynchos``) via a clade predicate. A future
   video *species* classifier that emits IOC labels plugs into the
   "specific" side for free (see :data:`_SPECIFIC_NAMESPACES`).

2. **Synonym bridge** — two labels at the *same* granularity, in different
   namespaces/modalities, that simply mean the same thing. Neither is more
   specific. This is the home for non-animal, cross-modal matches: once a
   video object detector lands, audio ``Truck`` and video ``truck``
   register here as a pair. See :data:`_CROSS_MODAL_SYNONYMS`.

Both are pure data. Adding a clade, a new species-level namespace, or a
vehicle synonym is a table edit — never a call-site change. ``same_source``
reasons over ``(namespace, id)`` only, so it is modality-agnostic.

Why membership bridges are clade-precise, not "any bird ≡ any bird"
-------------------------------------------------------------------
The tempting coarse rule — *any bird-like AudioSet label ≡ any IOC
species* (BirdNET only emits birds, so any IOC label is a bird) — is
**unsafe** as a merge rule. The fully-generic labels (``Bird``,
``Bird vocalization``, ``Chirp, tweet`` …) fire on almost every bird clip,
and BirdNET is multi-label, so one 30 s soundscape routinely yields
``American Crow`` + ``American Robin`` + a generic ``Bird``. If generic
``Bird`` bridged to *both* species, union-find would glue crow and robin
into one Entity through the shared generic anchor — re-creating exactly
the "soup" ADR 0013 set out to kill.

So membership bridges cover **only clade-specific coarse labels**
(``Crow`` → corvids), never the fully-generic ones. Generic labels stay
their own evidence and surface in the UI as *also detected at this time*.
"""

from __future__ import annotations

from typing import Callable, Optional

from .models import TaxonomyRef
from .species import is_corvidae

# Namespaces whose ids name a *specific member* (the specific side of a
# membership bridge). IOC scientific names are the only ones today; a
# future video species classifier emitting IOC labels joins automatically.
_SPECIFIC_NAMESPACES: frozenset[str] = frozenset({"ioc"})


# Membership bridges: coarse-label namespace -> { coarse id -> predicate }.
# The predicate takes the specific member's id (an IOC scientific name) and
# returns whether it falls inside the clade the coarse label denotes.
#
# Only clade-SPECIFIC coarse labels belong here (see module docstring on why
# the fully-generic AudioSet labels — Bird, Chirp, Squawk … — are absent).
# Each mid is verified against the bundled PANNs CSV at
# agents/orpheus-agent-audio-events/.../data/panns_class_labels_indices.csv.
_CLADE_BRIDGES: dict[str, dict[str, Callable[[str], bool]]] = {
    "audioset": {
        "/m/04s8yn": is_corvidae,   # 117: Crow → family Corvidae
        "/m/07r5c2p": is_corvidae,  # 118: Caw  → corvid vocalization
        # New clades drop in once their IOC predicate exists, e.g.
        #   "/m/09d5_":  is_strigiform,  # 119: Owl
        #   "/m/09ddx":  is_anatid,      # 104: Duck
    },
}


# Synonym bridges: unordered pairs of ``(namespace, id)`` that denote the
# SAME source at the same granularity, across namespaces/modalities. This is
# the home for non-animal, multi-modal matches. Empty until a second modality
# exists to pair with — once a video object detector lands, vehicles register
# here, e.g.:
#     frozenset({("audioset", "/m/07r04"), ("orpheus.custom", "truck")})
# Symmetry is automatic (membership is order-independent).
_CROSS_MODAL_SYNONYMS: frozenset = frozenset()


def _orient(
    a: TaxonomyRef, b: TaxonomyRef
) -> tuple[Optional[TaxonomyRef], Optional[TaxonomyRef]]:
    """Split a pair into ``(coarse, specific)`` for a membership bridge.

    The specific side is the species-level (IOC) ref; the coarse side is
    the other classifier's group label. Returns ``(None, None)`` when the
    pair isn't one-specific-and-one-coarse (e.g. both IOC, both AudioSet,
    or a vehicle pair) — nothing for a membership bridge to do.
    """
    a_specific = a.namespace in _SPECIFIC_NAMESPACES
    b_specific = b.namespace in _SPECIFIC_NAMESPACES
    if a_specific and not b_specific:
        return b, a
    if b_specific and not a_specific:
        return a, b
    return None, None


def _membership_match(a: TaxonomyRef, b: TaxonomyRef) -> bool:
    """True iff a coarse group label and a specific member name the same
    source (the member is inside the group's clade)."""
    coarse, specific = _orient(a, b)
    if coarse is None or specific is None:
        return False
    clades = _CLADE_BRIDGES.get(coarse.namespace)
    if not clades:
        return False
    predicate = clades.get(coarse.id)
    if predicate is None:
        return False
    # An IOC ref's id IS the scientific name (``Corvus brachyrhynchos``).
    return predicate(specific.id)


def _synonym_match(
    a: TaxonomyRef, b: TaxonomyRef, synonyms: frozenset = _CROSS_MODAL_SYNONYMS
) -> bool:
    """True iff the pair is a registered cross-modal synonym.

    ``synonyms`` is injectable so the mechanism can be exercised before any
    real pair is registered; production uses the module default.
    """
    return frozenset({(a.namespace, a.id), (b.namespace, b.id)}) in synonyms


def same_source(a: TaxonomyRef, b: TaxonomyRef) -> bool:
    """True iff a deterministic bridge links these two refs to one source.

    Symmetric: ``same_source(a, b) == same_source(b, a)``. Reflexive and
    same-namespace exact-match cases are handled upstream by name/taxonomy
    comparison; this function only crosses namespaces (a coarse group label
    vs. a specific member, or a cross-modal synonym pair).

    Modality-agnostic: reasons over ``(namespace, id)`` only, so a future
    video classifier — emitting IOC species or its own coarse labels —
    composes without touching any call site.
    """
    return _membership_match(a, b) or _synonym_match(a, b)
