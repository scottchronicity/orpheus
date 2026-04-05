# Orpheus Audio Motion Detector Agent

The audio motion detector agent monitors microphone arrays for motion-like acoustic signatures and publishes structured events through MQTT. The agent uses **stateful recording** to capture complete vocalizations, not just the loudest moments.

## Features

- **Stateful Recording**: Captures complete audio events with pre-buffer, holdoff, and duration constraints
- **Adaptive Thresholding**: Automatically adjusts to changing ambient noise levels
- **Multi-Channel Support**: Process up to 4 independent audio channels simultaneously (Orange, Yellow, Green, Blue cables)
- **Python 3.9.5 runtime** (Jetson compatible) with an isolated virtual environment
- **YAML-driven configuration** with environment overrides via [`orpheus_common.config.OrpheusConfig`](../../platform/orpheus-common/src/orpheus_common/config.py)
- **Structured logging** through [`orpheus_common.logging.setup_logging`](../../platform/orpheus-common/src/orpheus_common/logging.py)
- **MQTT event publication** using [`orpheus_common.mqtt.MQTTClient`](../../platform/orpheus-common/src/orpheus_common/mqtt.py)
- **Storage helpers** backed by `/data/orpheus` for persisting triggered clips
- **Systemd unit** and installer for deployment on edge devices

## Stateful Recording Behavior

Unlike simple threshold detectors that record whenever audio exceeds a level, this agent uses a **state machine** to capture complete vocalizations:

### States

1. **IDLE**: Monitoring audio, maintaining a pre-buffer
2. **TRIGGERED**: Audio exceeded threshold, transitioning to recording
3. **RECORDING**: Accumulating audio frames, watching for end conditions
4. **COMPLETE**: Recording finished, emitting detection event

### Recording Flow

```text
Audio > Trigger Threshold
  ↓
IDLE → TRIGGERED → RECORDING
                      ↓
          (silence holdoff OR max duration)
                      ↓
                   COMPLETE → Emit Event → IDLE
```

### Key Parameters

| Parameter | Purpose | Example |
| ----------- | --------- | --------- |
| `threshold_db` | Initial trigger level | `-30.0` dB |
| `margin_db` | Headroom above threshold | `10.0` dB |
| `release_threshold_db` | Level below which recording may end | `-35.0` dB |
| `holdoff_seconds` | Continue recording after quiet | `2.0` s |
| `min_duration_seconds` | Reject events shorter than this | `0.3` s |
| `max_duration_seconds` | Cap recordings at this length | `30.0` s |
| `prebuffer_seconds` | Include audio before trigger | `0.5` s |

### Example Scenario

A bird starts singing:

1. **Pre-buffer** continuously stores last 0.5s of audio
2. Song exceeds `-30 dB` → **TRIGGERED**
3. Agent transitions to **RECORDING**, including pre-buffer frames
4. Bird continues singing, audio stays above `-35 dB`
5. Bird pauses briefly, audio drops below `-35 dB`
6. Agent waits 2.0s (**holdoff**) in case bird resumes
7. After 2.0s of silence, recording **COMPLETES**
8. Event is saved (if duration ≥ 0.3s) and published to MQTT
9. Agent returns to **IDLE**

## Getting Started

```bash
cd agents/orpheus-agent-audio-motion
make install
make run
```

The agent uses the unified `orpheus.yaml` configuration from `orpheus-common`. The `make run` target accepts extra CLI arguments via `ARGS`, e.g. `make run ARGS="--log-level DEBUG"`.

## Development Workflow

```bash
make format        # ruff
make lint          # ruff
make test          # pytest
```

All commands operate within the agent-specific virtual environment under `venv/`.

## Deployment

```bash
make install-service
make service-start
make service-status
```

The installer script deploys the agent into `/opt/orpheus/agents/orpheus-agent-audio-motion`, creates a dedicated virtual environment, and installs the `orpheus-agent-audio-motion.service` systemd unit.

## Configuration

The agent uses the unified [`orpheus.yaml`](../../config/orpheus.example.yaml) configuration system. All settings can be overridden with environment variables prefixed with `ORPHEUS_`.

### Audio Channels

The Behringer UMC404HD interface has 4 input ports, each with a color-coded cable:

- **Port 1**: Orange Cable
- **Port 2**: Yellow Cable
- **Port 3**: Green Cable
- **Port 4**: Blue Cable

