# Orpheus Video Timelapser Agent

Timelapse video generation agent for IP cameras in the Orpheus wildlife monitoring platform.

## Overview

The Video Timelapser agent generates timelapse videos from camera snapshots at scheduled times. It wakes up every minute to check if any timelapse jobs should run, collects the last N snapshots, and stitches them into MP4 videos.

## Features

- **Scheduled Generation**: Configurable start times per camera (e.g., `06:00`, `18:00`)
- **Multiple Schedules**: Support multiple daily timelapses per camera
- **Smart Selection**: Uses last N snapshots, handles missing images gracefully
- **Quality Control**: Skips generation if fewer than 50% of expected snapshots exist
- **MPEG-4 Encoding**: Efficient MP4 format with configurable frame rates
- **Daily Execution**: Each job runs once per day, resets at midnight
- **Structured Logging**: Uses orpheus_common logging for consistent output

## Configuration

Timelapses are configured per-camera in `orpheus.yaml`:

```yaml
cameras:
  front-yard:
    type: "amcrest"
    host: "192.168.1.100"
    enabled: true
    snapshots:
      interval: "5m"  # Snapshots every 5 minutes
    timelapses:
      - start_time: "06:00"        # Morning timelapse at 6 AM
        lookback_window: "24h"     # Sample from last 24 hours
        sampling_interval: "15m"   # Sample every 15 minutes
        retention_days: 90         # Parsed and logged, but not applied — see Retention below
        clip_duration: 2.0         # Each image shown for 2 seconds
      - start_time: "18:00"        # Evening timelapse at 6 PM
        lookback_window: "48h"     # Sample from last 48 hours
        sampling_interval: "30m"   # Sample every 30 minutes
        retention_days: 90
        clip_duration: 1.0         # Each image shown for 1 second
  
  back-yard:
    type: "amcrest"
    host: "192.168.1.101"
    enabled: true
    snapshots:
      interval: "10m"
    timelapses:
      - start_time: "12:00"       # Noon timelapse
        lookback_window: "24h"
        sampling_interval: "15m"
        retention_days: 90
        clip_duration: 2.0
```

### Configuration Parameters

