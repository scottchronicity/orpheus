# Orpheus Video Motion Detection Agent

Motion detection service for Amcrest IP cameras in the Orpheus wildlife monitoring platform.

## Features

- **Multi-Camera Support**: Monitor up to 4 Amcrest IP5M-B1186EW-AI-V3 cameras simultaneously
- **Background Subtraction**: OpenCV-based motion detection using MOG2 algorithm
- **Stateful Recording**: Pre-buffer, trigger, and post-motion holdoff for complete event capture
- **MQTT Integration**: Publish detection events to message broker
- **Video Clip Storage**: Save motion events as MP4/AVI files with automatic cleanup
- **Systemd Integration**: Run as background service on Jetson Orin NX

## Architecture

Mirrors the `orpheus-agent-audio-motion` service architecture:

```bash
orpheus-agent-video-motion/
├── src/orpheus_agent_video_motion/
│   ├── main.py              # Entrypoint and coordinator
│   ├── config.py            # Configuration loader
│   ├── video_source.py      # RTSP video capture
│   ├── detector_algorithm.py # Motion detection algorithms
│   ├── camera_processor.py  # Per-camera processing pipeline
│   └── clip_saver.py        # Video clip persistence
├── tests/                   # Unit and integration tests
├── systemd/                 # System service files
└── Makefile                 # Build and deployment
```

## Quick Start

### Installation

```bash
make install
```

### Running Locally

```bash
make run
```

### Running Tests

```bash
make test
make coverage  # With 70% minimum coverage
```

### Production Deployment

```bash
make install-service
make service-start
```

## Configuration

The agent uses the unified `orpheus.yaml` configuration from `orpheus-common`. Camera settings are automatically loaded from the camera registry.

### Default Motion Detection Settings

- **Motion Threshold**: 25% of frame with detected motion
- **Release Threshold**: 12.5% (motion end detection)
- **Holdoff**: 2 seconds after motion stops
- **Min Duration**: 0.5 seconds
- **Max Duration**: 30 seconds
- **Prebuffer**: 1 second before motion trigger

### Video Settings

- **Resolution**: 640x480 (substream)
- **FPS**: 10 frames per second
- **Format**: MP4 (H.264 compression)

## MQTT Topics

This is a **Layer 1 agent** — it reads directly from camera hardware (RTSP streams) and has no MQTT input.

**Subscribes to:** Nothing. This agent reads RTSP streams directly from IP cameras; it does not consume any MQTT events.

**Publishes to:**

| Topic | Description |
| --- | --- |
| `orpheus/video/motion/events` | One event per completed motion clip |
| `orpheus/video/motion/status` | Per-camera health and connection status |

### Event Payload (`orpheus/video/motion/events`)

```json
{
  "event_id": "video_motion_20251204_223555_cam_front_yard",
  "timestamp": "2025-12-04T22:35:55.123456+00:00",
  "camera_id": "front-yard",
  "video_clip_path": "/mnt/data/video/motion/front-yard/20251204_223555.mp4",
  "duration_seconds": 4.8,
  "detection_type": "video.motion"
}
```

### Status Payload (`orpheus/video/motion/status`)

```json
{
  "status": "online",
  "timestamp": "2025-12-04T22:35:00.000000+00:00",
  "cameras": [
    {
      "camera_id": "front-yard",
      "state": "IDLE",
      "connected": true,
      "events_today": 12
    }
  ]
}
```

## Storage

Video clips are stored in `/mnt/data/video/motion/{camera_id}/` with automatic cleanup based on retention policy:

- **Retention**: 30 days (default)
- **Format**: MP4 with H.264 codec
- **Cleanup**: Triggered at 90% capacity, removes 25% oldest files

## Development

### Linting

```bash
make lint
```

### Formatting

```bash
make format
```

### Clean Build

```bash
make clean
make reinstall
```

## Dependencies

- Python 3.9+
- OpenCV (opencv-python)
- NumPy
- MQTT client (paho-mqtt)
- orpheus-common platform library

## System Requirements

- NVIDIA Jetson Orin NX (or compatible ARM64/x86_64 system)
- Network access to Amcrest IP cameras
- MQTT broker (orpheus-mqtt service)
- Storage for video clips

## See Also

- [orpheus-agent-audio-motion](../orpheus-agent-audio-motion/) - Audio motion detection service (reference implementation)
- [orpheus-common](../../platform/orpheus-common/) - Shared platform library
- [orpheus-dashboard](../../services/orpheus-dashboard/) - Web-based diagnostic interface
