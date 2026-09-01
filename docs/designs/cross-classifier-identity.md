# Cross-Classifier Identity & Event-Based Correlation

**Status:** Implemented, with §4 superseded — the identity stack described here is shipped (summary in
the merged feature work); kept as the design record.

**Author:** scott + claude

**Last updated:** 2026-05-21

**Companion docs:**
- [`audio-events-agent.md`](./audio-events-agent.md) (the agent that pushed
  this design over the edge)
- [`../adr/0011-temporal-localisation-and-taxonomy-references.md`](../adr/0011-temporal-localisation-and-taxonomy-references.md) (TaxonomyRef + intervals schema; the foundation this builds on)

---

## 1. The problem

Three different agents now claim to identify the same real-world animal:

| Agent | Native `species_code` for an American Crow |
|---|---|
| `orpheus-agent-bird-detection` (BirdNET) | `"amecro"` |
| `orpheus-agent-crow-detection` (crow-tools) | `"american_crow"` |
| `orpheus-agent-audio-events` (PANNs / AudioSet) | `"audioset_/m/04s8yn"` |

The event correlator clusters by string equality on `species_code`, so one
crow vocalization produces **three Entities**. Stats triple-count. The
Entities page has duplicates. Any future Director-style logic treating an
Entity as "one real animal" sees phantom animals.

We almost shipped a flat alias map (`{"amecro": "corvus", ...}`) as a
band-aid. That was the wrong primitive — it's a Python dict that needs hand
maintenance whenever a classifier is added, it's only used in exactly one
place (cluster-keying), it forgets transitivity, and it doesn't address the
*other* places identity-resolution will be needed (most immediately,
corollary discharge — see §6).

This document describes the layered replacement. Each layer is a self-
contained holon with a clear contract; together they handle cross-classifier
identity throughout the system, not just in clustering.

---

## 1.1 The lineage chain is the spine of the data model

Every Detection in Orpheus references the event that triggered it. This
already exists as `source_event_id` (immediate upstream parent) but the
implications haven't been formalised. The chain matters because the whole
system is built on **downstream enrichment** — each agent takes an
existing record and adds richer information that *references back* to
that record:

```text
  audio.motion (sensory input)        ← root of the chain
    └─ event_id: AM-001
       audio_clip_path: /data/.../clip.flac
       intervals: [(0.0, 3.2)]                     ← the whole clip
       ↓ (source_event_id)
  species.detected (BirdNET enriches)              ← "what species?"
    └─ event_id: BD-001
       source_event_id: AM-001
       taxonomy: (ioc, Corvus brachyrhynchos)
       species_code: corvus
       intervals: [(0.0, 3.0), (3.0, 6.0)]         ← per-window
       ↓ (source_event_id)
  crow.analyzed (crow-tools enriches further)      ← "what call type?"
    └─ event_id: CD-001
       source_event_id: BD-001
       metadata: {call_type: alert, age: adult, ...}
       intervals: [(2.0, 2.7)]                     ← AVES window
```

Two consequences this design must honour:

1. **The chain is the source of truth for "what was this about?"** A
   crow.analyzed Detection is about the same physical sound as the
   bird-detection that triggered it, which is about the same physical
   sound as the audio.motion that triggered THAT. Asking "which
   audio.motion event is this crow.analyzed about?" must always be
   answerable in O(1) or O(chain-length) — not "it depends on what
   else happened in the last 3 seconds."

2. **Downstream enrichment can arrive late.** crow-tools loads AVES +
   runs a classifier — possibly hundreds of milliseconds after the
   audio.motion event closed. The Entity might already be emitted by
   the time crow-tools weighs in. We need the chain to support
   reattaching late observations to the Entity they describe, not
   stranding them in a separate Entity.

### Propagating the chain root: `root_event_id`

The immediate `source_event_id` is enough to walk the chain, but
walking it requires DB lookups (one per hop). We denormalize the root
audio.motion event_id onto every Detection as a separate field
`root_event_id` so queries can answer "what physical event is this
Detection about?" in O(1):

| Producer | source_event_id | root_event_id |
|---|---|---|
| audio.motion | None | self.event_id (the audio.motion event is its own root) |
| species.detected (BirdNET) | audio.motion.event_id | source.root_event_id (== audio.motion.event_id) |
| crow.analyzed (crow-tools) | species.detected.event_id | source.root_event_id (chain through) |
| audio.classified (audio-events) | audio.motion.event_id | source.root_event_id (== audio.motion.event_id) |

