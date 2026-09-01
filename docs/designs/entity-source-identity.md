# Design: Source-Identity Entities (correlate same source, not co-occurrence)

**Status:** Implemented (pairs with ADR 0013)
**Date:** 2026-06-04
**Supersedes the Layer-2 clustering described in:** `cross-classifier-identity.md` §4

Shipped in the correlator: `Observation`, `intervals_overlap`,
`observations_same_source` and union-find source grouping in
`cluster_manager.py`, with `also_detected` on the entity event and "Also
detected at this time" in the dashboard.

## The problem this fixed

Entities used to cluster by emission wall-clock time regardless of species, so
the page filled with **"Insect"**, and opening one showed a Loon and a
Nuthatch listed as *evidence* for the insect. The case that prompted the
change:

> Entity **Insect** (51%), "5 sensors", 90ms time span. Evidence:
> Insect, Music, Cricket, **White-breasted Nuthatch** (6–9s),
> **Common Loon** (13.5–16.5s) — all from **mic-2**.

### Root cause

1. **Clips are 30 s.** An outdoor 30 s recording is a whole *soundscape*
   — a continuous cricket, a nuthatch at 0:06, a loon at 0:13 — not one
   animal event.
2. **Layer-2 clustered by emission wall-clock time** (`window_seconds`,
   3 s) **regardless of species**, and BirdNET + PANNs both finish a clip
   at ~the same instant, so everything from one clip collapsed into one
   cluster.
3. **Winner-takes-label:** the loudest, most continuous source (crickets)
   won, so the entity was labeled "Insect" and every other sound was
   dragged in as "evidence."

A second bug went with it: "# Sensors" counted observations rather than
distinct sensors, which is why the example claims five sensors for
observations that all came from mic-2. Both are fixed — the correlator now
appends a sensor only if it is not already present, and the dashboard renders
the distinct list.

**Co-occurrence is not identity.** A bird and a cricket genuinely overlap
in time and are two animals. Pure time-clustering can never separate them.

## Goals

1. **Correlate what is genuinely the same source** across classifiers and
   sensors (BirdNET `Crow` + PANNs `Crow` heard on 3 mics → one Crow).
2. **Show co-occurring-but-different sounds as context**, not as evidence
   ("also detected at this time"). The operator sees *both*.
3. **Distinct sources become distinct entities** — the 30 s clip above
   yields **Insect**, **White-breasted Nuthatch**, **Common Loon**, each
   with its own evidence. Birds stop being buried.
4. **Sensor- and modality-agnostic.** The model must already support the
   coming `video.motion → high-level classification → bird classification`
   chain, so a bird *seen on a camera* and *heard on a mic* at the same
   instant collapses into **one multi-modal entity**. Nothing may be
   audio-specific.
5. **"# Sensors"** becomes the count of *distinct sensors* that observed
   the source (e.g. "3 mics + 1 camera").

## Key enabler: absolute-time intervals

Every Observation already carries `TemporalInterval`s (ADR 0011), but they
are **relative to the clip start**. The whole design hinges on mapping them
to **absolute wall-clock time**:

```
absolute_interval = clip_root_timestamp + interval.start_seconds … + interval.end_seconds
```

Once intervals are absolute, "loon at 13.5–16.5 s of mic-2's clip" becomes
"loon at 12:30:44.8–12:30:47.8", which is directly comparable to an
observation from **any other sensor or modality** (another mic, or later a
camera). This is what makes overlap meaningful across the system and what
future-proofs it for video. The chain root timestamp is reachable now that
`root_event_id` is correct (ADR 0012).

## The model

### Observation (normalized, modality-agnostic)

```
Observation {
  label:        TaxonomyRef | call-type      # what
  confidence:   float
  abs_intervals: [(start: datetime, end: datetime)]   # when (absolute)
  sensor:       str            # mic-2, camera-1, …
  modality:     "audio" | "video"
  root_event_id: str           # the sensory-motion chain root
  classifier:   str            # birdnet | panns | crow-tools | video-* …
}
```

