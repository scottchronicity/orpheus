# ADR 0007: Timelapse Scheduling Race Condition Fix and Required Labels

**Status:** Accepted

**Date:** 2026-02-18

**Deciders:** Development Team

**Supersedes:** Portions of [ADR 0003](0003-timelapse-generation-architecture.md) (scheduling, label generation)

## Context

Two production bugs were discovered on the Jetson deployment affecting timelapse generation across four cameras (orpheus-eye-1 through eye-4):

### Bug 1: Race Condition in Sequential Scheduling

The timelapse loop processed cameras sequentially within a single 60-second tick. Each camera's timelapse generation (video encoding + ffmpeg transcode) took 10-30 seconds. By the time later cameras were evaluated, wall-clock time had advanced past the 90-second trigger window:

- orpheus-eye-1: 2149 timelapse files
- orpheus-eye-2: 2086 timelapse files
- orpheus-eye-3: 1964 timelapse files
- orpheus-eye-4: 1847 timelapse files

The ~14% drop from eye-1 to eye-4 was caused by processing time pushing later cameras past their trigger windows.

### Bug 2: Label Auto-Generation via `label_map`

`TimelapseConfig.from_dict()` contained a `label_map` dictionary that auto-generated labels from `lookback_window` values (e.g., `"24h"` → `"daily"`). This caused several problems:

1. Labels were silently overridden — explicit config labels were ignored when lookback_window matched a map entry.
2. New lookback windows (e.g., `"12h"`, `"6h"`) had no map entries, producing empty labels.
3. The mapping was non-obvious — reading the config YAML didn't tell you what label would actually appear in filenames.
4. Debugging required reading Python source to understand why a label was or wasn't present.

### Bug 3: Insufficient Logging

When investigating missing timelapses, there was no way to determine from logs alone:

- Which timelapse schedules were configured at startup
- Whether a job was skipped, triggered, or failed
- How long each job took
- How many snapshots were found vs. expected

## Decision

### 1. Collect-Then-Execute Scheduling Pattern

The timelapse loop now separates job evaluation from job execution in two distinct phases:

**Phase 1 — Collect:** Iterate all cameras and timelapse configs. Snapshot the current time ONCE per timezone into a `tz_times` cache before iterating. Evaluate all trigger conditions against the cached time. Append eligible jobs to a `jobs_to_run` list.

**Phase 2 — Execute:** Process all collected jobs sequentially. Processing time no longer affects which jobs are eligible.

This ensures that if cameras A, B, C, D all have a job due at 23:00:00, all four are collected at the same cached timestamp regardless of how long A's video takes to encode.

### 2. Label is Required — No Auto-Generation

`TimelapseConfig.from_dict()` now raises `ConfigError` if the `label` field is missing or empty. There is no fallback, no auto-generation, no `label_map`.

Every timelapse must have an explicit label in the YAML config:

```yaml
timelapses:
  - label: daily
    lookback_window: "24h"
    start_time: "23:00"
  - label: hourly
    lookback_window: "1h"
    start_time: "00:00"
```

This makes the config file the single source of truth for what appears in filenames.

### 3. Comprehensive Behavioral Logging

The timelapser agent now logs at every decision point:

- **Startup:** Full schedule dump for every camera/timelapse (label, start_time, lookback_window, sampling_interval, timezone) — grep for `"Timelapse schedule"`.
- **Per-tick:** Summary of collected jobs with count and identifiers.
- **Per-job start:** Camera, label, lookback window, interval number, timezone, date.
- **Per-job completion:** Camera, label, elapsed time.
- **Snapshot discovery:** Total snapshots on disk, glob pattern used.
- **Bucket sampling:** Snapshots in window, expected bucket count, lookback start/end times.
- **File output:** Output filename, directory, frame count, frame rate, final file size.

The goal: a single `journalctl` session should tell you exactly what the agent decided and why, without reading source code.

## Consequences

### Positive

- All cameras get equal scheduling opportunity regardless of processing order
- Labels are explicit and predictable — what you see in YAML is what appears in filenames
- Missing labels fail fast at config load, not silently at runtime
- Logs provide complete audit trail for debugging production issues

### Negative

- Existing configs without `label` fields will fail to load (intentional — forces explicit configuration)
- More verbose logs increase journald storage (acceptable tradeoff for debuggability)

### Neutral

- `timezone` on `TimelapseConfig` remains optional (defaults to `"UTC"`) — this is a different concern from label

## Related

- [ADR 0003: Timelapse Generation Architecture](0003-timelapse-generation-architecture.md) — original scheduling and filename design
- [ADR 0004: Jetson Video Codec Strategy](0004-jetson-video-codec-strategy.md) — ffmpeg transcode that contributes to per-job processing time
- `platform/orpheus-common/src/orpheus_common/config.py` — `TimelapseConfig.from_dict()` with required label
- `agents/orpheus-agent-video-timelapser/src/orpheus_agent_video_timelapser/main.py` — collect-then-execute loop
