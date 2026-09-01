# Orpheus Standard Data Models

This page is the wire contract: the JSON payloads agents publish to each other, and
what every field means. Read it if you are writing an agent, integrating against the
bus, or working out what a stored detection actually contains.

---

## Overview

Agents never call each other directly. They exchange JSON payloads over the messaging
backplane — NATS with JetStream by default, with mosquitto as the one-line MQTT
fallback. The `orpheus/...` topic names below are the contract on either backend:
NATS mirrors them as subjects, mosquitto uses them as literal topics.

---

## Detection Events

### Bird Detection Event

**Topic:** `orpheus/detection/bird/events`  
**Producer:** orpheus-agent-bird-detection  
**Consumers:** orpheus-agent-crow-detection, orpheus_ui

```python
@dataclass
class BirdDetectionEvent:
    event_id: str                    # "bird_det_YYYYMMDD_HHMMSS_chN_XXXX"
    timestamp: str                   # ISO 8601 UTC
    channel_id: str                  # "1", "2", "3", "4"
    detections: List[SpeciesDetection]
    audio_clip_path: str             # Absolute path on ORPHEUS_DATA_ROOT
    
@dataclass
class SpeciesDetection:
    species_code: str                # eBird code: "amecro", "comrav", etc.
    species_common: str              # "American Crow"
    confidence: float                # 0.0 - 1.0
    start_time: float                # Seconds from clip start
    end_time: float                  # Seconds from clip start
```

**JSON Example:**

```json
{
  "event_id": "bird_det_20251205_143022_ch1_a1b2c3",
  "timestamp": "2025-12-05T14:30:22.123456+00:00",
  "channel_id": "1",
  "detections": [
    {
      "species_code": "amecro",
      "species_common": "American Crow",
      "confidence": 0.87,
      "start_time": 0.5,
      "end_time": 3.2
    }
  ],
  "audio_clip_path": "/data/orpheus/audio/audio_motion/1/20251205T143022.flac"
}
```

---

### Audio Motion Detection Event

**Topic:** `orpheus/audio/motion/events`  
**Producer:** orpheus-agent-audio-motion  
**Consumers:** orpheus-agent-bird-detection, orpheus-agent-audio-events, orpheus_ui

The audio motion agent publishes detection events using `Detection.model_dump(mode="json")`, which produces a **nested** payload structure. The UI backend (`diagnostics.py`) flattens several fields from `metadata` to the top level before serving them to the frontend.

#### Nested payload (as published on the bus)

```json
{
  "event_id": "audio_det_20251205_143022_ch1_a1b2",
  "event_timestamp": "2025-12-05T14:30:22.000000+00:00",
  "timestamp": "2025-12-05T14:30:22.000000+00:00",
  "detection_type": "audio.motion",
  "channel": 1,
  "audio_clip_path": "/data/orpheus/audio/audio_motion/1/20251205T143022.flac",
  "context": {
    "lat": 47.606,
    "lon": -122.332,
    "sensor_id": "mic-1"
  },
  "metadata": {
    "channel_id": "1",
    "duration_seconds": 30.17,
    "peak_energy_db": -35.23,
    "average_energy_db": -48.09,
    "frame_count": 143
  }
}
```

#### Flattened payload (as served by the UI backend)

The `on_audio_detection_message` handler in the UI backend promotes the following
fields from `metadata` to the top level before caching:

| Field | Source | Fallback |
| ----- | ------ | -------- |
| `channel_id` | `metadata.channel_id` | `str(channel)`, then `"unknown"` |
| `duration_seconds` | `metadata.duration_seconds` | _(not set)_ |
| `peak_energy_db` | `metadata.peak_energy_db` | _(not set)_ |

The original `metadata` dict is preserved alongside the promoted fields.

> **Note for contributors:** If you add new fields to the `Detection.metadata`
> dict in the audio motion agent, you must also update the flattening logic in
> `services/orpheus_ui/backend/src/orpheus_ui/api/diagnostics.py` if the
> frontend needs those fields at the top level.

---

### Crow Analysis Event

**Topic:** `orpheus/detection/crow/events`  
**Producer:** orpheus-agent-crow-detection  
**Consumers:** orpheus_ui, future interaction agents

