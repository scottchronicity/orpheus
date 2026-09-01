# Read-Only Portal Architecture

**Status:** Implemented — items 1, 2 and 4–7 of §5 are shipped (read-only
`DetectionDB`, `expand_species_filter` lifted, replica dashboard behind
`ui.read_from_replica`, `portal/` projection + `ReadModel`,
`orpheus-public-export` JSON with provenance envelope). **Item 3 did not ship:**
`hourly_activity` and `species_activity_in_range` are still raw SQL in
`entities.py`. Plus
the N2 read-surface protection (`ui.rate_limit_enabled` / `ui.query_timeout_seconds`).
The public data-only frontend (item 8) and the MCP / citizen-science seams (9–10)
remain.
**Builds on (shipped):** `orpheus_common.mirror` (snapshot + transports + `orpheus-mirror` agent); `open_connection(read_only=True)` (`mode=ro` URI floor).

## Thesis

The owner wants "Orpheus UI = mainly a library; the dashboard, public
site, mirror, MCP, and export are thin embodiments." The honest reading
of the code is that **the shared layer is the read/query layer in
`orpheus_common.detection`, not the React app.** Two genuine,
non-speculative wins remain:

1. **DRY** — the query layer already lives in `orpheus-common`
   (`DetectionDB`, `equivalence`, `state_space`, `entity_taxonomy`,
   `mirror`). The only un-shared read code is a handful of raw-SQL
   reimplementations inside `services/orpheus_ui/backend/src/orpheus_ui/api/entities.py`.
   Lift those down so every embodiment shares one audited path.
2. **Safety** — there was no public/private boundary when this was written.
   `GET /api/entities` serialized `"context": ent.context` (raw
   lat/lon/elevation/sensor_id), `evidence` (clip paths), and
   `event_signature` straight to the client, so any internet-facing
   embodiment reusing it would have inherited the leak. That is what the
   `PublicProjection` chokepoint below was built for; it ships in
   `orpheus_common/portal/` with `SENSITIVE_FIELDS` and
   `PUBLIC_ALLOWED_KEYS`. The dashboard API is still the private one, and is
   meant to stay behind authentication.

So: lift the read/query helpers into `orpheus-common`, add **one
`PublicProjection` chokepoint**, repoint the existing dashboard at the
replica (config-gated, reversible), and add the public site as a thin
**static generator** over the projection. Defer the React-component/NPM
refactor and MCP/export as documented seams (no empty modules).

We **do not** build the speculative `data_views.{internal,public,mcp,
citizen_science}` four-namespace matrix. There are two live consumers
(internal full-fidelity, public coarsened). "Internal" is just "the read
model with no projection" — it needs no module. MCP/export are seams.

---

## 1. Architecture

### 1.1 Shared library boundary

Everything lands in the existing
`platform/orpheus-common/src/orpheus_common/` tree. No new top-level
repo, no NPM packages, no frontend churn.

```
platform/orpheus-common/src/orpheus_common/
  detection/
    database.py        # EXISTS — DetectionDB + open_connection(read_only=)
                       #   CHANGE: add read_only to DetectionDB.__init__ (see §3, §4)
                       #   LIFT:   hourly_activity(), species_activity_in_range(),
                       #           detection_metadata_by_ids()  (from entities.py)
    equivalence.py     # EXISTS — TaxonomyEquivalenceDB.equivalent_taxa()
                       #   LIFT:   expand_species_filter()  (from entities.py — privacy-load-bearing)
    models.py          # EXISTS — Entity, EntityEvidence, Detection, TaxonomyRef
    entity_taxonomy.py # EXISTS — EntityTaxonomy.entity_type_for() (coarse clade)
  state_space.py       # EXISTS — StateSpaceMemory
  mirror.py            # EXISTS — snapshot_db / mirror_once / run_mirror / transports / agent
  config.py            # EXISTS — MirrorConfig (staging_path), SiteConfig (lat/lon)
                       #   ADD:    PublicProjectionConfig (registered like self.mirror)
  portal/              # NEW (the only meaningful new library surface)
    __init__.py        #   public surface: ReadModel, PublicProjection,
                       #   PublicEntityRecord, PublicProjectionConfig, SENSITIVE_FIELDS
    read_model.py      #   ReadModel — the public-path HANDLE that withholds Entity
    projection.py      #   PublicProjection — THE chokepoint (§2)
    records.py         #   PublicEntityRecord — the ONLY type a public path may emit
    coarsen.py         #   coarsen_time(), coarsen_location() — config-driven, fail-closed
```

