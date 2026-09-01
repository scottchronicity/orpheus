# Storage retention

How recordings are deleted on an Orpheus station, and how to work on the code
that deletes them.

## One component deletes, and it is not an agent

Every agent used to trim its own directory. That produced four independent
answers to a question the disk only asks once: each agent honored a budget
scoped to its own files, knew nothing about the shared filesystem, and the
directories no agent owned — timelapses above all — grew without limit, because
a per-agent cleanup can only ever cover the agents that exist.

So retention moved out of the agents and into one component,
`orpheus-storage-sweep`. **No agent deletes a recording any more.** The
`_periodic_cleanup` tasks in `orpheus-agent-audio-motion` and
`orpheus-agent-video-motion` are gone, and so is the inline age purge in
`orpheus-agent-video-snapshotter`. If you are adding an agent that writes files
under `$ORPHEUS_DATA_ROOT`, do not give it a cleanup task — give its directory a
category in `storage.retention.categories` instead, so the one sweep that can
see the whole disk owns it too.

The reasoning behind the design is in `docs/designs/storage-retention.md`; the
module docstring in `src/orpheus_common/storage/sweep.py` is the short version
and the code is the authority.

## How it runs

The sweep is a one-shot command, not a daemon. A sweep is a measurement and a
decision — it holds no state between runs beyond a report on disk, so there is
nothing to supervise and nothing to leak on a board where three model agents
already carry memory caps.

- `systemd/orpheus-storage-sweep.service` — `Type=oneshot`, running
  `python -m orpheus_common.storage.sweep` as the `orpheus` user. It deliberately
  does not depend on the broker: making the component that deletes files wait on
  the component that delivers messages would mean a broker outage stops
  retention, and a full disk is worse than a late sweep.
- `systemd/orpheus-storage-sweep.timer` — every 15 minutes
  (`OnUnitActiveSec=15min`), first run five minutes after boot so it does not
  land while agents are loading models, `Persistent=true` so a station that was
  powered off sweeps once on the way up.
- `systemd/install.sh` installs both and enables the **timer**, never the
  service — enabling the service would run one sweep at boot and never again.
  That script is what `make -C platform/orpheus-common install-service` runs,
  which the repository-root `make services-install` calls.

The console script `orpheus-storage-sweep` is declared in `pyproject.toml`, so
the same entry point is available by name in an installed environment.

## How it decides

Three rules, applied in this order. Ceilings and pressure answer different
questions and are kept apart on purpose; the floor is underneath both.

1. **Ceilings** — `storage.retention.categories.<key>.max_gb` caps how much one
   kind of recording may hold. A category over its ceiling is trimmed back to
   it, oldest file first, *regardless of free space*: a ceiling is a statement
   about how much history the station keeps, and it is just as true on a drive
   with a terabyte spare.
2. **Pressure** — when free space falls below `storage.retention.reserve_gb`
   (default 100), every category above its floor gives up data in proportion to
   how much it has to give, in rounds of 512 MB per eligible category. Taking a
   fixed share each would empty a small category while a large one barely
   noticed; taking it all from the largest would make one kind of recording pay
   for a disk that every kind is filling. `min_free_space_percent`, if set,
   describes the same threshold as a percentage of the whole disk, and the
   **stricter** of the two applies — stations configured before `reserve_gb`
   existed do not silently get a looser guard.
3. **Floors are absolute** — `floor_days` per category is a stretch of recent
   recording that is never deleted for any reason. If holding the floor means
   missing a ceiling, or means failing to reach the reserve, the sweep logs at
   CRITICAL and stops. Deleting the last month of audio to satisfy a number in a
   config file is the worse outcome, and it is not reversible.
   `min_file_age_hours` is a second hard floor that always applies, so a clip
   still being written is never a candidate.

Eviction is always oldest-first, whatever the category. Selecting the largest
files would free space faster and leave an operator unable to say what window of
history they still have.

## Configuration

`config/orpheus.example.yaml` carries the annotated canonical shape. The
essentials:

```yaml
storage:
  retention:
    sweep_enabled: true          # false stops every deletion; measurement continues
    reserve_gb: 100              # free space the sweep works to keep
    sweep_interval_minutes: 15   # reported cadence; change the timer alongside it
    first_run_grace_hours: 24    # the first sweep after install reports, deletes nothing
    categories:
      audio_motion:  { max_gb: 600, floor_days: 30 }
      video_motion:  { max_gb: 60,  floor_days: 90 }
      snapshots:     { max_gb: 450, floor_days: 90 }
      timelapses:    { max_gb: 450, floor_days: 90 }
    min_file_age_hours: 1        # never delete a file younger than this
    min_free_space_percent: 10   # reconciled with reserve_gb; the stricter wins
```

`sweep_interval_minutes` is what the dashboard reports as the cadence;
`OnUnitActiveSec` in the timer is what actually schedules it. Change both
together.

### Keys that are accepted and no longer applied

They still parse, so an existing configuration file keeps working, but nothing
reads them into a deletion decision. Do not write new code against them:

- `raw_audio_days`, `raw_video_days` — age windows from the per-agent
  arrangement. `floor_days` is what protects recent recordings now, and `max_gb`
  is what bounds them.
- `max_size_gb`, `cleanup_trigger_percent`, `cleanup_amount_percent`,
  `check_interval_hours` — read only by the per-directory helper below, which
  nothing runs on a timer.
