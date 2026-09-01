# orpheus-agent-audio-events

General-purpose audio event classification agent. Tags every audio-motion-triggered
clip against the **AudioSet 527-class ontology** using **PANNs Sound Event
Detection** with native frame-level outputs. Runs in parallel with bird-detection,
crow-detection, and audio-motion on the Jetson Orin NX.

This agent is what lets the system answer "what else was in that clip?" —
dog barks, vehicles, human voices, rain, lawn mowers, anything in the AudioSet
ontology — and *when* in the clip each sound occurred.

## What it produces

For every `audio.motion` event arriving on `orpheus/audio/motion/events`,
the agent emits one `Detection(detection_type="audio.classified")` per
surviving AudioSet label on `orpheus/detection/audio/events`. Each emitted
Detection carries:

- `taxonomy`: `{namespace: "audioset", id: "/m/...", common_name: "..."}` per ADR 0011
- `species_code`: `"audioset_<machine_id>"` (correlator-friendly)
- `intervals`: list of `TemporalInterval(start_seconds, end_seconds, confidence)`
  describing *when* in the clip the label fired (frame-level, ~31 ms granularity)
- `source_event_id`: the immediate parent (the audio.motion event_id)
- `root_event_id`: the chain root (the audio.motion event_id at the
  top of the source-chain). One-hop downstream of audio-motion, so
  `root_event_id == source_event_id` for this agent. See
  [`docs/designs/cross-classifier-identity.md`](../../docs/designs/cross-classifier-identity.md) §1.1.

## Architecture

```text
orpheus/audio/motion/events
      │
      ▼
┌───────────────────────────────────────────┐
│ orpheus-agent-audio-events                │
│   1. Load clip, resample to 32 kHz mono   │
│   2. PANNs Cnn14_DecisionLevelMax → SED   │
│   3. Post-process frames → intervals       │
│   4. Emit one Detection per (class, clip)  │
└───────────────────────────────────────────┘
      │
      ▼
orpheus/detection/audio/events
```

See `docs/designs/audio-events-agent.md` for the full design and
`docs/adr/0011-temporal-localisation-and-taxonomy-references.md` for the
schema.

## Local development

```bash
make install       # create venv, install deps (orpheus-common + panns-inference)
make test          # run pytest
make coverage      # pytest + coverage report
make lint          # ruff
make download-models  # fetch PANNs checkpoint into $ORPHEUS_DATA_ROOT/models/
make run           # run the agent locally against your dev event-bus broker
```

## Configuration

Add (or omit — defaults are sensible) an `audio_events` section to `orpheus.yaml`:

```yaml
audio_events:
  enabled: true
  model_variant: cnn14_sed         # or "cnn10_sed" for the lighter fallback
  model_path: /data/orpheus/models/panns_cnn14_decision_level_max.pth
  sample_rate: 32000
  device: auto                     # auto (cuda if available, else cpu) | cuda | cpu
  clip_threshold: 0.3              # drop classes whose clip max < this
  frame_threshold: 0.2             # frames above this constitute intervals
  bridge_ms: 100                   # bridge sub-bridge gaps within a class
  min_interval_ms: 150             # drop intervals shorter than this
  max_labels_per_clip: null        # null = no cap; or e.g. 10 to keep top-K
  input_topic: orpheus/audio/motion/events
  output_topic: orpheus/detection/audio/events
```

## AudioSet labels

The bundled `data/audioset_class_labels_indices.csv` is a **sparse, curated
subset** of the 527-class ontology (~40 entries covering the Orpheus core:
birds, mammals, humans, vehicles, weather, environment). Indices outside the
bundled subset are silently skipped by post-processing.

Production deployments should swap in the canonical 527-row file — see
`src/orpheus_agent_audio_events/data/AUDIOSET_LICENSE.md` for the source.
A `make download-full-audioset-labels` target will be added in a follow-up
PR to automate this.

## Testing strategy

The agent's pipeline is fully unit-tested via the `DeterministicFakeSED`
class — a synthesizable, reproducible SED implementation that lets us
exercise post-processing, MQTT lifecycle, and Detection construction without
loading PyTorch or downloading the 300+ MB PANNs checkpoint.

**Jetson smoke test before deployment:**

1. `make install` + `make download-models` on the Jetson.
2. Deploy via `sudo ./systemd/install-service.sh`.
3. `sudo systemctl start orpheus-agent-audio-events`.
4. Trigger 10 audio-motion events from real microphones over 5 minutes.
5. Confirm:
   - Each clip gets at least one `audio.classified` Detection emitted within
     ~250 ms of the audio-motion event.
   - GPU memory headroom remains ≥1 GB alongside BirdNET + AVES + crow-tools.
   - CPU temperature stays under 80 °C (no thermal regression vs baseline).
6. Confirm in the UI that intervals render and playback seeks correctly.

If Cnn14 doesn't fit the budget, swap to Cnn10 via the `model_variant` config
key — same code path, no schema change.

## Open questions

See `docs/designs/audio-events-agent.md` §10. Most relevant to this agent:

- Confidence semantics: `Detection.confidence` is the clip-level max-pool
  score; each `TemporalInterval.confidence` is the score within that interval.
- Cardinality cap: currently uncapped (`max_labels_per_clip: null`). May
  need a cap if a noisy dawn-chorus clip yields too many labels above
  threshold and pollutes the DB.
- ONNX/TensorRT acceleration: separable optimisation. Not required for v1.
