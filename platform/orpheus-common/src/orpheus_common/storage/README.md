# `orpheus_common.storage`

Everything that knows where Orpheus writes files, how much of the disk they are
using, and what gets deleted when the disk fills.

| Module | What it owns |
|---|---|
| `paths.py` | Path construction under `$ORPHEUS_DATA_ROOT` — `get_data_root`, `get_audio_path`, `get_video_path`, `get_detections_path`, `ensure_directory`. |
| `usage.py` | Measurement without judgement: `DATA_ROOT_CATEGORIES` names the recording categories, `survey_data_root` answers how big each one is. |
| `sweep.py` | **The one component that deletes recordings.** Ceilings, pressure relief, floors, the published report, and the `orpheus-storage-sweep` command. |
| `cleanup.py` | The lower-level per-directory helper — `CleanupPolicy`, `StorageCleanup`, `cleanup_old_files_by_age`. Nothing runs it on a timer. |
| `management.py` | Two small standalone helpers predating the above — `cleanup_old_files` and `get_disk_usage`. |
| `timelapse.py` | Timelapse filename and tier conventions. |

## Retention lives in one place

Every agent used to trim its own directory, which gave four independent answers
to a question the disk only asks once — and left the directories no agent owned,
timelapses above all, growing without limit. Retention is now owned by
`orpheus-storage-sweep`, a `Type=oneshot` unit driven by
`orpheus-storage-sweep.timer` every 15 minutes, which sees every category and
the shared filesystem underneath them.

**No agent deletes anything.** If you are adding an agent that writes under
`$ORPHEUS_DATA_ROOT`, give its directory a category in
`storage.retention.categories` rather than a cleanup task of its own.

The sweep enforces three things in order: per-category **ceilings** (`max_gb`,
applied regardless of free space), **pressure** relief when free space falls
below `storage.retention.reserve_gb` (every category above its floor
contributes in proportion to what it has to give), and **floors** (`floor_days`
plus `min_file_age_hours`) that are never breached — if holding a floor means
missing a ceiling or failing to reach the reserve, the sweep logs at CRITICAL
and stops.

Details and the operator commands are in
[`docs/STORAGE_CLEANUP.md`](../../../docs/STORAGE_CLEANUP.md); the design
argument is in `docs/designs/storage-retention.md` at the repository root; the
module docstring in `sweep.py` is the short version.

### Reading what the sweep decided

The sweep publishes its last run to `$ORPHEUS_DATA_ROOT/.storage-sweep-state.json`
and nothing else needs to walk the data root to find out what is there:

```python
from orpheus_common.storage import get_data_root, read_state

report = read_state(get_data_root())
if report is None:
    print("The sweep has not run yet on this station")
else:
    for key, category in report["categories"].items():
        print(key, category["bytes"], "of", category["limit_bytes"])
```

`StorageSweep` itself takes `disk_space`, `now`, `scan`, and `remove` as
injectable callables, so a nearly-full disk, a floor that blocks eviction, and a
category over its ceiling can each be exercised in a test without filling a real
filesystem or deleting a real recording.

## The per-directory helper

`CleanupPolicy` and `StorageCleanup` still exist and still work. They apply a
size or age policy to a **single directory** and know nothing about the disk
that directory shares, which is precisely why the agents stopped using them:
four directories inside their budgets can still fill one filesystem, and a
per-directory policy has no floor to refuse to breach.

Use them for a one-off cleanup you are driving yourself, or for a directory
outside `$ORPHEUS_DATA_ROOT`. Use the sweep for anything a station does on its
own.

```python
from pathlib import Path

from orpheus_common.storage import CleanupPolicy, StorageCleanup

policy = CleanupPolicy(
    max_size_gb=50.0,
    cleanup_trigger_percent=90.0,   # act once the directory passes 90% of the limit
    cleanup_amount_percent=25.0,    # then remove 25% of it
    cleanup_strategy="oldest",      # "oldest" for time-series data; "largest" or "random" exist
    min_file_age_hours=1.0,
)

cleanup = StorageCleanup(policy)
result = cleanup.cleanup(Path("/data/orpheus/audio/motion"), dry_run=True)
print(f"Would remove {result.files_removed} files, {result.bytes_freed / 1024**2:.1f} MB")
```

Age alone, with no policy object:

```python
from pathlib import Path

from orpheus_common.storage import cleanup_old_files_by_age

deleted = cleanup_old_files_by_age(
    path=Path("/data/orpheus/audio/motion"),
    max_age_days=90,
    dry_run=True,
)
```

### API reference

`CleanupPolicy` — `max_size_gb`, `max_age_days` (informational),
`cleanup_strategy`, `cleanup_trigger_percent`, `cleanup_amount_percent`,
`min_file_age_hours`, `file_pattern`.

`StorageCleanup` — `scan_directory(path)`, `calculate_usage(path)`,
`needs_cleanup(path)`, `select_files_to_delete(files)`,
`cleanup(path, dry_run, manifest_dir)`.

`CleanupResult` — `files_removed`, `bytes_freed`, `manifest_path`,
`duration_seconds`, `errors`.

Both paths refuse to delete a file younger than `min_file_age_hours`, write a
CSV deletion manifest, offer `dry_run=True`, and continue past individual file
errors rather than abandoning the run.

## Configuration

`storage.retention` in `config/orpheus.example.yaml` is the annotated canonical
shape. `max_size_gb`, `cleanup_trigger_percent`, `cleanup_amount_percent` and
`check_interval_hours` are read only by `cleanup.py` and are therefore accepted
and unapplied on a running station; so are the age windows `raw_audio_days` and
`raw_video_days`. They stay parseable so an existing configuration file keeps
working — do not write new code against them.

## Tests and examples

```bash
make -C platform/orpheus-common test
```

`tests/storage/test_sweep.py` covers the sweep, `tests/test_storage_cleanup.py`
the per-directory helper, and `tests/test_storage_usage.py` the survey.
`examples/cleanup_demo.py` drives the helper interactively:

```bash
python examples/cleanup_demo.py /data/orpheus/audio --mode check
python examples/cleanup_demo.py /data/orpheus/audio --mode policy --dry-run
```
