"""Tests for the whole-data-root size survey.

The survey exists because cleanup only knows about directories it trims,
and the directories nothing trims are the ones that quietly get large. So
these assert that it measures everything it is pointed at, regardless of
whether any policy applies to it.
"""

from __future__ import annotations

import os
from pathlib import Path

from orpheus_common.storage.cleanup import DiskSpace
from orpheus_common.storage.usage import (
    DATA_ROOT_CATEGORIES,
    measure_directory,
    survey_data_root,
)

GB = 1024**3


def _write(path: Path, size_bytes: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size_bytes)
    return path


def _disk(free_percent: float, total_gb: float = 1000.0):
    total = int(total_gb * GB)
    return lambda _path: DiskSpace(total_bytes=total, free_bytes=int(total * free_percent / 100))


class TestMeasureDirectory:
    def test_sums_sizes_and_counts_files(self, tmp_path):
        _write(tmp_path / "a.wav", 100)
        _write(tmp_path / "b.wav", 250)

        assert measure_directory(tmp_path) == (350, 2)

    def test_descends_into_the_date_and_sensor_directories(self, tmp_path):
        """Recordings are filed under sensor/date, so a flat walk would read 0."""
        _write(tmp_path / "1" / "2026-08-25" / "clip.wav", 500)
        _write(tmp_path / "2" / "2026-08-25" / "clip.wav", 700)

        assert measure_directory(tmp_path) == (1200, 2)

    def test_a_missing_directory_is_zero_not_an_error(self, tmp_path):
        """A station that has recorded no timelapses genuinely holds none."""
        assert measure_directory(tmp_path / "never-created") == (0, 0)

    def test_an_empty_directory_is_zero(self, tmp_path):
        (tmp_path / "empty").mkdir()

        assert measure_directory(tmp_path / "empty") == (0, 0)

    def test_does_not_follow_symlinked_directories(self, tmp_path):
        """Otherwise a link into the data root double-counts, or loops forever."""
        real = tmp_path / "real"
        _write(real / "clip.wav", 100)
        link = tmp_path / "surveyed" / "link"
        link.parent.mkdir(parents=True)
        os.symlink(real, link)

        assert measure_directory(tmp_path / "surveyed") == (0, 0)

    def test_survives_a_file_deleted_mid_walk(self, tmp_path):
        """A cleanup pass can be deleting from the directory being surveyed."""
        _write(tmp_path / "keep.wav", 100)
        vanishing = _write(tmp_path / "gone.wav", 100)
        vanishing.unlink()

        total, count = measure_directory(tmp_path)
        assert (total, count) == (100, 1)

    def test_an_unreadable_subdirectory_does_not_abort_the_survey(self, tmp_path):
        _write(tmp_path / "readable" / "clip.wav", 100)
        locked = tmp_path / "locked"
        locked.mkdir()
        _write(locked / "hidden.wav", 999)
        os.chmod(locked, 0o000)
        try:
            total, count = measure_directory(tmp_path)
            # The readable half is still reported rather than losing everything.
            assert total >= 100 and count >= 1
        finally:
            os.chmod(locked, 0o755)


class TestSurveyDataRoot:
    def test_measures_every_category_including_the_unmanaged_ones(self, tmp_path):
        _write(tmp_path / "audio/audio_motion/1/a.wav", 100)
        _write(tmp_path / "video/video_motion/cam/b.mp4", 200)
        _write(tmp_path / "video/snapshots/cam/c.jpg", 300)
        _write(tmp_path / "video/timelapses/2026.08.25/d.mp4", 400)
        _write(tmp_path / "detections/orpheus.db", 500)

        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=40))
        sizes = {key: value["bytes"] for key, value in result["categories"].items()}

        assert sizes == {
            "audio_motion": 100,
            "video_motion": 200,
            "snapshots": 300,
            "timelapses": 400,
            "database": 500,
        }

    def test_reports_a_category_that_does_not_exist_yet(self, tmp_path):
        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=40))

        timelapses = result["categories"]["timelapses"]
        assert timelapses["bytes"] == 0
        assert timelapses["exists"] is False

    def test_carries_the_path_it_actually_measured(self, tmp_path):
        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=40))

        assert result["categories"]["timelapses"]["path"] == str(
            tmp_path / "video/timelapses"
        )

    def test_carries_a_label_and_description_for_each_category(self, tmp_path):
        """These are shown next to the size, so they travel with it."""
        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=40))

        for spec in DATA_ROOT_CATEGORIES:
            entry = result["categories"][spec.key]
            assert entry["label"] == spec.label
            assert entry["description"] == spec.description

    def test_stamps_the_survey_with_when_it_ran(self, tmp_path):
        """Freshness is the difference between a number and a stale number."""
        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=40))

        assert result["measured_at"]
        assert result["data_root"] == str(tmp_path)

    def test_reads_the_disk_the_categories_share(self, tmp_path):
        result = survey_data_root(tmp_path, disk_space=_disk(free_percent=23.4))

        assert result["disk"]["total_bytes"] == 1000 * GB
        assert result["disk"]["free_percent"] == 23.4

    def test_an_unreadable_disk_reports_none_rather_than_a_made_up_number(self, tmp_path):
        result = survey_data_root(tmp_path, disk_space=lambda _path: None)

        assert result["disk"]["total_bytes"] is None
        assert result["disk"]["free_bytes"] is None
        assert result["disk"]["free_percent"] is None
