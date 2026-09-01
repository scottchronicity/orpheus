# Event-Sourcing Determinism Contract

**Status:** Contract — binding, and in force. §1–§3 are prose that binds the
implementation. All four of §4's surface prerequisites shipped in
`event_bus_nats.py` (`stream_ensure`, `stream_publish`, `stream_replay`), and the
`audio.motion` shadow publishes behind `event_sourcing.shadow_publish_enabled`
(default off). Read §4's "Required" items as shipped, per
[`observability-and-event-sourcing.md`](./observability-and-event-sourcing.md) §3.

**Why this exists.** The destination (ADR 0017, backlog `[CORE] Event-sourcing`)
is "the durable JetStream log becomes the source of truth and the SQLite DB a
projection." That promise is only honest if **replaying the log reconstructs the
same state** — otherwise a 2029 rebuild silently invents data that never existed.
This document is the contract that makes "rebuild by replay" safe. Until every
clause here holds, SQLite stays the source of truth and the stream is **shadow-only**
(`event_sourcing.shadow_publish_enabled: false` by default).

This is **pure prose**. It binds the implementation; it ships before the shadow
publishes and long before any authoritative rebuild.

---

## 1. Column classification — what survives a rebuild

Every column of every persisted table, classified as:

- **payload-authoritative** — present in the domain event payload (the
  `Detection`); a rebuild reproduces it byte-for-byte. ADR 0012 guarantees
  `event_id` fidelity, which anchors this class.
- **rebuild-volatile** — a local artifact of *this* DB (rowids, insert
  wall-clocks). It legitimately differs across rebuilds and **must never be keyed
  on as identity**.
- **derived-non-reconstructable** — produced by re-running logic over the stream,
  and **not** faithfully reproducible from the detection stream alone (depends on
  state the stream does not carry).

### 1.1 `detections` (agent-owned, 1:1 with a domain event — the easy table)

| Column | Class | Note |
|---|---|---|
| `event_id` | payload-authoritative | The identity key. `UNIQUE NOT NULL`; ADR 0012 fidelity. Rebuild upserts on this. |
| `timestamp` | payload-authoritative | Event time (ISO-8601), from the payload — **not** insert time. |
| `detection_type` | payload-authoritative | |
| `channel` | payload-authoritative | |
| `species_code` / `species_common` | payload-authoritative | |
| `confidence` | payload-authoritative | |
| `audio_clip_path` | payload-authoritative (path); **file may be absent** | The string reconstructs; the *clip file* may have rolled off retention. A rebuild restores the row, never the media. |
| `metadata` / `event_metadata` | payload-authoritative | JSON; `event_id`/`source_event_id`/`context` serialized. |
| `source_event_id` / `root_event_id` | payload-authoritative | The chain identity (cross-classifier-identity). |
| `id` | **rebuild-volatile** | `AUTOINCREMENT` rowid. Already absent from `Detection.to_dict()`. **Ban on keying.** |
| `created_at` | **rebuild-volatile** | `DEFAULT CURRENT_TIMESTAMP` = DB insert wall-clock, not event time. Differs every rebuild. **Ban on keying.** |

**Verdict:** `detections` is faithfully rebuildable by replaying the detection
stream and upserting on `event_id`. The only non-reproducible columns are the two
local artifacts (`id`, `created_at`), neither of which is identity.

### 1.2 `entities` (correlator-DERIVED — the hard table, lead with this)

The `entities` table is **not** an agent-owned stream; it is a **projection the
event-correlator computes** by clustering detections. Replaying raw detections
re-runs correlation *under whatever logic is current at rebuild time*. That makes
most of it derived, and two columns **non-reconstructable**:

