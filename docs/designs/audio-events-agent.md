# Plan: Audio-Events Detection Agent (`orpheus-agent-audio-events`)

**Status:** Implemented — shipped and evolving. §§1–3 record the original
design rationale; §4.1 documents the **as-built** agent and is kept in sync
with `agents/orpheus-agent-audio-events/`.

**Author:** scott + claude

**Last updated:** 2026-07-02

**Doc-sync contract:** per non-negotiable #12 (AGENTS.md), changes to this
agent update this doc in the same commit.

**Tracks backlog issue:** [FEATURE] Audio Events Agent (PANNs AudioSet Classifier)
(this plan supersedes that issue's PANNs MobileNetV2 choice with PANNs CNN14 SED — rationale in §3.2)

**Companion ADR:** [`docs/adr/0011-temporal-localisation-and-taxonomy-references.md`](../adr/0011-temporal-localisation-and-taxonomy-references.md) (formal decision record for the schema extensions in §3.4)

---

## 1. Summary

Build a new detection agent — `orpheus-agent-audio-events` — that classifies every
audio-motion-triggered clip against the **AudioSet 527-class ontology** using a
**Sound Event Detection (SED) model with native frame-level outputs**. The agent
emits structured `Detection` events with intra-clip time intervals, so any
downstream consumer (event correlator, UI, future source-separation experiments)
can pinpoint *when* in a clip a labelled sound occurred — not just *what* was in it.

The work introduces a small, general schema extension to `Detection` (an
`intervals` field and a `taxonomy` reference) that applies to **every** detection
type in the system, not just the new agent. Bird-detection and crow-detection
backfill into the same fields. The agent runs in parallel with bird-detection
initially; placing bird-detection downstream of audio-events (as a gate) is
explicitly deferred to a follow-up.

Source separation is **out of scope** for this iteration. The agent's frame-level
output gives downstream consumers enough localisation to run separation as a
future experiment without re-architecting anything.

---

## 2. Goals & Non-Goals

### Goals

- A new agent that emits well-typed events tagging audio chunks against a
  widely-adopted taxonomy (AudioSet 527 classes — covers birds, mammals, humans,
  vehicles, weather, mechanical, music, environment).
- Per-detection **intra-clip time intervals** so downstream consumers know
  *when* in the clip the sound occurred. This metadata is general to the
  `Detection` model, not bolted onto this agent.
- **Generalisation, not hacks.** New fields land on `orpheus_common.detection.models`
  and are populated by every classifier that has the data (bird-detection has
  BirdNET windows; audio-motion has full clip span; crow-detection inherits from
  the bird event it's analysing).
- A new `/audio-events` UI page mirroring Birds/Crows, with intra-clip playback
  that highlights/jumps to the detected interval.
- Correlator integration: `audio.classified` becomes a clustering input;
  cross-classifier merge handled by an alias map (subset of the existing
  "[CORE] Correlator Alias Map" backlog issue — scoped down to the aliases we
  actually need on day one).
- All work runs on Jetson Orin NX alongside the existing inference stack
  (BirdNET ONNX + AVES PyTorch + crow-tools) without thermal/memory regression.

### Non-Goals (explicitly deferred)

- **Source separation.** If we ever extract individual signals from overlapping
  audio, the frame-level intervals from this work are the input. Tracked by
  the backlog issue "[SPIKE] Isolate Individual Bird Calls from Overlapped Audio."
- **Putting bird-detection behind audio-events.** Useful eventually (gate
  BirdNET on "bird vocalization > threshold") but premature until we trust the
  audio-events agent's recall on biological sounds.
- **GPS-aware / locality-aware tuning.** Bird-detection already has a soft
  geo-admit rule (commit `6951b8d`); audio-events ships without one and we
  evaluate after seeing field data.
- **Replacing the hardcoded `NON_BIRD_SOUNDS` filter** in the UI. Cleanup that
  with confidence once audio-events is producing the data; do it as a follow-up
  PR after this lands.
- **Full taxonomy reform** (the `[ARCH] Generalize the EntityEvent State Space
  Taxonomy` backlog issue). The `taxonomy` field we add here is forward-compatible
  with that work but doesn't pre-empt it.

---

## 3. Key Design Decisions

### 3.1 Where the agent sits in the topology

**Decision:** Parallel to bird-detection, both subscribing to
`orpheus/audio/motion/events`. Each emits its own `detection_type`. Correlator
merges them.

```text
            ┌─→ orpheus-agent-bird-detection ──→ orpheus/detection/bird/events ──┐
audio-motion┤                                                                     ├─→ correlator ─→ entities
            └─→ orpheus-agent-audio-events  ──→ orpheus/detection/audio/events ──┘
```

Why not chain audio-events → bird-detection? Two reasons:
1. We don't yet know if audio-events has the recall on quiet bird calls to safely
   gate BirdNET. Running parallel lets us measure agreement before changing
   topology. (BirdNET's recent sigmoid-multilabel fix `74a479a` matters here —
   it's now genuinely multi-label, so it can disagree with audio-events in useful ways.)
2. The bird-detection geo-filter logic that just landed (`6951b8d`) operates on
   raw audio. Inserting another inference step in front of it changes the latency
   budget — defer until we have measurements.

### 3.2 Model choice — PANNs CNN14 with built-in SED head

**Decision:** Use **PANNs `Cnn14_DecisionLevelMax`** (the SED variant of CNN14)
as the primary inference model. Backup is `Cnn10_DecisionLevelMax` (16× fewer
params) if Cnn14 is too heavy on Jetson alongside BirdNET + AVES + crow-tools.

| Criterion | PANNs Cnn14_DecisionLevelMax | PANNs Cnn10_DecisionLevelMax | EfficientAT mn10_as | CED-base |
|---|---|---|---|---|
| License | MIT | MIT | MIT | Apache-2.0 |
| Native FW | PyTorch | PyTorch | PyTorch | PyTorch (HF) |
| Frame-level SED | **built-in (10 ms framewise)** | **built-in** | clip-only (sliding window) | clip-only |
| Classes | AudioSet 527 | AudioSet 527 | AudioSet 527 | AudioSet 527 |
| Params | ~80 M | ~5 M | ~5 M | ~86 M |
| Disk | ~314 MB | ~21 MB | ~20 MB | ~86 MB |
| AudioSet mAP | 0.431 | 0.380 | 0.471 | 0.50 |
| SR | 32 kHz | 32 kHz | 32 kHz | 16 kHz |
| Maintenance | inactive but stable | inactive but stable | active (2024) | active (ICASSP 2024) |

Why Cnn14 over Cnn10:
- Cnn14 mAP 0.431 is plenty for coarse categories ("bird", "vehicle", "speech")
  that we actually care about — these aren't long-tail classes.
- Cnn10 is the fallback if we measure performance issues; the schema doesn't
  change and the model swap is a one-line config change in the agent.

Why PANNs SED over EfficientAT or CED:
- **Native frame-level outputs.** EfficientAT and CED give a single label vector
  per clip; PANNs SED gives a `(num_frames, 527)` matrix at 10 ms resolution out
  of the box (hop 320 @ 32 kHz, verified empirically — the "~31 ms" figure in
  older PANNs docs belongs to a different variant; see `model.py`). This is
  *the* differentiator for our localisation requirement.
- A sliding-window emulation on top of EfficientAT would give worse resolution
  and double our inference cost.
- The model audit notes EfficientAT and CED edge PANNs on accuracy; the audit
  also notes our use case ("bird/speech/vehicle" coarse tags) doesn't need that
  extra mAP. We can re-evaluate if real-world tagging is poor.

Risk: 80M params on Orin NX. Mitigation: budget a benchmarking step before
committing to Cnn14; if `panns_inference` Cnn14 + BirdNET + AVES + crow-tools
exceeds memory or latency budget, fall back to Cnn10 (same schema, same
post-processing pipeline).

ONNX/TensorRT export is **not** required for v1 — PyTorch native on Orin NX GPU
is fine for our duty cycle (only fires on audio-motion). Mark TensorRT
acceleration as a separable optimisation.

### 3.3 Taxonomy — AudioSet 527 + machine_id

**Decision:** Standardise on the AudioSet ontology (Google's hierarchical sound
event taxonomy with stable machine_ids like `/m/04rlf`). Carried in a new
`Detection.taxonomy` field as `{namespace: "audioset", id: "/m/04rlf"}`.

Why AudioSet:
- Every audited general-purpose model emits to this label set; switching models
  later doesn't change the schema.
- The ontology is hierarchical — we can roll up "American Crow" → "Bird" →
  "Animal" → "Sound" at query time without lossy denormalisation.
- License is CC BY-SA 4.0 on the ontology itself — fine for use in OSS code.
- Coexists cleanly with eBird codes (BirdNET) and the IOC scientific names
  (the species-links work in backlog) — different namespaces.

The `Detection.taxonomy` field accommodates future namespaces ("ebird", "ioc",
"itis", "inaturalist") without further schema change.

### 3.4 Event schema — generalise, don't bolt on

**Decision:** Extend the `Detection` model in `orpheus-common` with two new
optional fields. These are general — populated by **any** classifier that has
the data.

```python
# platform/orpheus-common/src/orpheus_common/detection/models.py

class TemporalInterval(BaseModel):
    """A contiguous time range within the source audio clip where this
    detection's signal was observed."""

    start_seconds: float        # offset from clip start (0.0 = beginning)
    end_seconds: float
    confidence: Optional[float] = None  # per-interval confidence if known


class TaxonomyRef(BaseModel):
    """A reference to a class in a well-known taxonomy.

    namespace ∈ {"audioset", "ebird", "ioc", "inaturalist", ...}
    """

    namespace: str
    id: str
    common_name: Optional[str] = None   # convenience copy; not authoritative


class Detection(OrpheusBaseEvent):
    # ... existing fields unchanged ...
    timestamp: datetime
    detection_type: str
    channel: Optional[int] = None
    species_code: Optional[str] = None       # kept for backward compat
    species_common: Optional[str] = None     # kept for backward compat
    confidence: Optional[float] = None
    audio_clip_path: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # NEW — both optional, both forward-compatible
    intervals: Optional[list[TemporalInterval]] = None
    taxonomy: Optional[TaxonomyRef] = None
```

Why a list of intervals on a single Detection (rather than N Detections each
with one interval):
- A single label firing in 1-2s and 5-6s of a 10s clip is naturally one logical
  observation ("there was a dog barking in this clip") with two sub-locations.
- One Detection per (class, clip) keeps cardinality sane in DB and correlator.
- `intervals=None` means "no localisation data" (legacy / clip-level only); the
  audio_clip_path semantic is unchanged.

Why `taxonomy` separate from `species_code`:
- Keeps backward compat — bird-detection / crow-detection consumers don't change.
- New consumers can prefer `taxonomy` when present (richer, namespaced) and fall
  back to `species_code`.
- The entity-type taxonomy work built on this field as its foundation, with no
  further migration (see ADR 0016).

Backward compat: round-trip tests for `to_dict()` / `from_dict()` must include
the new fields. Missing fields parse as `None` (current `from_dict` does the
right thing already for unknown keys).

ADR follow-up: this schema change warrants a new ADR (proposed ADR 0011,
"Temporal Localisation and Taxonomy References on Detections"). Draft alongside
Commit 1.

### 3.5 Post-processing — frames → intervals

PANNs SED gives `framewise_output[T, 527]` per clip. Turning that into the
`intervals` list is standard SED post-processing. Algorithm (as implemented
in `post_processing.py:post_process`):

1. Drop classes outside the **taxonomy whitelist** (below) *before*
   thresholding (`allowed_class_indices`).
2. For each class `c`, compute clip-level score (max-pool over frames).
3. Drop classes below `clip_threshold` (configurable, default **0.3**).
4. Optionally keep only the top-K classes by clip score
   (`max_labels_per_clip`, default **unset** = no cap).
5. For each surviving class, find contiguous frame runs above
   `frame_threshold` (configurable, default **0.2**).
6. Bridge gaps shorter than `bridge_ms` (default **100 ms**).
7. Drop intervals shorter than `min_interval_ms` (default **150 ms**).
8. Fallback: if a class cleared the clip threshold but no frame run
   survived steps 5–7, emit one interval spanning the region around the
   peak frame — the consumer still learns the label fired *somewhere*.
9. Each surviving (class, runs) → one `Detection` with `intervals` list.

These parameters live in agent config (see §4.1) and are tunable per
deployment. Reasonable defaults are documented in the agent's README.

**AudioSet taxonomy whitelist.** The agent ships a *sparse* curated CSV at
`src/orpheus_agent_audio_events/data/audioset_class_labels_indices.csv`
(columns `index, mid, display_name`; ~53 of the 527 classes today). It is
loaded by `audioset_ontology.load_labels()` (memoised, validated for missing
columns / duplicate / negative indices) and its key set is passed to
`post_process(allowed_class_indices=...)` — so class indices PANNs emits that
we have no curated label for are silently dropped before thresholding: the
user sees coarser tagging, not a crash, and nothing downstream ever receives
an unlabelled machine_id. Expanding coverage = expanding the CSV; a
`make download-full-audioset-labels` target (fetching the canonical 527-row
PANNs release file) is still a TODO — see the agent README. A second,
*complete* 527-row CSV (`data/panns_class_labels_indices.csv`) is bundled
solely to satisfy `panns_inference`'s own import-time labels lookup (§4.1
lifecycle notes); the ontology itself is CC BY-SA 4.0
(`data/AUDIOSET_LICENSE.md`).

---

## 4. Detailed Design

### 4.1 The agent — `orpheus-agent-audio-events` (as built)

> This section documents the **shipped** agent. The original plan ("clone the
> crow-detection template") is in the git history of this file; the layout and
> behavior below match the code.

```
agents/orpheus-agent-audio-events/
├── Makefile                 # incl. download-models / check-models (PANNs checkpoint)
├── pyproject.toml
├── pytest.ini
├── README.md
├── requirements.txt
├── systemd/
│   └── orpheus-agent-audio-events.service
├── src/orpheus_agent_audio_events/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py            # AudioEventsConfig dataclass over unified orpheus.yaml
│   ├── model.py             # SEDModel ABC + DeterministicFakeSED + PANNsCnn14SED
│   ├── post_processing.py   # frames → intervals algorithm (§3.5)
│   ├── audioset_ontology.py # class index ↔ machine_id / display-name mapping
│   ├── data/
│   │   ├── audioset_class_labels_indices.csv  # sparse curated whitelist (§3.5)
│   │   ├── panns_class_labels_indices.csv     # canonical 527-row PANNs labels
│   │   └── AUDIOSET_LICENSE.md
│   └── main.py              # AudioEventsAgent(Actor): hooks + worker pool + emission
└── tests/
    ├── conftest.py
    ├── test_audioset_ontology.py
    ├── test_config.py
    ├── test_main.py          # agent pipeline via DeterministicFakeSED (no torch)
    ├── test_model_fake.py
    ├── test_post_processing.py
    └── integration/
        └── test_pipeline_e2e.py  # REAL checkpoint + real audio samples; auto-skips
```

Unit tests exercise the whole pipeline through `DeterministicFakeSED`
(injectable framewise "events") so CI never imports torch / panns_inference;
the integration test loads the real checkpoint and the bundled
`artifacts/audio-samples/` clips and auto-skips when either is absent.

#### Config schema (`config.py`)

`AudioEventsConfig` is a dataclass built by `from_orpheus_config()` from the
`audio_events:` block of the unified `orpheus.yaml`. Every key is additive
and defaulted (defaults shown), so an absent block runs the agent with stock
settings:

```python
@dataclass
class AudioEventsConfig:
    enabled: bool = True                   # gate: Actor.enabled() honors this
    model_path: str = "$ORPHEUS_DATA_ROOT/models/panns_cnn14_decision_level_max.pth"
    model_variant: str = "cnn14_sed"       # or "fake" (DeterministicFakeSED)
    sample_rate: int = 32000               # PANNs native; we resample 48k→32k
    clip_threshold: float = 0.3
    frame_threshold: float = 0.2
    bridge_ms: int = 100
    min_interval_ms: int = 150
    max_labels_per_clip: int | None = None # top-K cap per clip; unset = no cap
    device: str = "auto"                   # "auto" | "cuda" | "cpu" | passthrough
    # MQTT (defaults also overridable via mqtt.topics.* in orpheus.yaml)
    input_topic: str = "orpheus/audio/motion/events"
    output_topic: str = "orpheus/detection/audio/events"
    # Concurrency
    max_concurrent_clips: int = 2          # bounded pool; a new tick starts a clip
                                           # without cancelling an in-flight one
```

Defaults are conservative; expect tuning during field validation.

**`device`** — resolved at model load via the shared
`orpheus_common.utils.select_torch_device` seam: `"auto"` (the default) picks
CUDA when available, else CPU — survivable on a GPU-less host; an explicit
`"cuda"` with no CUDA **fails loud at startup** (the operator demanded a GPU);
anything more specific (`"cuda:1"`, `"mps"`) passes through untouched.

**`max_concurrent_clips`** (bounded worker pool) — the agent dispatches each
`audio.motion` clip to a bounded `ThreadPoolExecutor`; a new tick starts a fresh
clip *without cancelling* an in-flight one (older instances run to completion —
bird and audio-events stay peers and the correlator fuses their outputs). The
pool is small so SED inference can't thrash the Jetson's shared RAM/GPU; excess
ticks queue rather than drop. Each submission is wrapped in `_process_safely`,
which captures a per-clip failure as error stats (`errors_count` / `last_error`)
so one bad clip can never kill a worker thread; counters and the latency window
mutated from worker threads are guarded by a stats lock. The drain runs in
`on_stopping` (pre-disconnect) so in-flight clips finish *and* publish before the
bus closes; `wait_inflight()` exposes the same barrier to tests.

#### MQTT subscribe / publish

- **Subscribe:** `orpheus/audio/motion/events` (raw audio-motion clips)
- **Publish:** `orpheus/detection/audio/events`

Topic stays inside the existing `orpheus/detection/<detector>/events` hierarchy
established by ADR 0006. No topology surgery.

#### Detection emission

For each audio-motion event (validated with `Detection.model_validate`;
non-conforming payloads are skipped at debug level):
1. Load the clip from `audio_clip_path`, downmix to mono, resample to the
   model's SR (32 kHz for PANNs; `kaiser_fast`).
2. Run SED → `framewise_output[T, 527]`.
3. Post-process (§3.5, incl. the taxonomy whitelist) → `ClassifiedClip`
   entries.
4. For each surviving class, emit one `Detection` (as built in
   `main.py:_emit_detection`):

```python
Detection(
    timestamp=datetime.now(timezone.utc),
    detection_type="audio.classified",          # registered via ADR 0011
    channel=source.channel,
    species_code=f"audioset_{machine_id}",      # back-compat key for correlator
    species_common=display_name,                # display label
    confidence=clip_score,                      # clip-level max-pool score
    audio_clip_path=str(audio_path),
    context=source.context,
    source_event_id=source.event_id,
    # Chain root: inherit from the source audio.motion if it has one,
    # else the source IS the root. See cross-classifier-identity §1.1.
    root_event_id=Detection.derive_root_event_id(source),
    intervals=[TemporalInterval(start_seconds=..., end_seconds=...,
                                confidence=interval_score)],
    taxonomy=TaxonomyRef(namespace="audioset", id=machine_id,
                         common_name=display_name),
    metadata={
        "model": config.model_variant,          # e.g. "cnn14_sed"
        "class_index": class_index,
        "clip_threshold": config.clip_threshold,
        "frame_threshold": config.frame_threshold,
        "inference_time_ms": inference_time_ms,
    },
)
```

Each Detection is published to `output_topic`, saved to the shared
`orpheus_common.DetectionDB`, and then (only when the event-sourcing shadow
resolved on — see below) `shadow_publish()`ed to the durable domain stream.

#### Lifecycle — `Actor` base (ADR 0017)

`AudioEventsAgent` subclasses `orpheus_common.actor.Actor`, which owns the
generic agent lifecycle: identity derivation, event-bus creation + connect,
subscription wiring, signal handlers, the startup health publish, a
`HeartbeatPublisher` (30 s default, injectable `Clock`), the optional
KV-TTL presence emitter, and the optional **operational-health dual-write**
(when `event_bus.health_kv_enabled` is on with a KV-capable backend, every
health payload is written to the `orpheus_health` KV bucket *in addition to*
the bus publish). The agent fills in the hooks:

- `enabled()` — honors `audio_events.enabled` (default true); a disabled
  agent logs and exits without connecting.
- `on_setup()` (pre-connect) — configures logging, builds the SED model via
  `build_model()` on the device resolved by `select_torch_device` (see the
  `device` knob above), loads the AudioSet labels dict, and opens the shared
  `DetectionDB`. A missing checkpoint or labels CSV **fails loud** with a
  pointer to `make download-models`. Tests inject `model` / `labels` /
  `detection_db` through the constructor and skip all of this.
- `subscriptions()` — `[(input_topic, _on_audio_motion_event)]`; the base
  subscribes before connect.
- `on_started()` (post-connect) — resolves the event-sourcing shadow (below)
  via `ensure_domain_stream()`.
- `health_payload(phase)` — the health/heartbeat dict (below).
- `on_stopping()` (pre-disconnect) — drains the worker pool
  (`executor.shutdown(wait=True)`, run off the event loop) so in-flight clips
  finish *and publish* before the bus closes; new submits are rejected.
- `on_shutdown()` — final log line with the processed/emitted counters.

Behavioral notes where the shipped code differs from the original draft of
this section:

- **No synthetic-clip warm-up at startup.** The draft planned one; the code
  loads the model in `on_setup()` and serves the first real clip cold
  (rationale: see commit history).
- **No automatic CPU fallback on GPU OOM.** Device selection is decided
  up front by `select_torch_device`: `device: auto` (the default) picks CUDA
  only when it's actually available; an explicit `device: cuda` on a
  GPU-less host fails loud at startup instead of silently degrading.
- A clip missing on disk (audio-motion cleanup race) is logged and skipped
  without crashing, as planned; an event without `audio_clip_path` warns and
  skips; a payload that fails `Detection` validation is skipped at debug
  level.
- **PANNs labels staging.** `panns_inference` hardcodes its labels-CSV path
  to `Path.home()/panns_data/` at *module-import* time. The `PANNsCnn14SED`
  constructor therefore stages the bundled canonical 527-row CSV at
  `$ORPHEUS_DATA_ROOT/panns_data/` and temporarily pins `$HOME` there for the
  duration of the import (serialised under a module lock, `$HOME` restored
  after) — so the path is the same no matter which user systemd runs the
  service as. If anything imported `panns_inference` earlier in the process
  the pin would be a silent no-op, so the constructor refuses loudly instead.

#### Event-sourcing shadow-publish (off by default)

`on_started()` calls `orpheus_common.event_sourcing.ensure_domain_stream()`:
when `event_sourcing.shadow_publish_enabled` is on **and** the backend serves
streams (NATS JetStream — a no-op on MQTT), the bounded durable domain stream
is ensured and the agent shadow-publishes every emitted Detection to it,
keyed by `event_id` (dedup-able), *after* the DB save. Best-effort — a stream
hiccup never stalls the agent and a `stream_ensure` failure leaves the shadow
off; the DB stays the source of truth. See
[`event-sourcing-determinism-contract.md`](./event-sourcing-determinism-contract.md).

#### Health & observability

`health_payload("startup"/"heartbeat")` reports: `status`, `model_loaded`,
`model_variant`, `started_at`, `timestamp`, `events_processed`,
`detections_emitted`, `errors_count`, `last_error`,
**`event_sourcing_shadow`** (whether the shadow is *actually* recording — a
silent self-disable on mqtt / `stream_ensure` error is otherwise invisible),
`last_inference_at`, and **`inference_latency_ms`** — `{samples, p50, p95,
max}` computed over a rolling window of the last 100 inferences (numpy-free
linear-interpolation percentile, so the Jetson dependency set stays lean).
`health_payload("shutdown")` is the offline subset (status + counters +
timestamp). The base publishes these on the agent's health topic and, when
enabled, dual-writes them to the operational-health KV.

### 4.2 Schema changes in `orpheus-common`

Single, additive PR to `orpheus-common`:

- Add `TemporalInterval`, `TaxonomyRef` Pydantic models in
  `platform/orpheus-common/src/orpheus_common/detection/models.py`.
- Extend `Detection` with `intervals: Optional[list[TemporalInterval]] = None`
  and `taxonomy: Optional[TaxonomyRef] = None`.
- Extend `Detection.to_dict()` / `from_dict()` round-trip.
- Tests cover:
  - Detection without new fields (legacy compat).
  - Detection with `intervals=None` (default).
  - Detection with multiple intervals serialises/deserialises identically.
  - Detection with `taxonomy` present and absent.

Ship this first. Every downstream change rests on it.

### 4.3 Database & storage

DB schema (`detections` SQLite table) needs additive migration:

- New column `intervals_json TEXT NULL` (stores JSON list of intervals).
- New column `taxonomy_namespace TEXT NULL`.
- New column `taxonomy_id TEXT NULL`.

Use the existing `ensure_schema_updates()` migration hook (same pattern as the
species-links plan in the backlog). Idempotent: re-running on a populated DB
is a no-op.

No backfill. Legacy rows have `intervals_json = NULL` and consumers handle that
as "no intra-clip localisation available."

### 4.4 Event correlator integration

Two changes in `agents/orpheus-agent-event-correlator/`:

1. **Accept the new detection type.** Add `"audio.classified"` to
   `PROCESSED_DETECTION_TYPES` in `main.py`.

2. **Cross-classifier merging.** The alias map proposed here was **rejected**
   before implementation, not shipped. Identity resolution lives in the
   `taxonomy_equivalence` table and `orpheus_common.detection.equivalence` — see
   [cross-classifier-identity.md](cross-classifier-identity.md) and ADR 0013.
   There is no `orpheus_common.detection.aliases` module and no `canonicalize()`.
   The sketch below is kept only so the rejection is legible:

   ```python
   # platform/orpheus-common/src/orpheus_common/detection/aliases.py
   SPECIES_CODE_ALIASES: dict[str, str] = {
       # Crow signals from three classifiers → one canonical key
       "amecro": "crow",                        # BirdNET
       "american_crow": "crow",                 # crow-tools
       "audioset_/m/04s8yn": "crow",            # PANNs Crow (class 117)
       "audioset_/m/07r5c2p": "crow",           # PANNs Caw  (class 118)

       # Obvious cross-classifier duplicates emerging from AudioSet
       # (verify exact machine_ids during impl — these are placeholders)
       # "audioset_/m/0bt9lr": "dog",           # PANNs Dog
       # "audioset_/m/09l8g": "human_voice",    # PANNs Speech
   }

   def canonicalize(species_code: str) -> str:
       return SPECIES_CODE_ALIASES.get(species_code, species_code)
   ```

   Then in `cluster_manager.py:process_observation`, replace the cluster-key
   lookup with `canonicalize(obs.species_code)`. Evidence list keeps the
   *original* `species_code` so users can see which classifier said what.

3. **Pass through `intervals`.** When the correlator builds an `Entity` and its
   `evidence` list, propagate each Detection's `intervals` into the evidence
   entry. (Schema change: add `intervals` to `EntityEvidence`.) This is what
   lets the UI/downstream show "the three classifiers all heard a crow,
   localised at 2.3-3.1s in the clip."

4. **Regression test:** three classifiers firing on the same clip (BirdNET,
   crow-tools, PANNs) merge into one Entity with three pieces of evidence;
   non-aliased species (e.g., "norcar") still cluster separately.

The full alias-discovery / taxonomic-hierarchy work is still owned by the
"[ARCH] Generalize the EntityEvent State Space Taxonomy" backlog issue. We
are intentionally scoping the alias map narrowly.

### 4.5 Cross-cutting: localisation on **every** detector

The point of putting `intervals` on the base `Detection` model is so it's
populated everywhere it makes sense.

- **`orpheus-agent-audio-motion`** — populate `intervals=[TemporalInterval(0.0,
  duration_seconds, confidence=None)]` to express "the whole clip is the motion
  window." Trivial change in `channel_processor.py`.
- **`orpheus-agent-bird-detection`** — BirdNET runs on overlapping 3-s windows.
  Today only the aggregated label survives; the per-window timestamps are
  discarded. Plumb them through: each emitted `Detection` for a species gets
  `intervals=[<each window where that species cleared threshold>]`. Surgical
  change in the BirdNET wrapper (`birdnet.py`) and the agent's emission code
  (`main.py`).
- **`orpheus-agent-crow-detection`** — operates on bird events; if the source
  bird Detection has `intervals`, pass them through to the emitted
  `crow.analyzed` Detection.
- **`orpheus-agent-video-motion`** etc. — out of scope (video time intervals
  are a different concept; revisit later if it becomes useful).

---

## 5. UI Changes

### 5.1 New `/audio-events` page

`services/orpheus_ui/frontend/src/pages/AudioEvents.tsx` mirrors `Birds.tsx`
and `Crows.tsx`. Reuses existing components:

- `SpeciesFilter` (relabelled "Labels" in this context — same component, different prop label)
- `DateRangeFilter`
- `ClipActions` (enhanced — see §5.2)
- Time-of-day chart, label distribution pie chart, hourly stacked bar
- React Query pagination

Backend endpoint `GET /api/data/audio-events/history` mirrors the
`bird-history` contract (date range, time-of-day window, labels CSV,
page/page_size). Mirror its tests one-to-one in
`services/orpheus_ui/backend/tests/`.

### 5.2 Intra-clip playback — highlight intervals

**Not built.** `ClipActions`
(`services/orpheus_ui/frontend/src/components/ClipActions.tsx`) offers play,
pause and download only; the `/audio-events` and Entities pages render each
detection's `intervals` as text instead. The rest of this section is a plan.

`ClipActions` (or a new `ClipPlayerWithIntervals` component) would render the
detected `intervals` as highlighted bands on the audio scrubber. Click a band
to seek and play just that range.

This would work for **all detection types** that carry `intervals` — Birds and
Crows pages get it for free, since bird-detection and crow-detection already
populate localisation (§4.5). Bird-detection's per-window timestamps become
visible as playable bands on the Birds page. No bird-specific code paths.

### 5.3 Entities page

Update the page description to "correlated animal and audio events from
multiple sensors." The Entity card UI shows evidence with intervals now (each
piece of evidence carries its own intra-clip interval data).

### 5.4 Backend "diagnostics" filter cleanup — deferred to follow-up

The hardcoded `NON_BIRD_SOUNDS` set at
`services/orpheus_ui/backend/src/orpheus_ui/api/diagnostics.py` exists
because BirdNET sometimes emits non-bird labels. Once audio-events is producing
real, taxonomy-correct labels, that hack should be retired in favour of filtering
by `detection_type` and `taxonomy.namespace`. **Don't do that in this PR** —
it's a separate follow-up PR that depends on this work being in production for
a few weeks of soak.

---

## 6. Testing Strategy

### 6.1 Unit tests

- **`orpheus-common`:** Round-trip tests for `Detection.to_dict()/from_dict()`
  with and without `intervals`/`taxonomy`. Equality across serialisation.
- **`orpheus-agent-audio-events`** (as built — no committed .wav unit
  fixtures; clips are synthesised on the fly and the SED is the
  deterministic fake, so unit CI never imports torch):
  - `test_post_processing.py`: synthetic SED matrices → expected intervals
    (threshold crossing, gap bridging, min-duration filter, whitelist,
    top-K cap, peak fallback).
  - `test_model_fake.py`: `DeterministicFakeSED` shape/injection contract.
  - `test_main.py`: end-to-end agent pipeline with the fake model + a mocked
    bus — feed an `audio.motion` event referencing a generated clip, assert
    correct `audio.classified` Detection(s) are emitted with intervals.
  - `test_config.py` / `test_audioset_ontology.py`: config defaults +
    labels-CSV loading/validation.
  - `tests/integration/test_pipeline_e2e.py`: the REAL checkpoint + real
    `artifacts/audio-samples/` clips; auto-skips when the checkpoint,
    samples, or torch are absent.
- **`orpheus-agent-event-correlator`:**
  - Three-classifier merge regression (BirdNET + crow-tools + PANNs all fire
    "crow" → one Entity, evidence list has three entries with original
    species_codes preserved).
  - Non-aliased species don't merge (e.g., "norcar" + "amecro" → two Entities).
  - Empty/unknown species_code passes through `canonicalize()` unchanged.

### 6.2 Audio fixtures

> **Superseded as built:** the unit tests synthesise clips at runtime against
> `DeterministicFakeSED` instead of committing .wav fixtures; real-audio
> coverage comes from `artifacts/audio-samples/` via the integration test
> (rationale: see commit history). The original fixture plan is kept below
> for reference.

Generate or curate ~6 fixtures in `tests/fixtures/`:

- `silence_3s.wav` — model should emit zero detections.
- `dog_bark_3s.wav` — single label, single interval.
- `speech_5s.wav` — single label, may span the whole clip.
- `crow_call_4s.wav` — bird/crow label; used by both audio-events test and
  three-classifier correlator regression.
- `overlap_dog_bird_8s.wav` — multi-label, distinct intervals (the localisation
  test; assert the two labels' intervals are non-overlapping in time).
- `dawn_chorus_10s.wav` — multi-bird overlap; smoke test that we don't crash
  and emit reasonable bird-vocalization tags.

Fixtures committed via Git LFS like other audio fixtures.

### 6.3 Jetson smoke test

A documented manual smoke test (recorded in `agents/orpheus-agent-audio-events/README.md`):

1. Deploy the agent on Jetson Orin NX.
2. Trigger 10 audio-motion events from real microphones over 5 minutes.
3. Confirm:
   - Each clip gets at least one `audio.classified` Detection emitted within
     250 ms of the audio-motion event.
   - GPU memory headroom remains ≥1 GB.
   - CPU temperature stays under 80 °C (no new thermal regression vs baseline).
4. Confirm in the UI that intervals render and playback seeks correctly.

Capture the inference latency and memory numbers in a comment on the tracking
issue. If Cnn14 doesn't fit the budget, swap to Cnn10 via config (same code
path, no schema change) and re-test.

### 6.4 Coverage

`make coverage` ≥70% on the new agent — matches existing component standard.

---

## 7. Phasing / Rollout Plan

Shipped as six commits in the order below. Retained for review archaeology; nothing here is outstanding work. Splitting
into commits (not PRs) keeps the entire change atomic from a deploy/review
perspective while keeping each step independently reviewable in the PR diff.

1. **Commit 1 — schema (orpheus-common).** Add `TemporalInterval`, `TaxonomyRef`,
   extend `Detection`. Round-trip tests. ADR 0011 draft. **Smallest, lands first.**
2. **Commit 2 — audio-motion backfill.** Populate `intervals=[(0, duration)]` on
   every audio.motion event. (Smoke-checks the schema in flight.)
3. **Commit 3 — new agent.** `orpheus-agent-audio-events`. Includes the
   audioset_ontology data file, model wrapper, post-processing, MQTT lifecycle,
   tests, systemd unit, Makefile, README. Plus DB column migration. **Largest commit.**
4. **Commit 4 — bird-detection localisation.** Plumb BirdNET per-window timestamps
   through into the emitted `species.detected` Detection's `intervals` list.
   Mirror in crow-detection (pass-through).
5. **Commit 5 — correlator integration.** Alias map (`aliases.py`) + accept
   `audio.classified` + propagate intervals into `EntityEvidence`. Three-classifier
   merge regression test.
6. **Commit 6 — UI.** `/audio-events` page, backend endpoint, ClipActions intervals
   highlighting. Update Entities page copy. (Note: bird/crow pages automatically
   benefit from Commit 4's intervals via the shared ClipActions enhancement.)

The PR ships green CI, ≥70% coverage on new code, and README/doc updates where
relevant. Tracked under the existing "[FEATURE] Audio Events Agent" backlog
issue.

---

## 8. Performance & Resource Budget

| Resource | Budget | Notes |
|---|---|---|
| Inference latency (Cnn14 SED, 3-s clip) | ≤ 200 ms on Orin NX GPU | Estimated; benchmark in Commit 3. Cnn10 fallback target: ≤ 50 ms. |
| Steady-state GPU memory | ≤ 1.5 GB for the new agent | BirdNET ~400 MB, AVES ~400 MB, crow-tools ~200 MB; ~6 GB headroom typical. |
| Steady-state CPU | ≤ 5% extra on idle | Audio-motion duty cycle determines real load. |
| DB row growth | ~2-5× current detection rate | We now emit multiple audio.classified per clip; budget storage and the existing rotation/cleanup policy. |
| Thermal | No regression in `jtop` CPU/GPU temps after 24h soak | If we see regression, drop to Cnn10. |

The backlog has `[HARDWARE] Dynamic Thermal Throttling & Load Shedding` — that
work would graceful-degrade this agent under heat, but we don't depend on it
landing first.

---

## 9. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cnn14 saturates Jetson alongside BirdNET + AVES + crow-tools | Med | High | Fall back to Cnn10 — same code path, config swap. Budget benchmarking in Commit 3. |
| AudioSet labels too noisy / not useful for our wetland soundscape | Med | Med | Thresholds are tunable; start conservative (0.3 clip / 0.2 frame). Re-evaluate after a week of field data. CED-base is a clean upgrade path. |
| Alias map accidentally merges legitimately distinct species | Low | High | Map is intentionally small (only crow on day one). Each addition needs a regression test. The full taxonomy work is tracked separately. |
| Schema change breaks an existing consumer | Low | High | All new fields default `None`. Round-trip tests in PR 1. Correlator's "dual-schema parsing" rule from ADR 0006 §3.3 also applies here. |
| Disk growth from many more detections | Med | Med | One Detection per (class, clip) keeps cardinality bounded by ~10× typical (most clips have ≤3 distinct labels above threshold). Monitor in the first week. |
| PANNs weights distribution | Low | Med | Commit via Git LFS to `artifacts/models/`, add `make download-models` target with HF mirror fallback. Same pattern as BirdNET/AVES. |
| Frame-level intervals from BirdNET don't align cleanly with audio-events intervals | Low | Low | Document expected granularity differences in the UI; let users see both as separate evidence on an Entity. |

---

## 10. Open Questions (historical — open at draft time)

Where the shipped code embodies an answer, it's noted inline.

1. **Model checkpoint hash to pin.** PANNs has no semver; we pin a specific
   download URL + sha256. Confirm which Cnn14_DecisionLevelMax checkpoint
   (the original Kong et al. release vs any community re-train).
   *Partially resolved:* `make download-models` prefers the in-repo LFS
   artifact (`artifacts/models/`) and falls back to the Zenodo release URL;
   no sha256 verification yet.
2. **Confidence semantics for `Detection.confidence`** when `intervals` is
   present. Proposal: `confidence` = clip-level max-pool score, and per-interval
   confidence lives on each `TemporalInterval`. Confirm.
   *Resolved as proposed* — see the emission snippet in §4.1.
3. **Cardinality cap.** If post-processing yields 12 labels above threshold for
   a noisy dawn-chorus clip, do we emit 12 Detections, or cap at top-K? Proposal:
   no cap initially, monitor, cap if DB growth is a problem.
   *Resolved:* a configurable top-K cap exists (`max_labels_per_clip`),
   default unset = no cap — the proposal, with the escape hatch pre-built.
4. **ADR 0011 timing.** Draft alongside Commit 1 or as a precursor commit?
   Proposal: alongside Commit 1 — the schema commit includes the ADR so the
   rationale is in the same review.
   *Resolved:* ADR 0011 shipped with the schema (see header).
5. **AudioSet machine_id for "Bird" parent vs "Bird vocalization, bird call,
   bird song" leaf.** Decide whether to roll up at emission time or query
   time. Proposal: emit leaves only; UI rolls up using the ontology hierarchy.
   *Current behavior:* the agent emits exactly the classes present in the
   curated whitelist CSV (§3.5) with no roll-up at emission time; the
   rationale for which classes are curated in is not recorded here (see
   commit history).

---

## 11. Deferred to Future Work

- **Source separation** (BirdMixIT / TDCN++ / future DCASE 2025 systems).
  Tracked by "[SPIKE] Isolate Individual Bird Calls from Overlapped Audio."
  Frame-level intervals from this work are the input for that experiment.
- **Bird-detection downstream of audio-events.** Evaluate after 2-4 weeks of
  parallel-run field data showing audio-events has acceptable recall on
  biological sounds.
- **Full state-space taxonomy** ("[ARCH] Generalize the EntityEvent State Space
  Taxonomy"). The `taxonomy` field we add here is the foundation.
- **NON_BIRD_SOUNDS filter retirement.** Cleanup PR after audio-events has
  soaked in production.
- **CED-base upgrade.** If accuracy on coarse labels is insufficient with PANNs
  Cnn14, swap models — no schema change, same post-processing (CED is clip-level
  so intervals would degrade to single-window spans).
- **Locality-aware tuning.** Once we have a few weeks of Michigan-specific data,
  consider down-weighting AudioSet classes that are implausible at the deployment
  location (the soft geo-admit pattern from `6951b8d` generalised).
- **ONNX/TensorRT acceleration.** If GPU contention is a problem.
- **Automatic alias-discovery for the correlator.** From the alias-map backlog
  issue: surface candidate aliases when two classifiers consistently fire on the
  same `source_event_id` with different species_codes.

---

## 12. References

### Internal

- Backlog: `docs/backlog.json` — issues `[FEATURE] Audio Events Agent`,
  `[CORE] Correlator Alias Map`, `[ARCH] Generalize the EntityEvent State Space
  Taxonomy`, `[SPIKE] Isolate Individual Bird Calls from Overlapped Audio`.
- ADR 0005: Event-Driven Architecture and Context.
- ADR 0006: Event Hierarchy and Taxonomy (new ADR 0011 to extend this).
- Recent commits on this branch: `74a479a` (sigmoid multi-label),
  `6951b8d` (geo-admit), `9dc0845` (dedupe by label idx).
- `platform/orpheus-common/src/orpheus_common/detection/models.py` —
  `Detection` model.
- `agents/orpheus-agent-crow-detection/` — clone template.
- `services/orpheus_ui/frontend/src/pages/Birds.tsx`,
  `services/orpheus_ui/frontend/src/pages/Crows.tsx` — UI template.

### External

- PANNs paper (Kong et al., 2020): https://arxiv.org/abs/1912.10211
- PANNs repo: https://github.com/qiuqiangkong/audioset_tagging_cnn
- `panns_inference` package: https://github.com/qiuqiangkong/panns_inference
- AudioSet ontology: https://github.com/audioset/ontology
- AudioSet ontology JSON: https://research.google.com/audioset/ontology/index.html
- Model audit (this conversation, in-thread) — full comparison table, taxonomy
  notes, latency estimates, sourcing.