- `video_snapshotter.retention_days` — the snapshotter's own age purge is gone.
  It logs at startup that the key is inert, so an operator who set it finds out
  from the journal rather than from a directory that never shrinks. Set
  `storage.retention.categories.snapshots` instead.
- `detections_days` — database row retention, applied by the detections database
  rather than by the sweep.

## Operator commands

| Command | What it does |
|---|---|
| `make storage-report` | A dry run: decides exactly what a real sweep would and deletes nothing, printing a per-category table of size, ceiling, floor, and the action it would take. Safe at any time. |
| `make storage-sweep` | One real sweep now, outside the timer's schedule. |
| `sudo systemctl disable --now orpheus-storage-sweep.timer` | Stops all deletion by unscheduling it. |
| `storage.retention.sweep_enabled: false` | Stops all deletion while the sweep keeps measuring, so the dashboard still shows what is growing. |
| `orpheus-storage-sweep --force` | Ends the first-run grace early and enforces now. |
| `orpheus-storage-sweep --json` | The full report on stdout, with logs moved to stderr so the output stays parseable. |

Exit code `2` means free space is below the reserve **and** every category is at
its floor — the one storage condition the sweep cannot resolve by itself. The
unit ends up failed on purpose, because a green timer would hide it. Lower
`floor_days`, lower `reserve_gb`, or add capacity.

### The first sweep after an install deletes nothing

`first_run_grace_hours` (default 24) gives a fresh install one window in which
the sweep says what it *would* delete without deleting it. An operator who
disagrees with the ceilings finds out before the recordings are gone rather than
after, which is the only order that matters for something irreversible. It logs
at CRITICAL when it would have removed something, naming `make storage-report`
as the way to review it.

## What it leaves under `$ORPHEUS_DATA_ROOT`

All three live with the data rather than with the deployment, so they travel
with a copied disk:

- `.storage-sweep-state.json` — the published report of the last run. The
  Diagnostics storage panel renders this rather than walking the directories
  itself; the sweep already surveyed them and already holds the policy, so a
  second walk would be a second, disagreeing answer. Written to a temporary file
  and renamed, so a reader mid-sweep sees the previous report in full rather
  than half of the next one.
- `.storage-sweep.lock` — a `flock`. The timer alone would not collide, but an
  operator running a sweep by hand during a scheduled one would, and two sweeps
  planning against a filesystem the other is changing would between them free
  far more than either intended. A dry run that finds the lock held carries on
  anyway — it only reads, so it can share the disk with a real sweep.
- `.storage-sweep-manifests/` — a CSV per sweep listing every path removed with
  its size and timestamp, so an operator can reconstruct exactly what
  disappeared. The most recent 50 are kept.

## The per-directory helper is still in the library

`CleanupPolicy`, `StorageCleanup`, and `cleanup_old_files_by_age` in
`orpheus_common.storage.cleanup` have not been removed, and they still work.
They are the lower-level tool: point one at a single directory and it applies a
size or age policy to that directory alone.

**Nothing in Orpheus runs them on a timer any more.** They have no view of the
shared filesystem, no notion of a floor, and no coordination with anything else
deleting from the same disk — which is exactly why the agents stopped using
them. Reach for them for a one-off cleanup you are driving yourself, or for a
directory outside `$ORPHEUS_DATA_ROOT`; use the sweep for anything a station
does on its own.

```python
from pathlib import Path

from orpheus_common.storage.cleanup import CleanupPolicy, StorageCleanup

policy = CleanupPolicy(
    max_size_gb=50.0,
    cleanup_trigger_percent=90.0,   # act once the directory passes 90% of the limit
    cleanup_amount_percent=25.0,    # then remove 25% of it
    cleanup_strategy="oldest",      # or "largest" / "random"
    min_file_age_hours=1.0,
    file_pattern="*.flac",
)

cleanup = StorageCleanup(policy)
result = cleanup.cleanup(Path("/data/orpheus/audio/motion"), dry_run=True)
print(f"Would remove {result.files_removed} files, {result.bytes_freed / 1024**2:.1f} MB")
```

Age alone, with no policy object:

```python
from pathlib import Path

from orpheus_common.storage.cleanup import cleanup_old_files_by_age

deleted = cleanup_old_files_by_age(
    path=Path("/data/orpheus/audio/motion"),
    max_age_days=90,
    dry_run=True,
    pattern="*.flac",
)
```

Both honor `min_file_age_hours`, write a deletion manifest, and support
`dry_run=True`. `examples/cleanup_demo.py` drives them interactively.

## Working on this code

- `src/orpheus_common/storage/sweep.py` — the sweep. `StorageSweep` takes
  `disk_space`, `now`, `scan`, and `remove` as injectable callables, so a
  nearly-full disk, a floor that blocks eviction, and a category over its
  ceiling can all be exercised without filling a real filesystem or deleting a
  real recording.
- `src/orpheus_common/storage/usage.py` — `survey_data_root` answers "how big",
  and throws the per-file detail away. The sweep keeps that detail separately
  because eviction needs it.
- `src/orpheus_common/storage/cleanup.py` — the per-directory helper above.
- `tests/storage/test_sweep.py` and `tests/test_storage_cleanup.py` cover the
  two respectively.

Run them with `make -C platform/orpheus-common test`.
