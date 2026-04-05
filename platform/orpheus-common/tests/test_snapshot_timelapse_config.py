"""Tests for snapshot and timelapse configuration classes."""

import pytest

from orpheus_common.config import (
    Camera,
    ConfigError,
    SnapshotConfig,
    TimelapseConfig,
)


class TestSnapshotConfig:
    """Tests for SnapshotConfig dataclass."""

    def test_from_dict_with_interval(self) -> None:
        """SnapshotConfig should parse interval from dict."""
        data = {"interval": "1h"}
        config = SnapshotConfig.from_dict(data)
        assert config.interval == "1h"

    def test_from_dict_defaults_to_zero(self) -> None:
        """SnapshotConfig should default to '0' when interval not provided."""
        config = SnapshotConfig.from_dict({})
        assert config.interval == "0"

    def test_from_dict_handles_none_as_zero(self) -> None:
        """SnapshotConfig should treat None interval as '0'."""
        data = {"interval": None}
        config = SnapshotConfig.from_dict(data)
        assert config.interval == "0"

    def test_from_dict_converts_to_string(self) -> None:
        """SnapshotConfig should convert interval to string."""
        data = {"interval": 30}
        config = SnapshotConfig.from_dict(data)
        assert config.interval == "30"


class TestTimelapseConfig:
    """Tests for TimelapseConfig dataclass."""

    def test_from_dict_with_all_fields(self) -> None:
        """TimelapseConfig should parse all fields from dict."""
        data = {
            "label": "custom",
            "start_time": "14:30",
            "lookback_window": "48h",
            "sampling_interval": "30m",
            "retention_days": 30,
            "clip_duration": 1.5,
        }
        config = TimelapseConfig.from_dict(data)
        assert config.label == "custom"
        assert config.start_time == "14:30"
        assert config.lookback_window == "48h"
        assert config.sampling_interval == "30m"
        assert config.retention_days == 30
        assert config.clip_duration == 1.5

    def test_from_dict_requires_label(self) -> None:
        """TimelapseConfig should raise ConfigError when label is missing."""
        with pytest.raises(ConfigError, match="missing required 'label'"):
            TimelapseConfig.from_dict({})
        with pytest.raises(ConfigError, match="missing required 'label'"):
            TimelapseConfig.from_dict({"label": ""})
        with pytest.raises(ConfigError, match="missing required 'label'"):
            TimelapseConfig.from_dict({"label": "  "})

    def test_from_dict_uses_defaults(self) -> None:
        """TimelapseConfig should use default values when not provided."""
        config = TimelapseConfig.from_dict({"label": "test"})
        assert config.label == "test"
        assert config.start_time == "00:00"
        assert config.lookback_window == "24h"
        assert config.sampling_interval == "15m"
        assert config.retention_days == 90
        assert config.clip_duration == 2.0

    def test_from_dict_validates_time_format(self) -> None:
        """TimelapseConfig should validate HH:MM format."""
        invalid_times = ["25:00", "12:60", "1:30", "12:3", "not-a-time"]
        for time_str in invalid_times:
            with pytest.raises(ConfigError, match="Invalid start_time format"):
                TimelapseConfig.from_dict({"label": "test", "start_time": time_str})

    def test_from_dict_accepts_valid_times(self) -> None:
        """TimelapseConfig should accept valid HH:MM times."""
        valid_times = ["00:00", "12:00", "23:59", "09:30"]
        for time_str in valid_times:
            config = TimelapseConfig.from_dict({"label": "test", "start_time": time_str})
            assert config.start_time == time_str

    def test_from_dict_validates_lookback_window(self) -> None:
        """TimelapseConfig should validate lookback_window format."""
        with pytest.raises(ConfigError, match="Invalid lookback_window format"):
            TimelapseConfig.from_dict({"label": "test", "lookback_window": "invalid"})
        with pytest.raises(ConfigError, match="Invalid lookback_window format"):
            TimelapseConfig.from_dict({"label": "test", "lookback_window": "24"})

    def test_from_dict_validates_sampling_interval(self) -> None:
        """TimelapseConfig should validate sampling_interval format."""
        with pytest.raises(ConfigError, match="Invalid sampling_interval format"):
            TimelapseConfig.from_dict({"label": "test", "sampling_interval": "invalid"})
        with pytest.raises(ConfigError, match="Invalid sampling_interval format"):
            TimelapseConfig.from_dict({"label": "test", "sampling_interval": "15"})

    def test_from_dict_validates_retention_days(self) -> None:
        """TimelapseConfig should reject invalid retention_days values."""
        with pytest.raises(ConfigError, match="retention_days must be >= 1"):
            TimelapseConfig.from_dict({"label": "test", "retention_days": 0})
        with pytest.raises(ConfigError, match="retention_days must be >= 1"):
            TimelapseConfig.from_dict({"label": "test", "retention_days": -1})

    def test_from_dict_validates_clip_duration(self) -> None:
        """TimelapseConfig should reject invalid clip_duration values."""
        with pytest.raises(ConfigError, match="clip_duration must be > 0"):
            TimelapseConfig.from_dict({"label": "test", "clip_duration": 0})
        with pytest.raises(ConfigError, match="clip_duration must be > 0"):
            TimelapseConfig.from_dict({"label": "test", "clip_duration": -1.0})

    def test_from_dict_default_timezone_is_utc(self) -> None:
        """TimelapseConfig should default to UTC timezone."""
        config = TimelapseConfig.from_dict({"label": "test"})
        assert config.timezone == "UTC"

    def test_from_dict_accepts_valid_timezones(self) -> None:
        """TimelapseConfig should accept valid timezone values."""
        valid_timezones = ["UTC", "local", "America/Los_Angeles", "Europe/London"]
        for tz in valid_timezones:
            config = TimelapseConfig.from_dict({"label": "test", "timezone": tz})
            assert config.timezone == tz

    def test_from_dict_rejects_invalid_timezone(self) -> None:
        """TimelapseConfig should reject invalid timezone values."""
        with pytest.raises(ConfigError, match="Invalid timezone"):
            TimelapseConfig.from_dict({"label": "test", "timezone": "NotATimezone123"})

    def test_from_dict_with_all_fields_including_timezone(self) -> None:
        """TimelapseConfig should parse all fields including timezone."""
        data = {
            "label": "custom",
            "start_time": "14:30",
            "lookback_window": "48h",
            "sampling_interval": "30m",
            "retention_days": 60,
            "clip_duration": 1.5,
            "timezone": "America/New_York",
        }
        config = TimelapseConfig.from_dict(data)
        assert config.label == "custom"
        assert config.start_time == "14:30"
        assert config.lookback_window == "48h"
        assert config.sampling_interval == "30m"
        assert config.retention_days == 60
        assert config.clip_duration == 1.5
        assert config.timezone == "America/New_York"


