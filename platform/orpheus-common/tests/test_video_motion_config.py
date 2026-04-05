"""Tests for VideoMotionConfig and VideoMotionDetectionConfig."""

import pytest

from orpheus_common.config import ConfigError, VideoMotionConfig, VideoMotionDetectionConfig


class TestVideoMotionDetectionConfig:
    """Tests for VideoMotionDetectionConfig dataclass."""

    def test_detection_config_defaults(self) -> None:
        """VideoMotionDetectionConfig should have sensible defaults."""
        detection = VideoMotionDetectionConfig()
        assert detection.algorithm == "background_subtraction"
        assert detection.motion_threshold == 25.0
        assert detection.release_threshold == 12.5
        assert detection.holdoff_seconds == 2.0
        assert detection.min_duration_seconds == 0.5
        assert detection.max_duration_seconds == 30.0
        assert detection.prebuffer_seconds == 1.0

    def test_detection_config_from_dict(self) -> None:
        """VideoMotionDetectionConfig.from_dict should parse all fields."""
        data = {
            "algorithm": "optical_flow",
            "motion_threshold": 30.0,
            "release_threshold": 15.0,
            "holdoff_seconds": 3.0,
            "min_duration_seconds": 1.0,
            "max_duration_seconds": 60.0,
            "prebuffer_seconds": 2.0,
        }
        detection = VideoMotionDetectionConfig.from_dict(data)
        assert detection.algorithm == "optical_flow"
        assert detection.motion_threshold == 30.0
        assert detection.release_threshold == 15.0
        assert detection.holdoff_seconds == 3.0
        assert detection.min_duration_seconds == 1.0
        assert detection.max_duration_seconds == 60.0
        assert detection.prebuffer_seconds == 2.0

    def test_detection_config_from_dict_partial(self) -> None:
        """VideoMotionDetectionConfig.from_dict should use defaults for missing fields."""
        data = {
            "algorithm": "background_subtraction",
            "motion_threshold": 35.0,
        }
        detection = VideoMotionDetectionConfig.from_dict(data)
        assert detection.algorithm == "background_subtraction"
        assert detection.motion_threshold == 35.0
        # Verify defaults are used for unspecified fields
        assert detection.release_threshold == 12.5
        assert detection.holdoff_seconds == 2.0


class TestVideoMotionConfig:
    """Tests for VideoMotionConfig dataclass."""

    def test_video_config_defaults(self) -> None:
        """VideoMotionConfig should have sensible defaults."""
        config = VideoMotionConfig()
        assert config.fps == 10
        assert config.width == 640
        assert config.height == 480
        assert config.detection is None

    def test_video_config_from_dict(self) -> None:
        """VideoMotionConfig.from_dict should parse all fields."""
        data = {
            "fps": 15,
            "width": 1280,
            "height": 720,
            "detection": {
                "algorithm": "optical_flow",
                "motion_threshold": 30.0,
            },
        }
        config = VideoMotionConfig.from_dict(data)
        assert config.fps == 15
        assert config.width == 1280
        assert config.height == 720
        assert config.detection is not None
        assert config.detection.algorithm == "optical_flow"
        assert config.detection.motion_threshold == 30.0

    def test_video_config_from_dict_without_detection(self) -> None:
        """VideoMotionConfig.from_dict should work without detection field."""
        data = {"fps": 10, "width": 640, "height": 480}
        config = VideoMotionConfig.from_dict(data)
        assert config.fps == 10
        assert config.width == 640
        assert config.height == 480
        assert config.detection is None

    def test_video_config_from_dict_invalid_fps(self) -> None:
        """VideoMotionConfig.from_dict should reject non-integer fps."""
        data = {"fps": "not an int", "width": 640, "height": 480}
        with pytest.raises(ConfigError, match="video.fps must be an integer"):
            VideoMotionConfig.from_dict(data)

    def test_video_config_from_dict_invalid_width(self) -> None:
        """VideoMotionConfig.from_dict should reject non-integer width."""
        data = {"fps": 10, "width": "not an int", "height": 480}
        with pytest.raises(ConfigError, match="video.width must be an integer"):
            VideoMotionConfig.from_dict(data)

    def test_video_config_from_dict_invalid_height(self) -> None:
        """VideoMotionConfig.from_dict should reject non-integer height."""
        data = {"fps": 10, "width": 640, "height": "not an int"}
        with pytest.raises(ConfigError, match="video.height must be an integer"):
            VideoMotionConfig.from_dict(data)

    def test_video_config_from_dict_flat_structure(self) -> None:
        """VideoMotionConfig.from_dict should handle flat structure with detection fields."""
        data = {
            "fps": 15,
            "width": 1280,
            "height": 720,
            "algorithm": "optical_flow",
            "motion_threshold": 30.0,
            "release_threshold": 15.0,
            "holdoff_seconds": 3.0,
            "min_duration_seconds": 1.0,
            "max_duration_seconds": 60.0,
            "prebuffer_seconds": 2.0,
        }
        config = VideoMotionConfig.from_dict(data)
        assert config.fps == 15
        assert config.width == 1280
        assert config.height == 720
        assert config.detection is not None
        assert config.detection.algorithm == "optical_flow"
        assert config.detection.motion_threshold == 30.0
        assert config.detection.release_threshold == 15.0
        assert config.detection.holdoff_seconds == 3.0
