# Observability and Event-Sourcing: The Two-Planes Law

**Status:** Design — decisive. Horizon: the boundary law is meant to outlast the stack it describes.
Implementation: the health migration is shipped through Phase 5 (KV dual-write,
`ui.health_source`, `event_bus.health_on_bus`), and the event-sourcing shadow +
`orpheus-reconcile` are shipped — all opt-in / off-by-default.

**One-sentence thesis:** Orpheus has **two planes that follow the grain of
reality** — a *perception/domain* plane that is **lossless and replayable**, and
an *instrumentation/operational* plane that is **sampleable and egress-only** —
and the durable artifact we are freezing is the **law that they never mix**, not
any stack that implements either side.

> **REVISION 1 (owner correction, 2026-06-30).** The first revision of this doc
> said operational health should be **frozen on the domain bus** ("never migrate,
> do nothing to it" — §6.3). The owner **rejected** that: operational health
> **migrates off the domain bus, non-regressively, with UI changes in scope and
> zero regression.** §6.3 is **withdrawn**; the boundary law is **refined** (the
> law governs the durable domain *log/topics*, not NATS-in-general — operational
> signal may ride a separate NATS **KV** substrate). Backlog #95 is re-framed from
> *cut* to *done-non-regressively*. **The authoritative health design is now §11**;
> where the older sections conflict, §11 wins.

---

## Context — the owner's actual question, and the scope worry

Three "stream of events" ideas have been forming, and they are starting to feel
like they might be the same thing — or three competing answers to one question:

1. **NATS JetStream** as the durable domain log (the thing detections live in,
   the thing you replay to rebuild state).
2. **OpenTelemetry** as "the source of events that go into other things."
3. **Local log-based metrics + maybe a local Grafana stack.**

The worry, stated plainly by the owner: *is this going out of scope?* For a
**one-operator box plus OSS users**, on an **8GB GPU-shared Jetson**, is Orpheus
about to grow a distributed-systems observability program it will spend forever
maintaining?

The owner also asked for the **nicest, most durable reconciliation** — something
that "hopefully we don't have to change ever" and "will just always serve the
people who want to use it." That is a request for a **law**, not a stack.

**This is a design effort, not an implementation plan.** The minimal first slice
(§9) exists to prove the seams, not to build the program.

### Verified starting facts (June 2026)

Facts as of the design (June 2026). Several have since changed — see the status
header, and check the code before relying on any of them:

- `telemetry.py` is **tracing-only**, off-by-default, zero-dep no-op when the SDK
  is absent. `get_tracer`/`setup_tracing` mirror `get_logger`. **It has zero
  production callers** (`grep` across `agents/`, `services/`, `platform/`).
- `setup_tracing` is **never called at boot anywhere** — so today even an operator
  who installs `[telemetry]` and sets `enabled: true` gets **zero spans**. The
  seam is only half-wired.
- `event_bus_nats.py` has `stream_ensure` / `stream_publish` / `stream_replay`.
  ~~`stream_ensure` has zero production callers.~~ It has one: `event_sourcing.py`. `stream_publish` does a bare
  `js.publish` with **no `Nats-Msg-Id`** (no dedup). `stream_replay` is a one-shot
  drain on an **ephemeral pull consumer that acks each message as delivered**.
- `stream_ensure(stream, subjects)` takes **only** name + subjects — there is **no
  per-stream `max_age`/`max_bytes`/discard config surface**. The only cap is
  `nats.conf`'s **account-level `max_file_store: 2GB`, shared across all streams
  AND the KV buckets.**
- The subject mapping `mqtt_to_nats_subject` / `nats_to_mqtt_topic` is **not a
  bijection** — its own docstring warns "a level like `v1.2` would mis-route."
- The **default backend is `nats`** (`config/orpheus.example.yaml`), not MQTT.
  MQTT is the explicit fallback and raises `NotImplementedError` on all
  `stream_*` surfaces.
- `Detection.to_dict()` already omits `id` and `created_at`. The `entities` table
  is **correlator-derived** (only the correlator calls `save_entity`), and carries
  `entity_id` (a fresh UUID per cluster) plus `is_self_generated` (depends on
  audio-playback echo-window state that is **not** in the detection stream).
- `pyproject.toml` pins `requires-python = ">=3.9, <3.10"` and
  `opentelemetry-sdk>=1.38,<1.42` with the note "1.41.x is the last line
  supporting Python 3.9."
- **Backlog #95 / Epic 5 exists and conflicts with this design** — see §6.

---

## 1. The two planes and their strict separation

| | **Perception / Domain plane** | **Instrumentation / Operational plane** |
|---|---|---|
| **Question it answers** | "What did the sensors observe?" | "Is the system healthy / where's the latency?" |
| **Carries** | Detections, Entities — the wildlife signal | traces (today); metrics, logs (later, opt-in) |
| **Fidelity** | **Lossless.** Sampling is a category error. | **Sampleable + droppable.** `sample_rate: 0.1` is correct here and *only* here. |
| **Authority** | **Source of truth** (ADR 0017). | **Never** a source of truth. Egress only. |
| **Replayable?** | Yes — `stream_replay` rebuilds state. | No. Telemetry has no replay, no rebuild, no projection. |
| **Substrate** | NATS JetStream durable log → SQLite projection. | OpenTelemetry → OTLP. |
| **Default footprint** | loopback `nats://127.0.0.1:4222`, byte-identical. | **None.** No-op until `[telemetry]` extra + `enabled: true`. |

**The boundary law (the sentence we freeze):**

> *Operational signal never enters the domain log; the domain log never carries
> operational telemetry. They share no wire, no payload, no consumer. The single
> sanctioned crossing is a W3C `traceparent` carried as opaque **transport-header**
> metadata on a domain message — read by the operational plane only, ignored by
> domain logic, droppable with zero domain effect.*

Lossless-vs-sampleable is ontological, not a
preference: the moment the planes merge, `sample_rate: 0.1` starts dropping
*wildlife observations* — telemetry config silently deleting the data the project
exists to collect. The separation isn't tidiness; it is the thing that makes that
failure impossible.

**The crossing is named, not built** — and its *mechanism* is named too, because
the review (correctly) caught that there is nowhere to put it today: domain
messages are JSON dict payloads, and the `EventBus` ABC `publish(topic, payload)`
/ `NatsBus.stream_publish(subject, payload)` signatures **expose no header
channel.** So the law is explicit that `traceparent` rides a **transport header**
(NATS message headers natively support this), **never the JSON body** — putting it
in the payload would violate the law's own "share no payload" clause and persist
telemetry into the domain log. Honoring the crossing later therefore requires an
**additive `headers=` parameter** on `publish`/`stream_publish`; that surface does
not exist yet and is a named prerequisite, not part of this horizon.

---

## 2. Where each existing piece fits

| Piece | Plane | Verdict |
|---|---|---|
| **`telemetry.py`** (`get_tracer`/`setup_tracing`, verified zero-cost no-op) | Operational | **STAYS, unchanged.** Already the right shape; its docstring already scopes itself ops-only. The one addition is a **boot-time `setup_tracing` call** so the seam actually emits (§9, item 4) — without it the tracer is a permanent no-op. |
| **`event_bus_nats.py` `stream_*`** | Domain | **STAYS as primitive — but the slice that calls it requires three additive surface fixes first** (per-stream retention config, `Nats-Msg-Id` dedup, and a `stream_ensure` caller). See §3 and §9. Stays on `NatsBus`, **not** the `EventBus` ABC — MQTT raises `NotImplementedError`; abstracting it is deferred until a 2nd backend needs durable streams. |
| **`replay.py` `ReplayEngine.load`** (hardwired `DetectionDB(db_path=Path(source))`) | Domain | **GROWS one optional seam:** `load(..., stream=None)`. Param is additive; absent = today's exact DB path. The **stream branch is gated** on the determinism contract (§3) and must be **callback/generator-streaming** (never buffer multi-year history into RAM — a Jetson OOM hazard). |
| **Bus-borne health** (`ActorStats` + `HeartbeatPublisher` → `orpheus/system/+/health`; UI wildcard → `ERROR_FEED`, four named topics, `/api/errors/recent`, audio p50/p95) | Operational, *physically on the domain bus* | [SUPERSEDED by §11] Originally: **stays exactly as-is, untouched, for this entire horizon.** This is the one genuine plane-tangle and the one breaking move if disturbed. We do **nothing** to it — not dual-emit, not mirror, *nothing*. See §6 for why, and for the known limitation we are knowingly freezing around. |
| **SQLite `DetectionDB`** | Domain (projection + audit-of-record) | **STAYS the source of truth for this entire horizon.** The "stream is truth" inversion is *named as the destination* (ADR 0017) but the **arbiter stays pinned to SQLite.** |
| **`mirror.py` / portal / KV-presence** | (orthogonal) | **Unchanged.** Already off-by-default; they are the proof the house style works. |

---

## 3. The event-sourcing prerequisites — making "rebuild by replay" honest

The determinism contract itself lives in
[event-sourcing-determinism-contract.md](event-sourcing-determinism-contract.md),
which is the single source for it. What follows is the summary this design
needs; where the two disagree, the contract wins.

The "rebuild the DB by replaying the log" inversion (backlog `[CORE]
Event-sourcing`) is **named as the destination but gated on a written contract.**
The review found the contract under-specified in ways that would corrupt data the
first time the stream branch is exercised. The contract (`docs/designs/
event-sourcing-determinism-contract.md`, written before any rebuild code) MUST
resolve all of the following. These are load-bearing, not tidiness:

### 3.1 The non-determinism lives in `entities`, not in `id`/`created_at`

`id` and `created_at` are already absent from `Detection.to_dict()` — the contract
formalizes a **ban on keying on them as identity** in one line, not as the
headline. **The real hazard is the `entities` table.** It is a correlator-derived
projection. Replaying raw detections re-runs correlation **under current logic**,
which:

- **Mints new `entity_id` UUIDs** per cluster — so any UI bookmark, citizen-science
  export, or external reference keyed on `entity_id` breaks across a rebuild.
- **Cannot reconstruct `is_self_generated`** — the echo/self-playback flag depends
  on the system's own audio-playback windows, **which are not in the detection
  stream.** A rebuild will flip this flag for any entity whose echo-window state is
  unrecoverable.

The contract must enumerate the **full** set of columns, table by table, from
`detection/models.py` + `database.py`, classifying each as
`payload-authoritative | rebuild-volatile | derived-non-reconstructable` — and
state plainly: **historical entity identity is NOT stable across rebuild unless
playback-window events are also durably logged. Forbid external keying on
`entity_id` for historical fidelity until that is true.** This is exactly the
"2029 rebuild silently invents entities that never existed" trap.

### 3.2 Rebuild mode is resolved NOW, not deferred-as-a-phrase

A rebuild must **never mutate the authoritative `orpheus.db`.** The mandated mode:

> A rebuild **writes-projection-directly** to a **separate/derived DB path** via an
> **idempotent upsert keyed on `event_id`** (whose fidelity ADR 0012 already
> guarantees). It **never goes through live agents** and **never overwrites** the
> authoritative file. The result is **diffed, never swapped in, without explicit
> human action.**

The rejected mode —
`re-publish-live` (what `ReplayEngine.play()` does today, re-emitting `_replay`-
tagged events onto live topics) — would **re-trigger correlation and re-write
rows**, because **no consumer in the repo guards against `_replay` payloads** (the
correlator's `save_entity` has no such check). If `re-publish-live` is ever chosen
for some future use, a repo-wide `_replay` guard in **every** persisting consumer
is an explicit precondition. Acceptance test: replay into a populated derived DB
and assert row counts + checksums are unchanged (idempotency).

### 3.3 The reconciliation job is specified, not "a tiny script"

It is named in three places as the divergence detector and the arbiter-flip gate,
so its unit of comparison must be defined or it produces un-actionable noise:

- **Compares stream messages to DB rows ONLY for agent-owned, 1:1-persisted
  detection types** (start with `audio.motion`, matching the shadow scope).
- **Keyed on the `event_id` set-difference**, NOT a raw count.
- **Explicitly excludes derived `entities`** (no 1:1 correspondence exists).
- Defines legitimate vs buggy divergence: *DB row with no stream message during the
  shadow phase = expected (DB is the writer); stream message with no DB row = the
  bug worth catching.*

### 3.4 The dedup prerequisite (stream/DB counts must be comparable)

`stream_publish` sets no `Nats-Msg-Id`, so a publish whose **ack is lost** on an
edge reconnect is **re-published as a distinct message** on retry — while the DB
save is idempotent (`event_id TEXT UNIQUE`). The two planes would then diverge
**by construction under normal edge-network conditions**, and §3.3's reconciliation
would report false divergence. **Prerequisite (not deferred):** domain
`stream_publish` MUST set `Nats-Msg-Id = detection.event_id`, so JetStream's
built-in dedup window makes the shadow idempotent and the counts directly
comparable. This is an additive change to the primitive + the spec.

### 3.5 The subject↔topic mapping is frozen as a guarded invariant, not a bijection

The existing functions are **not bijective** — any dotted topic level mis-routes,
and `nats_to_mqtt_topic` blindly maps every `.`→`/`. Freezing detections onto NATS
subjects makes this **load-bearing forever** (append-only + lossy reverse-map =
**unrecoverable rebuild corruption** the first time a dotted topic is persisted).
The contract MUST:

- **Freeze a tested invariant:** all durable-stream topic levels match
  `[a-z0-9_-]+` — **no dots, no wildcards** in published subjects — **enforced at
  `stream_publish` time with a fail-loud guard** so a dot can never silently enter
  the log.
- **Add a round-trip property test** (`mqtt → nats → mqtt == identity`) gating any
  topic added to a durable stream.
- *Or*, alternatively, **persist the original MQTT topic explicitly in a stream
  header** so the reverse map is a lookup, not a string transform.

Without the guard, the "rebuild by replay" guarantee is void the first time a
dotted topic is persisted.

### 3.6 The rebuild primitive must project-then-ack

`stream_replay` acks each message **as it is handed to the callback**, on an
**ephemeral** consumer. For the shadow phase (read-side/offline replay) this is
fine. But for authoritative rebuild, a crash mid-projection (DB write fails, OOM
on the 8GB Jetson) leaves **acked-but-never-projected** events that the next run
**does not resume** — and §3.3's reconciliation would then flag an unexplainable
divergence. **Prerequisite before "rebuild by replay" is wired:** the rebuild
primitive must **project-then-ack** (or use a durable named consumer that acks only
after the projection write commits). Today's ack-on-delivery ephemeral drain is
sufficient **only** for the offline/read-side replay it ships for.

### 3.7 Per-stream bounded retention is a prerequisite for the shadow's reversibility

`stream_ensure` cannot express `max_age`/`max_bytes`/`discard`. A shadow stream on
`audio.motion` (the highest-volume root) with no `max_age` grows until it hits the
**account-level 2GB cap shared with KV** — at which point JetStream returns publish
errors **for the whole account**, breaking KV presence and any other JetStream
user. That is **not** the clean "stop publishing, it ages out" the reversibility
story claims, and reverting leaves a stream pinned at the cap that an operator must
manually purge. **Prerequisite before the shadow lands:** an **additive
`StreamConfig` surface** on `stream_ensure` (a dedicated stream name + explicit
`max_age` AND `max_bytes` set **well under** the 2GB cap + `discard: old`), plus a
documented one-command purge/delete `make` target as the revert. Until that surface
exists, the shadow is **document-only** and must not publish.

---

## 4. The scope line — directly answering "are we going out of scope?"

**You are NOT going out of scope — *if* you freeze the law and cut the program.**
The worry is justified: a one-sentence law can smuggle a four-part observability
program in behind it (a meter SDK + W3C injection + a Grafana posture + dual-emit)
for a one-operator box where the tracer has **provably zero callers**. *That* would
be out of scope. Here is the line.

### BUILT NOW (cheap, durable, off-by-default, zero-dep default)

1. **The decision record** (§6 decides whether it is a new ADR or an amendment to
   ADR 0017) — the boundary law + the named-not-built `traceparent` crossing (with
   its transport-header mechanism note) + "health stays on the bus, untouched" +
   the explicit re-scope of backlog #95 (§6).
2. **The determinism contract** (`docs/designs/event-sourcing-determinism-
   contract.md`) — §3 in full. Pure prose; the prerequisite that makes "rebuild by
   replay" honest. **Net-new content** (the rebuild-volatile column enumeration,
   rebuild-mode mandate, reconciliation spec, dedup + ack + retention prerequisites,
   and topic-grammar invariant are written nowhere today).
3. **`ReplayEngine.load(..., stream=None)` seam shape** — **not built.** `load()`
   still takes `source`/`kind`/`start`/`end` only; there is no `stream` parameter.
   When it is built the stream branch must be streaming, not buffered.
4. **One real user per plane — sequenced and conditioned** (see §9). The
   shadow-publish earns the durable log its first writer; the tracer wiring is
   **conditioned on an actual debugging question existing** (see the §6 split).

### DEFERRED (explicitly, with reasons — "not now," not "never")

- **Grafana / Prometheus / Loki / Tempo stack** → an **optional docker-compose
  profile + a BYO recipe**, not repo-resident infra and **not a Jetson dependency.**
  `tempo` is already in `_KNOWN_BACKENDS`; the egress already speaks OTLP. (§7)
- **`get_meter` / `setup_metrics`** → **CUT.** No consumer exists; the tracer it
  would mirror has zero users. Speculative symmetry is not a user. The decision
  record must state **why** it is cut (zero consumer, mirrors a zero-user tracer)
  so a future contributor does not re-add it "for symmetry."
- **W3C `traceparent` injection across the bus** → named in the law; the
  `headers=` mechanism is a named prerequisite; **not built.**
- **Operational health migration** → **REVISED — now IN scope, non-regressive
  (§11).** (The original text here said "never migrate"; superseded by REVISION 1.
  Health moves off the domain bus to a KV substrate via a flag-gated parallel-run;
  backlog #95 is achieved non-regressively, not cut.)
- **Journal + snapshot split** (`start_seq`/`start_time` fast-forward) → **blocked
  on the determinism contract.** Snapshotting a non-deterministic projection is a
  correctness trap, not a perf knob.
- **Arbiter flip to "stream is truth"** → out of this horizon; human-gated behind
  reconciliation evidence.
- **Abstracting `stream_*` onto the `EventBus` ABC** → deferred until a 2nd backend
  needs durable streams.
- **A `headers=` channel on `publish`/`stream_publish`** → the prerequisite for the
  `traceparent` crossing; additive, deferred with the crossing.

---

## 5. The layered rollout

Each layer is a **config/deployment choice**, never a code change, and each is
independently reversible.

- **Layer 0 — Zero-dep default (the OSS fresh-clone experience).** Structured logs
  (`get_logger` JSON → journald) + SQLite + loopback NATS + health-on-bus → UI.
  **No telemetry SDK, no collector, no dashboard, no new dependency, zero CPU.**
  This is what 100% of installs get and what the project ships as the floor. It is
  already true today.
- **Layer 1 — Local OTel egress (opt-in, on-box).** `pip install
  orpheus-common[telemetry]` + `telemetry.enabled: true` + a boot-time
  `setup_tracing` call (the missing wiring, §9). The tracer lights up at
  `sample_rate: 0.1` (< 5% CPU budget — **to be measured, not asserted**, §9).
  **Edge note:** `backend: console` is a **dev/diagnostic rung only** — it writes
  spans to stdout/journald with no consumer, which on a sealed wetland Jetson is
  slow disk-fill on the same volume as the SQLite log and audio clips, with no
  rotation story. **On the Jetson, any enabled telemetry should target an OTLP
  endpoint** (local collector or remote) so spans leave the constrained disk.
- **Layer 2 — Local dashboards (opt-in docker profile).** An **optional**
  `docker-compose.observability.yml` (OTel Collector + Tempo/Grafana; Prometheus
  *if/when* metrics exist) + a BYO recipe. Operator sets `backend: tempo` +
  `endpoint: <collector>`. **Why this is durable and pin-independent:** the
  Collector, Tempo, Prometheus, and Grafana are **standalone OSS containers that
  speak OTLP — they have zero dependency on `orpheus-common` or its `<3.10` Python
  pin**, so they run on any host. The Jetson only ever runs the in-process tracer
  (3.9-pinned, already shipped) and emits OTLP over the wire. **For the single-host
  default (100% of installs today) this profile is on-Jetson-or-absent** — there is
  no mirror host, and the mirror-host placement is itself gated on ADR 0018 ("when
  a 2nd host is real"). We do **not** assume a mirror host exists.
- **Layer 3 — Remote backends (opt-in).** Same OTLP egress, `endpoint:` points at a
  remote collector / any APM. No code change — same seam, vendor-neutral by
  construction (CNCF OTLP).

The progression is purely additive; each step is a `config` edit + restart, never a
redeploy or a schema migration.

---

## 6. The backlog conflict and the health-on-bus freeze (owner decisions)

### 6.1 This design re-scopes backlog #95 / Epic 5 — explicitly, as an owner input

`[REFACTOR] OpenTelemetry (OTel) Migration (#95)` under `Epic 5: Observability &
Telemetry` has a Definition-of-Done this design **directly negates**, and it would
be dishonest to let two sources of truth drift (the exact two-schemas-drift sin the
boundary law condemns). The conflicts:

| #95 / Epic 5 says | This design says | Why |
|---|---|---|
| "3+ agents instrumented with traces" | one hot path, **conditioned** on a real question (§6.2) | no consumer = no user; symmetry is not a need |
| "W3C `traceparent` injected into MQTT headers" | named-not-built; needs a `headers=` seam first | no header channel exists on the ABC today |
| "Jaeger/Tempo added to Docker Compose dev env" | optional BYO profile, not repo-resident infra | not a Jetson dependency for a one-box deploy |
| "MQTT bus free of observability traffic" (the central criterion) | **health stays on the bus, untouched, this whole horizon** | migrating it **removes data the UI reads** (§6.3) |

**This is an owner decision, not an agent decision.** The decision record must
contain an explicit *"we are NOT doing #95's migration — here's why"* section, and
backlog #95 must be **groomed down or split** so the queue and the ADR agree. The
design *may well be right* that #95 reads as aspirational over-scope for a
one-operator box — but reshaping a groomed item is routed as an owner input, not
silently overridden.

### 6.2 The tracer slice is conditioned, not bundled "for symmetry"

The review correctly flagged that the "now" slice yokes **two independent
architectural threads** — event-sourcing (domain) and a tracer first-user
(operational) — with no shared code, dependency, risk, or deadline, justified only
by the aesthetic of "one user per plane." That is the same speculative-symmetry trap
used to **cut** `get_meter`. **Resolution: split the slice.** The ADR + determinism
contract + shadow-publish + reconciliation script are a coherent, self-justifying
**event-sourcing batch — ship that first.** The single `setup_tracing` + `get_tracer`
wiring is **orthogonal and earns its place only if there is an actual debugging or
latency question someone wants answered on a hot path today.** If there isn't, it is
**deferred by this design's own logic** (no consumer = cut), exactly like
`get_meter`. And note: audio-events **already publishes `inference_latency_ms`
p50/p95** on its health topic — so the candidate first-user span would *duplicate an
existing signal*. The first tracer user, if built, should cover a path **not**
already served by a health metric, and must **measure** the CPU delta on the Jetson
at `sample_rate: 0.1` to demonstrate (not assert) the < 5% budget.

### 6.3 Health-on-bus stays — [WITHDRAWN by REVISION 1; see §11]

> **This section is superseded.** The owner rejected "do nothing to health." Health
> migrates off the domain bus non-regressively (UI in scope); see **§11** for the
> authoritative design. The per-worker-cache limitation noted below is **fixed** by
> §11 (a shared KV source of truth), not frozen around. Text retained for provenance.

The way to never break the health the UI reads is to **do literally nothing to it.**
Not dual-emit (that manufactures two schemas that drift — the boundary law's exact
sin). Not mirror. Nothing. If health ever needs to reach Grafana, the additive
answer is an **off-Jetson bridge** that *subscribes* `orpheus/system/+/health` and
re-emits to OTLP — built only when a real user asks, never committed to in agents
now.

**Known limitation, explicitly accepted and parked:** the UI's in-memory health
caches (`ERROR_FEED`, `LATEST_AUDIO_EVENTS_HEALTH`, etc.) are **per-worker** and
break under multi-worker gunicorn. Freezing health-on-bus "forever" forecloses the
natural fix (a shared cache / durable health). This is an **out-of-horizon item,
consistent with the single-worker default** — named here so a future maintainer
knows it was *seen and parked*, not missed by the "never touch health" rule.

### 6.4 Host vitals (thermal/disk/RAM) — placed, not dismissed

System health (CPU/memory/disk/thermal) is **completely off the bus today** and is
operationally critical on a Jetson (thermal throttling, RAM exhaustion, disk full —
a top Resilience concern). "Metrics is the same *kind* as traces" is a
classification, not a plan, and **no external collector will produce host vitals for
an operator who hasn't deployed one.** The placement decision for this horizon:
[SUPERSEDED by §11.7 — host vitals are carved out, not on the bus] **host vitals stay a domain-adjacent operational signal on the existing bus** —
`SystemHealth` publishes to a heartbeat topic the UI already knows how to read
(additive, needs no telemetry SDK, no new dependency). They migrate to the
operational plane **the day `get_meter` is added**, and the trigger for that day is
named: **the first real thermal/disk incident that the bus signal cannot
adequately surface.** Not before.

---

## 7. Crisp answers to the owner's two questions

**Q: Is OTel or NATS the "source of events that go into other things"?**

**NATS JetStream. Definitively, and it is not a contest.** The domain event source
of truth is the JetStream durable log (lossless, replayable — the reason the project
exists); SQLite is its projection. **OpenTelemetry is never a candidate for that
role** — the APIs themselves prove it: `stream_replay` drains history oldest-first to
*rebuild* state; OTel has no replay, no rebuild, no projection semantics. The phrase
"OTel as the source of events that go into other things" is precisely the
conflation to retire: OTel is **operator observability, exported OUT** — it feeds
dashboards, never domain logic. Anything that "goes into other things" in the domain
sense rides JetStream.

**Q: Do local log-based metrics + Grafana belong in scope *now*?**

**The OTLP egress already belongs in scope (`tempo` is in `_KNOWN_BACKENDS`). The
Grafana/Prometheus *stack* is an optional, deferred docker profile + BYO recipe —
operator-downstream, not repo code, not a Jetson dependency, not built now.** "Local
log-based metrics" as a *third architecture* is a non-thing: it is the same KIND as
OTel (operational observability), just a different delivery mechanism. So the real
count was always **two concerns** — the settled domain log and the (now-scoped)
operational egress — never three. You decline to absorb a stack the standards-based
seam already lets users bring themselves. **That is staying in scope, decisively.**
(The one host-vitals metric class that no external collector will produce is placed
on the bus for this horizon — §6.4.)

---

## 8. Reversibility + OSS durability — the seams that mean this never changes

- **The boundary law** — words, not code. The actually-durable artifact.
- **`get_tracer` no-op** (verified `telemetry.py`): `_NoOpTracer`/`_NoOpSpan` fully
  satisfy the span API; `setup_tracing` returns `None` unless enabled. Reverting
  telemetry = turn off the flag → byte-identical to today. **Reversible by config.**
- **`stream_publish` as a pure shadow** — but only reversible-with-no-residue **once
  §3.7 (per-stream `max_age`/`max_bytes`) and §3.4 (`Nats-Msg-Id` dedup) ship.**
  With those: revert = stop publishing; bounded retention ages the stream out; the DB
  never depended on it. Without them the shadow can pin the shared 2GB account cap and
  leave residue — which is why the shadow is **document-only until those surfaces
  exist.** The arbiter stays on SQLite.
- **`ReplayEngine.load(stream=)`** — additive optional param; absent = today's exact
  DB path. The branch is streaming, not buffered (no OOM regression), and gated on
  the contract.
- **Optional docker profile + BYO recipe** — `git revert` of a compose file + a
  markdown doc; no agent dependency.
- **OTLP egress honesty:** the **wire** (OTLP/HTTP) is what is durable and
  vendor-neutral; the **SDK version** is pinned to the 3.9 floor (`<1.42`) and
  **will be bumped when the floor moves.** That is a **packaging-only change behind
  the optional extra, never a domain-plane change** — a bounded, accepted maintenance
  cost, not a claim that the library is frozen.
- **Config-reversibility:** the shadow is gated by a single off-by-default boolean
  (e.g. `event_sourcing.shadow_publish_enabled: false`, Pydantic default `False`),
  plus defaulted `StreamConfig` fields, so **old-config-on-new-binary and
  new-config-on-old-binary both validate** and behave as today.
- **Off-by-default + zero-hard-dep** — the same proven house style as
  mirror/portal/presence. A fresh OSS clone sees **zero** footprint change.

---

## 9. The minimal first-implementation slice

**Split into two independent batches** (§6.2). The event-sourcing batch is
self-justifying and ships first; the tracer wiring is conditioned and may be deferred.

### Batch A — Event-sourcing (ship this; internally ordered as a hard dependency)

1. **The decision record** — boundary law + named-not-built `traceparent` crossing
   (transport-header mechanism note) + "health stays on the bus, untouched" + the
   explicit re-scope of #95 (§6.1) + **why `get_meter` is cut.** Per the review,
   default to **amending ADR 0017** (it already owns "DB becomes a projection" and
   the NATS-authority claim) with a short note in
   `docs/designs/actor-model-and-control-plane.md`, rather than minting a parallel
   ADR — the durable artifact is the *sentence*, and a sentence does not need a new
   file when an owning ADR exists. (Mint a new ADR only if the owner prefers a
   standalone record.) *Pure prose. The durable win. **Lands before item 3.***
2. **`docs/designs/event-sourcing-determinism-contract.md`** — §3 in full:
   full per-table rebuild-volatile column enumeration (lead with `entities` /
   `entity_id` / `is_self_generated`); the **write-projection-directly, never mutate
   `orpheus.db`** rebuild-mode mandate; the `event_id` set-difference reconciliation
   spec; the **`Nats-Msg-Id` dedup**, **project-then-ack**, **per-stream
   `max_age`/`max_bytes`**, and **dot-free topic-grammar guard** prerequisites.
   *Pure prose. **Lands before item 3.***
3. **Additive primitive surfaces + shadow, one agent.** In order:
   (a) extend `stream_ensure` with a `StreamConfig` (name, `max_age`, `max_bytes`
   under the 2GB cap, `discard: old`); (b) make `stream_publish` set
   `Nats-Msg-Id = event_id` and add the fail-loud dot-in-subject guard;
   (c) call `stream_ensure` at startup on each of the four agents that own a detection topic (idempotent, gated by
   `shadow_publish_enabled`); (d) **shadow** `stream_publish` **after** the existing
   `db.save`, failures **logged loudly, never swallowed, never authoritative**, and
   a **no-op on the `mqtt` backend** (catch `NotImplementedError` — MQTT is the
   fallback and has no `stream_*`); plus the reconciliation `make` target from §3.3.
   Reversible: flag off. The stream then ages out within
`event_sourcing.max_age_seconds` (7 days by default). There is **no** one-command
purge target yet — an immediate purge is a manual `nats stream purge orpheus_domain`
on the broker. *Earns the durable log
   its first writer and produces the evidence any future inversion needs.*
4. **`ReplayEngine.load(stream=None)` seam shape** — parameter + dispatch only; the
   stream branch is stubbed/gated on the contract and documented as streaming. No
   rebuild wired.

### Batch B — Operational plane first-user (conditioned; defer if no live question)

5. **Wire telemetry end-to-end on one hot path** — call `setup_tracing(service,
   config)` once at agent startup (next to `create_event_bus`, gated on
   `telemetry.enabled`; **without this the tracer is a permanent no-op**), then
   `get_tracer` a span on a path **not already covered by a health metric**, at
   default `sample_rate: 0.1`, off-by-default. **Acceptance:** measure the CPU delta
   on the Jetson and confirm < 5% before calling the seam validated — demonstrate,
   don't assert. *Build this only if a real debugging/latency question exists today;
   otherwise defer (no consumer = cut), exactly like `get_meter`.*

### Explicitly NOT in either batch

`get_meter`/`setup_metrics`; W3C injection; the `headers=` channel; any
dashboard/compose; any health change; any snapshot; any arbiter flip; abstracting
`stream_*` onto the ABC; wiring the `ReplayEngine` stream branch (seam shape only,
gated on the contract).

---

## 10. Rejected alternatives

- **#95 / Epic 5 as written (full OTel migration, MQTT free of observability
  traffic, 3+ agents, W3C injection, Jaeger/Tempo in dev compose).** Rejected for
  this horizon: it migrates health **off the bus, removing data the UI reads**, for a
  one-operator box where the tracer has zero callers. Re-scoped as an explicit owner
  decision (§6.1), not silently overridden.
- **Freeze health-on-bus forever (do nothing).** Rejected by REVISION 1 (owner
  correction): health migrates off the domain bus non-regressively (§11). The
  migration uses a *transient* dual-WRITE (bus + KV) during the parallel-run — not a
  permanent dual-emit — verified equivalent by a diff endpoint, then the bus publish
  is retired. (The earlier "dual-emit drifts two schemas" worry is handled by the
  transient-and-verified parallel-run, not by freezing.)
- **`get_meter` / `setup_metrics` now (symmetry with the tracer).** Rejected: no
  metric has a consumer, and it would mirror a tracer that itself has zero users.
  Speculative symmetry is not a user. Added the day a metric has a consumer.
- **OTel as the domain event source ("events that go into other things").**
  Rejected: OTel has no replay/rebuild/projection; it is sampleable and egress-only.
  Making it a domain source would let `sample_rate` drop wildlife observations (§1).
  NATS JetStream is the source of truth (§7).
- **Repo-resident Grafana/Prometheus/Loki/Tempo stack on the Jetson.** Rejected: an
  always-on TSDB + dashboards on an 8GB GPU-shared box, with no metrics consumer
  today, is a clear over-build. Offered instead as an optional, vendor-neutral OTLP
  downstream profile users bring themselves (§5, §7).
- **A `re-publish-live` rebuild that re-emits onto live topics.** Rejected as the
  default: no consumer guards `_replay`, so it would re-trigger correlation and
  re-write the live DB. The mandated mode is write-projection-directly to a derived
  path, never mutating `orpheus.db` (§3.2).
- **A new standalone ADR for the boundary law.** Default-rejected in favor of
  **amending ADR 0017** (which already owns DB-as-projection and NATS authority), to
  avoid a third parallel source of truth (§6, §9). A standalone ADR is minted only on
  explicit owner preference.
- **Trusting the existing subject↔topic mapping as a bijection.** Rejected: it
  mis-routes any dotted level. Replaced by a **frozen, fail-loud, tested dot-free
  topic-grammar invariant** (or an explicit MQTT-topic stream header) before the
  stream is a source of truth (§3.5).
- **Treating "rebuild from the log" as a perf/snapshot feature.** Rejected: snapshots
  and the arbiter flip are **blocked on the determinism contract** — snapshotting a
  non-deterministic projection is a correctness trap, not a knob (§4).
- **Shadow-publishing before per-stream retention + dedup exist.** Rejected: it can
  pin the shared 2GB account cap (breaking KV presence) and produce false
  reconciliation divergence. The shadow is **document-only until §3.4 and §3.7
  ship** (§8, §9).

---

## The decision, in one breath

**Freeze the sentence, not the stack.** Two planes: JetStream is the lossless
replayable domain source of truth,
OTel is the sampleable egress-only operational plane, and they never mix except for
one named-not-built `traceparent` crossing that rides a transport header, never the
payload. Health migrates off the domain bus to a KV substrate non-regressively (§11),
including the sequenced per-worker cache fix; host vitals are carved out into their
own backlog item (§11.7). The "rebuild from the
log" inversion is *named as the destination* but *gated on a written determinism
contract* — full column enumeration, write-to-a-derived-DB rebuild mode, `event_id`
reconciliation, `Nats-Msg-Id` dedup, project-then-ack, per-stream bounded retention,
and a fail-loud dot-free topic grammar — and kept shadow-only with SQLite as arbiter
for this whole horizon. Backlog #95's MQTT-free migration is explicitly re-scoped as
an owner decision. Ship the event-sourcing batch (two documents + the guarded shadow
+ reconciliation); the tracer first-user is conditioned on a real question and
otherwise deferred. Cut the meter, the header injection, the dashboards-as-code, the
dual-emit, the snapshots, and the arbiter flip. **You are not going out of scope —
you are declining to build a distributed-systems observability program for a bird box
nobody is instrumenting yet, while keeping every seam that lets an OSS user opt into
exactly as much of it as they want.**

**Key files this design touches or freezes:**
`docs/adr/0017-actor-model-nats-backplane.md` (amended with the boundary law +
re-scope of #95, the default destination for the decision record),
`docs/designs/event-sourcing-determinism-contract.md` (new — §3),
`docs/designs/actor-model-and-control-plane.md` (short cross-reference note),
`platform/orpheus-common/src/orpheus_common/telemetry.py` (unchanged; first user +
boot-time `setup_tracing` added in conditioned Batch B),
`platform/orpheus-common/src/orpheus_common/event_bus_nats.py` (`stream_ensure` gains
a `StreamConfig`, `stream_publish` gains `Nats-Msg-Id` + dot-guard; first caller
added),
`platform/orpheus-common/src/orpheus_common/replay.py` (`load(stream=)` seam shape,
branch gated + streaming),
`platform/orpheus-common/src/orpheus_common/detection/database.py` +
`detection/models.py` (the rebuild-volatile / derived columns the contract names),
`platform/orpheus-common/src/orpheus_common/actor/heartbeat.py` + `actor/stats.py` +
`services/orpheus_ui/backend/src/orpheus_ui/main.py` + `api/entities.py`
(health-on-bus — explicitly untouched),
`docs/backlog.json` (#95 / Epic 5 — groomed down or split as an owner decision),
`config/orpheus.example.yaml` (off-by-default `event_sourcing.shadow_publish_enabled`
+ `StreamConfig` defaults).

---

## 11. Operational health migration (non-regressive) — owner-corrected redesign

**This section is authoritative for operational health and SUPERSEDES §6.3 / the
"never migrate" line in §4 / the dual-emit entry in §10** (REVISION 1, owner
correction). Produced by a dedicated design workflow (3 understand facets → design
→ 4 adversarial critics → synthesis; 28 HIGH/MEDIUM findings folded in). Every
load-bearing fact below was re-verified against the code.

## 11.1 Two-planes law (refined)

The system has two planes, and a third fully-optional one:

1. **The durable domain log.** The JetStream detection stream and the domain
   detection topics (`orpheus/audio/motion/events`, `orpheus/video/motion/events`,
   `orpheus/detection/bird/events`, `orpheus/detection/crow/events`,
   `orpheus/entities/animal`) are the lossless, replayable record of what the world
   did. (As shipped, the stream binds DEDICATED `orpheus/domain/...` re-rooted
   subjects — `event_sourcing.domain_subject()` maps each live topic, e.g.
   `orpheus/detection/bird/events` → `orpheus/domain/detection/bird/events` —
   never the live subjects themselves: a JetStream publish is also a core
   publish, so shadowing onto live subjects would double-deliver every detection
   to every live subscriber.) This plane **MUST NOT carry operational signal**. Operational health uses
   NATS **KV buckets only**; it **MUST NOT** be shadow-published into any JetStream
   stream (no `stream_ensure`/`stream_publish` for health). The durable domain
   stream carries detections exclusively.
2. **The operational plane.** Operational signal — agent liveness, the cross-agent
   error feed, pre-aggregated latency summaries, host vitals, audio-channel levels,
   scan summaries — lives on a **zero-dependency NATS KV substrate** (`orpheus_health`
   buckets) for queryable current-state — `orpheus_host_vitals` is planned (§11.7);
   nothing writes it today. Operational signal
   **MAY** ride NATS — it simply never rides the domain detection topics or the
   durable domain stream. There is exactly **one** operational substrate: KV. We do
   **not** add a second operational transport (an `orpheus.ops.*` subject namespace)
   — that reproduces the per-subscriber-process fragility we are fixing, and every
   operational signal here is low-rate last-value data KV serves natively.
3. **Deep telemetry (fully optional).** Distributed traces, fine-grained metric
   time-series, structured log export → OTel/OTLP (`telemetry.py`). **Additive**: the
   zero-dep operational view in plane 2 is always complete **without** it — no
   operator is ever forced to deploy Grafana/Prometheus/Tempo to see whether an agent
   is alive, erroring, hot, or slow. **Invariant:** turning OTel on must never
   *remove* a field from the KV operational view.

**Backend caveat (binding).** On the `mqtt` fallback backend `kv_*` raise
`NotImplementedError` and `Presence.supported()` is false. Therefore **on `mqtt` the
domain bus remains the operational plane** — health keeps riding
`orpheus/system/*/health`, and "free the domain bus of observability traffic" is a
**nats-only outcome**. The migration is backend-aware and **fail-safe, not
fail-dark**: it no-ops on `mqtt`, leaving today's working health path intact.

## 11.2 Producer inventory (the corrected ground truth)

The first design's "agents need no change — reuse `health_payload()` verbatim" is
**false for half the producers**. There are **seven** producers across **two**
mechanisms:

| Producer | Mechanism | Health topic today | Cadence | Payload source |
|---|---|---|---|---|
| audio-events | **Actor** | `orpheus/system/audio-events/health` | 30s heartbeat | `health_payload(phase)` |
| bird-detection | **Actor** | `orpheus/system/bird-detection/health` | 30s | `health_payload(phase)` |
| crow-detection | **Actor** | `orpheus/system/crow-detection/health` | 30s | `health_payload(phase)` |
| event-correlator | **Actor** | `orpheus/system/event-correlator/health` (+ scan summary) | 30s | `health_payload(phase)` |
| **audio-motion** | **hand-rolled** (non-Actor) | `orpheus/system/audio/health` | **5s loop** | `health_monitor.get_status()` |
| **video-motion** | **hand-rolled** | `orpheus/system/video/health` | **5s loop** | monitor status |
| **audio-playback** | **hand-rolled** | `orpheus/audio/playback/health` | loop | monitor status |

Two corrected false premises (verified): **(a) there is no 120ms firehose** —
audio-motion publishes on a **5s loop** (`publish_interval = 5.0`); the "120ms" was
only the frontend *poll* cadence against an in-memory cache, so audio levels are a
normal 5s last-value signal that fits `orpheus_health` like any heartbeat (the
dedicated-subject carve-out is deleted). **(b) Health is NOT already in KV** —
`Presence.online()` uses `client_id` (`orpheus-agent-audio-events`) and is
off-by-default, while every UI consumer keys off the **bare name** (`audio-events`):
a real **key-scheme mismatch**, and a **producer** change, not "turn on a consumer."

## 11.3 Substrate: KV buckets, one canonical key scheme

**Bucket `orpheus_health`** — per-producer liveness + stats, **TTL 90s** (3× the
fixed 30s heartbeat). **Canonical key = the bare producer name the UI already
expects** (`audio-events`, `bird-detection`, `crow-detection`, `event-correlator`,
`audio`, `video`, `audio-playback`); multi-instance uses a **flat `<name>__<instance_id>`**
encoding (matches how `Presence` writes; no unverified nested-`/`-key reliance).
`kv_list` returns every key — a strict gain over the old `+/health` wildcard that
couldn't match `+/+/health`. **One writer, one key:** `OperationalHealth.publish(key,
payload)` writes the producer's **existing payload verbatim** plus an *additive*
envelope (`agent`, `instance_id`, `phase`, `emitted_at`, `schema`) — the frontend
never sees a shape change. `Presence` keeps its own `client_id` liveness role
(unchanged, off by default); `OperationalHealth` is the named-key UI-facing writer.
No double-write of the same payload to two buckets.

**Key `auto-discovery`** in `orpheus_health` — written by the correlator's **existing
post-scan callback** (hours-long scan interval, NOT folded into the 30s heartbeat,
which would couple scan freshness to the heartbeat).

**Bucket creation owns the TTL (footgun mitigation).** NATS KV TTL is fixed at
*create* and silently ignored after. The first `publish()` creates the bucket with
the TTL — there is no `ensure()` method; **the UI consumer uses `create=False`**
(snapshot/watch only) so a consumer can never set the wrong TTL. The TTL is
**fleet-derived**: three times the largest `agents.<name>.heartbeat_seconds` in the
shared config, floored at 30s, or an explicit `event_bus.health_ttl_seconds`. So
**per-agent heartbeat overrides are safe** — that is what the derivation is for. Runbook: to change the TTL, delete the bucket on
the broker (owner-gated, not reversible-by-flag).

## 11.4 Staleness: keep today's receive-time basis (reject `emitted_at` as source)

Today staleness = the UI's own `monotonic()` **receive time**
(`HEALTH_STALE_AFTER_SECONDS = 90`); absence ⇒ `never_seen`/`never_run`. The
migration **keeps this exact basis** — staleness derives from **when the KV consumer
last observed the key change**, and **KV-key-absence ⇒ offline** (TTL aging gives
this free). Recomputing staleness from agent-stamped `emitted_at` is **rejected as
the source**: on an edge Jetson with NTP drift a slightly-future `emitted_at` reads
as zero/negative age — **false-fresh, hiding a dying agent**. `emitted_at` is an
**additive display field only**.

## 11.5 Deep-telemetry vs zero-dep split

Zero-dep KV (`orpheus_health`): liveness, `last_error` + error feed, counters,
**pre-aggregated** latency p50/p95/max, audio levels (key `audio`), video
agent-health (key `video`), scan summary (key `auto-discovery`). OTel/OTLP
(opt-in, SDK-gated): distributed traces, fine-grained metric time-series, structured
log export. **Dividing principle:** the zero-dep substrate carries the latest
*pre-aggregated* state ("is it alive/erroring/hot/slow right now"); anything that is
a time-series, a distribution, or a span goes to OTel and is fully optional.
`telemetry.py` is **untouched** by this work.

## 11.6 Parallel-run migration phases (every phase one revertible, flag-gated commit)

Flags: `event_bus.health_kv_enabled=false` (producers dual-write to KV),
`ui.health_source="bus"|"kv"|"both"` (default `"bus"`), `event_bus.health_on_bus=true`
(producers publish to the bus). **Mandatory boot-time feature-detect:** any process
whose backend lacks KV **forces `health_source="bus"` and ignores `health_kv_enabled`**.
The invariant:
**the bus health publish keeps running until Phase 5b**, so the existing UI path
works at every step.

- **Phase 0 — scaffolding, no behavior change.** Add flags (default to today),
  `OperationalHealth` façade, a UI `HealthKVCache` module not yet wired. Revert =
  delete files.
- **Phase 1 — producers dual-write to KV (additive; UI unchanged).** When
  `health_kv_enabled` AND KV supported, **all seven** producers write their existing
  payload to `orpheus_health` in addition to the bus: Actor agents via a best-effort
  KV write next to `_presence_refresh`; **hand-rolled agents via a dual-write shim in
  each existing `_publish_health_status()` 5s loop** (no Actor migration); correlator
  scan callback writes `auto-discovery`. All KV writes best-effort (KV failure logs,
  never disturbs the bus publish). Flag-off = byte-identical.
- **Phase 2 — UI reads KV in shadow + equivalence oracle (still serves from bus).**
  One **supervised** `kv_watch` on `orpheus_health` (existing lifespan client),
  primed by `snapshot()`, with a **periodic `kv_list` re-snapshot floor** (the watch
  permanently stops on error — verified — so it's an optimization, not the source of
  truth; on death, re-establish + re-prime with backoff). Add admin diff endpoint
  `/api/diagnostics/health-source-diff` — the **proof artifact** — covering per-field
  value diff, **bus-present/KV-absent AND KV-present/bus-absent**, the derived
  `stale`/age/offline computation, an "at least one source non-empty" guard, and a
  **transient-error probe** (so the KV-last-value error-feed fidelity gap is visible
  *before* promotion). Served endpoints still read the bus caches.
- **Phase 3 — promote UI to serve from KV (bus still publishing; one-flag rollback,
  no redeploy).** `ui.health_source="kv"`: the health endpoints read the KV cache;
  bus subscriptions still run (harmless). **Video hybrid named:** `/api/diagnostics/video`'s
  agent-health portion switches to KV but its `camera_count`/`last_detection` stay
  **domain-cache-derived** (`_video_detections_by_camera` from
  `orpheus/video/motion/events`); bird/crow detection summaries are pure domain-topic
  caches, **untouched**. Frontend unchanged (envelope only adds fields).
- **Phase 4 — soak (no code).** Days on the Jetson at `health_source="kv"`: diff
  stays empty across agent + UI restarts; a deliberate `kill -9` proves TTL offline
  detection; a `kv_watch` kill proves the supervisor + snapshot floor recover; a
  transient-error injection confirms the fidelity decision is acceptable.
- **Phase 5a — retire the bus health PUBLISH (the Epic-5 goal).** Producers stop the
  bus publish when `health_on_bus=false` (**default true** in the commit — a no-op
  until promoted per deployment after soak). **Gated on KV supported** — `mqtt` keeps
  publishing (fail-safe). All seven producers.
- **Phase 5b — retire the bus health SUBSCRIPTIONS (UI side, separate commit).** Drop
  the **five** health subscriptions behind `health_source != "bus"`; the **four
  detection subs + `entities/animal` MUST remain** (same `subscribe()` block — a test
  asserts they survive). **Recommended:** keep the bus subscriptions always-active
  until well after 5a is proven, so neither rollback needs a UI restart. Mixed-fleet
  states are defined-safe (agent-publishing-while-UI-not-subscribed = harmless;
  UI-subscribed-while-no-agent-publishes = empty cache, served from KV).

**Anti-skew invariant:** the UI must never be left with no populated source.
`health_on_bus=false` is the **last** flip, after the UI is confirmed on KV and
`health_kv_enabled` is verified on **all** producers; the diff endpoint's
"at-least-one-source-non-empty" guard backstops flag skew.

## 11.7 Per-worker cache fix (sequenced) + host vitals (carved out)

The per-worker in-memory caches (`ERROR_FEED`, `LATEST_*`) are a **latent**
multi-worker bug (the UI is single-worker today). **Sequenced, not bundled:** first
land the bus→KV migration single-worker (same harvest logic over the shared KV
cache, proven by the diff endpoint); **then**, as a separate follow-on with its own
diff verification, make the error feed a **pure projection of current KV last-values**
(identical across workers because it reads the same durable state). **Acknowledged
fidelity change:** a KV last-value error feed is **lossier** than the bus stream — a
sub-heartbeat error that clears is invisible to the projection; the Phase-2
transient-error probe makes this measurable before promotion; if sub-heartbeat error
history is needed, back it with the existing SQLite escape hatch (separate item).

**Host vitals (CPU/mem/thermal) are CARVED OUT** into their own backlog item —
net-new capability, not a migration of existing signal, kept out so this migration's
"only relocates proven-equivalent signal" reversibility argument stays airtight.
Placement fixed for bucket coherence: a `HostVitals` sampler (opt-in, zero-dep:
`psutil` optional with `/proc` fallback) writes **one key per host** to
`orpheus_host_vitals` (TTL 90s) under `host_vitals.role: "writer"|"off"` (default
off); thermal reuses `HardwareConfig.thermal_zone_path`; disk history **stays in
`StorageHistoryDB`** (the days-until-full chart needs the 6h trend); the UI shows a
"host vitals not enabled" affordance, not an empty panel. Writer-election + thermal
path are owner inputs.

## 11.8 Backlog #95 re-framed (cut → done-non-regressively)

The earlier "freeze" reasoning conflated the durable domain **log** with NATS in
general. The law keeps the **detection stream + domain topics** clean; operational
signal may ride NATS on a **separate KV substrate**. So **#95 / Epic 5 ("the domain
bus free of observability traffic") is achieved as the *outcome* of Phase 5a** (no
more `orpheus/system/*/health` on the **nats** backend after a clean soak), via a
flag-gated, independently-revertible parallel-run where the original bus path
survives untouched through Phase 4. On the `mqtt` fallback it is a **graceful no-op**
(the bus stays the operational plane) — documented, intended, not a regression.

## 11.9 Per-phase reversibility + no-regression summary

| Phase | Runs only if | Revert | No-regression guarantee |
|---|---|---|---|
| 0 | nothing reads the flags | delete files | byte-identical agents + UI |
| 1 | `health_kv_enabled` AND KV | flag off | bus publish byte-identical; KV write best-effort, isolated; all 7 producers |
| 2 | `health_source∈{kv,both}` AND KV | `="bus"` | served on bus; diff proves KV==bus (values + absence + staleness + transient-error) before promotion; watch supervised + snapshot floor |
| 3 | `health_source="kv"` | `="bus"` (no redeploy) | bus caches still warm; video/bird/crow domain fields stay bus-fed; live diff monitor |
| 4 | soak | flip back | hold incl. kill -9, watch-kill, transient-error on real HW |
| 5a | `health_on_bus=false` AND KV | `=true` | removes a publish nothing consumes post-soak; `mqtt` keeps publishing |
| 5b | `health_source!="bus"` | `="bus"` (+UI restart unless subs kept on) | detection subs provably retained; mixed-fleet states defined-safe |

## 11.10 File-touch map

- `config.py` — `event_bus.health_kv_enabled` (Ph1), `event_bus.health_on_bus`
  (Ph5a, default true), `ui.health_source` (Ph0), `host_vitals.role` (carved item).
- `orpheus_common/actor/operational_health.py` — **new** `OperationalHealth` façade
  over `orpheus_health` (bare-name keys, envelope, `ensure(ttl)` owns bucket-create,
  consumer `create=False`).
- `actor/base.py` — Ph1 dual-write next to `_presence_refresh`; Ph5a gate the bus
  health publish on `health_on_bus`; backend feature-detect (skip KV when unsupported).
- `agents/orpheus-agent-{audio-motion,video-motion,audio-playback}/…/main.py` —
  dual-write shim in each `_publish_health_status()` 5s loop (keys `audio`/`video`/
  `audio-playback`); Ph5a flag-gate. (Corrects "no agent changes.")
- `agents/orpheus-agent-event-correlator/…/main.py` — scan callback dual-writes
  `auto-discovery`.
- `services/orpheus_ui/backend/.../main.py` — Ph2 supervised `kv_watch` + snapshot
  prime + periodic re-snapshot; boot feature-detect forces `"bus"` when KV
  unsupported; Ph5b gate the **five** health subs, **retain the four detection subs +
  `entities/animal`** (assert in a test).
- `services/orpheus_ui/backend/.../api/entities.py` — KV-backed reads; error feed as
  KV last-value projection; `/api/diagnostics/health-source-diff`; staleness stays
  receive-time/absence based.
- `services/orpheus_ui/backend/.../api/diagnostics.py` — audio levels from KV key
  `audio`; video health-portion from KV key `video`; `camera_count`/`last_detection`
  stay domain-cache-derived.
- Frontend: **no shape changes** in any phase. Optional Phase-3 nicety: a
  multi-instance agent list (KV keys carry instance scope).
