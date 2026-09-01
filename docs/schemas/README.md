# Orpheus Event Schemas

> **These schemas are illustrative, not authoritative.** The wire contract is the Pydantic `Detection` model in `orpheus_common.detection.models`, which every agent serialises directly. Nothing in the codebase reads the files in this directory, nothing validates against them, and they have drifted: each one describes a top-level shape that the corresponding agent no longer publishes, so a real payload would fail validation against its own schema. They are kept as a readable sketch of the event families while they are regenerated from the models.

This directory contains JSON Schema sketches for three of the event types used in
the Orpheus platform. Events travel over the event bus — NATS with JetStream by
default, MQTT as a fallback — and the platform publishes more types than are
described here (audio classification, entity and entity-update events, playback
request and response, actuation, and health among them).

## Available Schemas

### Detection Events

| Schema | Description | Publisher | Topic |
| -------- | ------------- | ----------- | ------- |
| `audio-motion-event.schema.json` | Audio activity detected above threshold | orpheus-agent-audio-motion | `orpheus/audio/motion/events` |
| `bird-detection-event.schema.json` | Bird species identified via BirdNET | orpheus-agent-bird-detection | `orpheus/detection/bird/events` |
| `crow-detection-event.schema.json` | Crow vocalization analyzed (species, call type, quality) | orpheus-agent-crow-detection | `orpheus/detection/crow/events` |

## Schema Evolution

When modifying schemas:

1. **Add new optional fields** - Safe, backward compatible
2. **Make required fields optional** - Safe, but may indicate agent needs update
3. **Add new enum values** - Safe, backward compatible
4. **Remove fields or enum values** - Breaking change, requires coordination
5. **Change field types** - Breaking change, requires coordination

For breaking changes:

- Update schema version in `$id` field
- Update all agents and dashboard code
- Test thoroughly before deployment

## Validation

There is no CI job validating these files today, and no code loads them. If they
are to become a real contract, the direction is to generate them from the
Pydantic models rather than maintain them by hand — a hand-written schema beside
a Pydantic model is two sources of truth that drift, which is what happened here.