- **start_time**: `HH:MM` format (24-hour), when to generate timelapse
- **lookback_window**: Time window to sample from (e.g., "24h", "48h", "7d")
- **sampling_interval**: Interval between sampled snapshots (e.g., "15m", "30m", "1h")
- **retention_days**: Accepted and validated, and echoed in the startup schedule
  log, but nothing applies it — see [Retention](#retention) below
- **clip_duration**: How long each image is shown (seconds, can be fractional)

### Retention

**This agent does not delete timelapses, and neither does its `retention_days`
setting.** For a long time nothing deleted them at all, which is how timelapses
came to be one of the largest things on a station's disk. They are now the
`timelapses` category of `orpheus-storage-sweep`, the one component that removes
recordings, running from a systemd timer every 15 minutes.

The category is trimmed oldest-first once it passes
`storage.retention.categories.timelapses.max_gb` (450 GB by default), and sooner if
free space falls below `storage.retention.reserve_gb`; nothing inside `floor_days`
(90 by default) is ever deleted. `make storage-report` shows what the next sweep
would do. See
[Data & retention](../../docs/operator-manual/index.md#7-data-retention).

### Frame Rate Calculation

Frame rate is calculated as: `fps = 1.0 / clip_duration`

Examples:

- `clip_duration: 2.0` → 0.5 fps (2 seconds per image)
- `clip_duration: 1.0` → 1.0 fps (1 second per image)
- `clip_duration: 0.5` → 2.0 fps (0.5 seconds per image)

## MQTT Topics

**Subscribes to:** Nothing.

**Publishes to:** Nothing.

This agent is a scheduled batch processor that operates entirely on the filesystem. It reads JPEG snapshots written by `orpheus-agent-video-snapshotter`, stitches them into MP4 timelapse videos, and writes the output back to disk. No MQTT communication is involved.

## Storage

### Input (Snapshots)

```shell
/data/orpheus/video/snapshots/{YYYY.MM.DD}/{timestamp}.{camera_name}.jpg
```

### Output (Timelapses)

```shell
/data/orpheus/video/timelapses/{YYYY.MM.DD}/{HH-MM}.{camera_name}.mp4
```

Example:

```shell
/data/orpheus/video/timelapses/2025.01.15/06-00.front-yard.mp4
/data/orpheus/video/timelapses/2025.01.15/18-00.front-yard.mp4
```

## Behavior

### Execution Logic

1. **Wake Up**: Every 60 seconds
2. **Check Time**: Compare current local time to configured start times
3. **Job Deduplication**: Skip if job already ran today
4. **Snapshot Discovery**: Find all snapshots within lookback_window
5. **Bucket Sampling**: Select snapshots at sampling_interval intervals
6. **Validation**: Ensure sufficient snapshots exist for quality timelapse
7. **Stitching**: Create MP4 video with H.264 codec
8. **Completion Tracking**: Mark job as complete for the day

### Quality Controls

- **Minimum Threshold**: Requires sufficient snapshots for quality timelapse
  - Based on lookback_window and sampling_interval
  - Prevents low-quality timelapses from sparse data

- **Frame Consistency**: All frames resized to match first frame dimensions
  - Handles camera resolution changes gracefully

- **Error Isolation**: Failures for one camera don't affect others
  - Each camera/job processed independently

### Daily Reset

Completed jobs are tracked per date. At midnight (UTC), the tracking resets, allowing jobs to run again the next day.

## Usage

### Installation

```bash
# Install dependencies
make install

# Run tests
make test

# Check coverage
make coverage

# Lint code
make lint
```

### Running Locally

```bash
# Run with default config
orpheus-agent-video-timelapser

# Run with custom config
orpheus-agent-video-timelapser --config /path/to/orpheus.yaml

# Run with debug logging
orpheus-agent-video-timelapser --log-level DEBUG
```

### Systemd Service

```bash
# Enable and start
sudo systemctl enable orpheus-agent-video-timelapser
sudo systemctl start orpheus-agent-video-timelapser

# Check status
sudo systemctl status orpheus-agent-video-timelapser

# View logs
sudo journalctl -u orpheus-agent-video-timelapser -f
```

## Development

### Project Structure

```shell
orpheus-agent-video-timelapser/
├── src/orpheus_agent_video_timelapser/
│   ├── __init__.py       # Package initialization
│   ├── config.py         # Configuration loading
│   └── main.py           # Main agent logic
├── tests/
│   ├── conftest.py       # Test fixtures
│   ├── test_sanity.py    # Basic import tests
│   ├── test_config.py    # Configuration tests
│   └── test_main.py      # Main logic tests
├── systemd/              # Service installation
├── Makefile              # Build automation
├── pyproject.toml        # Project metadata
├── pytest.ini            # Pytest configuration
└── requirements.txt      # Dependencies
```

### Testing

```bash
# Run all tests
make test

# Run with coverage
make coverage

# Run specific test file
pytest tests/test_main.py -v

# Run specific test
pytest tests/test_main.py::test_generate_timelapse_success -v
```

### Code Quality

```bash
# Lint code
make lint

# Format code
make format
```

## Implementation Details

### Video Encoding

Videos use a two-phase encoding strategy for Jetson compatibility:

1. **Phase 1 (OpenCV)**: Write video with mp4v codec (reliable on Jetson)
2. **Phase 2 (ffmpeg)**: Transcode to H.264 for browser playback

See [ADR 0004: Jetson Video Codec Strategy](../../docs/adr/0004-jetson-video-codec-strategy.md) for details.

- **Final Codec**: H.264 (libx264)
- **Container**: MP4 with faststart
- **Quality**: CRF 28 (optimized for timelapse overview)
- **Frame Rate**: Calculated from `clip_duration`

### Resource Usage

- **Memory**: Loads all frames into memory before encoding
  - Example: 24 frames × 1920×1080 × 3 bytes ≈ 150 MB
- **CPU**: Video encoding is CPU-intensive
  - Runs once per schedule per day, minimal impact
- **Disk I/O**: Reads N snapshot files, writes 1 MP4 file

### Error Handling

- **Missing Directory**: Logged as warning, job skipped
- **Insufficient Snapshots**: Logged as warning, job skipped
- **Read Failures**: Individual frames skipped, continues if enough valid frames
- **Write Failures**: Logged as error, resources released

## Workflow Integration

### Typical Daily Flow

```shell
06:00 AM - Snapshotter captures image (5-minute intervals)
06:05 AM - Snapshotter captures image
06:10 AM - Snapshotter captures image
...
08:00 AM - Timelapser wakes up, checks schedules
08:00 AM - Morning timelapse runs:
           - Finds last 24 snapshots from today
           - Generates 06-00.front-yard.mp4
           - Marks job complete for today
08:01 AM - Timelapser sleeps for 60 seconds
...
18:00 PM - Timelapser detects evening schedule
18:00 PM - Evening timelapse runs (separate job)
```

### Snapshot Requirements

For reliable timelapses, ensure:

- Snapshotter interval < (clip_duration × clip_count)
- Example: 24 images × 2 seconds = 48 seconds total video
- With 5-minute snapshots, covers 2+ hours of activity

## Dependencies

- **opencv-python**: Video encoding and image processing
- **numpy**: Frame data manipulation
- **orpheus-common**: Shared configuration, logging, utilities

## Python Version

Requires Python 3.9.x for NVIDIA Jetson JetPack compatibility.

## License

See repository root LICENSE file.

## Related Documentation

- [ADR 0003: Timelapse Generation Architecture](../../docs/adr/0003-timelapse-generation-architecture.md)
- [ADR 0004: Jetson Video Codec Strategy](../../docs/adr/0004-jetson-video-codec-strategy.md)
- [orpheus_common.storage.timelapse](../../platform/orpheus-common/src/orpheus_common/storage/timelapse.py) - Filename utilities
- [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)

## Related Agents

- **orpheus-agent-video-snapshotter**: Captures periodic camera snapshots (source data)
- **orpheus-agent-video-motion**: Motion detection and clip saving
