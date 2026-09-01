# Orpheus Audio Playback Agent

Agent that listens to MQTT messages and plays audio files through connected speakers.

## Overview

The Audio Playback Agent subscribes to MQTT playback request messages and uses the Orpheus audio playback system to play sounds through configured audio output devices (e.g., Pyle speakers connected via Bluetooth).

## Features

- MQTT-based playback control
- **Support for multiple audio sources:**
  - Named sounds from registry (legacy)
  - Direct file paths (absolute or relative to data root)
  - Detection IDs (lookup from DetectionDB)
- **Advanced playback controls:**
  - Segment extraction (start_time, duration)
  - Volume control (0-100)
  - Repeat playback with pauses
- Multiple audio format support (WAV, MP3, FLAC, OGG, M4A, AIFF)
- Sound name registry for human-readable identifiers
- Graceful error handling
- Health status reporting
- Backward compatible with existing requests

## Dependencies

- `orpheus-common`: Core platform library
- `paho-mqtt`: MQTT client
- Audio playback backend (ffplay, aplay, paplay, or afplay)

## Configuration

The agent uses the unified `orpheus.yaml` configuration file through `OrpheusConfig`.

### MQTT Configuration

```yaml
mqtt:
  broker_host: "localhost"
  broker_port: 1883
  keepalive: 60
```

### Sound Configuration

```yaml
audio:
  sounds:
    sounds_dir: "platform/orpheus-common/sounds"
    auto_discover: false
    sounds:
      test_tone_1: "test_tone_1.wav"
      test_beep: "test_beep.wav"
      test_silence: "test_silence.wav"
```

## MQTT API

### Playback Request

**Topic:** `orpheus/audio/playback/request`

The agent supports two request formats for backward compatibility:

#### Legacy Format (Sound Name)

**Payload:**

```json
{
  "sound_name": "test_tone_1",
  "repeat_count": 3,
  "pause_between": 1.0
}
```

**Fields:**

- `sound_name` (required): Registered sound identifier
- `repeat_count` (optional): Number of times to play (default: 1)
- `pause_between` (optional): Seconds to pause between repeats (default: 0.0)

#### New Format (File Path or Detection ID)

**Play by File Path (absolute):**

```json
{
  "file_path": "/data/orpheus/audio/recording_123.wav",
  "repeat_count": 1,
  "start_time": 5.0,
  "duration": 10.0,
  "volume": 75
}
```

**Play by File Path (relative to data root):**

```json
{
  "file_path": "audio/recording_123.wav",
  "repeat_count": 2,
  "pause_between": 1.0,
  "volume": 50
}
```

**Play by Detection ID:**

```json
{
  "detection_id": "evt-audio-motion-20241205-123456",
  "repeat_count": 1,
  "start_time": 2.5,
  "duration": 5.0,
  "volume": 80
}
```

**Fields:**

- `file_path` (required if no detection_id): Path to audio file (absolute or relative)
- `detection_id` (required if no file_path): Detection event ID to lookup audio clip
- `repeat_count` (optional): Number of times to play (default: 1)
- `pause_between` (optional): Seconds to pause between repeats (default: 0.0)
- `start_time` (optional): Start playback at this time in seconds (default: beginning)
- `duration` (optional): Play only this many seconds (default: full file)
- `volume` (optional): Volume level 0-100 (default: system default, requires ffplay)

**Notes:**

- Segment extraction (`start_time`, `duration`) and `volume` control require ffplay
- If using relative `file_path`, it's resolved against the data root (`/data/orpheus/`)
- Detection ID lookup uses DetectionDB to find the associated audio clip path

### Playback Response

**Topic:** `orpheus/audio/playback/response`

**Success Payload (Legacy):**

```json
{
  "status": "success",
  "sound_name": "test_tone_1",
  "message": "Playback started"
}
```

**Success Payload (File Path):**

```json
{
  "status": "success",
  "file_path": "/data/orpheus/audio/test.wav",
  "message": "Playback started"
}
```

**Success Payload (Detection ID):**

```json
{
  "status": "success",
  "detection_id": "evt-audio-motion-20241205-123456",
  "message": "Playback started"
}
```

**Error Payload:**

```json
{
  "status": "error",
  "error": "Audio file not found: /path/to/file.wav"
}
```

### Health Status

**Topic:** `orpheus/audio/playback/health`

