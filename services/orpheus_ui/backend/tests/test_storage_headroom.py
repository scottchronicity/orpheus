"""Tests for the per-category storage headroom payload.

Two separate questions, and the tests hold them apart: what is each kind of
recording using, and which of those get trimmed automatically. Size is known
for everything under the data root; a ceiling exists for only some of it. The
rest is honesty — never a zero standing in for "not measured", never a
percentage for a directory that has no ceiling, and never silence when
nothing is deleting.

The input is now one report from orpheus-storage-sweep rather than one per
agent, because there is one deleter now.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from orpheus_ui.storage_categories import build_headroom_payload

GB = 1024**3


def _config(min_free_space_percent: float = 10.0, sweep_interval_minutes: float = 15.0):
    """A stand-in for OrpheusConfig carrying only what the builder reads."""
    return SimpleNamespace(
        storage=SimpleNamespace(
            retention=SimpleNamespace(
                min_free_space_percent=min_free_space_percent,
                sweep_interval_minutes=sweep_interval_minutes,
            )
        )
    )


def _fresh(minutes_ago: float = 1.0) -> str:
    """A timestamp a sweep would have written that recently.

    Relative rather than fixed: the panel now decides whether a report is
    current by comparing it against the sweep cadence, so a hard-coded stamp
    would age into "stale" and quietly change what these tests assert.
    """
    return (datetime.now().astimezone() - timedelta(minutes=minutes_ago)).isoformat()


def _survey(measured_at=None, disk=None, **category_bytes):
    measured_at = measured_at if measured_at is not None else _fresh()
    """A whole-data-root survey, shaped as survey_data_root() emits it."""
    defaults = {
        "audio_motion": 60 * GB,
        "video_motion": 30 * GB,
        "snapshots": 12 * GB,
        "timelapses": 296 * GB,
        "database": 3 * GB,
    }
    defaults.update(category_bytes)

    return {
        "measured_at": measured_at,
        "data_root": "/data/orpheus",
        "categories": {
            key: {
                "path": f"/data/orpheus/{key}",
                "label": key,
                "description": key,
                "bytes": value,
                "file_count": 100,
                "exists": True,
            }
            for key, value in defaults.items()
        },
        "disk": disk
        if disk is not None
        else {"total_bytes": 1000 * GB, "free_bytes": 400 * GB, "free_percent": 40.0},
    }


def _swept(limit_gb=600, floor_days=30, percent=10.0, **overrides):
    """One category's block of the sweep report."""
    base = {
        "path": "/data/orpheus/audio/audio_motion",
        "limit_bytes": limit_gb * GB,
        "bytes": 60 * GB,
        "percent_of_limit": percent,
        "trigger_percent": 100.0,
        "floor_days": floor_days,
        "over_ceiling": False,
        "floor_blocked": False,
        "last_sweep": None,
    }
    base.update(overrides)
    return base


def _report(survey=None, categories=None, **overrides):
    """The state file orpheus-storage-sweep publishes after every run."""
    base = {
        "swept_at": _fresh(),
        "data_root": "/data/orpheus",
        "dry_run": False,
        "sweep_enabled": True,
        "report_only": False,
        "reserve_bytes": 100 * GB,
        "free_bytes_before": 400 * GB,
        "free_bytes_after": 400 * GB,
        "guard_tripped": False,
        "blocked_under_reserve": False,
        "files_removed": 0,
        "bytes_freed": 0,
        "manifest_path": None,
        "categories": categories
        if categories is not None
        else {
            "audio_motion": _swept(600, 30),
            "video_motion": _swept(60, 90),
            "snapshots": _swept(450, 90),
            "timelapses": _swept(450, 90),
        },
        "survey": survey if survey is not None else _survey(),
    }
    base.update(overrides)
    return base


def _build(report, config=None, root="/data/orpheus"):
    cfg = config if config is not None else _config()
    with (
        patch("orpheus_ui.storage_categories.OrpheusConfig") as mock_cls,
        patch("orpheus_ui.storage_categories.get_data_root", return_value=Path(root)),
    ):
        mock_cls.get_instance.return_value = cfg
        return build_headroom_payload(report)


def _category(payload, key):
    return next(c for c in payload["categories"] if c["key"] == key)


