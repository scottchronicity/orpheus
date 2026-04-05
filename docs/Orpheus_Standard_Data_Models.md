# Orpheus Standard Data Models

**Document Date:** December 5, 2025  
**Purpose:** Define canonical data structures for inter-agent communication

---

## Overview

All Orpheus agents communicate via MQTT with JSON payloads. This document defines the **canonical data models** that agents MUST use for interoperability.

---

## Detection Events

### Bird Detection Event

**Topic:** `orpheus/detection/bird/events`  
**Producer:** orpheus-agent-bird-detection  
**Consumers:** orpheus-agent-crow-detection, orpheus-dashboard

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
**Consumers:** orpheus-agent-bird-detection, orpheus-dashboard

The audio motion agent publishes detection events using `Detection.model_dump(mode="json")`, which produces a **nested** payload structure. The UI backend (`diagnostics.py`) flattens several fields from `metadata` to the top level before serving them to the frontend.

#### Nested payload (as published on MQTT)

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
**Consumers:** orpheus-dashboard, future interaction agents

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
  "source_agent": "orpheus-dashboard",
  "audio_source": {
    "detection_id": "crow_det_20251205_143023_ch1_d4e5f6"
  },
  "playback_options": {
    "volume": 1.0
  }
}
```

### Playback Status

**Topic:** `orpheus/audio/playback/status`  
**Producer:** orpheus-agent-audio-playback  
**Consumers:** Requesting agents, dashboard

```python
@dataclass
class PlaybackStatus:
    request_id: str                  # Matches request
    status: str                      # "queued", "playing", "completed", "error"
    timestamp: str
    message: Optional[str]           # Human-readable status
    error: Optional[str]             # Error details if status="error"
    duration_played: Optional[float] # Seconds played so far
```

**JSON Example:**

```json
{
  "request_id": "play_20251205_143100_abc123",
  "status": "completed",
  "timestamp": "2025-12-05T14:31:02.500000+00:00",
  "message": "Playback completed successfully",
  "duration_played": 1.5
}
```

---

## Health Status

### Agent Health

**Topic:** `orpheus/system/{agent-name}/health`  
**Producer:** Each agent  
**Consumer:** orpheus-dashboard

```python
@dataclass
class AgentHealth:
    status: str                      # "online", "offline", "degraded"
    timestamp: str
    version: Optional[str]           # Agent/model version
    details: Optional[dict]          # Agent-specific details
```

---

## Database Schema Reference

### detections table

| Column | Type | Description |
| -------- | ------ | ------------- |
| `event_id` | TEXT | Primary identifier |
| `timestamp` | DATETIME | UTC timestamp |
| `detection_type` | TEXT | `audio.motion`, `bird.detected`, `crow.analyzed` |
| `channel` | INTEGER | Audio channel 1-4 |
| `species_code` | TEXT | eBird species code |
| `species_common` | TEXT | Common name |
| `confidence` | REAL | Detection confidence |
| `audio_clip_path` | TEXT | Path to audio file |
| `metadata` | TEXT | JSON with additional data |
| `source_event_id` | TEXT | Parent event link |

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

## Implementation in orpheus-common

These models should be implemented in `orpheus_common.models`:

```python
# platform/orpheus-common/src/orpheus_common/models/__init__.py

from .bird_detection import BirdDetectionEvent, SpeciesDetection
from .crow_analysis import CrowAnalysisEvent, CrowAnalysis, CrowBehaviors
from .playback import PlaybackRequest, PlaybackStatus, AudioSource, PlaybackOptions
from .health import AgentHealth

__all__ = [
    "BirdDetectionEvent",
    "SpeciesDetection", 
    "CrowAnalysisEvent",
    "CrowAnalysis",
    "CrowBehaviors",
    "PlaybackRequest",
    "PlaybackStatus",
    "AudioSource",
    "PlaybackOptions",
    "AgentHealth",
]
```

All models should:

- Use `@dataclass` or Pydantic `BaseModel`
- Include `to_dict()` and `from_dict()` methods
- Validate required fields
- Handle optional fields gracefully
