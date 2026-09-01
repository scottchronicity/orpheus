# ADR 0013: Source-Identity Entities (correlate same source, not co-occurrence)

**Status:** Accepted

**Date:** 2026-06-04

**Deciders:** Scott, Development Team

**Design doc:** [`docs/designs/entity-source-identity.md`](../designs/entity-source-identity.md)
**Revises the Layer-2 clustering of:** ADR 0011 / `cross-classifier-identity.md` §4

## Context

Layer-2 clustered every observation within a 3 s wall-clock window into one
Entity **regardless of species**, then picked a winner label. With 30 s
clips (a whole soundscape) this collapsed unrelated sounds into one "Insect"
Entity and listed a Loon and a Nuthatch as *evidence* for the insect.
"# Sensors" counted observations, not distinct sensors. Measured on jetson1.

Co-occurrence is not identity: a cricket and a loon overlap in time but are
two animals. And the model had to keep working when `video.motion → … →
species` detection arrives.

## Decision

An **Entity = a same-source group**, not a time window. Two observations
merge iff:

1. their in-clip **intervals overlap** (within tolerance; missing-interval
   observations are treated as overlapping so legacy data isn't over-split),
   **and**
2. their **labels denote the same source** — same species_code /
   common_name / taxonomy, or linked by the deterministic **static bridge**
   `same_source` (e.g. PANNs `Crow` `audioset:/m/04s8yn` ≡ BirdNET
   `American Crow` `ioc:Corvus brachyrhynchos`), or — for the long tail —
   by a learned Layer-3 **equivalence** (`eq_db.is_equivalent`). The
   correlator wires `same_source(a, b) or eq_db.is_equivalent(a, b)`.

Note what merge does **not** key on: the shared chain root. Two BirdNET
detections (crow + robin) trace back to the *same* `audio.motion` event —
one 30 s clip holds many animals — yet are different sources. Sharing a
root is necessary for provenance, never sufficient for identity; only
interval-overlap ∧ label-same-source merges them. (A future fine-grained
"audio event" source that isolates a single call would be a *stronger*
same-source signal we could add as an additional merge criterion; the
current logic already handles it correctly and would keep working.)

Each connected component (union-find over the cluster) becomes one Entity.
Co-occurring-but-incompatible observations form their **own** Entities and
are cross-referenced as **`also_detected`** ("also detected at this time")
on each sibling — surfaced in the UI as context, never as evidence. **#
Sensors** is now the count of distinct sensors in the group.

The model is **modality-agnostic** and **not animal-specific**: identity is
defined over `(namespace, id)` label + time + sensor metadata, none of it
audio- or species-specific. A future video "American Robin" and an audio
"American Robin" collapse into one multi-modal Entity; a truck heard *and*
seen registers as one source via a cross-modal synonym bridge
(`_CROSS_MODAL_SYNONYMS`) — no call-site changes, just a table entry.

The deterministic bridge handles the obvious cross-classifier merges (the
clade-specific AudioSet labels like `Crow`) the moment data arrives, on
laptop and Jetson alike — no learning, no human-in-the-loop, no DB state.
The learned equivalence graph remains as an additive long-tail fallback;
its co-occurrence *learning* is unchanged. Only genuinely unknown pairs
(no bridge, not yet learned) briefly form separate Entities and self-heal.

## Implementation

- `cluster_manager.py`: `_intervals_overlap` + `_label_compatible` +
  `_same_source` + union-find `_group_by_source`; `build_entity_events()`
  (plural) emits one Entity per group with `also_detected`. `ClusterManager`
  takes an injectable `is_equivalent`; the correlator wires
  `same_source(a, b) or eq_db.is_equivalent(a, b)`.
- `taxonomy_bridge.py` (orpheus-common): the deterministic static bridge.
  `same_source(a, b)` is pure data — a **membership bridge** (coarse clade
  label → IOC clade predicate, e.g. AudioSet `Crow`/`Caw` → `is_corvidae`)
  plus a **synonym bridge** (`_CROSS_MODAL_SYNONYMS`, same-granularity
  cross-modal pairs like a truck heard and seen). Fully-generic AudioSet
  labels (`Bird`, `Chirp` …) are deliberately excluded — they'd be
  promiscuous anchors that re-soup distinct co-occurring species.
- `also_detected` is nested in `event_signature` (already persisted as JSON)
  — no schema change.
- UI: Entities page renders an "Also detected at this time" section; evidence
  and "# Sensors" are now per-source automatically.

## Consequences

- The wall of "Insect" diversifies into real per-source Entities; birds
  resurface; the loon is no longer "evidence" for an insect.
- Tests that asserted the old soup ("two species → one Entity") were
  updated to assert the correct split, plus new tests cover the merge
  (same species across mics; equivalent cross-classifier labels), the split
  (disjoint intervals in one clip), and `also_detected`.

## Open follow-ups (in the design doc)

Absolute-time interval mapping for cross-sensor/cross-modal overlap; 30 s
clip length (a soundscape) as a separate knob; extending the membership
bridge to more clades as their IOC predicates are added (owl/`is_strigiform`,
duck/`is_anatid`, …) and the synonym bridge to real cross-modal pairs once a
video object detector lands.

*Done since first draft:* the "seed obvious cross-classifier equivalences so
the merge works out of the box" follow-up is now the deterministic
`same_source` bridge — see Implementation.