class TestCoverage:
    def test_every_category_under_the_data_root_is_reported(self):
        """Including the ones nothing cleans — those are the ones that surprise."""
        payload = _build(_report())

        keys = [c["key"] for c in payload["categories"]]
        assert keys == [
            "audio_motion",
            "video_motion",
            "snapshots",
            "timelapses",
            "database",
        ]

    def test_the_largest_directory_now_carries_a_ceiling(self):
        """The bug this guards: 296 GB of timelapses with nothing trimming them."""
        timelapses = _category(_build(_report()), "timelapses")

        assert timelapses["bytes"] == 296 * GB
        assert timelapses["measured"] is True
        assert timelapses["has_policy"] is True
        assert timelapses["limit_bytes"] == 450 * GB

    def test_the_database_is_measured_but_not_swept(self):
        """Database retention is a different mechanism; do not imply otherwise."""
        database = _category(_build(_report()), "database")

        assert database["bytes"] == 3 * GB
        assert database["has_policy"] is False

    def test_size_is_reported_for_categories_with_and_without_a_ceiling(self):
        payload = _build(_report())

        assert all(c["measured"] for c in payload["categories"])
        assert all(c["bytes"] is not None for c in payload["categories"])

    def test_every_recording_category_is_swept(self):
        """The whole point of one deleter: no recording directory is left out."""
        payload = _build(_report())

        with_policy = {c["key"] for c in payload["categories"] if c["has_policy"]}
        assert with_policy == {"audio_motion", "video_motion", "snapshots", "timelapses"}


class TestSizes:
    def test_carries_the_surveyed_sizes_through(self):
        audio = _category(_build(_report()), "audio_motion")

        assert audio["bytes"] == 60 * GB
        assert audio["file_count"] == 100

    def test_uses_the_surveyed_path_over_our_reconstruction_of_it(self):
        assert _category(_build(_report()), "timelapses")["path"] == "/data/orpheus/timelapses"

    def test_falls_back_to_the_data_root_when_nothing_has_surveyed(self):
        payload = _build(None, root="/srv/orpheus")

        assert _category(payload, "timelapses")["path"] == str(
            Path("/srv/orpheus") / "video/timelapses"
        )

    def test_an_unswept_station_reports_no_size_rather_than_zero(self):
        """Zero bytes reads as "empty"; the truth is "nothing has measured"."""
        payload = _build(None)

        for cat in payload["categories"]:
            assert cat["measured"] is False
            assert cat["bytes"] is None
            assert cat["file_count"] is None

    def test_a_genuinely_empty_directory_reports_zero_not_unknown(self):
        """Zero and unknown are different facts and must not collapse."""
        timelapses = _category(_build(_report(survey=_survey(timelapses=0))), "timelapses")

        assert timelapses["measured"] is True
        assert timelapses["bytes"] == 0

    def test_no_survey_means_no_timestamp_rather_than_now(self):
        assert _build(None)["measured_at"] is None

    def test_serves_the_cadence_so_a_stale_reading_reads_as_expected(self):
        payload = _build(None, config=_config(sweep_interval_minutes=30))

        assert payload["check_interval_hours"] == 0.5


class TestPolicy:
    def test_a_swept_category_carries_its_ceiling_and_floor(self):
        audio = _category(_build(_report()), "audio_motion")

        assert audio["policy_kind"] == "size_budget"
        assert audio["limit_bytes"] == 600 * GB
        assert audio["percent_of_limit"] == 10.0
        assert audio["trigger_percent"] == 100.0
        assert audio["retention_days"] == 30

    def test_a_ceiling_and_a_floor_are_both_reported_for_the_same_category(self):
        """They pull in opposite directions; showing one alone misleads."""
        video = _category(_build(_report()), "video_motion")

        assert video["limit_bytes"] == 60 * GB
        assert video["retention_days"] == 90

    def test_an_unswept_category_carries_no_policy_fields(self):
        """No ceiling exists, so inventing one as a percentage would be a lie."""
        database = _category(_build(_report()), "database")

        assert database["policy_kind"] is None
        assert database["limit_bytes"] is None
        assert database["percent_of_limit"] is None
        assert database["trigger_percent"] is None
        assert database["retention_days"] is None
        assert database["policy_note"] is None

    def test_a_healthy_category_carries_no_note(self):
        """A note is for what the numbers cannot say; usually there is nothing."""
        assert _category(_build(_report()), "audio_motion")["policy_note"] is None

    def test_a_ceiling_the_floor_will_not_let_it_reach_is_explained(self):
        """Otherwise the panel shows a category parked over its limit, unexplained."""
        report = _report(
            categories={
                "audio_motion": _swept(
                    600, 30, percent=140.0, over_ceiling=True, floor_blocked=True
                )
            }
        )
        audio = _category(_build(report), "audio_motion")

        assert audio["policy_note"] is not None
        assert "600 GiB" in audio["policy_note"]
        assert "30-day floor" in audio["policy_note"]

    def test_reports_the_window_of_recording_the_last_sweep_removed(self):
        report = _report(
            categories={
                "audio_motion": _swept(
                    600,
                    30,
                    last_sweep={
                        "files_removed": 812,
                        "bytes_freed": 4 * GB,
                        "oldest_removed": "2026-05-02T01:00:00+00:00",
                        "newest_removed": "2026-05-04T23:00:00+00:00",
                    },
                )
            }
        )
        sweep = _category(_build(report), "audio_motion")["last_sweep"]

        assert sweep["files_removed"] == 812
        assert sweep["oldest_removed"] == "2026-05-02T01:00:00+00:00"
        # The run's timestamp is what makes the counts legible.
        assert sweep["at"] == report["swept_at"]

    def test_a_sweep_that_removed_nothing_reports_no_last_sweep(self):
        assert _category(_build(_report()), "audio_motion")["last_sweep"] is None


