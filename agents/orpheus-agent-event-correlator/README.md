# Orpheus Event Correlator Agent

Temporal fusion agent that collapses a stream of per-event species detections into entity-level sighting records.

## Overview

Individual inference agents (BirdNET, crow classifier) emit one detection event per audio clip analyzed. In the real world, a single crow calling repeatedly over five seconds will produce many overlapping events — all for the same physical animal. The Event Correlator resolves this into a single, high-confidence **EntityEvent**: "an American Crow was present, here is all the evidence."

It subscribes to detection topics, groups incoming detections by species within a sliding time window, and when the window closes with no new observations, publishes a fused EntityEvent and persists it to the local DetectionDB.

## Responsibilities

- Subscribe to all configured detection topics (BirdNET, crow classifier, and any future inference agents)
- Ignore raw motion triggers (`audio.motion`) — only process species-level inferences
- Group observations by `species_code` within a configurable time window (default: 3 seconds)
- Fuse multiple observations into a single EntityEvent with aggregated evidence and max confidence
- Publish the EntityEvent to `orpheus/entities/animal`
- Persist the EntityEvent to DetectionDB (SQLite)
- Flush all open clusters gracefully on shutdown

## MQTT Topics

**Subscribes to** (configurable via `orpheus.yaml`):

| Topic | Source Agent | Event Type Processed |
| --- | --- | --- |
| `orpheus/detection/bird/events` | orpheus-agent-bird-detection | `species.detected` |
| `orpheus/detection/crow/events` | orpheus-agent-crow-detection | `crow.analyzed` |

The set of input topics is configured at runtime via `correlation.input_topics` in `orpheus.yaml`. Additional inference agents can be added without modifying this agent's code.

Detection events with `detection_type: "audio.motion"` are explicitly ignored — they are raw triggers, not species identifications.

**Publishes to:**

| Topic | Description |
| --- | --- |
| `orpheus/entities/animal` | Fused EntityEvent — one record per confirmed animal presence |
| `orpheus/system/event-correlator/health` | Agent liveness (online/offline, event counts) |

## Event Formats

### Input: Bird Detection Event (`orpheus/detection/bird/events`)

```json
{
  "event_id": "bird_det_20251204_223557_ch1_001",
  "source_event_id": "audio_motion_20251204_223555_ch1",
  "timestamp": "2025-12-04T22:35:58.123456+00:00",
  "channel_id": "1",
  "detection_type": "species.detected",
  "detections": [
    {
      "species_code": "amecro",
      "species_scientific": "Corvus brachyrhynchos",
      "species_common": "American Crow",
      "confidence": 0.87,
      "start_time": 0.5,
      "end_time": 1.2
    }
  ],
  "audio_clip_path": "/data/orpheus/audio/audio_motion/1/2025-12-04/event_20251204_223555.flac",
  "model_version": "BirdNET_V2.4",
  "inference_time_ms": 145
}
```

### Input: Crow Analysis Event (`orpheus/detection/crow/events`)

```json
{
  "event_id": "crow_det_20251205_091230_ch2",
  "source_event_id": "audio_motion_20251205_091228_ch2",
  "timestamp": "2025-12-05T09:12:30.000000+00:00",
  "channel_id": "2",
  "detection_type": "crow.analyzed",
  "species_code": "amecro",
  "species_common": "American Crow",
  "confidence": 0.91,
  "audio_clip_path": "/data/orpheus/audio/audio_motion/2/2025-12-05/event_20251205_091228.flac"
}
```

### Output: EntityEvent (`orpheus/entities/animal`)