**`ReadModel`** is a thin handle, not a god-object. The lifted query
methods land on the existing classes (`DetectionDB`,
`TaxonomyEquivalenceDB`) where they belong — that's the DRY win and it
needs no facade. `ReadModel` exists for exactly one reason: it is the
object the **public path holds instead of an `Entity`**. It hands the
public path only `PublicProjection`-wrapped iterators; it never returns a
raw `Entity` to a public consumer. (Per the hybrid critique: don't add a
facade as a general UI dependency — the UI keeps using `DetectionDB`
directly via its existing singleton.)

### 1.2 Embodiments as thin consumers (text diagram)

```
                      LIVE Jetson DB  (writers: agents only)
                      /data/orpheus/detections/orpheus.db
                              |
                              |  orpheus-mirror agent  (SHIPPED)
                              |  snapshot_db (VACUUM INTO) -> push-only, no --delete
                              v
                      READ-ONLY REPLICA
                      <data_root>/mirror/orpheus.db   (== MirrorConfig.staging_path)
                              |
        +---------------------+--------------------------+-------------------+
        |                     |                          |                   |
   open_connection      open_connection           open_connection      (live OR replica)
   (read_only=True)     (read_only=True)          (read_only=True)     (read_only=True)
        |                     |                          |                   |
        v                     v                          v                   v
  ===========         =================          ==============       ==============
  INTERNAL LAN        PUBLIC STATIC SITE         MCP (SEAM ONLY)      EXPORT (SEAM ONLY)
  DASHBOARD           (orpheus-public-export)    off-Jetson, parked   orpheus-export CLI
  (existing FastAPI   CLI -> static JSON+HTML                         local files only
   + React SPA)            |                          |                   |
        |                  |                          |                   |
  ReadModel /         ReadModel (PUBLIC)         ReadModel (PUBLIC)   ReadModel (FULL)
  DetectionDB         => PublicProjection        => PublicProjection  => full Entity
  (FULL fidelity)          |                          |               (platforms need
        |                  v                          v                exact GPS/time)
  Entity.to_dict /    PublicEntityRecord         PublicEntityRecord        |
  rich serializers    (no context/clip/          (no context/clip/    per-platform
        |              exact-time slots)          exact-time slots)    sidecars + WAV
        v                  v                          v                   v
   LAN only           nginx/Caddy static         controlled egress    human uploads
   JWT auth           (no app on hot path)       bearer auth          (no network)
   write paths        zero write paths
   (prefs/audit)      internet-hardened
                      by being a CDN bundle
```

**The fork is structural and chosen at app-construction time**, not
per-request: the public/MCP apps construct a `ReadModel` that *only*
yields `PublicEntityRecord`; they never import the internal serializers
or clip routers (those live in `services/orpheus_ui` and are not
dependencies of the public apps).

| Embodiment | DB handle | Projection | Frontend | New code | Net |
|---|---|---|---|---|---|
| Internal LAN dashboard | replica, `read_only=True` | none (full `Entity`) | existing React SPA, unchanged | repoint + lift consumption | LAN, JWT, write paths |
| Public static site | replica, `read_only=True` | `PublicProjection` (mandatory) | same bundle, data-only JSON | static generator (small) | internet, zero write paths |
| Mirror | n/a (producer) | n/a | n/a | **SHIPPED** | push-only, no `--delete` |
| MCP | replica, `read_only=True` | `PublicProjection` default | n/a | **seam only** (parked) | controlled, off-Jetson |
| Export | live or replica, `read_only=True` | none (full fidelity) | n/a | **seam only** | local files only |

