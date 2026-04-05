"""Tests for VideoHealthMonitor."""

import time

from orpheus_common.diagnostics.video_health import (
    VideoHealthMonitor,
    get_video_health_monitor,
    reset_video_health_monitor,
)


class TestVideoHealthMonitorBasic:
    """Basic functionality tests for VideoHealthMonitor."""

    def test_initial_state(self):
        """Monitor should start with zero counts and not running."""
        monitor = VideoHealthMonitor()
        status = monitor.get_status()

        assert status["running"] is False
        assert len(status["cameras"]) == 0

    def test_set_running(self):
        """Should track running state."""
        monitor = VideoHealthMonitor()
        assert monitor.is_running() is False

        monitor.set_running(True)
        assert monitor.is_running() is True
        assert monitor.get_status()["running"] is True

        monitor.set_running(False)
        assert monitor.is_running() is False

    def test_reset(self):
        """Reset should clear all counters."""
        monitor = VideoHealthMonitor()
        monitor.record_frame("cam1", 50.0)
        monitor.record_detection("cam1")
        monitor.record_mqtt_message()
        monitor.set_running(True)

        monitor.reset()

        status = monitor.get_status()
        assert len(status["cameras"]) == 0
        assert status["mqtt"]["messages_sent"] == 0


class TestFrameTracking:
    """Tests for frame processing tracking."""

    def test_record_frame(self):
        """Should track frame processing with motion values."""
        monitor = VideoHealthMonitor()
        monitor.record_frame("cam1", 25.5)

        status = monitor.get_status()
        assert len(status["cameras"]) == 1

        cam = status["cameras"][0]
        assert cam["camera_id"] == "cam1"
        assert cam["frames_processed"] == 1
        assert cam["motion_level"] == 25.5

    def test_multiple_frames(self):
        """Should accumulate frame counts."""
        monitor = VideoHealthMonitor()

        for _ in range(10):
            monitor.record_frame("cam1", 15.0)

        status = monitor.get_status()
        cam = next(c for c in status["cameras"] if c["camera_id"] == "cam1")
        assert cam["frames_processed"] == 10

    def test_multiple_cameras(self):
        """Should track multiple cameras independently."""
        monitor = VideoHealthMonitor()

        monitor.record_frame("cam1", 20.0)
        monitor.record_frame("cam2", 30.0)
        monitor.record_frame("cam1", 25.0)

        status = monitor.get_status()
        assert len(status["cameras"]) == 2

        cam1 = next(c for c in status["cameras"] if c["camera_id"] == "cam1")
        cam2 = next(c for c in status["cameras"] if c["camera_id"] == "cam2")

        assert cam1["frames_processed"] == 2
        assert cam2["frames_processed"] == 1

    def test_motion_averaging(self):
        """Should average motion values over a window."""
        monitor = VideoHealthMonitor(motion_averaging_window=3)

        monitor.record_frame("cam1", 10.0)
        monitor.record_frame("cam1", 20.0)
        monitor.record_frame("cam1", 30.0)

        status = monitor.get_status()
        cam = status["cameras"][0]

        # Average should be (10 + 20 + 30) / 3 = 20.0
        assert cam["motion_level"] == 20.0

    def test_peak_motion_tracking(self):
        """Should track and decay peak motion values."""
        monitor = VideoHealthMonitor()

        # Record high motion
        monitor.record_frame("cam1", 80.0)
        status = monitor.get_status()
        cam = status["cameras"][0]
        assert cam["peak_motion"] == 80.0

        # Record lower motion - peak should decay
        monitor.record_frame("cam1", 10.0)
        status = monitor.get_status()
        cam = status["cameras"][0]
        # Peak should be less than 80 due to decay
        assert cam["peak_motion"] < 80.0
        assert cam["peak_motion"] > 10.0


class TestDetectionTracking:
    """Tests for motion detection event tracking."""

    def test_record_detection(self):
        """Should track detection events."""
        monitor = VideoHealthMonitor()
        monitor.record_detection("cam1")

        status = monitor.get_status()
        cam = status["cameras"][0]
        assert cam["detections_count"] == 1
        assert cam["last_detection"] is not None

    def test_multiple_detections(self):
        """Should accumulate detection counts."""
        monitor = VideoHealthMonitor()

        for _ in range(5):
            monitor.record_detection("cam1")

        status = monitor.get_status()
        cam = status["cameras"][0]
        assert cam["detections_count"] == 5

    def test_last_detection_timestamp(self):
        """Should update last detection timestamp."""
        monitor = VideoHealthMonitor()

        monitor.record_detection("cam1")
        status1 = monitor.get_status()
        first_timestamp = status1["cameras"][0]["last_detection"]

        time.sleep(0.01)  # Small delay

        monitor.record_detection("cam1")
        status2 = monitor.get_status()
        second_timestamp = status2["cameras"][0]["last_detection"]

        # Second timestamp should be later
        assert second_timestamp > first_timestamp