```python
@dataclass
class CrowAnalysisEvent:
    event_id: str                    # "crow_det_YYYYMMDD_HHMMSS_chN_XXXX"
    source_event_id: str             # Links to triggering bird detection
    timestamp: str                   # ISO 8601 UTC
    channel_id: str
    species_code: str                # "amecro", "comrav", "fisccr"
    species_common: str
    birdnet_confidence: float        # Original BirdNET confidence
    crow_analysis: CrowAnalysis      # Detailed analysis
    audio_clip_path: str
    model_version: str               # "crow-tools-v1"

@dataclass 
class CrowAnalysis:
    crow_count: int                  # 1=single, 2=pair, 3+=group
    crow_age: str                    # "adult" or "juvenile"
    behaviors: CrowBehaviors
    quality: int                     # 1=poor, 2=good
    num_seconds_analyzed: int

@dataclass
class CrowBehaviors:
    alert: bool                      # Warning/contact calls
    begging: bool                    # Juvenile food requests  
    soft_song: bool                  # Quiet social vocalizations (subsong)
    rattle: bool                     # Aggressive rattling display
    mob: bool                        # Mobbing behavior
```

**JSON Example:**

```json
{
  "event_id": "crow_det_20251205_143023_ch1_d4e5f6",
  "source_event_id": "bird_det_20251205_143022_ch1_a1b2c3",
  "timestamp": "2025-12-05T14:30:23.456789+00:00",
  "channel_id": "1",
  "species_code": "amecro",
  "species_common": "American Crow",
  "birdnet_confidence": 0.87,
  "crow_analysis": {
    "crow_count": 1,
    "crow_age": "adult",
    "behaviors": {
      "alert": true,
      "begging": false,
      "soft_song": false,
      "rattle": false,
      "mob": false
    },
    "quality": 2,
    "num_seconds_analyzed": 3
  },
  "audio_clip_path": "/data/orpheus/audio/audio_motion/1/20251205T143022.flac",
  "model_version": "crow-tools-v1"
}
```

---

## Audio Playback

### Playback Request

**Topic:** `orpheus/audio/playback/request`  
**Producers:** Any agent needing to play audio  
**Consumer:** orpheus-agent-audio-playback

```python
@dataclass
class PlaybackRequest:
    request_id: str                  # Unique request identifier
    timestamp: str                   # ISO 8601 UTC
    source_agent: str                # Requesting agent name
    audio_source: AudioSource        # Where to get audio
    playback_options: PlaybackOptions

@dataclass
class AudioSource:
    # One of these must be provided:
    path: Optional[str]              # Absolute path or relative to ORPHEUS_DATA_ROOT
    detection_id: Optional[str]      # Look up path from DetectionDB
    url: Optional[str]               # Future: remote audio source
    
    # Optional segment extraction:
    start_time: Optional[float]      # Seconds (None = start of file)
    end_time: Optional[float]        # Seconds (None = end of file)

@dataclass
class PlaybackOptions:
    volume: float = 1.0              # 0.0 - 1.0
    channel: Optional[int] = None    # Specific output channel (None = all)
    repeat: int = 1                  # Number of times to play
    delay_between: float = 0.0       # Seconds between repeats
```

**JSON Example - Play by Path:**

```json
{
  "request_id": "play_20251205_143100_abc123",
  "timestamp": "2025-12-05T14:31:00.000000+00:00",
  "source_agent": "orpheus-agent-crow-interaction",
  "audio_source": {
    "path": "/data/orpheus/audio/audio_motion/1/20251205T143022.flac",
    "start_time": 0.5,
    "end_time": 2.0
  },
  "playback_options": {
    "volume": 0.8,
    "repeat": 1
  }
}
```

**JSON Example - Play by Detection ID:**

```json
{
  "request_id": "play_20251205_143200_def456",
  "timestamp": "2025-12-05T14:32:00.000000+00:00",
  "source_agent": "orpheus_ui",
  "audio_source": {
    "detection_id": "crow_det_20251205_143023_ch1_d4e5f6"
  },
  "playback_options": {
    "volume": 1.0
  }
}
```

### Playback Response

**Topic:** `orpheus/audio/playback/response`  
**Producer:** orpheus-agent-audio-playback  
**Consumers:** Requesting agents, dashboard

The response is a flat envelope, published once per request. It echoes back whichever
identifier the request used, so a caller can match it up; there is no `request_id` and
no progress reporting — the agent answers when playback has been *started*, not when
it finishes.

```python
@dataclass
class PlaybackResponse:
    status: str                      # "success" or "error"
    message: Optional[str]           # Human-readable status, on success
    error: Optional[str]             # Error description, when status="error"
    sound_name: Optional[str]        # Echoed back, when the request named a sound
    file_path: Optional[str]         # Echoed back, when the request gave a path
    detection_id: Optional[str]      # Echoed back, when the request gave a detection
```

**JSON Example - Success:**

```json
{
  "status": "success",
  "message": "Playback started",
  "detection_id": "crow_det_20251205_143023_ch1_d4e5f6"
}
```

**JSON Example - Error:**

```json
{
  "status": "error",
  "error": "Sound not found: alarm_caw",
  "sound_name": "alarm_caw"
}
```

---

## Health Status

### Agent Health

