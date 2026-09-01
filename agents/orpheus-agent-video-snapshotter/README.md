# Orpheus Video Snapshotter Agent

Periodic snapshot capture agent for IP cameras in the Orpheus wildlife monitoring platform.

## Overview

The Video Snapshotter agent captures periodic still images from configured IP cameras at specified intervals. Snapshots are saved to date-organized directories for easy retrieval and analysis.

## Features

- **Periodic Capture**: Configurable snapshot intervals per camera (e.g., `5m`, `10m`, `1h`)
- **On-Demand Connection**: Opens RTSP stream only for capture, minimizes resource usage
- **Date Organization**: Saves snapshots to `{YYYY.MM.DD}` directories
- **UTC Timestamps**: Filenames include ISO 8601 UTC timestamps
- **Graceful Shutdown**: Handles SIGTERM/SIGINT signals cleanly
- **Structured Logging**: Uses orpheus_common logging for consistent output

## Configuration

Snapshots are configured per-camera in `orpheus.yaml`:

```yaml
cameras:
  front-yard:
    type: "amcrest"
    host: "192.168.1.100"
    enabled: true
    snapshots:
      interval: "5m"  # Capture every 5 minutes
  
  back-yard:
    type: "amcrest"
    host: "192.168.1.101"
    enabled: true
    snapshots:
      interval: "10m"  # Capture every 10 minutes
  
  driveway:
    type: "amcrest"
    host: "192.168.1.102"
    enabled: true
    snapshots:
      interval: "0"  # Disabled (interval of "0")
```

### Interval Format

Intervals support duration suffixes:

- `s` - seconds (e.g., `30s`)
- `m` - minutes (e.g., `5m`)
- `h` - hours (e.g., `1h`)
- `d` - days (e.g., `1d`)

Set `interval: "0"` to disable snapshots for a camera.

## MQTT Topics

**Subscribes to:** Nothing.

**Publishes to:** Nothing.

This agent operates entirely outside the MQTT bus. It reads RTSP streams directly from cameras on a timer and writes JPEG files to disk. It does not emit events or consume commands via MQTT. Downstream consumers (e.g., `orpheus-agent-video-timelapser`, the dashboard) read the snapshot files directly from the filesystem.

## Storage

Snapshots are saved to:

```shell
/data/orpheus/video/snapshots/{YYYY.MM.DD}/{UTC_ISO_TIMESTAMP}.{camera_name}.jpg
```

Example:

```shell
/data/orpheus/video/snapshots/2025.01.15/2025-01-15T14-30-45.123Z.front-yard.jpg
```

### Retention

**This agent does not delete snapshots.** It used to purge them on an age window
of its own; that job now belongs to `orpheus-storage-sweep`, which runs from a
systemd timer every 15 minutes and is the only thing on the station that removes a
recording.

Snapshots are the `snapshots` category: trimmed oldest-first once they pass
`storage.retention.categories.snapshots.max_gb` (450 GB by default), and sooner if
free space falls below `storage.retention.reserve_gb`, with nothing inside
`floor_days` (90 by default) ever deleted. `make storage-report` shows what the
next sweep would do.

`video_snapshotter.retention_days` is inert — it still parses, and the agent logs
at startup that nothing applies it, so an operator who set it learns that from the
journal rather than from a directory that never shrinks. Configure
`storage.retention.categories.snapshots` instead. See
[Data & retention](../../docs/operator-manual/index.md#7-data-retention).

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

### Running

```bash
# Run with default config
orpheus-agent-video-snapshotter

# Run with custom config
orpheus-agent-video-snapshotter --config /path/to/orpheus.yaml

# Run with debug logging
orpheus-agent-video-snapshotter --log-level DEBUG
```

### Systemd Service

```bash
# Enable and start
sudo systemctl enable orpheus-agent-video-snapshotter
sudo systemctl start orpheus-agent-video-snapshotter

# Check status
sudo systemctl status orpheus-agent-video-snapshotter

# View logs
sudo journalctl -u orpheus-agent-video-snapshotter -f
```

## Development

### Project Structure

```shell
orpheus-agent-video-snapshotter/
├── src/orpheus_agent_video_snapshotter/
│   ├── __init__.py       # Package initialization
│   ├── config.py         # Configuration loading
│   └── main.py           # Main agent logic
├── tests/
│   ├── conftest.py       # Test fixtures
│   ├── test_sanity.py    # Basic import tests
│   ├── test_config.py    # Configuration tests
│   └── test_main.py      # Main logic tests
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
pytest tests/test_config.py -v

# Run specific test
pytest tests/test_main.py::test_capture_snapshot_success -v
```

### Code Quality

```bash
# Lint code
make lint

# Format code
make format

# Type check
make typecheck
```

## Implementation Details

### Capture Process

1. **Timer Check**: Every second, check if interval elapsed for each camera
2. **Open Stream**: Open RTSP connection to camera
3. **Read Frame**: Capture single frame from stream
4. **Close Stream**: Immediately release RTSP connection
5. **Save Image**: Write JPEG to date-organized directory
6. **Update Timer**: Record capture time for interval calculation

### Resource Usage

- **Minimal Connection Time**: RTSP streams opened only during capture
- **Low Memory**: No video buffering, single frame at a time
- **Efficient I/O**: JPEG compression with quality=90

### Error Handling

- **Stream Failures**: Logged, skipped until next interval
- **Write Failures**: Logged, directory creation attempted
- **Invalid Config**: Logged, camera skipped

## Dependencies

- **opencv-python**: Video capture and image encoding
- **numpy**: Frame data manipulation
- **orpheus-common**: Shared configuration, logging, utilities

## Python Version

Requires Python 3.9.x for NVIDIA Jetson JetPack compatibility.

## License

See repository root LICENSE file.

## Related Documentation

- [ADR 0002: Video Snapshot Architecture](../../docs/adr/0002-video-snapshot-architecture.md)
- [ADR 0003: Timelapse Generation Architecture](../../docs/adr/0003-timelapse-generation-architecture.md)
- [docs/ARCHITECTURE.md](../../docs/ARCHITECTURE.md)

## Related Agents

- **orpheus-agent-video-timelapser**: Generates timelapse videos from snapshots
- **orpheus-agent-video-motion**: Motion detection and clip saving
- **orpheus-agent-audio-motion**: Audio motion detection