The rule for every emitting agent: `self.root_event_id =
parent.root_event_id ?? parent.event_id`. If the parent has no
root_event_id (legacy data), use the parent's own event_id as the root.
Each agent inherits and propagates — adding a fourth detector tomorrow
requires zero changes elsewhere.

### "Enrich existing event" use cases this enables

| Use case | How the chain serves it |
|---|---|
| "Show me every classifier's opinion on audio.motion AM-001" | `SELECT * FROM detections WHERE root_event_id = 'AM-001'` |
| "Which Entity does this late crow.analyzed belong to?" | Look up Entity whose `event_signature.audio_motion_source_ids` contains the new Detection's `root_event_id` |
| "What's the chain that produced this Entity row?" | The Entity's `event_signature.audio_motion_source_ids` is the set of roots; for each root, find all Detections with that `root_event_id` |
| Correlator late-arrival enrichment | **Implemented** behind `correlation.late_enrichment.enabled` (default off). The cluster manager keeps a TTL'd map of `root_event_id` → recently-emitted Entities (a LIST per root — one cluster emits one entity per same-source group). A late Observation enriches an existing Entity only when it is full-same-source (interval overlap AND label compatibility — the same predicate clustering uses; where a persisted evidence item's clip origin can't be proven post-emit, the gate mirrors clustering's cross-root fallback and skips the interval comparison) with some evidence item of a recent Entity; the row is updated in place via the additive `DetectionDB.update_entity`. Guarantees: the emit-time `is_self_generated` verdict is preserved verbatim (never recomputed against the widened span), state-space memory is not re-recorded (no double count), and updates publish only on `orpheus/entity-updates/animal` (a sibling root no entity-create wildcard can catch). Bounded: absolute TTL (default 300 s, an engineering latency bound over the slowest classifier chain) + a root-count cap; restart amnesia accepted (in-memory map — one TTL window of duplicates after a restart, self-healing). |

### Why this isn't just "use source_event_id"

`source_event_id` is the *immediate* parent — for crow.analyzed, that's
the bird-detection event_id, not the audio.motion event_id. To answer
"what physical event was this about?" via `source_event_id` alone you'd
walk the chain on every query. `root_event_id` denormalizes the answer
onto every row. Both fields stay — source_event_id for the audit chain,
root_event_id for the O(1) physical-event lookup.

---

## 2. Holonic framing — who owns what

Orpheus is moving toward a [holonic](https://en.wikipedia.org/wiki/Holon_(philosophy))
architecture: each agent is autonomous (a whole) but also a participant in a
larger whole (the system). For identity resolution to scale as we add agents,
each layer must respect holon boundaries.

| Layer | Holon | Owns | Doesn't own |
|---|---|---|---|
| 1 — Canonical TaxonomyRef | Each classifier agent | Mapping from its native output to a canonical (namespace, id) pair | Other classifiers' mappings, cross-namespace equivalences |
| 2 — Event-based clustering | `orpheus-agent-event-correlator` | Grouping classifier observations into "physical events" by sensor + time + audio.motion lineage | Species identity, taxonomies |
| 3 — TaxonomyEquivalence registry | `orpheus-common` (a shared library, not an agent) | The bidirectional, transitive equivalence graph; the helper APIs to consult it | Detection mechanics; the existence of any particular classifier |
| 3' — Equivalence auto-discovery | `orpheus-correlator` worker (or a separate process) | Observing co-occurrence and proposing equivalence rows | Accepting them (that's a human or a confidence threshold) |

**The key holonic property:** if you add a new classifier tomorrow
(say `orpheus-agent-spectrogram-cnn`), the work needed is **entirely
local to that new agent** — write its mapping into the canonical namespace.
You don't touch the correlator, you don't touch other agents, you don't
edit a shared dict. The new agent's output is interoperable as soon as it
emits a well-formed TaxonomyRef.

---

## 3. Layer 1 — Per-classifier canonical `TaxonomyRef` at the source

### The contract

Every emitting agent (any agent that publishes a `Detection`) **must**
populate the `Detection.taxonomy` field with a `TaxonomyRef` in a
well-known namespace. The TaxonomyRef.id is the canonical identifier
within that namespace.

