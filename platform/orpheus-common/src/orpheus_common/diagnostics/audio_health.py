"""
Audio health monitoring for Orpheus platform.

Provides real-time diagnostics for audio hardware including XRUN tracking,
signal level analysis, timing measurements, and system state monitoring.

This module is designed to be reusable by any agent that does audio capture
and provides both CLI-friendly and JSON API-friendly status output.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import psutil

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


# Audio level thresholds in dBFS
LEVEL_THRESHOLD_GREEN = -18.0  # Below this = green (quiet)
LEVEL_THRESHOLD_YELLOW = -6.0  # Below this = yellow (moderate), above = red (loud)
NO_SIGNAL_THRESHOLD = -90.0  # Below this = no signal warning


@dataclass
class ChannelStatus:
    """Status for a single audio channel."""

    channel_id: str
    level_db: float = -100.0
    peak_db: float = -100.0
    has_signal: bool = False
    level_color: str = "green"  # "green", "yellow", "red", "none" (no signal)
    level_history: list[float] = field(default_factory=list)
    avg_level_db: float = -100.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "channel_id": self.channel_id,
            "level_db": round(self.avg_level_db, 1),  # Use averaged level
            "peak_db": round(self.peak_db, 1),
            "has_signal": self.has_signal,
            "level_color": self.level_color,
        }


@dataclass
class HardwareConfig:
    """Audio hardware configuration status."""

    sample_rate: int = 0
    buffer_size: int = 0
    device_name: str = ""
    num_channels: int = 0
    format: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "sample_rate": self.sample_rate,
            "buffer_size": self.buffer_size,
            "device_name": self.device_name,
            "num_channels": self.num_channels,
            "format": self.format,
        }


@dataclass
class TimingStats:
    """Audio callback timing statistics."""

    last_callback_time: float = 0.0
    callback_interval_ms: float = 0.0
    min_interval_ms: float = float("inf")
    max_interval_ms: float = 0.0
    jitter_ms: float = 0.0  # Standard deviation of intervals
    callback_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "callback_interval_ms": round(self.callback_interval_ms, 2),
            "min_interval_ms": (
                round(self.min_interval_ms, 2) if self.min_interval_ms != float("inf") else 0.0
            ),
            "max_interval_ms": round(self.max_interval_ms, 2),
            "jitter_ms": round(self.jitter_ms, 2),
            "callback_count": self.callback_count,
        }


@dataclass
class SystemInfo:
    """System information relevant to audio processing."""

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


class AudioHealthMonitor:
    """
    Monitor audio system health including XRUNs, signal levels, and timing.

    This class is thread-safe and designed to be updated from audio callbacks
    while being read from other threads for status reporting.

    Example usage:
        monitor = AudioHealthMonitor()
        monitor.set_hardware_config(sample_rate=48000, buffer_size=1024, ...)

        # In audio callback:
        monitor.record_callback(audio_data, channel_id)
        monitor.record_xrun(is_input_overflow=True)

        # For status reporting:
        status = monitor.get_status()
    """

    def __init__(
        self, thermal_zone_path: Optional[str] = None, level_averaging_window: int = 10
    ) -> None:
        """
        Initialize the audio health monitor.

        Args:
            thermal_zone_path: Path to thermal zone file for temperature reading.
                              Defaults to /sys/class/thermal/thermal_zone0/temp
            level_averaging_window: Number of samples to average for channel levels (default: 10)
        """
        self._lock = threading.RLock()

        # XRUN counters
        self._input_overflow_count = 0
        self._input_underflow_count = 0
        self._output_overflow_count = 0
        self._output_underflow_count = 0
        self._total_xrun_count = 0

        # XRUN rate tracking (sliding window)
        self._xrun_timestamps: list[float] = []  # Timestamps of XRUNs for rate calculation
        self._xrun_window_seconds = 60.0  # Track XRUNs over last 60 seconds

        # Channel status
        self._channels: dict[str, ChannelStatus] = {}
        self._level_averaging_window = level_averaging_window

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
            self._input_overflow_count = 0
            self._input_underflow_count = 0
            self._output_overflow_count = 0
            self._output_underflow_count = 0
            self._total_xrun_count = 0
            self._channels.clear()
            self._timing_stats = TimingStats()
            self._interval_history.clear()
            self._mqtt_messages_sent = 0
            self._mqtt_messages_since_start = 0
            self._mqtt_last_reset = time.time()
            self._start_time = time.time()

    def set_running(self, running: bool) -> None:
        """Set the running state of the audio system."""
        with self._lock:
            self._is_running = running
            if running:
                self._start_time = time.time()

    def is_running(self) -> bool:
        """Return whether the audio system is running."""
        with self._lock:
            return self._is_running

    def set_hardware_config(
        self,
        sample_rate: int = 0,
        buffer_size: int = 0,
        device_name: str = "",
        num_channels: int = 0,
        audio_format: str = "",
    ) -> None:
        """
        Set the hardware configuration for display.

        Args:
            sample_rate: Sample rate in Hz
            buffer_size: Buffer/block size in samples
            device_name: Name of the audio device
            num_channels: Number of audio channels
            audio_format: Audio sample format (e.g., "int16", "float32")
        """
        with self._lock:
            self._hardware_config = HardwareConfig(
                sample_rate=sample_rate,
                buffer_size=buffer_size,
                device_name=device_name,
                num_channels=num_channels,
                format=audio_format,
            )

    def record_xrun(
        self,
        is_input_overflow: bool = False,
        is_input_underflow: bool = False,
        is_output_overflow: bool = False,
        is_output_underflow: bool = False,
    ) -> None:
        """
        Record an XRUN (buffer overrun/underrun) event.

        Args:
            is_input_overflow: Input buffer overflow (data lost)
            is_input_underflow: Input buffer underflow
            is_output_overflow: Output buffer overflow
            is_output_underflow: Output buffer underflow (audio glitch)
        """
        current_time = time.time()

        with self._lock:
            if is_input_overflow:
                self._input_overflow_count += 1
                self._total_xrun_count += 1
                self._xrun_timestamps.append(current_time)
            if is_input_underflow:
                self._input_underflow_count += 1
                self._total_xrun_count += 1
                self._xrun_timestamps.append(current_time)
            if is_output_overflow:
                self._output_overflow_count += 1
                self._total_xrun_count += 1
                self._xrun_timestamps.append(current_time)
            if is_output_underflow:
                self._output_underflow_count += 1
                self._total_xrun_count += 1
                self._xrun_timestamps.append(current_time)

    def record_channel_level(self, channel_id: str, level_db: float) -> None:
        """
        Record the current signal level for a channel.

        Args:
            channel_id: Channel identifier
            level_db: Signal level in dBFS (0 = full scale, negative values)
        """
        with self._lock:
            if channel_id not in self._channels:
                self._channels[channel_id] = ChannelStatus(channel_id=channel_id)

            channel = self._channels[channel_id]
            channel.level_db = level_db

            # Add to history for averaging
            channel.level_history.append(level_db)
            if len(channel.level_history) > self._level_averaging_window:
                channel.level_history.pop(0)

            # Calculate running average
            channel.avg_level_db = sum(channel.level_history) / len(channel.level_history)

            # Update peak with slow decay
            if level_db > channel.peak_db:
                channel.peak_db = level_db
            else:
                # Decay peak towards current level
                channel.peak_db = channel.peak_db * 0.95 + level_db * 0.05

            # Determine signal presence based on averaged level
            channel.has_signal = channel.avg_level_db > NO_SIGNAL_THRESHOLD

            # Determine color based on averaged level
            if channel.avg_level_db < NO_SIGNAL_THRESHOLD:
                channel.level_color = "none"
            elif channel.avg_level_db < LEVEL_THRESHOLD_GREEN:
                channel.level_color = "green"
            elif channel.avg_level_db < LEVEL_THRESHOLD_YELLOW:
                channel.level_color = "yellow"
            else:
                channel.level_color = "red"

    def record_callback_timing(self) -> None:
        """
        Record that an audio callback has occurred.

        Call this at the start of each audio callback to track timing.
        """
        current_time = time.time()

        with self._lock:
            self._timing_stats.callback_count += 1

            if self._timing_stats.last_callback_time > 0:
                interval_ms = (current_time - self._timing_stats.last_callback_time) * 1000

                self._timing_stats.callback_interval_ms = interval_ms

                # Update min/max
                if interval_ms < self._timing_stats.min_interval_ms:
                    self._timing_stats.min_interval_ms = interval_ms
                if interval_ms > self._timing_stats.max_interval_ms:
                    self._timing_stats.max_interval_ms = interval_ms

                # Store for jitter calculation
                self._interval_history.append(interval_ms)
                if len(self._interval_history) > self._max_history_size:
                    self._interval_history.pop(0)

                # Calculate jitter (standard deviation)
                if len(self._interval_history) > 1:
                    mean = sum(self._interval_history) / len(self._interval_history)
                    variance = sum((x - mean) ** 2 for x in self._interval_history) / len(
                        self._interval_history
                    )
                    self._timing_stats.jitter_ms = variance**0.5

            self._timing_stats.last_callback_time = current_time

    def record_mqtt_message(self) -> None:
        """Record that an MQTT message was sent."""
        with self._lock:
            self._mqtt_messages_sent += 1
            self._mqtt_messages_since_start += 1

    def get_xrun_count(self) -> int:
        """Get total XRUN count (all types)."""
        with self._lock:
            return self._total_xrun_count

    def get_xrun_rate(self) -> float:
        """
        Get XRUN rate over the sliding window.

        Returns:
            XRUNs per minute over the last 60 seconds
        """
        current_time = time.time()
        window_start = current_time - self._xrun_window_seconds

        with self._lock:
            # Remove old timestamps outside the window
            self._xrun_timestamps = [t for t in self._xrun_timestamps if t >= window_start]

            # Calculate rate
            if len(self._xrun_timestamps) == 0:
                return 0.0

            # XRUNs per minute
            elapsed_seconds = min(current_time - self._start_time, self._xrun_window_seconds)
            if elapsed_seconds > 0:
                return (len(self._xrun_timestamps) / elapsed_seconds) * 60.0
            return 0.0

    def get_system_info(self) -> SystemInfo:
        """
        Get current system information.

        Returns:
            SystemInfo with CPU, memory, and thermal state
        """
        info = SystemInfo()

        try:
            # CPU usage (non-blocking)
            info.cpu_percent = psutil.cpu_percent(interval=None)

            # CPU frequency
            freq = psutil.cpu_freq()
            if freq:
                info.cpu_freq_mhz = freq.current

            # Memory
            mem = psutil.virtual_memory()
            info.memory_percent = mem.percent

            # Load average (Unix only)
            if hasattr(os, "getloadavg"):
                info.load_average = os.getloadavg()

            # Thermal - try to read Jetson thermal zone or generic thermal
            info.thermal_temp_c = self._get_thermal_temp()
            if info.thermal_temp_c is not None and info.thermal_temp_c > 80:
                info.thermal_throttling = True

        except Exception as e:
            logger.debug("Error getting system info", error=str(e))

        return info

    def _get_thermal_temp(self) -> Optional[float]:
        """Read thermal temperature from system."""
        # Build list of thermal paths to try
        thermal_paths = []

        # If a custom path is configured, try it first
        if self._thermal_zone_path:
            thermal_paths.append(self._thermal_zone_path)

        # Add fallback paths for common locations (excluding any already added)
        fallback_paths = [
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/devices/virtual/thermal/thermal_zone0/temp",
        ]
        for fallback in fallback_paths:
            if fallback not in thermal_paths:
                thermal_paths.append(fallback)

        for path in thermal_paths:
            try:
                with open(path) as f:
                    temp_str = f.read().strip()
                    # Temperature is typically in millidegrees
                    return float(temp_str) / 1000.0
            except (FileNotFoundError, PermissionError, ValueError):
                continue

        # Try psutil sensors as final fallback
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Get the first available temperature
                for name, entries in temps.items():
                    if entries:
                        return entries[0].current
        except Exception:
            pass

        return None

    def get_status(self) -> dict[str, Any]:
        """
        Get complete audio health status as a dictionary.

        This method returns a dictionary suitable for both CLI display
        and JSON API responses.

        Returns:
            Dictionary with:
                - running: bool - Whether audio system is active
                - xrun: dict - XRUN counts by type
                - channels: list - Per-channel status
                - hardware: dict - Hardware configuration
                - timing: dict - Callback timing statistics
                - system: dict - CPU, memory, thermal state
                - session: dict - Session information
        """
        with self._lock:
            # Channel status
            channels = [ch.to_dict() for ch in self._channels.values()]

            # Calculate channels with no signal
            no_signal_channels = [
                ch.channel_id for ch in self._channels.values() if not ch.has_signal
            ]

            # Session duration
            session_duration = time.time() - self._start_time

            # Calculate XRUN rate and health status
            xrun_rate = self.get_xrun_rate()

            # Calculate glitch percentage (what % of audio callbacks had glitches)
            callback_count = self._timing_stats.callback_count
            glitch_percentage = 0.0
            if callback_count > 0:
                glitch_percentage = (self._total_xrun_count / callback_count) * 100.0

            # Determine health status based on glitch percentage
            # <0.5% = good, 0.5-2% = warning, >2% = critical
            if glitch_percentage < 0.5:
                health_status = "good"
                health_description = "Audio system operating normally"
            elif glitch_percentage < 2.0:
                health_status = "warning"
                health_description = (
                    f"Some audio glitches detected ({glitch_percentage:.1f}% of callbacks)"
                )
            else:
                health_status = "critical"
                health_description = (
                    f"High audio glitch rate ({glitch_percentage:.1f}% of callbacks) - "
                    f"check system load"
                )

            # Calculate MQTT rate (messages per minute)
            current_time = time.time()
            time_since_reset = current_time - self._mqtt_last_reset
            mqtt_rate_per_minute = (
                (self._mqtt_messages_sent / time_since_reset) * 60.0
                if time_since_reset > 0
                else 0.0
            )

            return {
                "running": self._is_running,
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "health_status": health_status,
                "health_description": health_description,
                "xrun": {
                    "total": self._total_xrun_count,
                    "rate_per_minute": round(xrun_rate, 1),
                    "percentage": round(glitch_percentage, 2),
                    "window_seconds": self._xrun_window_seconds,
                    "input_overflow": self._input_overflow_count,
                    "input_underflow": self._input_underflow_count,
                    "output_overflow": self._output_overflow_count,
                    "output_underflow": self._output_underflow_count,
                },
                "channels": channels,
                "channels_description": (
                    f"Levels averaged over {self._level_averaging_window} samples "
                    f"(~{round(self._level_averaging_window * 0.2, 1)}s)"
                ),
                "no_signal_channels": no_signal_channels,
                "hardware": self._hardware_config.to_dict(),
                "timing": self._timing_stats.to_dict(),
                "system": self.get_system_info().to_dict(),
                "mqtt": {
                    "messages_sent": self._mqtt_messages_sent,
                    "messages_since_start": self._mqtt_messages_since_start,
                    "rate_per_minute": round(mqtt_rate_per_minute, 2),
                    "window_seconds": round(time_since_reset, 1),
                },
                "session": {
                    "duration_seconds": round(session_duration, 1),
                    "started_at": datetime.fromtimestamp(self._start_time, tz=timezone.utc)
                    .isoformat()
                    .replace("+00:00", "Z"),
                },
            }


# Singleton instance for global access
_global_monitor: Optional[AudioHealthMonitor] = None
_global_monitor_lock = threading.Lock()


def get_audio_health_monitor(thermal_zone_path: Optional[str] = None) -> AudioHealthMonitor:
    """
    Get the global AudioHealthMonitor singleton.

    Creates a new instance if one doesn't exist.

    Args:
        thermal_zone_path: Path to thermal zone file. If None, uses default.
                          Only used when creating a new instance.

    Returns:
        The global AudioHealthMonitor instance
    """
    global _global_monitor

    with _global_monitor_lock:
        if _global_monitor is None:
            _global_monitor = AudioHealthMonitor(thermal_zone_path=thermal_zone_path)
        return _global_monitor


def reset_audio_health_monitor(thermal_zone_path: Optional[str] = None) -> None:
    """
    Reset the global AudioHealthMonitor singleton.

    Creates a fresh instance, discarding any previous state.

    Args:
        thermal_zone_path: Path to thermal zone file. If None, uses default.
    """
    global _global_monitor

    with _global_monitor_lock:
        _global_monitor = AudioHealthMonitor(thermal_zone_path=thermal_zone_path)