---

## 2. The public/private chokepoint (PublicProjection)

This is the load-bearing safety mechanism. The owner explicitly distrusts
auto-filtering ("a forgotten field leaks"). The answer is to make the
public shape **structurally incapable** of carrying sensitive fields —
an output *type that has no slot for them* plus an *allow-list
constructor* plus an *artifact-scanning test that fails the build* — not
a redactor that strips fields.

### 2.1 The verified leak surface (widened per critiques)

The library-first and hybrid critiques both caught that the leak is
**two independent precise-location channels**, not one:

- **Per-event** lat/lon/elevation/sensor_id ride on `Entity.context`
  (`models.py`), populated by the correlator from
  `SpatiotemporalContext` (`events.py`), and are **already
  serialized raw** at `entities.py`.
- **Site-level** lat/lon live in `SiteConfig` (`config.py`).
- Clip paths ride on `EntityEvidence.clip_path`,
  `Detection.audio_clip_path/video_clip_path`; exact second-precision
  `timestamp: datetime` on both `Entity` and `Detection`;
  `event_signature` (traceability internals); and freeform
  `metadata: dict[str, Any]` bags on both `Detection` and `Entity` that
  can contain arbitrary sensor/debug strings.

`SENSITIVE_FIELDS` (the set the test diffs against) is therefore the
**union of all of these**:

```
SENSITIVE_FIELDS = {
    "context", "lat", "lon", "elevation", "sensor_id",
    "clip_path", "audio_clip_path", "video_clip_path",
    "timestamp",            # exact second-precision
    "event_signature", "metadata", "evidence",
    "is_self_generated",
    "source_event_id", "root_event_id",   # lineage ids — join keys back to the private chain
}

Read the set from `orpheus_common/portal/projection.py` rather than from this
copy: an out-of-date privacy kernel is exactly the thing that must not drift.
```

### 2.2 The output type — `PublicEntityRecord`

```python
class PublicEntityRecord(BaseModel):
    species_code: str
    common_name: str
    entity_type: Optional[str]      # coarse clade (Animal.Bird.Crow), already derived
    confidence_band: Optional[str]  # "high"/"medium"/"low"; omitted if unconfigured
    date_bucket: str                # coarsened time — never seconds
    region_label: str               # coarsened location — never raw lat/lon
    # There is NO context, NO lat/lon, NO sensor_id, NO clip field,
    # NO exact timestamp, NO event_signature, NO evidence, NO metadata.
    model_config = ConfigDict(frozen=True)   # hygiene, not the privacy kernel (see 2.4)
```

`PublicProjection.project_entity(entity: Entity) -> PublicEntityRecord`
is the **only** constructor of this type. It is an **allow-list
builder**: it names each field it copies and never does
`entity.to_dict()` / `model_dump()` / `dict(entity)`. A sensitive field
added to `Entity` next month flows nowhere — it is simply never
referenced. This inverts the deny-list failure mode the owner doesn't
trust.

### 2.3 Coarsening (config-driven, fail-closed, no guessed thresholds)

`coarsen.py` holds pure functions:

```python
def coarsen_time(ts: datetime, granularity: str) -> str: ...   # "day" | "hour"; v1 default "day"
def coarsen_location(lat, lon, *, mode, grid_deg, site_label) -> str: ...
```

`PublicProjectionConfig` (registered on `OrpheusConfig` next to
`self.mirror`, with `from_dict` + safe defaults so an old config with no
`public:` section yields a **disabled, fail-closed** projection — the
`MirrorConfig` precedent):

