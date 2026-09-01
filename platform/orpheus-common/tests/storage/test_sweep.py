"""Tests for the one component that deletes recordings.

Every assertion here is about something irreversible, so the bias is toward
proving the sweep does *not* delete: floors hold, young files survive, a dry
run leaves the disk untouched. The cases that do delete assert exactly which
files went, because "freed enough bytes" is true of deleting everything.

The filesystem and the disk reading are both injected. Nothing here fills a
real disk, and nothing waits for a real clock.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from orpheus_common.config import SweepCategory
from orpheus_common.storage.cleanup import DiskSpace
from orpheus_common.storage.sweep import (
    EXIT_BLOCKED,
    EXIT_OK,
    PRESSURE_CHUNK_BYTES,
    StorageSweep,
    read_state,
    scan_category,
    write_state,
)

GB = 1024**3
MB = 1024**2

CATEGORY_DIRS = {
    "audio_motion": "audio/audio_motion",
    "video_motion": "video/video_motion",
    "snapshots": "video/snapshots",
    "timelapses": "video/timelapses",
}

NOW = datetime(2026, 8, 26, 12, 0, 0).astimezone()


class Retention:
    """A ``storage.retention`` block, duck-typed like the real config."""

    def __init__(self, **kwargs):
        self.reserve_gb = kwargs.pop("reserve_gb", 100.0)
        self.min_free_space_percent = kwargs.pop("min_free_space_percent", 0.0)
        self.min_file_age_hours = kwargs.pop("min_file_age_hours", 1.0)
        self.sweep_interval_minutes = kwargs.pop("sweep_interval_minutes", 15.0)
        self.sweep_enabled = kwargs.pop("sweep_enabled", True)
        self.first_run_grace_hours = kwargs.pop("first_run_grace_hours", 24.0)
        self.categories = kwargs.pop("categories", {})
        assert not kwargs, f"unexpected: {kwargs}"


def make_file(root: Path, category: str, name: str, *, size: int, age_days: float) -> Path:
    """A recording of a given size, aged by setting its mtime.

    Sparse: the sweep decides on ``st_size`` and mtime and never reads a byte,
    so these allocate no blocks. Writing them for real meant a test modelling a
    full disk needed a genuinely large one — fine on a laptop, and the reason
    this suite went red on a CI runner while passing locally.
    """
    path = root / CATEGORY_DIRS[category] / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as handle:
        handle.truncate(size)
    stamp = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (stamp, stamp))
    return path


def disk(free_gb: float, total_gb: float = 4000.0):
    def _read(_path):
        return DiskSpace(total_bytes=int(total_gb * GB), free_bytes=int(free_gb * GB))

    return _read


def sweeper(root: Path, retention: Retention, *, free_gb: float = 1000.0, **kwargs) -> StorageSweep:
    return StorageSweep(
        root,
        retention,
        disk_space=kwargs.pop("disk_space", disk(free_gb)),
        now=lambda: NOW,
        **kwargs,
    )


def rule(max_gb: float, floor_days: int) -> SweepCategory:
    return SweepCategory(max_gb=max_gb, floor_days=floor_days)


# -- the quiet case ------------------------------------------------------


def test_healthy_station_deletes_nothing(tmp_path):
    """Under every ceiling with room to spare: measure, publish, leave alone."""
    kept = make_file(tmp_path, "audio_motion", "a.flac", size=4 * MB, age_days=400)
    retention = Retention(categories={"audio_motion": rule(max_gb=600, floor_days=30)})

    result = sweeper(tmp_path, retention, free_gb=1100).run()

    assert kept.exists()
    assert result.files_removed == 0
    assert result.blocked_under_reserve is False
    # The survey rides along on every sweep, including the ones that do
    # nothing — that is what keeps the dashboard current.
    assert result.report["survey"]["categories"]["audio_motion"]["bytes"] == 4 * MB
    assert result.report["categories"]["audio_motion"]["last_sweep"] is None


def test_report_carries_every_configured_category(tmp_path):
    retention = Retention(
        categories={
            "audio_motion": rule(600, 30),
            "video_motion": rule(60, 90),
            "snapshots": rule(450, 90),
            "timelapses": rule(450, 90),
        }
    )
    report = sweeper(tmp_path, retention).run().report
    assert set(report["categories"]) == {
        "audio_motion",
        "video_motion",
        "snapshots",
        "timelapses",
    }
    assert report["categories"]["timelapses"]["limit_bytes"] == 450 * GB


# -- ceilings ------------------------------------------------------------


def test_ceiling_removes_oldest_first_and_stops_at_the_limit(tmp_path):
    """Over budget by 3 MB: the three oldest go, the rest stay."""
    files = [
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=1 * MB, age_days=300 - i)
        for i in range(10)
    ]
    retention = Retention(categories={"timelapses": rule(max_gb=7 / 1024, floor_days=30)})

    result = sweeper(tmp_path, retention).run()

    assert [f.name for f in files if not f.exists()] == ["t0.mp4", "t1.mp4", "t2.mp4"]
    assert result.files_removed == 3
    assert result.bytes_freed == 3 * MB
    outcome = result.report["categories"]["timelapses"]
    assert outcome["over_ceiling"] is True
    assert outcome["floor_blocked"] is False
    assert outcome["last_sweep"]["files_removed"] == 3
    # The window that disappeared, so an operator can say what they lost.
    assert outcome["last_sweep"]["oldest_removed"] < outcome["last_sweep"]["newest_removed"]


def test_ceiling_applies_with_the_disk_nearly_empty(tmp_path):
    """A ceiling is not a low-disk rule; it holds on a drive with room."""
    old = make_file(tmp_path, "video_motion", "v.mp4", size=8 * MB, age_days=200)
    retention = Retention(categories={"video_motion": rule(max_gb=1 / 1024, floor_days=30)})

    sweeper(tmp_path, retention, free_gb=3900).run()

    assert not old.exists()


def test_floor_blocks_the_ceiling_and_keeps_the_recordings(tmp_path):
    """Over budget, but everything is recent. The floor wins."""
    recent = [
        make_file(tmp_path, "audio_motion", f"a{i}.flac", size=4 * MB, age_days=3) for i in range(5)
    ]
    retention = Retention(categories={"audio_motion": rule(max_gb=1 / 1024, floor_days=30)})

    result = sweeper(tmp_path, retention).run()

    assert all(f.exists() for f in recent)
    assert result.files_removed == 0
    assert result.report["categories"]["audio_motion"]["floor_blocked"] is True


def test_floor_boundary_splits_the_same_directory(tmp_path):
    """Only what is outside the floor may go, however far over budget."""
    inside = make_file(tmp_path, "snapshots", "new.jpg", size=6 * MB, age_days=10)
    outside = make_file(tmp_path, "snapshots", "old.jpg", size=6 * MB, age_days=200)
    retention = Retention(categories={"snapshots": rule(max_gb=1 / 1024, floor_days=90)})

    result = sweeper(tmp_path, retention).run()

    assert inside.exists()
    assert not outside.exists()
    assert result.report["categories"]["snapshots"]["floor_blocked"] is True


def test_min_file_age_protects_a_clip_still_being_written(tmp_path):
    """floor_days=0 hands everything to the sweep except the last hour."""
    fresh = make_file(tmp_path, "audio_motion", "now.flac", size=8 * MB, age_days=1 / 48)
    old = make_file(tmp_path, "audio_motion", "old.flac", size=8 * MB, age_days=2)
    retention = Retention(
        min_file_age_hours=1.0,
        categories={"audio_motion": rule(max_gb=1 / 1024, floor_days=0)},
    )

    sweeper(tmp_path, retention).run()

    assert fresh.exists()
    assert not old.exists()


# -- pressure ------------------------------------------------------------


def test_pressure_spreads_across_categories_in_proportion(tmp_path):
    """Two categories over their floors both give, the bigger one more.

    Ceilings are set high so nothing here is ceiling-driven — this is the
    shared disk running low, which is a different question.
    """
    for i in range(40):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)
    for i in range(10):
        make_file(tmp_path, "snapshots", f"s{i}.jpg", size=64 * MB, age_days=300 - i)

    retention = Retention(
        reserve_gb=100.0,
        categories={"timelapses": rule(4000, 90), "snapshots": rule(4000, 90)},
    )
    # 2 GB short of the reserve.
    result = sweeper(tmp_path, retention, free_gb=98.0).run()

    timelapses = result.report["categories"]["timelapses"]["last_sweep"]
    snapshots = result.report["categories"]["snapshots"]["last_sweep"]
    assert timelapses is not None and snapshots is not None
    # timelapses hold 4x what snapshots do, so they carry ~4x the loss.
    ratio = timelapses["bytes_freed"] / snapshots["bytes_freed"]
    assert 3.0 < ratio < 5.0
    assert result.bytes_freed >= 2 * GB


def test_pressure_leaves_a_category_that_is_all_floor_alone(tmp_path):
    """A category with nothing outside its floor contributes nothing."""
    for i in range(40):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)
    protected = make_file(tmp_path, "audio_motion", "recent.flac", size=64 * MB, age_days=2)

    retention = Retention(
        reserve_gb=100.0,
        categories={"timelapses": rule(4000, 90), "audio_motion": rule(4000, 30)},
    )
    result = sweeper(tmp_path, retention, free_gb=99.0).run()

    assert protected.exists()
    assert result.report["categories"]["audio_motion"]["last_sweep"] is None
    assert result.report["categories"]["timelapses"]["last_sweep"]["files_removed"] > 0


def test_pressure_stops_at_the_reserve_rather_than_emptying_the_disk(tmp_path):
    """Free enough and no more — a low disk is not a reason to delete it all."""
    for i in range(60):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)

    freed_so_far = {"bytes": 0}

    def shrinking_disk(_path):
        # 1 GB short at the start; every deletion counts toward closing it.
        return DiskSpace(total_bytes=4000 * GB, free_bytes=int(99 * GB) + freed_so_far["bytes"])

    def remove(path: Path):
        freed_so_far["bytes"] += path.stat().st_size
        path.unlink()

    retention = Retention(reserve_gb=100.0, categories={"timelapses": rule(4000, 90)})
    result = sweeper(tmp_path, retention, disk_space=shrinking_disk, remove=remove).run()

    assert result.bytes_freed >= 1 * GB
    # One round is 512 MB per eligible category; overshoot is bounded by it.
    assert result.bytes_freed < 1 * GB + 2 * PRESSURE_CHUNK_BYTES
    assert result.blocked_under_reserve is False


def test_pressure_with_every_floor_holding_reports_blocked(tmp_path):
    """The one thing the sweep cannot fix: short on disk, nothing eligible."""
    keep = [
        make_file(tmp_path, "audio_motion", f"a{i}.flac", size=64 * MB, age_days=2)
        for i in range(10)
    ]
    retention = Retention(reserve_gb=100.0, categories={"audio_motion": rule(4000, 30)})

    result = sweeper(tmp_path, retention, free_gb=10.0).run()

    assert all(f.exists() for f in keep)
    assert result.blocked_under_reserve is True
    assert result.report["blocked_under_reserve"] is True
    assert result.report["guard_tripped"] is True


def test_unreadable_disk_still_enforces_ceilings(tmp_path):
    """No free-space reading is a reason to skip pressure, not everything."""
    old = make_file(tmp_path, "timelapses", "t.mp4", size=8 * MB, age_days=300)
    retention = Retention(categories={"timelapses": rule(max_gb=1 / 1024, floor_days=90)})

    result = sweeper(tmp_path, retention, disk_space=lambda _p: None).run()

    assert not old.exists()
    assert result.blocked_under_reserve is False
    assert result.report["free_bytes_after"] is None


# -- thresholds ----------------------------------------------------------


def test_reserve_takes_the_stricter_of_bytes_and_percent(tmp_path):
    """Upgrading stations have the percentage set; it must not loosen the guard."""
    retention = Retention(reserve_gb=100.0, min_free_space_percent=10.0, categories={})
    sweep = sweeper(tmp_path, retention)

    # 10% of 4 TB is 400 GB, which is stricter than 100 GB.
    assert sweep.effective_reserve_bytes(DiskSpace(4000 * GB, 500 * GB)) == 400 * GB
    # 10% of 500 GB is 50 GB, which is looser — the byte figure wins.
    assert sweep.effective_reserve_bytes(DiskSpace(500 * GB, 100 * GB)) == 100 * GB


def test_percent_of_limit_reflects_the_post_sweep_size(tmp_path):
    for i in range(10):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=1 * MB, age_days=300 - i)
    retention = Retention(categories={"timelapses": rule(max_gb=5 / 1024, floor_days=30)})

    report = sweeper(tmp_path, retention).run().report

    assert report["categories"]["timelapses"]["bytes"] == 5 * MB
    assert report["categories"]["timelapses"]["percent_of_limit"] == pytest.approx(100.0)


# -- dry run -------------------------------------------------------------


def test_dry_run_decides_everything_and_touches_nothing(tmp_path):
    files = [
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=1 * MB, age_days=300 - i)
        for i in range(10)
    ]
    retention = Retention(categories={"timelapses": rule(max_gb=7 / 1024, floor_days=30)})

    result = sweeper(tmp_path, retention).run(dry_run=True)

    assert all(f.exists() for f in files)
    assert result.files_removed == 3
    assert result.report["dry_run"] is True
    assert result.manifest_path is None


def test_dry_run_under_pressure_terminates(tmp_path):
    """Nothing is freed, so the loop has to advance on its own accounting."""
    for i in range(20):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)
    retention = Retention(reserve_gb=100.0, categories={"timelapses": rule(4000, 90)})

    result = sweeper(tmp_path, retention, free_gb=99.0).run(dry_run=True)

    assert result.files_removed > 0
    assert Path(tmp_path / CATEGORY_DIRS["timelapses"] / "t0.mp4").exists()


# -- what it leaves behind -----------------------------------------------


def test_the_report_states_free_space_before_and_after(tmp_path):
    """The pair is what says what the sweep bought; one number alone does not."""
    for i in range(4):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=8 * MB, age_days=300 - i)
    retention = Retention(categories={"timelapses": rule(max_gb=1 / 1024, floor_days=30)})

    freed = {"bytes": 0}

    def growing_free(_path):
        return DiskSpace(total_bytes=4000 * GB, free_bytes=int(500 * GB) + freed["bytes"])

    def remove(path: Path):
        freed["bytes"] += path.stat().st_size
        path.unlink()

    report = sweeper(tmp_path, retention, disk_space=growing_free, remove=remove).run().report

    assert report["free_bytes_before"] == 500 * GB
    assert report["free_bytes_after"] == 500 * GB + report["bytes_freed"]


def test_manifest_records_what_disappeared(tmp_path):
    make_file(tmp_path, "timelapses", "t0.mp4", size=8 * MB, age_days=300)
    retention = Retention(categories={"timelapses": rule(max_gb=1 / 1024, floor_days=30)})

    result = sweeper(tmp_path, retention).run()

    assert result.manifest_path is not None
    body = result.manifest_path.read_text()
    assert "t0.mp4" in body
    assert result.report["manifest_path"] == str(result.manifest_path)


def test_state_is_published_atomically(tmp_path):
    write_state(tmp_path, {"swept_at": "2026-08-26T12:00:00+00:00", "files_removed": 0})
    assert read_state(tmp_path)["files_removed"] == 0

    write_state(tmp_path, {"swept_at": "2026-08-26T12:15:00+00:00", "files_removed": 7})
    assert read_state(tmp_path)["files_removed"] == 7
    # No temporary files left over from the rename.
    assert not list(tmp_path.glob(".sweep-state-*"))


def test_missing_or_corrupt_state_reads_as_absent(tmp_path):
    assert read_state(tmp_path) is None
    (tmp_path / ".storage-sweep-state.json").write_text("{ not json")
    assert read_state(tmp_path) is None


def test_scan_skips_a_file_that_vanishes_mid_walk(tmp_path):
    make_file(tmp_path, "timelapses", "t0.mp4", size=1024, age_days=1)
    files = scan_category(tmp_path / CATEGORY_DIRS["timelapses"])
    assert [f.path.name for f in files] == ["t0.mp4"]
    assert scan_category(tmp_path / "nope") == []


def test_a_file_removed_by_something_else_is_not_counted_as_freed(tmp_path):
    """A recording that rolls over mid-sweep must not inflate bytes_freed."""
    make_file(tmp_path, "timelapses", "t0.mp4", size=8 * MB, age_days=300)
    retention = Retention(categories={"timelapses": rule(max_gb=1 / 1024, floor_days=30)})

    def vanish(path: Path):
        raise FileNotFoundError(path)

    result = sweeper(tmp_path, retention, remove=vanish).run()

    assert result.files_removed == 0
    assert result.bytes_freed == 0


# -- the command ---------------------------------------------------------


@pytest.fixture
def station(tmp_path, monkeypatch):
    """A data root the command will find, with config pointing at it.

    The disk is stubbed roomy. Without it these tests measure the free space of
    whatever machine is running them: a laptop with a terabyte spare passes, a
    CI runner with 14 GB is under the 100 GB reserve before the first file is
    written, so every one of them exits EXIT_BLOCKED. A test of the command's
    exit codes has no business depending on the host's disk. The one test that
    wants pressure patches this again with its own numbers.
    """
    from orpheus_common import config as config_module
    from orpheus_common.storage import sweep as sweep_module

    retention = Retention(
        reserve_gb=100.0,
        categories={"timelapses": rule(max_gb=1 / 1024, floor_days=30)},
    )

    class Storage:
        def __init__(self):
            self.retention = retention

    class Config:
        storage = Storage()

    monkeypatch.setattr(
        config_module.OrpheusConfig, "get_instance", classmethod(lambda cls: Config())
    )
    monkeypatch.setattr(
        "orpheus_common.storage.paths.get_data_root", lambda: tmp_path, raising=True
    )
    monkeypatch.setattr(
        sweep_module, "read_disk_space", lambda _p: DiskSpace(4000 * GB, 2000 * GB)
    )
    monkeypatch.setenv("ORPHEUS_DATA_ROOT", str(tmp_path))
    return tmp_path, retention


def test_first_run_is_report_only(station, capsys):
    """A fresh install says what it would do before it does it."""
    from orpheus_common.storage.sweep import main

    root, _ = station
    doomed = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    assert main([]) == EXIT_OK

    assert doomed.exists(), "the first sweep after install must delete nothing"
    state = read_state(root)
    assert state["report_only"] is True
    assert state["files_removed"] == 1
    assert state["installed_at"]


def test_the_second_run_inside_the_grace_still_reports_only(station):
    from orpheus_common.storage.sweep import main

    root, _ = station
    doomed = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main([])
    main([])

    assert doomed.exists()
    assert read_state(root)["report_only"] is True


def test_force_ends_the_grace(station):
    from orpheus_common.storage.sweep import main

    root, _ = station
    doomed = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main([])
    assert doomed.exists()

    assert main(["--force"]) == EXIT_OK
    assert not doomed.exists()
    assert read_state(root)["report_only"] is False


def test_force_ends_the_grace_for_good_not_for_one_run(station):
    """The next timer tick must not quietly revert to report-only."""
    from orpheus_common.storage.sweep import main

    root, _ = station
    make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main([])
    main(["--force"])

    later = make_file(root, "timelapses", "t1.mp4", size=8 * MB, age_days=300)
    assert main([]) == EXIT_OK

    assert not later.exists()
    assert read_state(root)["report_only"] is False


def test_enforcement_begins_once_the_grace_expires(station):
    from orpheus_common.storage.sweep import main

    root, _ = station
    doomed = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main([])
    state = read_state(root)
    state["installed_at"] = (datetime.now().astimezone() - timedelta(hours=48)).isoformat()
    write_state(root, state)

    assert main([]) == EXIT_OK
    assert not doomed.exists()


def test_the_report_says_the_grace_ended_once_it_has(station):
    """The field is what an operator checks to see whether deletion is live.

    It used to be set only by --force, so a station that had aged out of the
    window and was deleting normally published `grace_ended: false` forever.
    """
    from orpheus_common.storage.sweep import main

    root, _ = station

    main([])
    assert read_state(root)["grace_ended"] is False, "still inside the window"

    state = read_state(root)
    state["installed_at"] = (datetime.now().astimezone() - timedelta(hours=48)).isoformat()
    write_state(root, state)

    assert main([]) == EXIT_OK
    published = read_state(root)
    assert published["grace_ended"] is True
    assert published["report_only"] is False


def test_disabling_the_sweep_still_publishes_measurements(station):
    """Switching deletion off must not blind the dashboard."""
    from orpheus_common.storage.sweep import main

    root, retention = station
    retention.sweep_enabled = False
    retention.first_run_grace_hours = 0.0
    kept = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    assert main([]) == EXIT_OK

    assert kept.exists()
    state = read_state(root)
    assert state["sweep_enabled"] is False
    assert state["survey"]["categories"]["timelapses"]["bytes"] == 8 * MB


def test_dry_run_does_not_overwrite_the_published_report(station):
    """`make storage-report` is a read; it must not disturb what the panel shows."""
    from orpheus_common.storage.sweep import main

    root, retention = station
    retention.first_run_grace_hours = 0.0
    make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main([])
    published = read_state(root)["swept_at"]

    assert main(["--dry-run"]) == EXIT_OK
    assert read_state(root)["swept_at"] == published


def test_blocked_under_reserve_exits_nonzero(station, monkeypatch):
    """systemd should show this red — it needs a person."""
    from orpheus_common.storage import sweep as sweep_module

    root, retention = station
    retention.first_run_grace_hours = 0.0
    retention.categories = {"timelapses": rule(4000, 90)}
    make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=2)
    monkeypatch.setattr(sweep_module, "read_disk_space", lambda _p: DiskSpace(4000 * GB, 10 * GB))

    assert sweep_module.main([]) == EXIT_BLOCKED


def test_json_output_is_the_published_report(station, capsys):
    from orpheus_common.storage.sweep import main

    root, retention = station
    retention.first_run_grace_hours = 0.0
    make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    main(["--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["data_root"] == str(root)
    assert payload["categories"]["timelapses"]["last_sweep"]["files_removed"] == 1


def test_a_second_enforcing_sweep_backs_off(station):
    """The lock is what stops two sweeps planning against each other."""
    from orpheus_common.storage import sweep as sweep_module

    root, retention = station
    retention.first_run_grace_hours = 0.0
    doomed = make_file(root, "timelapses", "t0.mp4", size=8 * MB, age_days=300)

    holder = sweep_module._acquire_lock(root)
    assert holder is not None
    try:
        assert sweep_module.main([]) == EXIT_OK
        assert doomed.exists(), "the blocked sweep must not delete"
    finally:
        holder.close()

    assert sweep_module.main([]) == EXIT_OK
    assert not doomed.exists()


# -- the runaway cases ---------------------------------------------------
#
# Each of these was a real defect found in review, and each one deletes far
# more than the design permits. They are grouped because they share a shape:
# the sweep is chasing a number that is not responding to what it deletes,
# and its only stopping condition was an empty pool.


def test_pressure_stops_when_deleting_stops_returning_space(tmp_path):
    """A disk that will not respond must cost a few rounds, not the archive.

    The loop's only convergence test used to be "is free space above the
    reserve" and its only stall test "did this round free bytes". Both are
    satisfied forever by a writer refilling as fast as the sweep deletes, so
    the sweep worked through every recording above every floor in one pass.
    """
    survivors = [
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)
        for i in range(200)
    ]

    def frozen_disk(_path):
        # Deleting changes nothing: something else is taking the space back.
        return DiskSpace(total_bytes=4000 * GB, free_bytes=int(50 * GB))

    retention = Retention(reserve_gb=100.0, categories={"timelapses": rule(4000, 90)})
    result = sweeper(tmp_path, retention, disk_space=frozen_disk).run()

    assert result.blocked_under_reserve is True, "a disk that will not recover must be reported"
    # Bounded by the stall detector: a handful of rounds, not the whole pool.
    assert result.bytes_freed <= 4 * PRESSURE_CHUNK_BYTES
    remaining = [f for f in survivors if f.exists()]
    assert len(remaining) > 150, f"only {len(remaining)} of 200 recordings survived"


def test_a_category_symlinked_off_the_data_root_is_never_touched(tmp_path):
    """A second drive symlinked into place is not ours to delete from.

    Deleting there also never returns space to the disk that was full, so the
    pressure loop would keep taking from it round after round.
    """
    elsewhere = tmp_path / "other_drive" / "timelapses"
    elsewhere.mkdir(parents=True)
    archived = elsewhere / "precious.mp4"
    with open(archived, "wb") as handle:
        handle.truncate(64 * MB)
    stamp = (NOW - timedelta(days=900)).timestamp()
    os.utime(archived, (stamp, stamp))

    root = tmp_path / "dataroot"
    (root / "video").mkdir(parents=True)
    (root / "video" / "timelapses").symlink_to(elsewhere, target_is_directory=True)

    retention = Retention(reserve_gb=100.0, categories={"timelapses": rule(0.001, 1)})
    result = StorageSweep(
        root, retention, disk_space=disk(10.0), now=lambda: NOW
    ).run()

    assert archived.exists(), "the sweep deleted a file outside the data root"
    assert result.bytes_freed == 0
    assert "timelapses" not in result.report["categories"]


def test_an_empty_category_is_not_reported_as_held_back_by_its_floor(tmp_path):
    """floor_blocked drives a panel note that would be false about nothing.

    The note reads "over its ceiling, but everything it still holds is inside
    the floor", and an operator lowers floor_days because of it.
    """
    make_file(tmp_path, "audio_motion", "a.flac", size=64 * MB, age_days=2)
    retention = Retention(
        reserve_gb=100.0,
        categories={"audio_motion": rule(4000, 30), "timelapses": rule(4000, 90)},
    )

    result = sweeper(tmp_path, retention, free_gb=10.0).run()

    assert result.blocked_under_reserve is True
    assert result.report["categories"]["audio_motion"]["floor_blocked"] is True
    assert result.report["categories"]["timelapses"]["floor_blocked"] is False


def test_a_sweep_that_deleted_nothing_publishes_a_forecast_not_a_history(tmp_path):
    """The panel spent the whole grace window reporting deletions that never happened."""
    for i in range(20):
        make_file(tmp_path, "timelapses", f"t{i}.mp4", size=64 * MB, age_days=300 - i)

    retention = Retention(categories={"timelapses": rule(0.5, 90)})
    result = sweeper(tmp_path, retention).run(dry_run=True)

    block = result.report["categories"]["timelapses"]
    assert block["last_sweep"] is None, "a sweep that deleted nothing must not report a deletion"
    assert block["would_remove"]["files_removed"] > 0
    # And the size shown is what the category still holds, not what it would
    # hold — the bar and the number beside it used to disagree.
    assert block["bytes"] == result.report["survey"]["categories"]["timelapses"]["bytes"]