class TestSweepState:
    """Whether anything is actually deleting — the question the old panel could
    not answer, above an arrangement where nothing trimmed the largest
    directory on the disk."""

    def test_a_running_sweep_reads_as_enforcing(self):
        assert _build(_report())["sweep_state"] == "enforcing"

    def test_the_first_run_grace_is_visible(self):
        assert _build(_report(report_only=True))["sweep_state"] == "report_only"

    def test_a_disabled_sweep_is_visible(self):
        assert _build(_report(sweep_enabled=False))["sweep_state"] == "disabled"

    def test_a_sweep_that_has_never_run_is_visible(self):
        assert _build(None)["sweep_state"] == "never_run"

    def test_a_sweep_that_has_stopped_reads_as_stale(self):
        """The failure the panel most needs to catch and could not show.

        The report only changes when a sweep succeeds, so a dead timer leaves
        its last good report in place and the panel went on rendering it as
        'enforcing' — bars, percentages and byte counts, all indefinitely old,
        on a station where nothing else deletes recordings.
        """
        old = _fresh(minutes_ago=60 * 24 * 7)
        payload = _build(_report(survey=_survey(measured_at=old), swept_at=old))

        assert payload["sweep_state"] == "stale"

    def test_one_missed_tick_is_not_stale(self):
        """A slow walk or a reboot is not a fault; amber that cries wolf gets ignored."""
        recent = _fresh(minutes_ago=20)
        payload = _build(_report(survey=_survey(measured_at=recent), swept_at=recent))

        assert payload["sweep_state"] == "enforcing"


class TestFilesystem:
    def test_takes_the_disk_reading_from_the_survey(self):
        fs = _build(_report())["filesystem"]

        assert fs["total_bytes"] == 1000 * GB
        assert fs["free_bytes"] == 400 * GB
        assert fs["free_percent"] == 40.0

    def test_reports_the_reserve_in_bytes_because_that_is_the_runway(self):
        fs = _build(_report())["filesystem"]

        assert fs["reserve_bytes"] == 100 * GB
        assert fs["guard_enabled"] is True

    def test_a_tripped_guard_comes_from_the_sweep(self):
        fs = _build(_report(guard_tripped=True))["filesystem"]

        assert fs["guard_tripped"] is True
        assert fs["blocked_under_reserve"] is False

    def test_short_on_disk_with_every_floor_holding_is_its_own_state(self):
        """Tripped means low; blocked means low and nothing may be deleted."""
        fs = _build(_report(guard_tripped=True, blocked_under_reserve=True))["filesystem"]

        assert fs["blocked_under_reserve"] is True

    def test_reports_no_disk_reading_when_nothing_has_swept(self):
        fs = _build(None)["filesystem"]

        assert fs["total_bytes"] is None
        assert fs["free_percent"] is None
        assert fs["reserve_bytes"] is None
        assert fs["guard_enabled"] is False

    def test_the_configured_percentage_is_still_reported(self):
        """Operators upgrading from the per-agent arrangement have it set."""
        fs = _build(_report(), config=_config(min_free_space_percent=25))["filesystem"]

        assert fs["min_free_space_percent"] == 25

    def test_a_zero_reserve_means_the_guard_is_off(self):
        fs = _build(_report(reserve_bytes=0))["filesystem"]

        assert fs["guard_enabled"] is False

    def test_an_unreadable_disk_reports_none_rather_than_a_made_up_number(self):
        survey = _survey(disk={"total_bytes": None, "free_bytes": None, "free_percent": None})
        fs = _build(_report(survey=survey))["filesystem"]

        assert fs["total_bytes"] is None
        assert fs["free_percent"] is None