- `time_granularity: str = "day"` — maximally safe v1.
- `location_mode: str = "site_label"` — single coarse owner-supplied
  string (e.g. `"Site A"`). **Grid mode is not shipped in v1.** If/when
  added, `grid_deg` carries a **hard minimum floor** (e.g. reject
  `< 0.05°`, ~5 km) so an owner cannot accidentally publish near-exact
  location. A safety floor is a guardrail, not a guessed product value.
- `site_label: str = ""` — fail-closed: if unset, `region_label` renders
  a constant placeholder, never a real coordinate.
- `confidence_bands` — unset by default → `confidence_band` is
  **omitted**, not guessed.

**Emphasis (per hybrid critique):** in a single-site deployment, lat/lon
is effectively constant, so the dominant exposures are **clips and exact
timestamps**, not coordinates. The projection drops clips/evidence
*entirely* and buckets time *unconditionally*; `region_label` fails
closed to `site_label`. Coordinate-coarsening is a future seam, not the
load-bearing v1 work.

### 2.4 Why it can't be bypassed (structural, not conventional)

Four enforced properties, in priority order:

1. **The artifact-scanning test is the kernel (graft from `minimal`).**
   The fail-closed test runs against the **generator's emitted JSON/HTML
   files**, not just `project_entity`'s return value. It (a) asserts the
   emitted key set is a **subset of an explicit `PUBLIC_ALLOWED_KEYS`
   allow-list** (so a newly-added leaky field on the record fails by
   construction), and (b) greps every emitted artifact for **planted
   sentinels** — a known lat/lon, a clip path, a second-precision
   timestamp. Add a leaky field and CI goes red **before any public byte
   ships.** This converts "convention" into "structural": even though the
   generator *holds* raw `Entity` objects, an accidental `to_dict()` is
   caught by scanning what actually got written to disk.
2. **No clip/coordinate slot exists.** `PublicEntityRecord` has no field
   to put a clip URL or a coordinate on. The public site and MCP
   *cannot* emit media or precise location even by mistake — stronger
   than "return URLs not bytes." Door left open: an opt-in `clip_url`
   field behind a config flag, later.
3. **Read-only + push-only isolation.** Public/MCP open the replica with
   `read_only=True` (`mode=ro` at the SQLite driver level —
   `database.py`). The replica is a *different file on a different
   host*, reached only via push-only `SshRsyncTransport` (no `--delete`,
   `mirror.py`).
4. **`frozen` is hygiene, not the kernel (corrected per all three
   critiques).** We do **not** rely on `extra="forbid"` as "the
   can't-be-bypassed property" — it only rejects unknown *kwargs* on
   construction; it is silent if someone *adds* a leaky field to the
   record class. The real guard is property 1 (the allow-list test).
   `frozen`/explicit-fields are defense-in-depth on a terminal leaf type.

**Audit surface = one file + one test.** To prove no leak: read
`projection.py`, confirm `PublicEntityRecord` has no sensitive fields,
and confirm the artifact test runs in CI.

---

## 3. Reuse map

### Reused unchanged (the working system stays working)

- **Entire React frontend** (`frontend/src/**`) — all pages, components,
  charts, auth. **No** Phase-1–5 extraction, no NPM packaging. The
  static public site reuses the *same build* because `API_BASE = ''`
  (`lib/utils.ts`) already speaks relative URLs — the same bundle is
  servable from the dashboard backend *or* baked into the static site.
  **Privacy is enforced data-side, not component-side:** the public JSON
  is `PublicEntityRecord[]` with no clip field, so even if a page renders
  `ClipActions`, `clipPath` is `undefined` and it shows its expired
  state. (The library-first claim "just don't import `ClipActions`" is
  **false** — clip emission is spread across all six pages
  (`Crows/Birds/Entities/Audio/AudioEvents/Video.tsx`); we do not rely on
  it.)