| Column | Class | Note |
|---|---|---|
| `entity_id` | **derived-non-reconstructable** | A **fresh UUID minted per cluster** at correlation time. A rebuild mints *new* ones → any UI bookmark, citizen-science export, or external reference keyed on `entity_id` **breaks across a rebuild**. |
| `is_self_generated` | **derived-non-reconstructable** | The echo / self-playback flag depends on the system's own **audio-playback windows**, which are **not in the detection stream**. A rebuild cannot recover them → the flag flips for any entity whose echo-window state is lost. |
| `species` / `common_name` | derived | Recomputed (canonicalization, alias/equivalence) under current logic — may differ if that logic changed since the original run. |
| `confidence` | derived | Recomputed from the cluster. |
| `evidence` | derived | The contributing `event_id`s + their data, re-gathered. |
| `context` / `event_signature` | derived | Recomputed cluster geometry (sensors, span). |
| `entity_type` | derived | Recomputed (entity-type taxonomy). |
| `timestamp` | derived | Cluster time, recomputed. |
| `id` / `created_at` | rebuild-volatile | Local artifacts. |

**The rule this forces (load-bearing):**

> **Historical entity identity is NOT stable across a rebuild** unless the
> audio-playback-window events are *also* durably logged on the domain stream.
> Until that is true, **forbid external/persistent keying on `entity_id` for
> historical fidelity** — `entity_id` is stable only within a single live run, not
> across a reconstruction. Citizen-science exports and UI deep-links that must
> survive a rebuild key on the **detection `event_id` chain** (`root_event_id`),
> never on `entity_id`.

Making `entity_id`/`is_self_generated`
reconstructable is a *future* item (durably log playback-window events) and is an
explicit precondition of ever treating a rebuilt `entities` table as authoritative.

---

## 2. Rebuild mode — write-projection-directly, never mutate `orpheus.db`

A rebuild **must never mutate the authoritative `orpheus.db`.** The one sanctioned
mode:

> A rebuild **writes the projection directly** to a **separate / derived DB path**
> via an **idempotent upsert keyed on `event_id`** (whose fidelity ADR 0012
> guarantees). It **never goes through live agents**, **never re-publishes onto live
> topics**, and **never overwrites** the authoritative file. The result is
> **diffed**, and **never swapped in without explicit human action**.

**Rejected mode — `re-publish-live`** (what `ReplayEngine.play()` does today:
re-emit `_replay`-tagged events onto live topics). It would **re-trigger
correlation and re-write rows**, because **no persisting consumer in the repo
guards against `_replay` payloads** (the correlator's `save_entity` has no such
check). If `re-publish-live` is ever wanted for some other purpose, a **repo-wide
`_replay` guard in every persisting consumer** is an explicit precondition.

**Acceptance test:** replay a stream into an already-populated derived DB and assert
row counts + per-row checksums are **unchanged** (idempotency).

---

## 3. Reconciliation — the divergence detector + the only gate to "stream is truth"

The shadow phase publishes detections to the stream *in addition to* the
authoritative DB write. Reconciliation is what proves the two agree before anyone
considers flipping the arbiter. Its unit of comparison is **defined**, not "a tiny
script":

- **Scope:** agent-owned, 1:1-persisted detection types only. The shadow covers all
  four agent-owned detection topics (`DOMAIN_DETECTION_TOPICS`) on one bounded
  stream; reconciliation is scoped per detection type and defaults to
  `audio.motion`, widened with `--detection-type`.
- **Key:** the **`event_id` set-difference**, never a raw count.
- **Excludes** the derived `entities` table entirely (no 1:1 correspondence exists).
- **Legitimate vs buggy divergence, named:**
  - *DB row with no stream message, during the shadow phase* → **expected** (the DB
    is the authoritative writer; the stream is catching up / disabled on some hosts).
  - *Stream message with no DB row* → **the bug worth catching** (a publish the DB
    never recorded — the integrity violation that would corrupt a future rebuild).

The reconciliation `make` target reports the set-difference both ways with that
interpretation. A clean reconciliation over a soak window is the **evidence** any
future arbiter-flip ("stream is truth") is gated on — and that flip stays
human-gated and out of the current horizon regardless.

---

## 4. Prerequisites the durable stream must satisfy *before* it publishes

These are additive surface fixes on the existing `stream_*` primitives. The shadow
was document-only until all four shipped; they have, so it is live behind
`event_sourcing.shadow_publish_enabled` (see the parent design §3.7).