```python
# orpheus_common.detection.TaxonomyRef (already exists per ADR 0011)
class TaxonomyRef(BaseModel):
    namespace: str         # well-known ID for the taxonomy authority
    id: str                # canonical identifier within the namespace
    common_name: Optional[str] = None
```

`namespace` must be one of the values in the **Well-Known Namespace Registry**
(see §3.2). Adding a namespace is a documentation change with two-line
support in `orpheus-common`; it is not an agent change.

### Per-classifier mappings (concrete)

Each classifier owns a small mapping module that translates its native
output into a TaxonomyRef. These modules live inside the respective agent.

| Classifier | Native output | Maps to namespace | Mapping module |
|---|---|---|---|
| BirdNET (`orpheus-agent-bird-detection`) | `"Corvus brachyrhynchos_American Crow"` (latin_common pair from `labels.json`) | `"ioc"` (IOC scientific name — directly what BirdNET emits) | `birdnet/taxonomy_mapping.py` |
| crow-tools (`orpheus-agent-crow-detection`) | `"crow"` or `"unknown"` (binary corvid-flag, NOT a species ID) | **(no TaxonomyRef emitted)** — see note below | n/a |
| audio-events (`orpheus-agent-audio-events`) | AudioSet machine_id (e.g. `"/m/04s8yn"`) | `"audioset"` | the existing `audioset_ontology.py` already does this |

**crow-tools deliberately does not emit a TaxonomyRef.** Reading the
actual implementation (`classifier.py`), crow-tools is a *call-type
analyzer* on top of an upstream corvid detection — it determines `alert`
vs `contact` vs `territory`, age class, and quality, but its species
field is just `"crow"` or `"unknown"`. It does not independently
identify which corvid species (American Crow vs Common Raven vs Fish
Crow). That identity lives on the upstream `species.detected` event
from BirdNET, which under Layer 2 will be evidence on the same Entity
as the `crow.analyzed` event. crow-tools's contribution is call-type
metadata, not species classification, and forcing a `(orpheus.custom,
corvidae)` ref would be a noise-up rather than a clarification.

If a future bird model in the crow agent does emit species-level
identification (e.g. a "BirdMixIT-style" separation that names the
exact corvid), this changes — add a `crow_detection/taxonomy_mapping.py`
mapping module at that point.

**Why `ioc` and not `ebird` for bird agents:** BirdNET emits IOC scientific
names directly. eBird alpha codes would require a Latin → alpha lookup
table that we'd have to maintain in sync with BirdNET label updates.
Scientific names are also globally unique (eBird alpha codes only need to
be unique within the eBird taxonomy). Both bird agents using the same
namespace (`ioc`) means BirdNET ↔ crow-tools merging works without any
equivalence-table lookup. The equivalence table handles the residual
`ioc` ↔ `audioset` cross-namespace bridge for species PANNs also tags.

`ebird` remains in the namespace registry as a reserved future option
(e.g. if we ever integrate the eBird API directly).

**The mapping module contract:**

```python
# agents/orpheus-agent-X/src/.../taxonomy_mapping.py

def to_taxonomy_ref(native_code: str) -> Optional[TaxonomyRef]:
    """Map this classifier's native species_code to a canonical TaxonomyRef.

    Returns None if the code is unknown (the agent should still emit the
    Detection with `taxonomy=None` rather than dropping it; downstream
    consumers handle the None case).
    """
```

Unit tests live with the agent. The mapping module is a unit-testable
artifact — adding a new species mapping is a test+data change.

### Why this kills 80% of the duplication immediately

BirdNET and crow-tools already use **the same animal** with two different
labels. BirdNET maps to `(ioc, "Corvus brachyrhynchos")` and crow-tools emits
no ref at all, so they never compete; Layer 3 handles the residual
`(ioc, …)` against `(audioset, "/m/04s8yn")`. Under Layer 2 they cluster
together with no equivalence-table
lookup needed. The equivalence table (Layer 3) only handles the residual
cross-namespace case: `(ebird, "amecro")` vs `(audioset, "/m/04s8yn")`.

That residual case is what an actual taxonomy authority can answer (Cornell
Lab has eBird-to-AudioSet mappings for a chunk of common birds), so even
the equivalence table starts mostly pre-populated from external data.

### 3.2 Well-Known Namespace Registry

The registry is a frozen set of strings in `orpheus-common`. Lock these as
v1; adding a namespace requires a doc PR + one-line code change.