- **UI FastAPI backend** — all 5 routers
  (`system/cameras/diagnostics/entities/media`). One surgical repoint
  (§4).
- **Mirror pipeline** — `snapshot_db`, `mirror_once`, `run_mirror`,
  transports, the `orpheus-mirror` agent. Consumed as-is.
- **Read-only seam** — `open_connection(read_only=True)`
  (`database.py`).
- **Canonical query methods** — `DetectionDB.query/iter_query/
  count_by_hour/species_distribution/get_chain/get_entities/
  get_entity_by_id`; `TaxonomyEquivalenceDB.equivalent_taxa`;
  `StateSpaceMemory`; `EntityTaxonomy.entity_type_for`.

### Newly built (small, additive)

- `orpheus_common/portal/` — `read_model.py`, `projection.py`,
  `records.py`, `coarsen.py` (+ `SENSITIVE_FIELDS`, allow-list test).
- `orpheus-public-export` CLI + static generator (sibling of
  `orpheus-mirror`'s `main()`), output under
  `$ORPHEUS_DATA_ROOT/public_site/` (never hardcoded).
- `PublicProjectionConfig` registration in `config.py`.

### orpheus-common lifts (DRY consolidation — "one lift over N one-offs")

| UI raw-SQL today | Lift to | Consumed by public v1? |
|---|---|---|
| `_expand_species_filter_via_equivalences` (`entities.py`, wraps `equivalent_taxa` at `:150,165`) | `equivalence.py: expand_species_filter()` | **YES — privacy-load-bearing, lift FIRST** |
| `_compute_entity_stats` (`entities.py`) | `DetectionDB.hourly_activity()` | YES (charts) |
| `_compute_all_species_in_range` (`entities.py`) | `DetectionDB.species_activity_in_range()` | YES (species list) |
| `_fetch_detection_metadata` (`entities.py`) | `DetectionDB.detection_metadata_by_ids()` | **NO — internal evidence panel only; do NOT migrate v1** |

The equivalence lift is **on the privacy boundary** (library-first +
minimal critiques): if the public species list is computed by a
different path than the audited one, a species the owner later intends to
`suppress_species` could appear publicly via an equivalence the
generator expands but the suppression list doesn't cover. Lift it
**before** the public site ships. `_fetch_detection_metadata` is
internal-only — migrating it for symmetry is exactly the speculative
churn the owner forbade; leave it.

---

## 4. Reversibility + migration (additive, no big-bang)

Every step is an independent, revertible commit (Reversibility
Contract). The working dashboard keeps working at every step.

**Step 0 (orpheus-common lift — the real, non-trivial work the `minimal`
critique exposed).** Add `read_only: bool = False` to
`DetectionDB.__init__`; when set, **skip** `_init_schema()` +
`ensure_schema_updates()` (both open a *writer* connection today —
`database.py`) and thread `read_only` into every
`open_connection(self.db_path)` call across the query methods. Without
this, pointing `DetectionDB` at the replica *attempts to migrate the
read-only mirror* and throws. This is an orpheus-common change to the
most-used class in the repo — **not a UI one-liner.** Gated by existing
DB tests + a new test asserting read-only mode never opens a writer
connection. Revert = drop the kwarg.

**Step 1 — lift the read methods** (`expand_species_filter`,
`hourly_activity`, `species_activity_in_range`) into orpheus-common;
`entities.py` calls them. Behavior byte-identical (the lifted code *is*
the existing SQL). **The byte-identical fixture MUST include a species
with known equivalents** (e.g. a corvid pair) or the equivalence gate is
theater (library-first F5; note `equivalent_taxa` has a method form and
a module form with `min_confidence=0.5` — pin the method form). Revert =
restore the local functions.

**Step 2 — add `portal/` (records + projection + ReadModel + tests),
nothing consumes it.** Dead code; revert = delete the dir.

**Step 3 — add `PublicProjectionConfig` (disabled default).** Inert;
`from_dict` empty-section default leaves existing configs untouched
(`MirrorConfig` precedent). Revert = drop the `config.py` line.

**Step 4 — repoint the internal dashboard at the replica (the ONLY
behavior change to the running system).** Gate on config; default keeps
live-DB behavior (prod byte-identical until flipped):

```python
# db.py — additive, reversible
cfg = OrpheusConfig.get_instance()
if cfg.ui.read_from_replica and cfg.mirror.staging_path:
    _db = DetectionDB(db_path=Path(cfg.mirror.staging_path), read_only=True)
else:
    _db = DetectionDB()          # unchanged live-DB default
```

**Critical correctness fix (minimal + hybrid critiques):**
`MirrorConfig` has **no `replica_path`** — the replica is at
`staging_path`. And the repoint is **not** confined to the `db.py`
singleton: `entities.py` construct `DetectionDB()` **directly**
(the equivalence-diagnostics/scan endpoints), bypassing the singleton and
leaving two endpoints on the live DB = split-brain. **Route all
DetectionDB construction through one read-only factory; add a test that
no module-level `DetectionDB()` remains outside it.** Add `ui.read_from_replica`
to a `UIConfig` (or a dashboard flag on an existing config). Revert =
flip the flag. This is the cheap-validation step (resolves the
documented UI/agent contention) and it ships **early**.

**Step 5 — ship `orpheus-public-export` + static generator** (off by
default; runs only when `public.enabled`). New directory, touches zero
existing files. **Retroactive-suppression note (minimal critique):** the
generator is the **sole writer** to the published dir and **fully
replaces** it each run, so a later `suppress_species` is retroactive on
next regenerate. Flag that already-CDN'd files complicate the owner's
"opt-in later" intent — suppression is regenerate-and-repurge, not
edit-in-place. Revert = stop running it / delete the dir.

No step requires another deployed simultaneously. Internal works at every
step (2/3/5 don't touch it; 0/1 are identical-behavior; 4 is a guarded
swap).

---

## 5. Sequenced epics/items (flywheel-pickable)

Ordered; each marked **[small]** / **[big]**. First few are concrete and
build on shipped mirror + `open_connection(read_only=True)`.

1. **[big] Read-only `DetectionDB` constructor.** Add `read_only` kwarg;
   skip schema init/migration when set; thread into all query
   `open_connection` calls. Test: read-only mode never opens a writer;
   write attempt raises. *(Step 0 — unblocks everything.)*
2. **[small] Lift `expand_species_filter` into `equivalence.py`;**
   `entities.py` calls it. Byte-identical fixture **with a corvid
   equivalence pair**. *(Privacy-load-bearing — must precede public.)*
3. **[small] Lift `hourly_activity` + `species_activity_in_range` into
   `DetectionDB`;** `entities.py` calls them. Byte-identical response
   tests. *(Leave `_fetch_detection_metadata` in the UI.)*
4. **[small] Repoint internal dashboard at the replica.** Read-only
   factory routing ALL `DetectionDB()` construction (incl.
   `entities.py`); `cfg.mirror.staging_path`;
   `ui.read_from_replica` flag (default off). Test: no stray
   construction; flipping the flag reads the replica. *(Early
   cheap-validation; fixes UI/agent contention.)*
5. **[small] Add `portal/` records + `ReadModel` handle** that yields
   only `PublicEntityRecord`. Unit test: `ReadModel` public path never
   returns an `Entity`.
6. **[big] `PublicProjection` + `coarsen.py` + `PublicProjectionConfig`
   (disabled, fail-closed).** Allow-list constructor; time-bucket
   unconditional; clips/evidence/context/metadata dropped;
   `region_label` fail-closed to `site_label`; **no grid mode.** Unit
   test: emitted key set ⊆ `PUBLIC_ALLOWED_KEYS`; no `SENSITIVE_FIELDS`
   key present.
7. **[big] `orpheus-public-export` static generator** (JSON under
   `$ORPHEUS_DATA_ROOT/public_site/`, sole writer, full-replace). **The
   artifact-scanning test runs in CI** (subset + sentinel grep on
   emitted files). Off by default behind `public.enabled`. Operator
   rollback note in `DONE.md` (new internet-exposed surface).
8. **[small] Public frontend = data-only build.** Same bundle hydrated
   from `PublicEntityRecord[]`; verify `ClipActions` renders expired
   (no clip field). nginx/Caddy static serve config.
9. **[seam, doc-only] MCP** — `ReadModel` + `PublicProjection` default;
   off-Jetson. **Blocked on the `<3.10` pin (Owner-gate below).** Parked
   per roadmap pivot.
10. **[seam, doc-only] Citizen-science export** — `ReadModel` full
    fidelity (no projection), local files only. Deferred.

---

## 6. Owner-gates + open questions

1. **Python `<3.10` upper pin vs off-Jetson.**
   `orpheus-common/pyproject.toml:12` is `>=3.9, <3.10` — a hard **upper**
   bound. v1 public-export therefore runs **on 3.9, on/near the Jetson**,
   reading the local replica (which is what §1 describes). "Off-Jetson
   3.10+" for MCP/public requires either relaxing the upper pin or
   splitting `portal/` into a thinner package with no cap. **Owner call
   when MCP/off-Jetson public becomes real** — not a v1 assumption.
2. **`UIConfig` vs `MirrorConfig` flag** for `read_from_replica`. Default
   off either way. Lean: small new `UIConfig` (dashboard concerns will
   grow). Confirm placement.
3. **`site_label` value** (e.g. `"Site A"`) — owner-supplied; fail-closed
   placeholder until set. No guessed content.
4. **Confidence bands** — cutpoints are owner thresholds; omitted until
   configured.
5. **Grid mode** — out of v1. If ever wanted, owner sets `grid_deg`
   above the hard floor (~0.05°). Confirm the floor value.
6. **First-version allow-list review.** The chokepoint defends against
   *new* fields; the *initial* `PUBLIC_ALLOWED_KEYS` still needs one
   human review pass. The artifact test pins it thereafter.

---

## Key file citations

- Private-dashboard serialization (raw `context` / `evidence` / `event_signature` — internal-only by design): `services/orpheus_ui/backend/src/orpheus_ui/api/entities.py`
  (`context`/`evidence`/`event_signature` raw).
- Second location channel: `platform/orpheus-common/.../events.py`
  (`SpatiotemporalContext` lat/lon/sensor_id) → `models.py`
  (`Entity.context`); `models.py` (`metadata`).
- Read-only seam: `platform/orpheus-common/.../detection/database.py`.
- Read-only constructor: `database.py` — `DetectionDB(read_only=True)` skips
  `_init_schema()` and `ensure_schema_updates()`.
- Read-only DB factory: `services/orpheus_ui/backend/src/orpheus_ui/db.py`.
  All `DetectionDB` construction goes through it.
- Still-unlifted UI SQL: `_compute_entity_stats` and
  `_compute_all_species_in_range` in `entities.py` (item 3, not shipped).
  `_fetch_detection_metadata` stays internal by design.
- Replica path: `config.py` (`MirrorConfig.staging_path`); config
  registration precedent: `config.py`.
- Mirror (shipped): `platform/orpheus-common/.../mirror.py`.
- Frontend retarget seam: `services/orpheus_ui/frontend/src/lib/utils.ts`
  (`API_BASE=''`).
- Python pin gate: `platform/orpheus-common/pyproject.toml:12`.

NEW (all additive): `orpheus_common/portal/{read_model,projection,records,coarsen}.py`;
`orpheus-public-export` CLI; `PublicProjectionConfig` in `config.py`.