**Payload:**

```json
{
  "status": "healthy",
  "is_playing": false,
  "available_sounds": ["test_tone_1", "test_beep", "test_silence"],
  "timestamp": "2024-12-04T12:34:56Z"
}
```

## Installation

```bash
cd agents/orpheus-agent-audio-playback
make install
```

## Running Locally

```bash
make run
```

With custom log level:

```bash
make run ARGS="--log-level DEBUG"
```

## Testing

Run all tests:

```bash
make test
```

Run with coverage:

```bash
make coverage
```

## Systemd Service

Install as systemd service:

```bash
make install-service
```

Start the service:

```bash
sudo systemctl start orpheus-agent-audio-playback
```

Check status:

```bash
sudo systemctl status orpheus-agent-audio-playback
```

View logs:

```bash
sudo journalctl -u orpheus-agent-audio-playback -f
```

## Example Usage

### Using the nats CLI

```bash
# Legacy: Play a named sound once
nats pub 'orpheus.audio.playback.request' '{"sound_name": "test_tone_1"}'

# Legacy: Play with repeats
nats pub 'orpheus.audio.playback.request' '{"sound_name": "test_beep", "repeat_count": 3, "pause_between": 1.0}'

# New: Play by file path with segment extraction
nats pub 'orpheus.audio.playback.request' '{"file_path": "/data/orpheus/audio/recording.wav", "start_time": 5.0, "duration": 10.0, "volume": 75}'

# New: Play by detection ID
nats pub 'orpheus.audio.playback.request' '{"detection_id": "evt-audio-motion-20241205-123456", "volume": 50}'

# New: Play relative path with volume control
nats pub 'orpheus.audio.playback.request' '{"file_path": "audio/alerts/crow_detected.wav", "repeat_count": 2, "volume": 80}'
```

### Using Python MQTT client

```python
from orpheus_common.mqtt import MQTTClient

client = MQTTClient(broker_host="localhost")
client.connect()

# Legacy: Simple playback
client.publish("orpheus/audio/playback/request", {
    "sound_name": "test_tone_1"
})

# Legacy: With repeats
client.publish("orpheus/audio/playback/request", {
    "sound_name": "test_beep",
    "repeat_count": 5,
    "pause_between": 2.0
})

# New: Play by file path with segment
client.publish("orpheus/audio/playback/request", {
    "file_path": "/data/orpheus/audio/recording.wav",
    "start_time": 10.0,
    "duration": 30.0,
    "volume": 60
})

# New: Play by detection ID
client.publish("orpheus/audio/playback/request", {
    "detection_id": "evt-species-crow-20241205-143022",
    "volume": 75
})
```

## Common Use Cases

### 1. Review Detected Audio Events

When a species is detected, play the audio clip for review:

```python
# Assuming detection event received
detection_id = detection_event["event_id"]

# Play the audio clip
client.publish("orpheus/audio/playback/request", {
    "detection_id": detection_id,
    "volume": 70
})
```

### 2. Play Segment of Long Recording

Extract and play a specific segment from a long recording:

```python
# Play 30 seconds starting at 2 minutes into the file
client.publish("orpheus/audio/playback/request", {
    "file_path": "/data/orpheus/audio/hourly/2024-12-05-14.wav",
    "start_time": 120.0,  # 2 minutes
    "duration": 30.0,      # 30 seconds
    "volume": 60
})
```

### 3. Alert Sound for Species Detection

Play an alert sound when a specific species is detected:

```python
# Play alert sound at high volume
client.publish("orpheus/audio/playback/request", {
    "sound_name": "crow_alert",
    "repeat_count": 3,
    "pause_between": 0.5,
    "volume": 90
})
```

### 4. Playback Audio Motion Clip

Play the audio clip that triggered motion detection:

```python
# From audio motion event
audio_clip_path = motion_event["audio_clip_path"]

client.publish("orpheus/audio/playback/request", {
    "file_path": audio_clip_path,
    "volume": 70
})
```

### 5. Compare Multiple Detections

Play segments from multiple detections for comparison:

```python
import time

detection_ids = ["evt-1", "evt-2", "evt-3"]

for detection_id in detection_ids:
    # Play each detection with a pause between
    client.publish("orpheus/audio/playback/request", {
        "detection_id": detection_id,
        "volume": 65
    })
    time.sleep(5)  # Wait 5 seconds between clips
```