### 4.1 `Nats-Msg-Id` dedup — so stream and DB counts are comparable
`stream_publish` today does a bare `js.publish` with no message id. A publish whose
**ack is lost** on an edge reconnect is re-published as a *distinct* message on
retry, while the DB save is idempotent (`event_id TEXT UNIQUE`). The two planes
would then diverge **by construction under normal edge-network conditions** and §3's
reconciliation would report false positives. **Required:** domain `stream_publish`
sets `Nats-Msg-Id = detection.event_id`, so JetStream's dedup window makes the
shadow idempotent and counts directly comparable.

### 4.2 Dot-free topic grammar — a guarded invariant, not a trusted bijection
`mqtt_to_nats_subject` / `nats_to_mqtt_topic` are **not bijective** (the docstring
warns "a level like `v1.2` would mis-route"; the reverse map blindly does `.`→`/`).
Freezing detections onto NATS subjects makes this **load-bearing forever**
(append-only log + lossy reverse map = unrecoverable rebuild corruption the first
time a dotted topic is persisted). **Required:**
- **Freeze + test the invariant:** every durable-stream topic level matches
  `[a-z0-9_-]+` — **no dots, no wildcards** — **enforced at `stream_publish` with a
  fail-loud guard** so a dot can never silently enter the log.
- **Round-trip property test** (`mqtt → nats → mqtt == identity`) gating any topic
  added to a durable stream.
- *Alternative:* persist the original MQTT topic in a stream **header** so the
  reverse map is a lookup, not a string transform.

### 4.3 Project-then-ack — so a crashed rebuild resumes
`stream_replay` acks each message **as delivered**, on an **ephemeral** consumer.
Fine for offline/read-side replay (what it ships for). But for authoritative
rebuild, a crash mid-projection (DB write fails, OOM on the 8GB Jetson) leaves
**acked-but-never-projected** events the next run does not resume. **Required before
"rebuild by replay" is wired:** the rebuild primitive **projects, then acks** (or
uses a durable named consumer that acks only after the projection commit). Today's
ack-on-delivery ephemeral drain is sufficient **only** for the offline replay it
already serves.

### 4.4 Per-stream bounded retention — so the shadow is reversible-with-no-residue
`stream_ensure(name, subjects)` cannot express `max_age`/`max_bytes`/`discard`. A
shadow stream on `audio.motion` (the highest-volume root) with no `max_age` grows
until it hits the **account-level `max_file_store: 2GB` shared with the KV buckets**
— at which point JetStream returns publish errors **for the whole account** (breaking
KV presence + config-service + everything JetStream). That is not the clean "stop
publishing, it ages out" the reversibility story needs. **Required before the shadow
lands:** an additive `StreamConfig` on `stream_ensure` (a **dedicated stream name**,
explicit `max_age` **and** `max_bytes` set **well under** the 2GB cap,
`discard: old`) + a documented one-command stream-purge `make` target as the revert.

---

## 5. What this contract gates

Until §1–§4 hold and a soak-window reconciliation (§3) is clean, the following stay
out of scope (they are correctness traps without this contract, not perf knobs):

- **Journal + snapshot split** (`start_seq`/`start_time` fast-forward) — snapshotting
  a non-deterministic projection persists invented state.
- **Arbiter flip to "stream is truth"** — human-gated behind reconciliation evidence;
  out of the current horizon.
- **Authoritative rebuild of `entities`** — blocked until playback-window events are
  durably logged (§1.2), so `entity_id`/`is_self_generated` become reconstructable.

What is *unblocked* by this contract: the **shadow publish** of `audio.motion`
(once §4 ships), the **`event_id` reconciliation** that earns the trust, and an
**offline read-side replay / derived-view rebuild** that never touches `orpheus.db`
(§2).

## Where this lives in the tree

- `platform/orpheus-common/src/orpheus_common/detection/database.py` — both
  `CREATE TABLE` statements and `ensure_schema_updates()`
- `platform/orpheus-common/src/orpheus_common/detection/models.py` —
  `Detection.to_dict()`
- `platform/orpheus-common/src/orpheus_common/event_bus_nats.py` — `stream_ensure`,
  `stream_publish`, `stream_replay`, and the subject mapping
- `platform/orpheus-common/src/orpheus_common/event_sourcing.py` — the shadow
- `platform/orpheus-common/src/orpheus_common/reconcile.py` — the §3 job