class TestCameraWithSnapshotsAndTimelapses:
    """Tests for Camera dataclass with snapshots and timelapses."""

    def test_camera_without_snapshots_or_timelapses(self) -> None:
        """Camera should work without snapshots or timelapses."""
        data = {"type": "amcrest", "host": "192.168.1.100"}
        camera = Camera.from_dict("test", data)
        assert camera.name == "test"
        assert camera.snapshots is None
        assert camera.timelapses is None

    def test_camera_with_snapshots(self) -> None:
        """Camera should parse snapshots configuration."""
        data = {
            "type": "amcrest",
            "host": "192.168.1.100",
            "snapshots": {"interval": "30m"},
        }
        camera = Camera.from_dict("test", data)
        assert camera.snapshots is not None
        assert camera.snapshots.interval == "30m"

    def test_camera_with_single_timelapse(self) -> None:
        """Camera should parse single timelapse configuration."""
        data = {
            "type": "amcrest",
            "host": "192.168.1.100",
            "timelapses": [
                {
                    "label": "half-day",
                    "start_time": "08:00",
                    "lookback_window": "12h",
                    "sampling_interval": "30m",
                }
            ],
        }
        camera = Camera.from_dict("test", data)
        assert camera.timelapses is not None
        assert len(camera.timelapses) == 1
        assert camera.timelapses[0].label == "half-day"
        assert camera.timelapses[0].start_time == "08:00"
        assert camera.timelapses[0].lookback_window == "12h"
        assert camera.timelapses[0].sampling_interval == "30m"

    def test_camera_with_multiple_timelapses(self) -> None:
        """Camera should parse multiple timelapse configurations."""
        data = {
            "type": "amcrest",
            "host": "192.168.1.100",
            "timelapses": [
                {"label": "daily", "start_time": "00:00", "lookback_window": "24h"},
                {
                    "label": "long-view",
                    "start_time": "12:00",
                    "lookback_window": "48h",
                    "sampling_interval": "1h",
                    "clip_duration": 1.0,
                },
            ],
        }
        camera = Camera.from_dict("test", data)
        assert camera.timelapses is not None
        assert len(camera.timelapses) == 2
        assert camera.timelapses[0].start_time == "00:00"
        assert camera.timelapses[1].start_time == "12:00"
        assert camera.timelapses[1].clip_duration == 1.0

    def test_camera_with_both_snapshots_and_timelapses(self) -> None:
        """Camera should parse both snapshots and timelapses."""
        data = {
            "type": "amcrest",
            "host": "192.168.1.100",
            "snapshots": {"interval": "1h"},
            "timelapses": [{"label": "daily", "start_time": "00:00"}],
        }
        camera = Camera.from_dict("test", data)
        assert camera.snapshots is not None
        assert camera.snapshots.interval == "1h"
        assert camera.timelapses is not None
        assert len(camera.timelapses) == 1
