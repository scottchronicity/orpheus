# ADR 0016: Entity-type state-space taxonomy

**Status:** Accepted

**Date:** 2026-06-26

**Deciders:** Scott, Development Team

**Backlog:** "[ARCH] Generalize the EntityEvent State Space Taxonomy" (Epic 1)

## Context

The correlator emits `EntityEvent`s identified only by a flat `species_code`
string. Epic 1 (the cognitive holarchy) needs a richer, semantic state space —
`Animal → (Bird, Critter)`, `Human → (Known, Unknown)`, `Plant` — that most
downstream work depends on. The ASR asks for an `entity_type` that *replaces*
the flat string, a Pydantic `EntityEvent` model, a data-driven taxonomy file,
backward-compatible MQTT, and a migration.

Two repo realities shape the design:

1. **The Reversibility Contract** (the studio stacks many commits and rolls the
   whole branch back to bare `main`): schema must be additive, config
   defaulted, new behavior off-by-default, MQTT additive; the previous binary
   must read the new DB untouched.
2. **There is already a cross-classifier identity system** — `TaxonomyRef`
   (ioc / audioset / ebird), the `species.py` predicates (`is_corvidae`), and
   `taxonomy_bridge._CLADE_BRIDGES` (AudioSet mid → clade predicate). A second,
   parallel identity authority would be a serious smell.

## Decision

`entity_type` is an **additive, derived, nullable projection** of the existing
identity — not a replacement, and not a new authority.

- **Registry, not enum.** The canonical `entity_type` is a dotted string
  (`"Animal.Bird.Crow"`) validated against a tree loaded from
  `detection/data/entity_taxonomy.yaml` (`entity_taxonomy.EntityTaxonomy`).
  Data-driven so the taxonomy extends by editing data, not code — and so it
  survives Python 3.9 (no `match`). Mirrors the `KNOWN_NAMESPACES`
  frozenset-registry precedent. Internal nodes are valid types too: a detection
  may resolve only to `Animal.Bird` (coarse) — there is **no `_self` sentinel**,
  so `topic_for` stays injective.
- **Derivation reuses the existing seams.** `derive_entity_type` resolves
  through a single `predicate → leaf` table: the IOC path runs the predicate on
  the scientific name; the AudioSet path maps a mid → its predicate via
  `_CLADE_BRIDGES` (the **single source** of the mid list) → the same leaf. Then
  a specific `legacy_species_codes` map, then a coarse `detection_type` default.
  No mid list is copied into the YAML. The per-evidence `TaxonomyRef` remains the
  source of truth; `entity_type` is documented "not authoritative."
- **Entity-level rule: the display pick.** An entity's `entity_type` derives
  from the same highest-confidence "display" observation that sets
  `species_code`, so the two are always consistent (rather than a "most-specific
  wins" rule that could contradict the displayed species).
- **`EntityEvent` model** (`events.py`) is a standalone `BaseModel` mirroring the
  correlator's emit dict (NOT an `OrpheusBaseEvent` subclass, whose
  `event_id`/`event_timestamp`/model-`context` would collide). The correlator
  builds *through* it, so the model is the single source of the wire shape (the
  emit dict is its additive superset), not a dead parallel type.
- **Additive persistence.** `entities.entity_type` is a recipe-31 additive
  nullable column; `species TEXT NOT NULL` is untouched. Old binary ignores the
  column; new binary migrates a legacy DB and reads pre-migration rows as `None`.
- **Backward-compatible topics.** `orpheus/entities/animal` is **always**
  published. Behind `correlation.publish_entity_type_topics` (default `false`)
  the correlator *also* publishes on the `entity_type`-routed topic
  (`orpheus/entities/animal/bird/crow`). The legacy topic is never removed, so
  the compat requirement holds unconditionally.
- **Migration.** `backfill_entity_types` (+ `make backfill-entity-types`)
  populates `entity_type` where NULL using the *same* `derive_entity_type` as
  live emission, idempotent and streamed (mirrors the `root_event_id` backfill).

## Consequences

- Adding a type is a YAML edit; adding a clade is one predicate in
  `species.py` + two YAML lines (AudioSet mids stay single-sourced). `Human.*`, `Plant`, `Animal.Critter` are declared but
  unreachable until a detector emits them — intentional (the state space is the
  point).
- `entity_type` is coarse and lossy for multi-species clusters (it mirrors the
  existing `species_code` display pick). The full picture stays in per-evidence
  taxonomy. If a consumer later needs all of a cluster's types, add an additive
  `entity_types: list` — don't pre-build it.
- Whole change is additive + off-by-default; reverting any commit leaves a green
  tree. The deferred `species`-flat-string removal the ASR imagined is
  explicitly NOT done (it would break reversibility).
- Replay topic-routing is a follow-up (replay keeps the legacy topic, which now
  carries `entity_type`).