### Using CLI tool

```bash
# Legacy: Play once
orpheus_play_sound test_tone_1

# Legacy: Play with repeats
orpheus_play_sound test_beep --repeat 3 --pause 1.0

# New: Play file with segment extraction (requires updated CLI tool)
orpheus_play_audio --file /data/orpheus/audio/recording.wav --start 5.0 --duration 10.0 --volume 75

# New: Play by detection ID (requires updated CLI tool)
orpheus_play_audio --detection-id evt-audio-motion-20241205-123456 --volume 50
```

## Architecture

```bash
┌─────────────────────────────────────────┐
│  Event bus (orpheus-backplane: NATS)    │
└─────────────┬───────────────────────────┘
              │
              │ orpheus/audio/playback/request
              ↓
┌─────────────────────────────────────────┐
│  Audio Playback Agent                   │
│                                         │
│  ┌─────────────────────────────────┐   │
│  │  MQTT Message Handler            │   │
│  └──────────┬──────────────────────┘   │
│             ↓                           │
│  ┌─────────────────────────────────┐   │
│  │  Request Router                  │   │
│  │  (Legacy vs New Format)          │   │
│  └────┬──────────────────┬─────────┘   │
│       │                  │              │
│       ↓                  ↓              │
│  ┌─────────┐    ┌──────────────────┐   │
│  │ Sound   │    │ Audio Source     │   │
│  │ Registry│    │ Resolver         │   │
│  └─────────┘    │ - File Path      │   │
│                 │ - Detection DB   │   │
│                 └────────┬─────────┘   │
│                          ↓              │
│  ┌─────────────────────────────────┐   │
│  │  Audio Player                    │   │
│  │  (SubprocessAudioPlayer)         │   │
│  │  - Segment extraction            │   │
│  │  - Volume control                │   │
│  └──────────┬──────────────────────┘   │
│             ↓                           │
└─────────────┼───────────────────────────┘
              ↓
     ┌────────────────────┐
     │  Audio Output       │
     │  (Pyle Speakers)    │
     └────────────────────┘
```

### Data Flow

1. **MQTT Request**: Message arrives on `orpheus/audio/playback/request`
2. **Format Detection**: Agent determines if request is legacy (sound_name) or new format (file_path/detection_id)
3. **Audio Source Resolution**:
   - Legacy: Lookup sound name in registry
   - File path: Resolve absolute or relative path
   - Detection ID: Query DetectionDB for audio clip path
4. **Playback**: Audio player processes file with optional segment extraction and volume control
5. **Response**: Success or error published to `orpheus/audio/playback/response`

## Troubleshooting

### No audio output

1. Check audio device configuration:

   ```bash
   aplay -l  # List audio devices
   ```

2. Check Bluetooth connection (for Pyle speakers):

   ```bash
   bluetoothctl devices
   bluetoothctl info <device-address>
   ```

3. Test audio manually:

   ```bash
   ffplay platform/orpheus-common/sounds/test_tone_1.wav
   ```

### Sound not found errors

1. List available sounds:

   ```bash
   # Start Python REPL
   python3
   >>> from orpheus_common.audio import get_sound_registry
   >>> registry = get_sound_registry()
   >>> print(registry.list_sounds())
   ```

2. Check sound registry configuration in `config/orpheus.yaml`

3. Verify sound files exist in configured directory

### Agent not receiving playback requests

1. Check the backplane broker is running:

   ```bash
   systemctl status orpheus-backplane
   ```

2. Watch the request subject:

   ```bash
   nats sub 'orpheus.audio.playback.>'
   ```

3. Check agent logs:

   ```bash
   journalctl -u orpheus-agent-audio-playback -f
   ```

## Development

### Code Style

- Python 3.9+ compatible
- Use `ruff` for formatting and linting
- Follow existing orpheus-common patterns
- Type hints required for public APIs

### Adding New Sounds

1. Add sound file to `platform/orpheus-common/sounds/`
2. Update `config/orpheus.yaml`:

   ```yaml
   audio:
     sounds:
       sounds:
         my_new_sound: "my_sound.wav"
   ```

3. Reload sound registry or restart agent

### Testing (coverage)

All new functionality must include tests with ≥70% coverage.

Run tests during development:

```bash
make test
```

Check coverage:

```bash
make coverage
```

## License

MIT License - See LICENSE file for details