class TestMQTTTracking:
    """Tests for MQTT message tracking."""

    def test_record_mqtt_message(self):
        """Should track MQTT messages sent."""
        monitor = VideoHealthMonitor()
        monitor.record_mqtt_message()

        status = monitor.get_status()
        assert status["mqtt"]["messages_sent"] == 1
        assert status["mqtt"]["messages_since_start"] == 1

    def test_multiple_mqtt_messages(self):
        """Should accumulate MQTT message counts."""
        monitor = VideoHealthMonitor()

        for _ in range(10):
            monitor.record_mqtt_message()

        status = monitor.get_status()
        assert status["mqtt"]["messages_sent"] == 10
        assert status["mqtt"]["messages_since_start"] == 10

    def test_mqtt_rate_calculation(self):
        """Should calculate MQTT rate per minute."""
        monitor = VideoHealthMonitor()

        # Record some messages
        for _ in range(5):
            monitor.record_mqtt_message()

        status = monitor.get_status()
        # Rate should be positive
        assert status["mqtt"]["rate_per_minute"] >= 0


class TestHardwareConfiguration:
    """Tests for hardware configuration tracking."""

    def test_set_hardware_config(self):
        """Should store hardware configuration."""
        monitor = VideoHealthMonitor()
        monitor.set_hardware_config(fps=10, width=640, height=480, num_cameras=4)

        status = monitor.get_status()
        hw = status["hardware"]

        assert hw["fps"] == 10
        assert hw["width"] == 640
        assert hw["height"] == 480
        assert hw["num_cameras"] == 4

    def test_set_camera_thresholds(self):
        """Should store camera-specific thresholds."""
        monitor = VideoHealthMonitor()
        monitor.set_camera_thresholds("cam1", 25.0, 12.5)

        status = monitor.get_status()
        cam = status["cameras"][0]

        assert cam["motion_threshold"] == 25.0
        assert cam["release_threshold"] == 12.5


class TestTimingStatistics:
    """Tests for timing statistics tracking."""

    def test_frame_interval_tracking(self):
        """Should track frame intervals."""
        monitor = VideoHealthMonitor()

        # Record multiple frames to generate intervals
        for _ in range(5):
            monitor.record_frame("cam1", 10.0)
            time.sleep(0.01)  # Small delay between frames

        status = monitor.get_status()
        timing = status["timing"]

        # Should have timing statistics
        assert timing["frame_count"] == 5
        assert timing["frame_interval_ms"] > 0


class TestStatusOutput:
    """Tests for status output structure."""

    def test_status_has_required_fields(self):
        """Status should have all required top-level fields."""
        monitor = VideoHealthMonitor()
        status = monitor.get_status()

        required_fields = [
            "running",
            "uptime_seconds",
            "cameras",
            "hardware",
            "timing",
            "system",
            "mqtt",
            "health_description",
        ]

        for field in required_fields:
            assert field in status

    def test_camera_status_structure(self):
        """Camera status should have all required fields."""
        monitor = VideoHealthMonitor()
        monitor.record_frame("cam1", 20.0)
        monitor.record_detection("cam1")

        status = monitor.get_status()
        cam = status["cameras"][0]

        required_fields = [
            "camera_id",
            "motion_level",
            "peak_motion",
            "motion_threshold",
            "release_threshold",
            "frames_processed",
            "detections_count",
            "last_detection",
        ]

        for field in required_fields:
            assert field in cam


class TestSingleton:
    """Tests for global singleton instance."""

    def test_get_video_health_monitor(self):
        """Should return singleton instance."""
        monitor1 = get_video_health_monitor()
        monitor2 = get_video_health_monitor()

        # Should be the same instance
        assert monitor1 is monitor2

    def test_reset_video_health_monitor(self):
        """Should reset the singleton instance."""
        monitor = get_video_health_monitor()
        monitor.record_frame("cam1", 50.0)
        monitor.record_detection("cam1")

        reset_video_health_monitor()

        status = monitor.get_status()
        assert len(status["cameras"]) == 0


class TestHealthDescription:
    """Tests for health description messages."""

    def test_running_description(self):
        """Should generate appropriate description when running."""
        monitor = VideoHealthMonitor()
        monitor.set_running(True)
        monitor.record_frame("cam1", 20.0)
        monitor.record_frame("cam2", 30.0)
        monitor.record_detection("cam1")
        monitor.record_detection("cam2")
        monitor.record_detection("cam2")

        status = monitor.get_status()
        desc = status["health_description"]

        assert "operational" in desc.lower()
        assert "2" in desc  # 2 cameras
        assert "3" in desc  # 3 detections

    def test_not_running_description(self):
        """Should generate appropriate description when not running."""
        monitor = VideoHealthMonitor()
        monitor.set_running(False)

        status = monitor.get_status()
        desc = status["health_description"]

        assert "not running" in desc.lower()