**Topic:** `orpheus/system/{agent-name}/health`  
**Producer:** Each agent  
**Consumer:** orpheus_ui

```python
@dataclass
class AgentHealth:
    status: str                      # "online", "offline", "degraded"
    timestamp: str
    version: Optional[str]           # Agent/model version
    details: Optional[dict]          # Agent-specific details
```

There is no `AgentHealth` class in the tree, and nothing publishes `version` or
`details`. Each agent builds its own health dict in `health_payload()`: the
default in `orpheus_common.actor.base` is `status` plus the `ActorStats` counters
(`events_processed`, `errors_count`, `last_error`), and every agent overrides it —
bird-detection adds `model_loaded`, `timestamp` and `detections_found`; the
correlator adds its window and feature flags. Read `health_payload()` in the agent
you care about before consuming this topic.

---

## Database Schema Reference

### detections table

| Column | Type | Description |
| -------- | ------ | ------------- |
| `event_id` | TEXT | Primary identifier |
| `timestamp` | DATETIME | UTC timestamp |
| `detection_type` | TEXT | `audio.motion`, `species.detected`, `crow.analyzed`, `audio.classified` |
| `channel` | INTEGER | Audio channel 1-4 |
| `species_code` | TEXT | eBird species code |
| `species_common` | TEXT | Common name |
| `confidence` | REAL | Detection confidence |
| `audio_clip_path` | TEXT | Path to audio file |
| `metadata` | TEXT | JSON with additional data |
| `source_event_id` | TEXT | Parent event link |
| `id` | INTEGER | Primary key, autoincrement |
| `root_event_id` | TEXT | Root of the lineage chain (ADR 0012) |
| `created_at` | TEXT | Row insertion time |
| `event_metadata` | TEXT | The JSON sidecar (ADR 0005) |
| `intervals_json` | TEXT | Intra-clip localisation (ADR 0011) |
| `taxonomy_namespace` | TEXT | Label authority (ADR 0011) |
| `taxonomy_id` | TEXT | Identifier within that authority (ADR 0011) |

`ensure_schema_updates()` adds the last four to a legacy database on startup, so
an older DB gains them without a migration step.

### metadata JSON for crow.analyzed

```json
{
  "crow_analysis": {
    "crow_count": 1,
    "crow_age": "adult",
    "behaviors": {
      "alert": true,
      "begging": false,
      "soft_song": false,
      "rattle": false,
      "mob": false
    },
    "quality": 2,
    "num_seconds_analyzed": 3
  },
  "source_event_id": "bird_det_...",
  "model_version": "crow-tools-v1"
}
```

---

## Species Codes Reference

### Corvids (Crow Detection Targets)

| Code | Common Name | Scientific Name |
| ------ | ------------- | ----------------- |
| `amecro` | American Crow | Corvus brachyrhynchos |
| `comrav` | Common Raven | Corvus corax |
| `fisccr` | Fish Crow | Corvus ossifragus |

### Crow Behaviors

| Behavior | Description | Audio Characteristics |
| ---------- | ------------- | ---------------------- |
| `alert` | Warning/contact calls | Standard "caw" vocalizations |
| `begging` | Juvenile food requests | Whiny, pleading tones |
| `soft_song` | Quiet social vocalizations | Low clicking, warbling (subsong) |
| `rattle` | Aggressive display | Rapid rattling sounds |
| `mob` | Mobbing behavior | Rapid repeated alarm calls |

---

## Entity Events

`orpheus/entities/animal` — produced by `orpheus-agent-event-correlator`,
consumed by the dashboard. One message per real animal, carrying every
classifier's evidence.

`EntityEvent` (`orpheus_common.events`) is a standalone model, deliberately not
an `OrpheusBaseEvent` subclass — see [ADR 0016](adr/0016-entity-type-taxonomy.md).
Its fields: `entity_id`, `species_code`, `common_name`, `confidence`,
`entity_type`, `context`, `evidence` (a `list[EntityEvidence]`), `also_detected`,
`event_signature`, `is_self_generated`.

Late-arriving evidence is published separately on
`orpheus/entity-updates/animal`, a sibling root rather than a child, so a
wildcard subscription to entity creation cannot pick it up by accident. With
`publish_entity_type_topics` enabled, entities also route by type —
`orpheus/entities/animal/bird/crow`.

See [ADR 0013](adr/0013-source-identity-entities.md) for what merge keys on.

## Where these live

The one shipped model is `Detection` in `orpheus_common.detection.models`, and
every agent publishes `Detection.model_dump(mode="json")` (ADR 0006 §3). Entities
are `Entity` in the same module and `EntityEvent` in `orpheus_common.events`.

There is no `orpheus_common.models` package. The shapes above describe what lands
*inside* the `Detection` envelope's fields — its `metadata` in particular — not
separate Python classes to import.

