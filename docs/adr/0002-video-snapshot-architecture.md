# ADR 0002: Video Snapshot Architecture

**Status:** Accepted

**Date:** 2026-01-25

**Deciders:** Development Team

## Context

The Orpheus wildlife monitoring system requires continuous capture of still images from IP cameras for:

1. Source material for timelapse video generation
2. Event-based image analysis (bird detection, motion analysis)
3. Historical record of camera views

We needed to decide:

- How snapshots should be captured and stored
- Filename conventions for easy sorting and retrieval
- Directory organization for date-based access
- Resource management for RTSP connections

## Decision

### 1. On-Demand RTSP Connection

The snapshotter opens RTSP streams only momentarily to capture each frame, then immediately closes the connection. This approach:

- Minimizes CPU/memory usage on the Jetson
- Reduces camera load (cameras have limited concurrent stream capacity)
- Avoids stale frame issues from long-running connections

```python
# Conceptual approach
cap = cv2.VideoCapture(rtsp_url)
ret, frame = cap.read()
cap.release()  # Immediately release
```

### 2. Storage Path Convention

Snapshots are stored in date-organized directories with UTC timestamps:

```shell
/data/orpheus/video/snapshots/{YYYY.MM.DD}/{timestamp}.{camera_name}.jpg
```

Example:

```shell
/data/orpheus/video/snapshots/2026.01.25/2026-01-25T14-30-45.123Z.orpheus-eye-1.jpg
```

**Design decisions:**

- **Date directories**: Enables easy cleanup (delete old directories) and browsing
- **UTC timestamps**: Avoids timezone/DST issues in filenames
- **Camera suffix**: Allows all cameras' snapshots in same directory for cross-camera analysis
- **ISO 8601 format**: Lexicographic sorting equals chronological sorting

### 3. Configuration-Driven Intervals

Each camera can have its own snapshot interval:

```yaml
cameras:
  orpheus-eye-1:
    snapshots:
      interval: "5m"  # Every 5 minutes
  orpheus-eye-2:
    snapshots:
      interval: "10m"  # Every 10 minutes
```

Interval of `"0"` disables snapshots for that camera.

### 4. Agent Architecture

The snapshotter runs as a standalone systemd service:

- Wakes every 60 seconds to check if any camera needs a snapshot
- Per-camera tracking of last snapshot time
- Graceful shutdown on SIGTERM/SIGINT
- No MQTT dependency (purely filesystem-based output)

## Consequences

### Positive

- Low resource usage through on-demand connections
- Simple, reliable operation with no external dependencies
- Easy cleanup via date directory deletion
- Snapshots available for both timelapse and real-time analysis

### Negative

- Momentary latency (1-2 seconds) for each capture due to RTSP handshake
- Missing snapshots if camera is temporarily unreachable (no retry logic)
- No MQTT notification of new snapshots (consumers must poll filesystem)

### Neutral

- Snapshots stored as JPEG (standard, universal format)
- Each camera operates independently (no cross-camera coordination)

## Alternatives Considered

### 1. Continuous RTSP Stream with Frame Sampling

Rejected: Would consume significant CPU and memory on Jetson, cameras have limited stream capacity.

### 2. Camera-Side Snapshot (HTTP API)

Considered for future: Some cameras support HTTP snapshot endpoints, which would be faster. Current approach works universally with any RTSP camera.

### 3. Event-Driven Snapshots (Motion Triggered)

Rejected for this use case: Motion-triggered snapshots are handled by video-motion agent. Snapshotter provides regular, predictable intervals for timelapse source material.

## Related

- [ADR 0003: Timelapse Generation Architecture](0003-timelapse-generation-architecture.md)
- [agents/orpheus-agent-video-snapshotter/README.md](../../agents/orpheus-agent-video-snapshotter/README.md)
- [docs/ARCHITECTURE.md](../ARCHITECTURE.md)