Each audio channel can have independent detection settings:

```yaml
audio:
  channels:
    - id: 1
      name: "Orange Cable (Port 1)"
      enabled: true
      device: "alsa://orpheus_umc?channel=1"
      detection:
        algorithm: "adaptive_threshold"
        threshold_db: -30.0
        margin_db: 10.0
        release_threshold_db: -35.0
        holdoff_seconds: 2.0
        min_duration_seconds: 0.3
        max_duration_seconds: 30.0
        prebuffer_seconds: 0.5
        window_seconds: 30.0
        update_interval_seconds: 5.0
```

### Detection Algorithms

#### Fixed Threshold

Uses a constant trigger level:

```yaml
detection:
  algorithm: "fixed_threshold"
  threshold_db: -30.0    # Trigger when audio > -30 dB
  margin_db: 10.0        # Additional headroom
```

#### Adaptive Threshold

Automatically adjusts to ambient noise:

```yaml
detection:
  algorithm: "adaptive_threshold"
  threshold_db: -30.0              # Initial threshold
  margin_db: 10.0                  # Trigger margin
  window_seconds: 30.0             # Rolling window for averaging
  update_interval_seconds: 5.0     # How often to recalculate
```

The threshold adapts by calculating the mean energy over the last `window_seconds`, updated every `update_interval_seconds`.

### Environment Overrides

Override any configuration value with environment variables:

```bash
# Override threshold for Orange Cable (channel 0 in array)
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__THRESHOLD_DB=-25.0

# Change holdoff duration
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__HOLDOFF_SECONDS=3.0

# Switch to fixed threshold
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__ALGORITHM=fixed_threshold
```

### Laptop Development

For laptop development, copy `config/.env.laptop.example` to `config/.env.laptop` and source it before running the agent. This configures a single microphone channel instead of the 4-channel Jetson setup.

```bash
source config/.env.laptop
make run
```

## Tuning Detection Parameters

### Too Many False Positives?

- **Increase** `threshold_db` (e.g., `-30.0` → `-25.0`)
- **Increase** `margin_db` (e.g., `10.0` → `15.0`)
- **Increase** `min_duration_seconds` (e.g., `0.3` → `0.5`)
- Consider switching to `adaptive_threshold` algorithm

### Missing Quiet Vocalizations?

- **Decrease** `threshold_db` (e.g., `-30.0` → `-35.0`)
- **Decrease** `margin_db` (e.g., `10.0` → `8.0`)
- **Increase** `window_seconds` for adaptive (e.g., `30.0` → `45.0`)

### Recordings Cut Off Too Early?

- **Increase** `holdoff_seconds` (e.g., `2.0` → `3.0`)
- **Decrease** `release_threshold_db` (e.g., `-35.0` → `-40.0`)

### Recordings Too Long?

- **Decrease** `max_duration_seconds` (e.g., `30.0` → `20.0`)
- **Decrease** `holdoff_seconds` (e.g., `2.0` → `1.5`)

### Missing Start of Vocalizations?

- **Increase** `prebuffer_seconds` (e.g., `0.5` → `1.0`)

## Persistent ALSA Device Alias Setup (Jetson)

**Why:** ALSA card names (e.g., `U192k`, `UMC404HD`) can change after reboots or hardware changes, breaking device strings in your config. To ensure reliable deployment, create a persistent ALSA alias and update your config to use it.

### Step-by-Step Guide

1. **Identify your audio interface's current ALSA card name:**

  ```bash
  aplay -l
  # Look for your device, e.g., "card 1: U192k [Behringer UMC404HD]"
  ```

1. **Create or edit `/etc/asound.conf` to define a persistent alias:**

  ```bash
  sudo nano /etc/asound.conf
  ```

  Add the following, replacing `U192k` with your current card name if different:

  ```conf
  pcm.orpheus_umc {
     type hw
     card U192k
  }
  ctl.orpheus_umc {
     type hw
     card U192k
  }
  ```

1. **Update your Orpheus config to use the alias:**
  In your `orpheus.yaml` (or via environment variable), set the device string to:

  ```yaml
  device: "alsa://orpheus_umc?channel=1"
  ```

  (Repeat for each channel as needed.)

1. **Restart the agent and verify:**

  ```bash
  sudo systemctl restart orpheus-agent-audio-motion
  # Or use your local run command
  ```

  Check logs for successful device access and detection events.