| Namespace | Example id | Source / authority | Notes |
|---|---|---|---|
| `"ebird"` | `"amecro"` | Cornell Lab eBird alpha codes | Bird species canonical key; BirdNET + crow-tools map here |
| `"ioc"` | `"Corvus brachyrhynchos"` | IOC World Bird List Latin binomial | Alternate bird key; BirdNET emits this too |
| `"audioset"` | `"/m/04s8yn"` | Google AudioSet ontology machine_ids | Coarse "Bird" / "Vehicle" / "Rain" categories — what audio-events emits |
| `"inaturalist"` | `"taxa/12345"` | iNaturalist taxon IDs | Reserved for future iNatSounds-style classifiers |
| `"itis"` | `"179913"` | ITIS taxonomic serial numbers | Reserved for future mammalian / reptile classifiers |
| `"orpheus.custom"` | `"local.crow_alarm"` | Per-deployment custom labels | Escape hatch for purely-internal categories that don't have an external authority |

---

## 4. Layer 2 — Event-based clustering (the correlator refactor)

### The pivot

Today the correlator groups Observations by `(species_code, time-window)`
into a `TemporalCluster`. We change the cluster key to be the
**physical event** — independent of species.

> **Superseded.** The time-window cluster key below shipped, then was replaced
> by same-source graph clustering — interval overlap AND label compatibility —
> because it produced entities like an "Insect" carrying a Loon as evidence. See
> ADR 0013 and [entity-source-identity.md](entity-source-identity.md). The
> section is kept for the Layer-1/Layer-3 context it establishes; the algorithm
> below is **not** what runs.

**Cluster key: time-window only.** Any Observation arriving within
`window_seconds` of the currently-open cluster's last update extends
that cluster. When the window expires (no new Observations for
`window_seconds`), the cluster closes and emits an Entity.

```python
# Pseudocode
on_observation(obs):
    if open_cluster is None or (now - open_cluster.last_updated) > window:
        close_and_emit(open_cluster)
        open_cluster = new_cluster()
    open_cluster.add(obs)
    open_cluster.last_updated = now
    reset_timer(window_seconds)

on_timer_fire():
    close_and_emit(open_cluster)
    open_cluster = None
```

This is the right primitive for single-site Orpheus deployments:
- **Multi-mic**: three mics hearing the same crow produce three audio.motion
  events with *different* source_ids — but they're temporally close, so
  they cluster correctly.
- **Multi-species**: a dawn-chorus clip where BirdNET emits one Detection
  per species → all those Observations cluster (one Entity per acoustic
  moment, with evidence per species). This is the multi-species view the
  user explicitly wanted preserved.
- **Three-classifier same-event**: BirdNET + audio-events both firing on
  the same clip → all Observations within the window → one cluster.

The Entity records its `event_signature` as **metadata derived from the
cluster's Observations** — the set of distinct audio.motion source_ids
that contributed, plus the cluster's start/end timestamps. This is
queryable ("which audio.motion events fed this Entity?") but is NOT the
cluster key.

```python
class EventSignature(BaseModel):
    """Derived metadata describing how the cluster was assembled.
    NOT the cluster key — kept on the Entity for traceability."""
    audio_motion_source_ids: list[str]   # all source_ids in the cluster
    start_time: datetime                  # earliest observation timestamp
    end_time: datetime                    # latest observation timestamp
    sensor_ids: list[str]                 # which mics contributed
```

**Single-site assumption:** Orpheus deployments are single-site today.
Time-window-only clustering relies on the fact that all mics on one
Floating Tank are exposed to roughly the same acoustic event at roughly
the same time. If a future deployment ever spans multiple physical sites,
the cluster algorithm extends with a sensor-group dimension — but that
work is gated by the multi-site assumption ever changing.

### Schema changes

`EntityEvidence` gains per-evidence taxonomy + species so each opinion is
self-describing:

```python
class EntityEvidence(BaseModel):
    event_id: str
    source_event_id: Optional[str] = None
    sensor_id: str = ""
    clip_path: Optional[str] = None
    confidence: float = 0.0
    intervals: Optional[list[TemporalInterval]] = None   # already exists
    # NEW under Layer 2:
    species_code: Optional[str] = None        # the classifier's native code
    species_common: Optional[str] = None
    taxonomy: Optional[TaxonomyRef] = None    # canonical (from Layer 1)
    detection_type: str = ""                  # which classifier emitted it
```

