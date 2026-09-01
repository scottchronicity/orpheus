# ADR 0011: Temporal Localisation and Taxonomy References on Detections

**Status:** Accepted

**Date:** 2026-05-21

**Deciders:** Development Team

**Companion design doc:** [`docs/designs/audio-events-agent.md`](../designs/audio-events-agent.md)

## Context

ADR 0005 introduced `OrpheusBaseEvent` and `SpatiotemporalContext`. ADR 0006
formalised the event hierarchy and the `detection_type` taxonomy
(`audio.motion`, `species.detected`, `crow.analyzed`). Together these gave us
event identity, lineage, location, and per-classifier semantic typing.

What's still missing — and what blocks several pieces of upcoming work — is a
general way to express:

1. **Where in the audio clip a detection's signal occurred.** BirdNET runs on
   overlapping 3-second windows and knows which window(s) it found a species
   in; we throw that data away. The new audio-events agent (PANNs SED) will
   emit frame-level scores at 10 ms resolution; we need somewhere to put them.
   (This ADR first said ~31 ms, which is a different upstream PANNs variant.
   The shipped constant is `PANNS_FRAME_DURATION_SECONDS = 0.01`.)
   Today the only place to stash this metadata is the free-form `metadata`
   dict, which means every consumer has to know to look there and every
   producer is free to invent its own key shape — exactly the failure mode
   ADR 0006 was written to fix.

2. **Which authoritative taxonomy a label belongs to.** `species_code` is a
   free-form string today; consumers assume "ebird alpha code" by convention.
   That convention breaks the moment we add a second classifier (PANNs/AudioSet,
   future iNaturalist, etc.) whose identifiers come from a different authority.
   The correlator already pays the price for this: BirdNET emits `amecro` and
   crow-tools emits `american_crow` for the same real-world bird, and they
   silently fail to merge into one cluster (cluster key is the raw
   `species_code` string).

The new audio-events agent (see companion design doc) brings both problems to
a head at the same time. Solving them in a general way — rather than bolting
agent-specific fields onto `Detection.metadata` — keeps the schema honest and
unlocks downstream features (UI clip-player interval highlighting, future
source-separation experiments, cross-classifier alias maps and eventually
proper hierarchical taxonomy work).

### Requirements

- Backward compatible: legacy event payloads (no new fields) must still
  deserialise under the dual-schema rule from ADR 0006 §3.3.
- The fields must be **general** — populated by any detector that has the
  data, consumed by any agent or UI that wants it. Not bolted onto one agent.
- Cross-compatible with future taxonomic-hierarchy work (the backlog issue
  "[ARCH] Generalize the EntityEvent State Space Taxonomy") — i.e., this ADR
  should be a *foundation*, not a step that needs undoing.
- Optional everywhere. A detector without intra-clip localisation data, or
  one whose label set isn't in a registered taxonomy, must still produce a
  valid `Detection`.

## Decision

### 1. New shared models in `orpheus_common.detection.models`

```python
class TemporalInterval(BaseModel):
    start_seconds: float
    end_seconds: float
    confidence: Optional[float] = None


class TaxonomyRef(BaseModel):
    namespace: str
    id: str
    common_name: Optional[str] = None
```

Both are tiny, immutable-by-convention Pydantic models. They live alongside
`Detection`, `Entity`, and `EntityEvidence`.

### 2. Extensions to `Detection`

```python
class Detection(OrpheusBaseEvent):
    # ... existing fields unchanged ...

    intervals: Optional[list[TemporalInterval]] = None
    taxonomy: Optional[TaxonomyRef] = None
```

Both default to `None`. `to_dict()` / `from_dict()` round-trip them; missing
keys on input parse as `None` (per ADR 0006 §3.3 compatibility rule).

### 3. Semantics

- `intervals` describes **when within `audio_clip_path`** the detected signal
  was observed. Offsets are in seconds from the start of the clip. A single
  Detection may carry multiple non-contiguous intervals (one label firing in
  1-2 s and 5-6 s of a 10 s clip is one logical observation with two
  sub-locations — keeps DB cardinality bounded).