Both `audio.motion → audio.classified → species.detected` and the future
`video.motion → … → bird` produce Observations of exactly this shape.

### Entity = same-source group

Build an undirected graph over the Observations in a spatiotemporal
neighborhood. Add an edge between two Observations iff **both**:

- **Temporal:** their `abs_intervals` overlap (within a small tolerance,
  e.g. ±0.5 s to absorb classifier window jitter), **and**
- **Identity:** their labels are *compatible* —
  - same classifier + same species, or
  - cross-classifier via an **accepted/learned equivalence**
    (`equivalent_taxa()` — BirdNET `Crow` ≡ PANNs `/m/04s8yn`), or
  - same coarse taxon (configurable; e.g. both map to family/order), or
  - cross-modal compatible (a camera "Bird" ↔ a mic bird species, via the
    same equivalence machinery).

Each **connected component = one Entity.** Its `species` is the
highest-confidence label in the component; its sensors are the *distinct*
`sensor` values; its modalities are the distinct `modality` values.

Observations that are temporally near the entity but **not** edge-connected
(incompatible label) are **not** members — they belong to their own
entities, and are surfaced as **"also detected at this time."**

### "Also detected at this time/place" (context)

For an entity, the context list = observations from *other* entities whose
`abs_intervals` overlap the entity's span (optionally same/nearby sensors).
This is presentation only — it's a query over neighboring entities, not
membership. The operator sees the full picture without the label lying.

## Decoupling identity from equivalence-learning (the chicken-and-egg)

Layer-3 auto-discovery **learns** equivalences *from co-occurrence*. If we
only ever merged already-equivalent labels, nothing new would be learned.
Resolution: **keep co-occurrence tracking exactly as is for learning**
(observe which labels co-fire on shared roots → propose equivalences at
Jaccard thresholds), but base the **Entity** on *identity* (overlap ∧
compatibility). The two are separate concerns:

- *Learning* asks "do these labels tend to co-occur?" → co-occurrence.
- *Entity* asks "is this the same source right now?" → identity.

**Bootstrapping:** before any cross-classifier equivalence is learned,
BirdNET-Crow and PANNs-Crow form *two* entities for the same bird (slight
over-count). Same-classifier-same-species across sensors still merges
immediately (no equivalence needed). As equivalences accumulate, the
cross-classifier merges kick in. This degradation is graceful and visible.

## UI changes

- Entity detail: split the current "Evidence" into **Evidence**
  (same-source observations, across classifiers/sensors/modalities) and
  **Also detected at this time** (overlapping neighbors).
- **# Sensors** = count of distinct `sensor` values in the entity (and
  show modality breakdown when video lands).
- Entities list naturally diversifies (real species surface instead of a
  wall of "Insect").

## Open questions (decide during implementation)

1. **Overlap tolerance** (±0.5 s?) and whether sensors at different
   locations should require spatial proximity once GPS/site differs.
2. **Coarse-taxon merging:** do we merge two different warbler species that
   overlap, or keep them distinct? Start *strict* (exact species /
   accepted equivalence only) and loosen if it fragments.
3. **Clip length:** 30 s makes each clip a soundscape. Independently of
   this redesign, shorter motion clips (or event sub-segmentation) would
   reduce how much lands in one neighborhood. Tracked separately.
4. **Cross-modal correlation window:** audio and video of the same animal
   won't have identical intervals; define the tolerance when video lands.

## Migration / compatibility

- Additive: existing Entities stay; new clustering applies going forward.
- The correlator already receives intervals + correct `root_event_id`
  (ADR 0012), so no new data is required — only absolute-time mapping +
  the graph build.
- No schema change strictly required for the core; `EntityEvidence` may
  gain a `relation: "evidence" | "co_occurring"` flag for the UI split.