```json
{
  "entity_id": "3f7a1c2e-9b4d-4e8f-a1b2-c3d4e5f60718",
  "timestamp": "2025-12-04T22:35:59.456789+00:00",
  "species_code": "amecro",
  "common_name": "American Crow",
  "confidence": 0.91,
  "context": {
    "lat": 47.6062,
    "lon": -122.3321,
    "timestamp": "2025-12-04T22:35:59.456789+00:00"
  },
  "evidence": [
    {
      "event_id": "bird_det_20251204_223557_ch1_001",
      "source_event_id": "audio_motion_20251204_223555_ch1",
      "sensor_id": "channel_1",
      "clip_path": "/data/orpheus/audio/audio_motion/1/2025-12-04/event_20251204_223555.flac",
      "confidence": 0.87
    },
    {
      "event_id": "crow_det_20251204_223558_ch1",
      "source_event_id": "audio_motion_20251204_223555_ch1",
      "sensor_id": "channel_1",
      "clip_path": "/data/orpheus/audio/audio_motion/1/2025-12-04/event_20251204_223555.flac",
      "confidence": 0.91
    }
  ]
}
```

### Health Message (`orpheus/system/event-correlator/health`)

```json
{
  "status": "online",
  "window_seconds": 3.0,
  "timestamp": "2025-12-04T22:30:00.000000+00:00"
}
```

On shutdown:

```json
{
  "status": "offline",
  "events_received": 1482,
  "entities_emitted": 347,
  "timestamp": "2025-12-04T23:59:59.000000+00:00"
}
```

## How Temporal Clustering Works

1. An incoming detection event is parsed and validated
2. Each species identified in the event becomes an `Observation`
3. The `ClusterManager` looks up the active `TemporalCluster` for that `species_code`
   - If no cluster exists, a new one is created and a countdown timer is started
   - If a cluster already exists, the observation is added and the timer is **reset**
4. When the timer expires (default: 3 seconds after the last observation), the cluster closes
5. The cluster builds an `EntityEvent` by aggregating all observations: max confidence, all evidence clips, averaged GPS coordinates from context
6. The EntityEvent is published to MQTT and persisted to DetectionDB

The timer reset behavior means that a continuously calling crow will be grouped into a single EntityEvent for as long as it keeps vocalizing, up to the window duration after the last call.

## Configuration

In `orpheus.yaml`:

```yaml
correlation:
  window_seconds: 3.0
  input_topics:
    - orpheus/detection/bird/events
    - orpheus/detection/crow/events
```

| Parameter | Default | Description |
| --- | --- | --- |
| `window_seconds` | `3.0` | Seconds after last observation before a cluster closes |
| `input_topics` | (required) | List of MQTT topics to subscribe to for detection events |

## Installation

```bash
make install           # Create venv, install dependencies

sudo make install-service  # Install as systemd service
sudo systemctl enable orpheus-agent-event-correlator
sudo systemctl start orpheus-agent-event-correlator
```

## Usage

```bash
# Run in foreground (development)
make run

# As a systemd service
sudo systemctl start orpheus-agent-event-correlator
sudo systemctl status orpheus-agent-event-correlator

# View logs
make service-logs
```

## Development

```bash
make test        # Run pytest
make coverage    # Check coverage (≥70% required)
make lint        # Ruff lint check
make format      # Ruff auto-format
```

## Storage

EntityEvents are persisted to DetectionDB at the path configured in `orpheus.yaml` (typically `/data/orpheus/detections.db`). The database is also written to by the inference agents; the event correlator adds entity-level records that represent the fused view across multiple raw detections.

## Position in the Architecture

The Event Correlator occupies **Layer 3** of the agent hierarchy:

```bash
Layer 1 (Sensors):    orpheus-agent-audio-motion, orpheus-agent-video-motion
Layer 2 (Inference):  orpheus-agent-bird-detection, orpheus-agent-crow-detection
Layer 3 (Fusion):     orpheus-agent-event-correlator  ← this agent
Act Stack:            orpheus-agent-audio-playback (awaiting interaction policy)
```

The EntityEvents published to `orpheus/entities/animal` are the primary input that the **Act stack interaction policy** (not yet built) should consume. If you are interested in building the Active Inference-based response logic, this is the upstream data stream you would subscribe to. See [GitHub Discussions](https://github.com/scottchronicity/orpheus/discussions) to get involved.