`Entity` keeps its legacy `species` / `common_name` fields as **display-
only quick labels** populated from the highest-confidence evidence, but
gains an `event_signature`:

```python
class Entity(BaseModel):
    entity_id: str
    timestamp: datetime
    # Legacy display fields — populated from the highest-confidence
    # evidence's species_code/common_name as a quick label. NOT
    # authoritative. Code that needs the real answer reads `evidence`.
    species: str = ""
    common_name: str = ""
    confidence: float = 0.0
    # NEW under Layer 2:
    event_signature: dict       # serialised EventSignature
    evidence: list[EntityEvidence]
    context: Optional[dict] = None
```

**There is no `species_consensus` field.** Evidence is the source of
truth — a dawn chorus with five species vocalizing produces one Entity
with five pieces of evidence (or more, with multiple classifiers
contributing per species). Collapsing that to a single "consensus
species" would defeat the entire point of moving to event-based
clustering. The legacy `species`/`common_name` fields exist for casual
display (table list, mobile push notifications, etc.); for any decision
that depends on species identity, walk the evidence list.

The Entities page detail view renders the full evidence breakdown
("Crow ← BirdNET 0.9, Robin ← BirdNET 0.7, Bird vocalization ←
PANNs 0.85") so multi-species events are visible at a glance.

### Migration story

The Entity table schema migration is additive: one new column,
`event_signature TEXT NULL`. Existing rows have `species` populated and
`event_signature = NULL` — readable, queryable, just from the old shape.

The UI is updated in the same PR to render either shape. The per-species
query path becomes `WHERE EXISTS (SELECT 1 FROM evidence WHERE
taxonomy ∈ equivalent_taxa(target))` for new rows, falling back to the
old `species` column for legacy rows.

### What this gives us

- One Entity per physical event. The Entities page becomes "things that
  happened, with classifier opinions attached."
- Cross-classifier identity stops mattering at clustering time.
- The "Bird Correlation vs BirdNET" dashboard becomes a property of every
  Entity ("BirdNET's evidence said X, audio-events's evidence said Y") —
  the standalone endpoint becomes redundant or a thin aggregate over
  Entity evidence.
- Per-evidence intervals already work (ADR 0011 + the existing intervals
  propagation), so the UI can show "BirdNET heard a crow from 0–3 s, PANNs
  heard a crow from 0.5–2.8 s" on the same Entity.

---

## 5. Layer 3 — `TaxonomyEquivalence` table + auto-discovery

For the residual cross-namespace cases — e.g. proving that
`(ebird, "amecro")` and `(audioset, "/m/04s8yn")` refer to the same real
animal — we maintain a bidirectional equivalence graph in SQL, not code.

### Schema

```sql
CREATE TABLE taxonomy_equivalence (
    -- Bidirectional: stored both ways for fast lookup, or canonicalised
    -- to (alphabetically-lesser-namespace, lesser-id) and walked
    -- bidirectionally at query time. v1 stores both ways for simplicity.
    namespace_a TEXT NOT NULL,
    id_a        TEXT NOT NULL,
    namespace_b TEXT NOT NULL,
    id_b        TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,   -- "these are the same" certainty
    source      TEXT NOT NULL,               -- "manual" | "auto_discovered" | "ontology_import"
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    notes       TEXT,
    PRIMARY KEY (namespace_a, id_a, namespace_b, id_b)
);

CREATE INDEX idx_taxeq_a ON taxonomy_equivalence (namespace_a, id_a);
CREATE INDEX idx_taxeq_b ON taxonomy_equivalence (namespace_b, id_b);

-- Negative assertions: "we checked, these are NOT equivalent"
-- Prevents auto-discovery from re-proposing rejected matches.
CREATE TABLE taxonomy_non_equivalence (
    namespace_a TEXT NOT NULL, id_a TEXT NOT NULL,
    namespace_b TEXT NOT NULL, id_b TEXT NOT NULL,
    source      TEXT NOT NULL,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (namespace_a, id_a, namespace_b, id_b)
);
```

### Helper APIs (in `orpheus_common.detection.equivalence`)

```python
def equivalent_taxa(
    ref: TaxonomyRef, *, min_confidence: float = 0.5
) -> set[TaxonomyRef]:
    """All TaxonomyRefs equivalent to ``ref``, transitively.

    Walks the equivalence graph via BFS. Returns a set including ``ref``
    itself. Respects negative assertions: a non-equivalence row blocks
    that edge.
    """

def is_equivalent(
    a: TaxonomyRef, b: TaxonomyRef, *, min_confidence: float = 0.5
) -> bool:
    """True iff ``a`` and ``b`` are in the same equivalence class."""

def record_equivalence(
    a: TaxonomyRef, b: TaxonomyRef, confidence: float, source: str
) -> None:
    """Insert (or update) an equivalence row. Idempotent."""

def record_non_equivalence(
    a: TaxonomyRef, b: TaxonomyRef, source: str, notes: str = ""
) -> None:
    """Mark a pair as explicitly NOT equivalent (blocks auto-discovery
    from re-proposing)."""
```

These helpers are pure functions over the DB. Every consumer (correlator
queries, corollary discharge, UI species filter, future Director) calls
the same APIs.

### Auto-discovery worker

A background job runs periodically (every 1-6 h is fine — this is not
latency-sensitive):

```text
For each pair of (TaxonomyRef A, TaxonomyRef B) seen on a shared
source_event_id within the last N days:
  occurrences_A     = count of source_event_ids where A fired
  occurrences_B     = count of source_event_ids where B fired
  co_occurrences_AB = count of source_event_ids where BOTH fired
  jaccard           = co_occurrences_AB / (occurrences_A + occurrences_B - co_occurrences_AB)

If jaccard >= AUTO_PROPOSE_THRESHOLD (default 0.6) and the pair is not
already in taxonomy_equivalence or taxonomy_non_equivalence:
  insert with source="auto_discovered", confidence=jaccard

Two gates the sketch above omits and the shipped worker applies:
`min_cooccurrences` (default 5) skips thin pairs outright, and
`cross_namespace_accept_only` caps same-namespace pairs at `pending_review` even
above the accept threshold — so two species that merely share a dawn chorus are
never auto-merged. The config keys are `accept_threshold` and
`propose_threshold` under `correlation.auto_discovery`.
```

A separate threshold (`AUTO_ACCEPT_THRESHOLD`, default 0.9) governs
whether the row is treated as "active" immediately or queued for human
review.

For the corvid crow case in real Michigan data we expect jaccard to be
very high quickly — BirdNET and PANNs fire on the same audio.motion event
almost every time there's a crow.

### Consumers

| Consumer | What it does with Layer 3 |
|---|---|
| Entities API filtering by species | "Find all Entities where any evidence has a TaxonomyRef equivalent to `(ebird, amecro)`" — does a graph walk via `equivalent_taxa()`, then `WHERE evidence.taxonomy IN (set)`. |
| Bird Correlation dashboard | Replaces today's hard-coded `BIRD_LIKE_AUDIOSET_MIDS` set with `equivalent_taxa(TaxonomyRef("ebird", "any-bird-parent"))` once the equivalence graph has crow ↔ AudioSet:Crow rows. (Until then, the hard-coded set is fine.) |
| Future corollary-discharge filter | When the playback agent plays a clip with `played_taxonomy=(ebird, "amecro")`, the filter consults `equivalent_taxa()` to know that an incoming `(audioset, "/m/04s8yn")` Detection from our own mic is self-generated. |
| Future Director agent | Reasoning about "did a coyote visit?" without caring which specific classifier said so. |

---

## 6. Why this all matters for corollary discharge (and beyond)

The "echo problem" (the backlog issue
`[CORE] Implement Corollary Discharge (The "Echo" Problem)`) needs the
exact same primitive Layer 3 provides:

> When the system plays a crow call through the speaker, its own
> microphone hears it and triggers a detection.

To tag that re-detection as self-generated, the filter has to ask:
"is this incoming Detection's taxonomy equivalent to the taxonomy I played
N seconds ago?" That's `is_equivalent(playback_ref, detection_ref)`. The
filter doesn't need a hierarchical taxonomy; it just needs the
equivalence primitive.

Same for the Director agent later: "Did we observe a coyote tonight?"
becomes a query over Entity evidence with `equivalent_taxa()`. No species
hand-coding in the Director's logic.

The Layer 3 primitive is a thin shared service. Every agent that needs identity resolution consults it. Adding
a new agent doesn't change the primitive.

---

## 7. What we deliberately do **not** do here

- **Full hierarchical ontology** (`Animal.Bird.Corvidae.Corvus.brachyrhynchos`
  tree, cluster-at-genus-level, etc.) — that's the
  `[ARCH] Generalize the EntityEvent State Space Taxonomy` backlog issue.
  When it lands, it can use the same TaxonomyRef + Equivalence primitives;
  it just adds a third axis (parent-of relationships).
- **Sensor-geometry-aware multi-mic clustering** — the
  single-site assumption stands and there is no `sensor_group` concept (§9.2).
  The "two mics 3 m apart heard the same crow" cross-mic merging is left for a
  follow-up.
- **Per-species confidence calibration across classifiers** — when BirdNET
  says 0.6 and PANNs says 0.85, how do we synthesise a single confidence?
  Smarter aggregation is future work; there is no `species_consensus` field (§4).
- **Realtime equivalence updates** — auto-discovery runs as a periodic
  background job; live agents read a snapshot. No live propagation needed
  because equivalence is essentially static (~minutes to update is fine).

---

## 7.5 Late-arrival enrichment (deferred to follow-up commit)

Once `root_event_id` propagation is in place (Layer 1.5, see commit
sequence below), the correlator can re-attach late-arriving downstream
events to their already-emitted Entities. The mechanism:

1. After emitting an Entity, the correlator keeps an in-memory
   `recent_entities: dict[root_event_id, entity_id]` map with a TTL
   (e.g. 5 minutes — generous enough to outlast slow downstream models).
2. When a new Observation arrives whose `root_event_id` matches an entry in
   this map, the correlator enriches the existing entity instead of creating a
   new cluster.
3. What shipped uses a different API than this sketch — there is no
   `append_evidence` — and publishes to `orpheus/entity-updates/animal`, a
   sibling root rather than a child, so an entity-creation wildcard cannot
   double-count the update. See §1.1 for the shipped mechanism.
4. Subscribers to `orpheus/entities/animal` receive an
   `entity.updated` event (new topic) so live consumers (UI, future
   Director) refresh their state.

Until this commit lands, late-arriving crow.analyzed events produce a
separate Entity that consumers can still relate to the original via
`root_event_id` querying (view-time correlation). The data model
supports both modes; the choice of when to consolidate is an
implementation detail.

## 8. Commit sequence (within this PR)

Each step is independently testable. Order matters because Layer 2 builds
on Layer 1's TaxonomyRefs.

1. **Strip the alias map.** ✓ (done)
2. **`orpheus-common` namespace registry.** Add a frozen `KNOWN_NAMESPACES`
   set and the `Detection.taxonomy.namespace` validation against it.
3. **Layer 1 — BirdNET mapping module.** `birdnet/taxonomy_mapping.py`
   parses BirdNET's `"Scientific_Common"` labels and emits
   `(ioc, scientific)` TaxonomyRefs. Bird-detection populates
   `Detection.taxonomy` on emission. ✓ done.
4. **Layer 1 — crow-tools clarification.** Document that crow-tools does
   NOT emit a TaxonomyRef (it's a call-type analyzer, not a species
   classifier). Comment in main.py points readers at the design doc.
   ✓ done.
5. **Layer 1 — audio-events.** Already populates
   `TaxonomyRef(namespace="audioset", ...)` on every emitted Detection
   (shipped in the earlier audio-events agent commit). ✓ done.
5.5. **Layer 1.5 — root_event_id propagation (chain spine).** Add
    `root_event_id` to Detection. Each agent inherits and propagates
    so downstream consumers can find the originating audio.motion
    event in O(1) without walking the chain. Underpins the
    late-arrival enrichment work in §7.5.
6. **Layer 3 — schema migration.** New `taxonomy_equivalence` and
   `taxonomy_non_equivalence` tables via `ensure_schema_updates()` in
   `orpheus-common`. Idempotent.
7. **Layer 3 — `equivalence.py` helpers.** `equivalent_taxa`,
   `is_equivalent`, `record_equivalence`, `record_non_equivalence`. Pure
   functions; unit tests with synthetic equivalence graphs (transitivity,
   negative assertions, confidence thresholds).
8. **Layer 3 — seed data.** Insert the crow-family cross-namespace
   equivalences as `source="manual"` rows. Replaces the alias map's
   data, in proper data form.
9. **Layer 2 — `EventSignature` + cluster-key change.** Refactor
   `ClusterManager.process_observation` to key on event_signature instead
   of species_code. Update tests.
10. **Layer 2 — schema migration on `entities` table.** Add
    `event_signature TEXT NULL` column. Additive. Legacy
    `species`/`common_name` stay populated by the cluster manager as
    display-only labels from the highest-confidence evidence.
11. **Layer 2 — EntityEvidence per-evidence taxonomy.** Add the new fields
    (`species_code`, `species_common`, `taxonomy`, `detection_type`) to
    EntityEvidence. Correlator populates them from each Observation.
12. **Layer 3 — auto-discovery worker.** A periodic asyncio task inside the
    event-correlator, **enabled by default** (`correlation.auto_discovery.enabled:
    true`, six-hour interval, seven-day lookback). Pairs at Jaccard ≥
    `accept_threshold` record as `accepted` and merge live; those in
    `[propose_threshold, accept_threshold)` record as `pending_review` for
    approval at `/equivalences`.
13. **Backend: Entities API species filter via `equivalent_taxa()`.**
14. **UI: Entities page renders per-event with evidence breakdown.**
15. **UI: Bird Correlation dashboard sources its bird-like set from
    `equivalent_taxa()` rather than the hardcoded MID set.**
16. **Backfill: optional one-shot job to compute `event_signature` and
    `species_consensus` for legacy Entity rows. Skippable.**

---

## 9. Resolved decisions

1. **BirdNET emission: single TaxonomyRef per Detection in the `ioc`
   namespace.** Use the scientific name from BirdNET's
   `Latin_Common`-formatted labels directly (no Latin-to-alpha lookup
   needed). crow-tools emits **no** TaxonomyRef — it is a call-type analyzer,
   not a species classifier (§3), and takes its species identity from the
   upstream `species.detected` event.
   Layer 3 handles the residual `ioc` ↔ `audioset` cross-namespace
   bridge. (Earlier draft preferred `ebird` alpha codes; flipped to
   `ioc` because that's what the model actually emits.) If a future
   bird model needs to expose richer per-detection structure
   (multiple candidate refs with per-candidate confidence), it goes
   into `Detection.metadata` as model-specific data, not by overloading
   `Detection.taxonomy`.
2. **No `sensor_group` concept.** Single-site assumption holds; multi-
   site is a hypothetical future addition. EventSignature is just
   `(audio_motion_source_ids, time_bucket)`.
3. **Auto-discovery worker lives inside the event-correlator** as a
   periodic asyncio task. If it ever grows to the point of fighting the
   correlator for resources or attention, it gets spun out as a sub-agent
   then — not pre-emptively.
4. **Equivalence thresholds (v1 defaults; tune after observation):**
   - `AUTO_ACCEPT_THRESHOLD = 0.9` — Jaccard ≥ this auto-inserts a row
     with source="auto_discovered". Active immediately.
   - `AUTO_PROPOSE_THRESHOLD = 0.6` — Jaccard in [0.6, 0.9) inserts a
     row but flagged `pending_review` (a `status` column on the table).
     Active when status flips to "accepted".
   - Below 0.6: ignored.
   - These defaults live in `orpheus.yaml` and can be tuned in deployment.
   - Document for retuning after roughly 80 hours of real operation —
     we'll have meaningful co-occurrence data by then.
5. **No species_consensus field.** Evidence is the source of truth;
   collapsing to a single consensus species would defeat the purpose of
   event-based clustering. The legacy `Entity.species`/`common_name`
   fields stay as display-only quick labels populated from the highest-
   confidence evidence. Code that needs the real answer walks the
   evidence list.
6. **TaxonomyRef equivalence is reflexive, symmetric, and transitive.**
   Reflexivity is by construction (no row needed: `is_equivalent(a, a)`
   returns True trivially). Symmetry is enforced by either storing both
   directions or canonicalising and walking both ways. Transitivity is
   handled by the BFS walk in `equivalent_taxa()`.

---

## 10. References

- ADR 0011 — Temporal Localisation and Taxonomy References on Detections
- ADR 0006 — Event Hierarchy and Taxonomy
- ADR 0016 — Entity Type Taxonomy, the hierarchical ontology work this design
  is the substrate for (shipped)
- Corollary discharge — the system tagging what it played itself (shipped) —
  the next consumer of Layer 3
- Backlog: `[CORE] State Space Likelihood & Latent Memory` — queries
  Entities by species; will use `equivalent_taxa()`
- Cornell Lab eBird taxonomy: <https://ebird.org/science/taxonomy>
- IOC World Bird List: <https://www.worldbirdnames.org/>
- AudioSet ontology: <https://research.google.com/audioset/ontology/>
