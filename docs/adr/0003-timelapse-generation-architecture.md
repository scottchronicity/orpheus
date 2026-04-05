# ADR 0003: Timelapse Generation Architecture

**Status:** Accepted

**Date:** 2026-01-25

**Deciders:** Development Team

## Context

The Orpheus system needs to generate timelapse videos from camera snapshots for:

1. Compressed visual summaries of daily activity
2. Dashboard playback of historical camera views
3. Wildlife behavior analysis over time

Key design questions:

- How to schedule timelapse generation
- Filename conventions for organization and UI display
- Tier system for multiple lookback windows
- Video codec selection for playback compatibility

## Decision

### 1. Tiered Timelapse System

Multiple timelapse durations (tiers) run on different schedules:

| Tier | Lookback | Label | Typical Use |
| ---- | -------- | ----- | ----------- |
| tl0 | 24h | daily | Full day review |
| tl1 | 12h | tl-12h | Half-day review |
| tl2 | 6h | tl-6h | Quarter-day review |
| tl3 | 1h | hourly | Recent activity |
| tl4 | 30m | half-hour | Short-term review |
| tl5 | 10m | ten-minute | Near real-time |
| tl6 | 1m | one-minute | Testing only |

This allows the dashboard to show progressively detailed views.

### 2. Standardized Filename Format

Timelapse files use a structured naming convention defined in `orpheus_common.storage.timelapse`:

```shell
{camera_id}.{label}.{tier}.{lookback}.{YYYYMMDD-HHMMSS}.mp4
```

Example:

```shell
orpheus-eye-1.hourly.tl3.1h.20260125-170000.mp4
```

**Components:**

- `camera_id`: Camera identifier (e.g., `orpheus-eye-1`)
- `label`: Human-readable schedule name (e.g., `daily`, `hourly`, `half-hour`)
- `tier`: Tier identifier for programmatic access (e.g., `tl0`, `tl3`)
- `lookback`: Duration for display (e.g., `24h`, `1h`)
- `timestamp`: Generation time in UTC

This format enables:

- Lexicographic sorting = chronological sorting
- Easy parsing by dashboard/UI
- Clear identification at a glance
- Tier-based filtering and cleanup

### 3. Bucket Sampling Algorithm

Rather than using all snapshots, timelapse uses bucket sampling:

1. Divide lookback window into buckets based on `sampling_interval`
2. Select one snapshot per bucket (closest to bucket center)
3. Skip generation if < 50% of expected snapshots available

Example: 1h lookback with 5m sampling = 12 buckets, need ≥6 snapshots.

### 4. Storage Organization

```shell
/data/orpheus/video/timelapses/{YYYY.MM.DD}/{filename}.mp4
```

Example:

```shell
/data/orpheus/video/timelapses/2026.01.25/orpheus-eye-1.hourly.tl3.1h.20260125-170000.mp4
```

### 5. Interval-Based Scheduling

Each timelapse tier can run multiple times per day based on its lookback window:

- 24h timelapse: Once at configured time (e.g., 23:00)
- 1h timelapse: Every hour
- 10m timelapse: Every 10 minutes

Job deduplication prevents running the same job twice in the same interval.

## Consequences

### Positive

- Multiple resolution levels for different analysis needs
- Standardized filenames enable dashboard filtering and display
- Bucket sampling ensures consistent frame density
- Tier system is extensible (add new tiers as needed)

### Negative

- Multiple tiers increase storage requirements
- Complex scheduling logic for interval management
- Job deduplication state must be maintained in memory

### Neutral

- Filename format change from simple `{HH-MM}.{camera}.mp4` to structured format
- Shared filename utilities in `orpheus_common.storage.timelapse`

## Related

- [ADR 0002: Video Snapshot Architecture](0002-video-snapshot-architecture.md)
- [ADR 0004: Jetson Video Codec Strategy](0004-jetson-video-codec-strategy.md)
- [orpheus_common.storage.timelapse](../../platform/orpheus-common/src/orpheus_common/storage/timelapse.py)
- [agents/orpheus-agent-video-timelapser/README.md](../../agents/orpheus-agent-video-timelapser/README.md)
