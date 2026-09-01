# 22 — Schema and migrations

## Models

The canonical Pydantic models are in
`platform/orpheus-common/src/orpheus_common/detection/models.py`:

| Model | Purpose |
|---|---|
| `TaxonomyRef` | `(namespace, id, common_name)`. Frozen, hashable on (ns, id). |
| `TemporalInterval` | `(start_seconds, end_seconds, confidence)`. Intra-clip localisation. |
| `Detection` | Per-classifier event. Has `taxonomy`, `intervals`, `source_event_id`, `root_event_id`, etc. |
| `EntityEvidence` | Per-evidence row inside an Entity. Has its own `taxonomy`, `species_code`, `detection_type`. |
| `Entity` | Correlated event. Has `evidence: list[EntityEvidence]` + `event_signature`. |

`TaxonomyEquivalenceDB` (in `equivalence.py`) stores the cross-namespace
graph. Includes `equivalent_taxa(ref)` and `is_equivalent(a, b)`.

## The "well-known namespace" registry

`orpheus_common.detection.namespaces.KNOWN_NAMESPACES` is the
authoritative list of namespace strings that `TaxonomyRef.namespace`
may take. Currently:

- `ebird` — eBird alpha codes (Cornell Lab); the canonical bird key
- `ioc` — IOC World Bird List Latin binomial; the alternate bird key (BirdNET
  emits these)
- `audioset` — AudioSet machine_ids (PANNs SED emits these)
- `orpheus.custom` — per-deployment custom labels. The escape hatch: use this
  rather than inventing a namespace.
- `inaturalist` — iNaturalist taxon IDs (reserved)
- `itis` — ITIS TSN (reserved)

**Never invent a namespace.** If you need a new one, add it to
`KNOWN_NAMESPACES` and document why in the ADR series.

## Migrations are additive only

Schema changes are introduced via `ensure_schema_updates()` in
`platform/orpheus-common/src/orpheus_common/detection/database.py`.
The rules:

1. **`ADD COLUMN ... TEXT NULL`** (or similar) only. Never alter type;
   never drop. Old code must still read new rows.
2. **`CREATE TABLE IF NOT EXISTS`** for new tables. Idempotent.
3. **Guard ALTER on existing tables** in case the table doesn't exist
   yet (some tests init only a subset of tables):
   ```python
   cursor.execute("PRAGMA table_info(entities)")
   cols = {row[1] for row in cursor.fetchall()}
   if cols and "new_column" not in cols:
       cursor.execute("ALTER TABLE entities ADD COLUMN new_column TEXT")
   ```
4. **Add the column to the `CREATE TABLE` statement too**, for fresh
   DBs.

Forward-rollback compatibility: old code reads new columns? No problem —
unknown columns are ignored by SQLite SELECT. New code reads old rows?
The new column is NULL; downstream code must handle.

## When you add a field to a model

You MUST update ALL of these. A missed step is a silent persistence
bug.

1. **The Pydantic model** in `models.py`. New field with sensible default
   (often `Optional[T] = None`).
2. **`Model.to_dict()`** — include the new key.
3. **`Model.from_dict()`** — read the new key with `.get(...)`.
4. **`Model.derive_*()` helpers** (if any) — update if relevant.
5. **`CREATE TABLE`** statement in `_init_schema` — for fresh DBs.
6. **`ensure_schema_updates()`** — `ADD COLUMN` (idempotent).
7. **`DetectionDB.save()` / `save_entity()`** — add the new column to the INSERT.
8. **`_row_to_<thing>()`** — read the column out via
   `row["new_column"]`. Use `"new_column" in row.keys()` guard if
   you're reading from a possibly-old schema.
9. **Round-trip tests** in `tests/test_detection_database.py` — save
   a model with the new field, query it back, assert the field
   survived.

See commit `1bb7fcd` "Layer 1.5 + Layer 2 persistence" for a full
worked example of adding multiple fields.

## Entity persistence shape

`Entity.evidence` is a `list[EntityEvidence]`, serialised to JSON in
the entities table's `evidence` column. To add a field to
`EntityEvidence`:

1. Add to the Pydantic model.
2. `model_dump(mode="json")` will serialise it automatically.
3. `EntityEvidence(**dict)` will parse it automatically.

No DB column change needed for fields ON the evidence; only at the
Entity-table level.

## The `event_signature` field on Entity

Added in Layer 2. Holds the cluster's derived metadata:
- `audio_motion_source_ids: list[str]` — the chain roots
- `sensor_ids: list[str]` — mics that contributed
- `start_time` / `end_time` — first / last evidence timestamp

`None` for legacy Entities (additive migration). The correlator's
`ClusterManager._build_event_signature` constructs it.

## See also

- [`99-gotchas.md`](99-gotchas.md) — schema landmines (missed save_*
  updates, partial-init test gotcha).
- [`docs/designs/cross-classifier-identity.md`](../designs/cross-classifier-identity.md)
  — the full design of the current schema layering.
- [`docs/adr/0011-temporal-localisation-and-taxonomy-references.md`](../adr/0011-temporal-localisation-and-taxonomy-references.md)
  — the ADR that introduced `intervals` and `taxonomy`.