- `intervals=None` means "no intra-clip localisation available" — that is the
  legacy state and remains a valid state.
- `taxonomy` describes **which authority owns the label and what its
  identifier is there**. Registered namespaces live in
  `orpheus_common.detection.namespaces.KNOWN_NAMESPACES`: `ebird` (alpha codes),
  `ioc`, `audioset` (Google's 527-class ontology, machine_id values like
  `/m/04rlf`), `inaturalist`, `itis`, and `orpheus.custom` as the escape hatch.
  `TaxonomyRef` raises on anything else, so adding a namespace is a registry edit
  plus a doc update in the same PR — a code change, not a documentation change.
  Still no schema migration.
- `species_code` and `species_common` are **kept unchanged** for backward
  compatibility. New consumers should prefer `taxonomy` when it is present
  and fall back to `species_code`. Old consumers continue to work.

### 4. Conventions for populating intervals across the system

The design doc spells this out in detail (see Cross-cutting §4.5 there).
Summary:

- `audio.motion` populates `intervals=[(0.0, duration_seconds)]` — the full
  clip span.
- `species.detected` (BirdNET) populates `intervals` from the BirdNET sliding
  windows where the species cleared threshold.
- `crow.analyzed` (crow-detection) passes through intervals from the source
  bird Detection.
- `audio.classified` (audio-events) populates `intervals` from PANNs SED
  framewise post-processing.
- Detectors that genuinely have no localisation data emit `intervals=None`.

### 5. No new DB columns in this ADR

Persistence of the new fields is intentionally **deferred** to the SQLite
migration that lands with the audio-events agent (see design doc, §4.3). This
ADR governs only the in-memory and over-the-wire schema. Storing intervals
and taxonomy requires three additive columns (`intervals_json`,
`taxonomy_namespace`, `taxonomy_id`) via the existing
`ensure_schema_updates()` hook — that work lands in a later commit of the
same PR.

## Consequences

### Positive

- Cross-classifier evidence becomes structured. The correlator can show
  "BirdNET said `ioc:Corvus brachyrhynchos` from 2.3-3.1 s; PANNs said
  `audioset_/m/04s8yn` (Crow) from 2.4-3.0 s" as two pieces of evidence on
  the same Entity, with
  comparable intra-clip locations.
- UI clip players can highlight detected intervals on the waveform without
  caring which detector produced them.
- Source-separation experiments can use intervals as input regions of
  interest — without re-running classification.
- The full taxonomy work can adopt `taxonomy` as its foundation — no migration
  cost. (It since did; see ADR 0016.)
- ADR 0006's "agents must use `orpheus_common` models exclusively" rule
  continues to hold; we add fields to the shared model rather than letting
  each agent improvise in `metadata`.

### Negative

- Two more optional fields on every `Detection` payload. Serialisation cost
  is negligible (Pydantic skips `None` lists when consumers want compact
  output).
- Producers that should populate `intervals` but don't will pass type checks
  silently. Mitigation: consumer-side code that wants intervals should treat
  `intervals=None` as "no data" rather than asserting presence; reviewers
  should flag PRs that add a classifier without populating `intervals` when
  the model has the data.
- One more concept for newcomers to learn. The companion design doc and this
  ADR are the documentation.

### Risks

- **Convention drift on namespaces.** If two PRs land conflicting strings
  (`"audio_set"` vs `"audioset"`), consumers break. Mitigation: keep the
  canonical list in this ADR (and in `audioset_ontology.py` once it lands);
  add the chosen string in the same PR that introduces the producer.
- **Inconsistent confidence semantics.** Per-interval confidence (on
  `TemporalInterval.confidence`) and clip-level confidence (on
  `Detection.confidence`) may disagree. Convention: `Detection.confidence`
  is the clip-level max-pool score; each `TemporalInterval.confidence` is
  the score within that interval. Document in each detector's README.
