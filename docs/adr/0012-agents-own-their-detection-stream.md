# ADR 0012: Agents Own (and Persist) Their Own Detection Stream

**Status:** Accepted

**Date:** 2026-06-04

**Deciders:** Scott, Development Team

**Related:** ADR 0011 (temporal localisation + taxonomy refs), the
cross-classifier-identity stack (`docs/designs/cross-classifier-identity.md`)

## Context

Every classifier agent emits a detection stream and persists it to the
shared `DetectionDB`:

| Agent | detection_type | persists its own stream? |
|---|---|---|
| bird-detection | `species.detected` | yes (`db.save`) |
| audio-events | `audio.classified` | yes (`db.save`) |
| crow-detection | `crow.analyzed` | yes (`db.save`) |
| **audio-motion** | `audio.motion` | **NO (only published to MQTT)** |

`audio.motion` is special: it is the **root of every detection chain**.
When a clip triggers motion, audio-motion publishes an `audio.motion`
event with a generated `event_id`. Every downstream classifier
(bird-detection, audio-events, crow-detection) receives that event and
stores the motion `event_id` as its own `source_event_id` (and, where
set, `root_event_id`). The cross-classifier-identity stack
(correlation → entity clustering, lineage/chain walking, the
`root_event_id` backfill, the Bird-Correlation-vs-BirdNET parity
dashboard) all join detections **back to the audio.motion root by that
event_id**.

Because audio-motion never persisted its own stream, the
`audio.motion` rows in the DB were being written by an accidental
recorder: the **UI backend** (`orpheus_ui/api/diagnostics.py`,
`on_audio_detection_message`) subscribed to the motion topic and called
`db.save()`. Critically, it constructed a **brand-new `Detection`
without passing `event_id`**, so the model's `default_factory` minted a
*fresh* UUID on every save.

### The bug this caused

The persisted chain root's `event_id` (minted by the UI backend) never
matched the `event_id` audio-motion published (and that every downstream
detection stored as `source_event_id`). The chain was structurally
unjoinable. Measured on the production Jetson DB (read-only):

- **0 of 6,512** recent `species.detected` rows had a `source_event_id`
  that matched **any** row's `event_id` — the chain resolved nowhere.
- The `root_event_id` backfill reported **62% of rows "chain broken"**
  (975k of 1.56M) for the same reason.
- The Bird-Correlation parity dashboard reported **100% "neither"**
  (8,832 audio.motion events, 0 matched to bird or audio-events).

Entity clustering, detection-chain/lineage endpoints, and auto-discovery
were all silently degraded by the same root cause.

This is also an **architecture/ownership smell**: a presentation-layer
service (the UI backend) was performing data persistence for a stream it
doesn't own, and doing it lossily.

## Decision

**Each agent owns and persists its own detection stream. The UI backend
is presentation-only and does not write to `DetectionDB`.**

Concretely:

1. **audio-motion persists its own `audio.motion` stream.** The agent
   constructs the `Detection` (it already did, to publish it — with the
   correct `event_id` and `root_event_id == event_id`) and now also
   calls `DetectionDB.save()` on that *same object*, immediately after
   publishing. Persistence is best-effort and happens AFTER publish:
   a DB error is logged and swallowed so a storage hiccup does not stop
   motion detection or MQTT publishing. Wired via a `detection_db`
   parameter on `ChannelProcessor`, constructed once in the agent's `main`.

2. **The UI backend stops persisting `audio.motion`.**
   `on_audio_detection_message` keeps its in-memory cache (for the live
   audio-levels display) but no longer calls `db.save()`. The historical
   `audio.motion` rows now come from the agent, with the published id.

### Invariant (enforced by test)

> The persisted `audio.motion` row carries the **same `event_id`** the
> agent published, and `root_event_id == event_id`.

See `agents/orpheus-agent-audio-motion/tests/test_detection_db_persistence.py`.

## Consequences

- **Forward-correct immediately.** New `audio.motion` rows carry the
  published id, so new detections chain correctly — correlation, entity
  clustering, lineage, and the backfill all work for data recorded after
  this ships.
- **Historical rows are not retroactively fixed.** The ~512k existing
  `audio.motion` rows were written by the UI backend with wrong
  (minted) ids; downstream rows reference ids that were never persisted.
  Recovering history requires a separate one-time migration that
  re-links children to their motion root by a stable shared key
  (`audio_clip_path` — the motion row and all its children share the
  exact clip path). Logged as a follow-up in the backlog.
  The parity dashboard is an intentionally multi-day, forward-looking
  tool, so forward-correctness is sufficient for its purpose.
- **Resilience improved.** audio.motion persistence no longer depends on
  the UI service being up.
- **No new dependency.** audio-motion already depends on orpheus-common;
  it just uses `DetectionDB` now.

## Rule for future agents

**If you add an agent that emits a detection stream, that agent
persists its own stream to `DetectionDB` (`db.save()` on the same
`Detection` it publishes). Never rely on another service — and never on
the UI backend — to record your stream. Never reconstruct a `Detection`
for persistence without preserving the published `event_id` /
`source_event_id` / `root_event_id`: those ids are the cross-classifier
chain and minting new ones silently breaks correlation, lineage, and
entity clustering.**

This rule is mirrored in `docs/agent-instructions/21-event-bus-and-data-flow.md`
and `docs/agent-instructions/30-recipes-adding-agent.md`.
