"""
Video health monitoring for Orpheus platform.

Provides real-time diagnostics for video hardware including motion detection tracking,
frame rate monitoring, and system state monitoring.

This module is designed to be reusable by any agent that does video capture
and provides both CLI-friendly and JSON API-friendly status output.
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import psutil

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class CameraStatus:
    """Status for a single camera."""

    camera_id: str
    motion_level: float = 0.0  # Current motion percentage
    peak_motion: float = 0.0  # Peak motion in window
    avg_motion: float = 0.0  # Average motion in window
    motion_history: list[float] = field(default_factory=list)
    motion_threshold: float = 25.0
    release_threshold: float = 12.5
    frames_processed: int = 0
    detections_count: int = 0
    last_detection_time: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "camera_id": self.camera_id,
            "motion_level": round(self.avg_motion, 1),  # Use averaged motion
            "peak_motion": round(self.peak_motion, 1),
            "motion_threshold": round(self.motion_threshold, 1),
            "release_threshold": round(self.release_threshold, 1),
            "frames_processed": self.frames_processed,
            "detections_count": self.detections_count,
            "last_detection": (
                self.last_detection_time.isoformat() if self.last_detection_time else None
            ),
        }


@dataclass
class HardwareConfig:
    """Video hardware configuration status."""

    fps: int = 0
    width: int = 0
    height: int = 0
    num_cameras: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "num_cameras": self.num_cameras,
        }


@dataclass
class TimingStats:
    """Video processing timing statistics."""

    last_frame_time: float = 0.0
    frame_interval_ms: float = 0.0
    min_interval_ms: float = float("inf")
    max_interval_ms: float = 0.0
    jitter_ms: float = 0.0  # Standard deviation of intervals
    frame_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "frame_interval_ms": round(self.frame_interval_ms, 2),
            "min_interval_ms": (
                round(self.min_interval_ms, 2) if self.min_interval_ms != float("inf") else 0.0
            ),
            "max_interval_ms": round(self.max_interval_ms, 2),
            "jitter_ms": round(self.jitter_ms, 2),
            "frame_count": self.frame_count,
        }


@dataclass
class SystemInfo:
    """System information relevant to video processing."""

    cpu_percent: float = 0.0
    cpu_freq_mhz: float = 0.0
    memory_percent: float = 0.0
    thermal_throttling: bool = False
    thermal_temp_c: Optional[float] = None
    load_average: tuple = field(default_factory=lambda: (0.0, 0.0, 0.0))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "cpu_percent": round(self.cpu_percent, 1),
            "cpu_freq_mhz": round(self.cpu_freq_mhz, 1),
            "memory_percent": round(self.memory_percent, 1),
            "thermal_throttling": self.thermal_throttling,
            "thermal_temp_c": (round(self.thermal_temp_c, 1) if self.thermal_temp_c else None),
            "load_average": [round(x, 2) for x in self.load_average],
        }


class VideoHealthMonitor:
    """
    Monitor video system health including motion detection, frame rates, and timing.

    This class is thread-safe and designed to be updated from video processing
    while being read from other threads for status reporting.

    Example usage:
        monitor = VideoHealthMonitor()
        monitor.set_hardware_config(fps=10, width=640, height=480, num_cameras=4)

        # In video processing:
        monitor.record_frame(camera_id, motion_value)
        monitor.record_detection(camera_id)

        # For status reporting:
        status = monitor.get_status()
    """

    def __init__(
        self, thermal_zone_path: Optional[str] = None, motion_averaging_window: int = 10
    ) -> None:
        """
        Initialize the video health monitor.

        Args:
            thermal_zone_path: Path to thermal zone file for temperature reading.
                              Defaults to /sys/class/thermal/thermal_zone0/temp
            motion_averaging_window: Number of samples to average for motion levels (default: 10)
        """
        self._lock = threading.RLock()

        # Camera status
        self._cameras: dict[str, CameraStatus] = {}
        self._motion_averaging_window = motion_averaging_window

        # Hardware configuration
        self._hardware_config = HardwareConfig()

        # Thermal zone configuration
        self._thermal_zone_path = thermal_zone_path

        # Timing statistics
        self._timing_stats = TimingStats()
        self._interval_history: list[float] = []
        self._max_history_size = 100

        # MQTT message counters
        self._mqtt_messages_sent = 0
        self._mqtt_messages_since_start = 0
        self._mqtt_last_reset = time.time()

        # Session info
        self._start_time = time.time()
        self._is_running = False

    def reset(self) -> None:
        """Reset all counters and statistics."""
        with self._lock:
            self._cameras.clear()
            self._timing_stats = TimingStats()
            self._interval_history.clear()
            self._mqtt_messages_sent = 0
            self._mqtt_messages_since_start = 0
            self._mqtt_last_reset = time.time()
            self._start_time = time.time()

    def set_running(self, running: bool) -> None:
        """Set the running state of the video system."""
        with self._lock:
            self._is_running = running
            if running:
                self._start_time = time.time()

    def is_running(self) -> bool:
        """Return whether the video system is running."""
        with self._lock:
            return self._is_running

    def set_hardware_config(
        self,
        fps: int = 0,
        width: int = 0,
        height: int = 0,
        num_cameras: int = 0,
    ) -> None:
        """
        Set the hardware configuration for display.

        Args:
            fps: Frames per second
            width: Frame width in pixels
            height: Frame height in pixels
            num_cameras: Number of cameras
        """
        with self._lock:
            self._hardware_config = HardwareConfig(
                fps=fps,
                width=width,
                height=height,
                num_cameras=num_cameras,
            )

    def set_camera_thresholds(
        self, camera_id: str, motion_threshold: float, release_threshold: float
    ) -> None:
        """
        Set motion detection thresholds for a camera.

        Args:
            camera_id: Camera identifier
            motion_threshold: Motion detection threshold percentage
            release_threshold: Release threshold percentage
        """
        with self._lock:
            if camera_id not in self._cameras:
                self._cameras[camera_id] = CameraStatus(camera_id=camera_id)

            camera = self._cameras[camera_id]
            camera.motion_threshold = motion_threshold
            camera.release_threshold = release_threshold

    def record_frame(self, camera_id: str, motion_value: float) -> None:
        """
        Record a processed frame with its motion value.

        Args:
            camera_id: Camera identifier
            motion_value: Motion value as percentage (0-100)
        """
        current_time = time.time()

        with self._lock:
            if camera_id not in self._cameras:
                self._cameras[camera_id] = CameraStatus(camera_id=camera_id)

            camera = self._cameras[camera_id]
            camera.motion_level = motion_value
            camera.frames_processed += 1

            # Add to history for averaging
            camera.motion_history.append(motion_value)
            if len(camera.motion_history) > self._motion_averaging_window:
                camera.motion_history.pop(0)

            # Calculate running average
            camera.avg_motion = sum(camera.motion_history) / len(camera.motion_history)

            # Update peak with slow decay
            if motion_value > camera.peak_motion:
                camera.peak_motion = motion_value
            else:
                # Decay peak towards current motion
                camera.peak_motion = camera.peak_motion * 0.95 + motion_value * 0.05

            # Update timing stats
            if self._timing_stats.last_frame_time > 0:
                interval_ms = (current_time - self._timing_stats.last_frame_time) * 1000.0
                self._timing_stats.frame_interval_ms = interval_ms
                self._timing_stats.min_interval_ms = min(
                    self._timing_stats.min_interval_ms, interval_ms
                )
                self._timing_stats.max_interval_ms = max(
                    self._timing_stats.max_interval_ms, interval_ms
                )

                # Track intervals for jitter calculation
                self._interval_history.append(interval_ms)
                if len(self._interval_history) > self._max_history_size:
                    self._interval_history.pop(0)

                # Calculate jitter (standard deviation)
                if len(self._interval_history) > 1:
                    mean_interval = sum(self._interval_history) / len(self._interval_history)
                    variance = sum((x - mean_interval) ** 2 for x in self._interval_history) / len(
                        self._interval_history
                    )
                    self._timing_stats.jitter_ms = variance**0.5

            self._timing_stats.last_frame_time = current_time
            self._timing_stats.frame_count += 1

    def record_detection(self, camera_id: str) -> None:
        """
        Record a motion detection event.

        Args:
            camera_id: Camera identifier
        """
        with self._lock:
            if camera_id not in self._cameras:
                self._cameras[camera_id] = CameraStatus(camera_id=camera_id)

            camera = self._cameras[camera_id]
            camera.detections_count += 1
            camera.last_detection_time = datetime.now(timezone.utc)

    def record_mqtt_message(self) -> None:
        """Record that an MQTT message was sent."""
        with self._lock:
            self._mqtt_messages_sent += 1
            self._mqtt_messages_since_start += 1

    def get_status(self) -> dict[str, Any]:
        """
        Get comprehensive video system status.

        Returns:
            Dictionary containing all health metrics suitable for JSON serialization.
        """
        with self._lock:
            current_time = time.time()
            uptime_seconds = current_time - self._start_time

            # Calculate MQTT rate (messages per minute)
            time_since_reset = current_time - self._mqtt_last_reset
            mqtt_rate_per_minute = (
                (self._mqtt_messages_sent / time_since_reset) * 60.0
                if time_since_reset > 0
                else 0.0
            )

            # Build camera list
            cameras_list = [camera.to_dict() for camera in self._cameras.values()]

            # Get system info
            system_info = self._get_system_info()

            status = {
                "running": self._is_running,
                "uptime_seconds": round(uptime_seconds, 1),
                "cameras": cameras_list,
                "hardware": self._hardware_config.to_dict(),
                "timing": self._timing_stats.to_dict(),
                "system": system_info.to_dict(),
                "mqtt": {
                    "messages_sent": self._mqtt_messages_sent,
                    "messages_since_start": self._mqtt_messages_since_start,
                    "rate_per_minute": round(mqtt_rate_per_minute, 2),
                    "window_seconds": round(time_since_reset, 1),
                },
            }

            # Add descriptive health message
            if self._is_running:
                num_cameras = len(self._cameras)
                total_detections = sum(c.detections_count for c in self._cameras.values())
                status["health_description"] = (
                    f"Video system operational: {num_cameras} camera(s), "
                    f"{total_detections} detection(s) total"
                )
            else:
                status["health_description"] = "Video system not running"

            # Add cameras description
            if cameras_list:
                status["cameras_description"] = "Per-camera motion levels and thresholds"
            else:
                status["cameras_description"] = "No cameras configured"

            return status

    def _get_system_info(self) -> SystemInfo:
        """Get current system information."""
        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            memory_percent = psutil.virtual_memory().percent

            # Get CPU frequency if available
            cpu_freq_mhz = 0.0
            try:
                cpu_freq = psutil.cpu_freq()
                if cpu_freq:
                    cpu_freq_mhz = cpu_freq.current
            except Exception:
                pass

            # Get load average
            try:
                load_avg = psutil.getloadavg()
            except (AttributeError, OSError):
                load_avg = (0.0, 0.0, 0.0)

            # Get thermal info if available
            thermal_temp_c = None
            thermal_throttling = False

            thermal_path = self._thermal_zone_path or "/sys/class/thermal/thermal_zone0/temp"
            try:
                with open(thermal_path) as f:
                    temp_millidegrees = int(f.read().strip())
                    thermal_temp_c = temp_millidegrees / 1000.0
                    # Consider throttling if temp > 80C (conservative threshold)
                    thermal_throttling = thermal_temp_c > 80.0
            except (FileNotFoundError, ValueError, PermissionError) as e:
                # Thermal info not available or unreadable; this is expected on some systems.
                logger.debug("Could not read thermal info", thermal_path=thermal_path, error=str(e))

            return SystemInfo(
                cpu_percent=cpu_percent,
                cpu_freq_mhz=cpu_freq_mhz,
                memory_percent=memory_percent,
                thermal_throttling=thermal_throttling,
                thermal_temp_c=thermal_temp_c,
                load_average=load_avg,
            )
        except Exception as e:
            logger.warning("Failed to get system info", error=str(e))
            return SystemInfo()


# Global singleton instance
_video_health_monitor: Optional[VideoHealthMonitor] = None
_monitor_lock = threading.Lock()


def get_video_health_monitor() -> VideoHealthMonitor:
    """
    Get the global video health monitor singleton.

    Returns:
        VideoHealthMonitor instance (creates one if it doesn't exist).
    """
    global _video_health_monitor
    with _monitor_lock:
        if _video_health_monitor is None:
            _video_health_monitor = VideoHealthMonitor()
        return _video_health_monitor


def reset_video_health_monitor() -> None:
    """Reset the global video health monitor (mainly for testing)."""
    global _video_health_monitor
    with _monitor_lock:
        if _video_health_monitor is not None:
            _video_health_monitor.reset()