1. **If you see 'Device or resource busy' errors:**

- Ensure no other process (e.g., PulseAudio, another agent) is using the device:

    ```bash
    fuser -v /dev/snd/*
    ps aux | grep pulse
    sudo systemctl --user mask pulseaudio
    ```

- Stop or kill any conflicting processes before starting the agent.

**Tip:** This alias setup should be part of your deployment checklist for all Jetson devices to avoid future issues with device renaming.

## Troubleshooting

### No Detections Appearing

1. **Check audio input**:

   ```bash
   # List available audio devices
   python3 -m sounddevice
   ```

2. **Verify threshold settings**:

   ```bash
   # Run with debug logging
   make run ARGS="--log-level DEBUG"
   ```

   Look for energy level reports like: `Orange Cable (Port 1): energy=-42.3 dB, threshold=-30.0 dB`

3. **Test with lower threshold**:

   ```bash
   export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__THRESHOLD_DB=-50.0
   make run
   ```

### Too Many Short Events

Increase `min_duration_seconds`:

```bash
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__MIN_DURATION_SECONDS=0.5
```

### Recordings Missing Parts of Calls

Increase `holdoff_seconds` or decrease `release_threshold_db`:

```bash
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__HOLDOFF_SECONDS=3.0
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__RELEASE_THRESHOLD_DB=-40.0
```

### Adaptive Threshold Not Adapting

Check `window_seconds` and `update_interval_seconds`:

```bash
# Faster adaptation
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__WINDOW_SECONDS=15.0
export ORPHEUS_AUDIO__CHANNELS__0__DETECTION__UPDATE_INTERVAL_SECONDS=3.0
```

## MQTT Topics

This is a **Layer 1 agent** — it reads directly from hardware (ALSA audio devices) and has no MQTT input.

**Subscribes to:** Nothing. This agent is a pure source; it does not consume any MQTT events.

**Publishes to:**

| Topic | Description |
| --- | --- |
| `orpheus/audio/motion/events` | One event per completed recording |
| `orpheus/audio/motion/status` | Periodic agent health and per-channel statistics |

### Event Payload (`orpheus/audio/motion/events`)

```json
{
  "event_id": "audio_motion_20251204_223555_ch1",
  "timestamp": "2025-12-04T22:35:55.123456+00:00",
  "channel_id": "1",
  "audio_clip_path": "/data/orpheus/audio/motion/2025-12-04/channel_1/event_20251204_223555.flac",
  "duration_seconds": 3.2,
  "peak_db": -18.4,
  "detection_type": "audio.motion"
}
```

This event is the primary input consumed by the downstream inference agents (`orpheus-agent-bird-detection`, `orpheus-agent-crow-detection`).

### Status Payload (`orpheus/audio/motion/status`)

```json
{
  "status": "online",
  "timestamp": "2025-12-04T22:35:00.000000+00:00",
  "channels": [
    {
      "channel_id": "1",
      "name": "Orange Cable (Port 1)",
      "state": "IDLE",
      "current_db": -42.3,
      "threshold_db": -30.0,
      "events_today": 47
    }
  ]
}
```

## Storage

Audio clips are saved to:

```shell
/data/orpheus/audio/motion/{YYYY-MM-DD}/channel_{id}/event_{timestamp}.flac
```

Retention is controlled by `storage.retention.raw_audio_days` in `orpheus.yaml`.

## Next Steps

1. ✅ Multi-channel audio capture implemented ([`audio_source.py`](src/orpheus_agent_audio_motion/audio_source.py))
2. ✅ Stateful recording with pre-buffer and holdoff ([`detector_algorithm.py`](src/orpheus_agent_audio_motion/detector_algorithm.py))

See [GitHub Issues](https://github.com/scottchronicity/orpheus/issues) for planned improvements.

## License

See the main Orpheus project LICENSE file.

## Contributing

Contributions welcome! This agent is production-ready but can be extended with:

- Additional detection algorithms (e.g., frequency-based)
- Machine learning classification integration
- Real-time audio visualization
- Advanced noise filtering

## Related Documentation

- [Orpheus Common Library](../../platform/orpheus-common/README.md)
- [Multi-Channel Audio Implementation](MULTI_CHANNEL_AUDIO.md)
- [MQTT Broker Setup](../../services/orpheus-mqtt/README.md)
