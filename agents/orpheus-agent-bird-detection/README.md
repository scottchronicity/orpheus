# Orpheus Bird Detection Agent

Bird species detection agent using BirdNET ONNX model for real-time audio analysis.

## Overview

Subscribes to audio motion events from `orpheus-agent-audio-motion` and performs species identification using BirdNET deep learning model. Publishes detection events to MQTT and stores results in DetectionDB.

## Features

- **BirdNET Integration**: Uses ONNX-optimized BirdNET model for fast inference
- **3-second windowed analysis**: Analyzes audio in overlapping windows for better detection
- **DetectionDB Storage**: Persists all detections to SQLite database
- **MQTT-based**: Publishes detection events for downstream consumers
- **Configurable confidence threshold**: Filter low-confidence detections

## Installation

```bash
# Install dependencies
make install

# Install systemd service
sudo make install-service
```

## Model Management

This agent requires BirdNET models for inference. Models are managed via Git LFS and stored in `$ORPHEUS_DATA_ROOT/models/`.

### Required Models

- **birdnet.onnx**: Main acoustic analysis model (ONNX FP32)
- **birdnet_meta.tflite**: Geographic filtering model (TFLite FP16) for hybrid inference
- **labels.json**: Species label mappings

### Initial Setup (Bootstrap)

Download models from upstream sources:

```bash
export ORPHEUS_DATA_ROOT=/data/orpheus  # or ~/data/orpheus for development
make download-models
```

This will download:

- BirdNET ONNX model from Hugging Face (onnx-community/BirdNET)
- BirdNET Meta Model from BirdNET-Pi community repository
- Species labels from Hugging Face

### Production Deployment

After initial bootstrap and committing models to Git LFS, use:

```bash
make pull-models  # Pull models from Git LFS
make check-models # Verify all models are present
```

### Verifying Models

```bash
make check-models
```

Expected output:

```bash
✓ birdnet.onnx (29M)
✓ birdnet_meta.tflite (6.1M)
✓ labels.json (144K, 6522 species)
✅ All models present
```

## Configuration

Edit `/path/to/orpheus.yaml`:

```yaml
bird_detection:
  model_path: "/data/orpheus/models/birdnet.onnx"
  confidence_threshold: 0.5
  location_lat: 42.5
  location_lon: -83.5
```

## Usage

```bash
# Run directly
make run

# Or as systemd service
sudo systemctl start orpheus-agent-bird-detection
sudo systemctl status orpheus-agent-bird-detection

# View logs
make service-logs
```

## Development

```bash
# Run tests
make test

# Check coverage
make coverage

# Lint code
make lint          # ruff

# Format code
make format        # ruff
```

## MQTT Topics

**Subscribes to:**

- `orpheus/audio/motion/events` - Audio motion detection events

**Publishes to:**

- `orpheus/detection/bird/events` - Bird species detection events

## Event Format

### Output Event

```json
{
  "event_id": "bird_det_20251204_223557_ch1_001",
  "source_event_id": "audio_motion_...",
  "timestamp": "2025-12-04T22:35:58.123456+00:00",
  "channel_id": "1",
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
  "audio_clip_path": "/data/orpheus/audio/audio_motion/1/...",
  "model_version": "BirdNET_V2.4",
  "inference_time_ms": 145
}
```
