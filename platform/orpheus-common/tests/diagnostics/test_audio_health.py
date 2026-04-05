"""Tests for AudioHealthMonitor."""

import time

from orpheus_common.diagnostics.audio_health import (
    AudioHealthMonitor,
    get_audio_health_monitor,
    reset_audio_health_monitor,
)


class TestAudioHealthMonitorBasic:
    """Basic functionality tests for AudioHealthMonitor."""

    def test_initial_state(self):
        """Monitor should start with zero counts and not running."""
        monitor = AudioHealthMonitor()
        status = monitor.get_status()

        assert status["running"] is False
        assert status["xrun"]["total"] == 0
        assert len(status["channels"]) == 0

    def test_set_running(self):
        """Should track running state."""
        monitor = AudioHealthMonitor()
        assert monitor.is_running() is False

        monitor.set_running(True)
        assert monitor.is_running() is True
        assert monitor.get_status()["running"] is True

        monitor.set_running(False)
        assert monitor.is_running() is False

    def test_reset(self):
        """Reset should clear all counters."""
        monitor = AudioHealthMonitor()
        monitor.record_xrun(is_input_overflow=True)
        monitor.record_channel_level("ch1", -20.0)
        monitor.set_running(True)

        monitor.reset()

        assert monitor.get_xrun_count() == 0
        assert len(monitor.get_status()["channels"]) == 0


class TestXRUNTracking:
    """Tests for XRUN (buffer overrun/underrun) tracking."""

    def test_record_input_overflow(self):
        """Should track input overflow XRUNs."""
        monitor = AudioHealthMonitor()
        monitor.record_xrun(is_input_overflow=True)

        status = monitor.get_status()
        assert status["xrun"]["total"] == 1
        assert status["xrun"]["input_overflow"] == 1
        assert status["xrun"]["input_underflow"] == 0

    def test_record_input_underflow(self):
        """Should track input underflow XRUNs."""
        monitor = AudioHealthMonitor()
        monitor.record_xrun(is_input_underflow=True)

        status = monitor.get_status()
        assert status["xrun"]["total"] == 1
        assert status["xrun"]["input_underflow"] == 1

    def test_record_output_overflow(self):
        """Should track output overflow XRUNs."""
        monitor = AudioHealthMonitor()
        monitor.record_xrun(is_output_overflow=True)

        status = monitor.get_status()
        assert status["xrun"]["total"] == 1
        assert status["xrun"]["output_overflow"] == 1

    def test_record_output_underflow(self):
        """Should track output underflow XRUNs."""
        monitor = AudioHealthMonitor()
        monitor.record_xrun(is_output_underflow=True)

        status = monitor.get_status()
        assert status["xrun"]["total"] == 1
        assert status["xrun"]["output_underflow"] == 1

    def test_multiple_xruns(self):
        """Should accumulate multiple XRUNs."""
        monitor = AudioHealthMonitor()

        for _ in range(5):
            monitor.record_xrun(is_input_overflow=True)
        for _ in range(3):
            monitor.record_xrun(is_output_underflow=True)

        assert monitor.get_xrun_count() == 8
        status = monitor.get_status()
        assert status["xrun"]["input_overflow"] == 5
        assert status["xrun"]["output_underflow"] == 3


class TestChannelLevels:
    """Tests for per-channel signal level tracking."""

    def test_record_channel_level(self):
        """Should track channel signal levels."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("channel-1", -25.0)

        status = monitor.get_status()
        assert len(status["channels"]) == 1
        assert status["channels"][0]["channel_id"] == "channel-1"
        assert status["channels"][0]["level_db"] == -25.0

    def test_multiple_channels(self):
        """Should track multiple channels independently."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("ch1", -20.0)
        monitor.record_channel_level("ch2", -30.0)
        monitor.record_channel_level("ch3", -40.0)

        status = monitor.get_status()
        assert len(status["channels"]) == 3

        # Find channels by ID
        ch_by_id = {ch["channel_id"]: ch for ch in status["channels"]}
        assert ch_by_id["ch1"]["level_db"] == -20.0
        assert ch_by_id["ch2"]["level_db"] == -30.0
        assert ch_by_id["ch3"]["level_db"] == -40.0

    def test_level_color_green(self):
        """Levels below -18dB should be green."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("ch1", -25.0)

        channels = monitor.get_status()["channels"]
        assert channels[0]["level_color"] == "green"

    def test_level_color_yellow(self):
        """Levels between -18dB and -6dB should be yellow."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("ch1", -12.0)

        channels = monitor.get_status()["channels"]
        assert channels[0]["level_color"] == "yellow"

    def test_level_color_red(self):
        """Levels above -6dB should be red."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("ch1", -3.0)

        channels = monitor.get_status()["channels"]
        assert channels[0]["level_color"] == "red"

    def test_no_signal_detection(self):
        """Should detect channels with no signal (below -90dB)."""
        monitor = AudioHealthMonitor()
        monitor.record_channel_level("ch1", -95.0)
        monitor.record_channel_level("ch2", -20.0)

        status = monitor.get_status()
        assert "ch1" in status["no_signal_channels"]
        assert "ch2" not in status["no_signal_channels"]

        ch_by_id = {ch["channel_id"]: ch for ch in status["channels"]}
        assert ch_by_id["ch1"]["has_signal"] is False
        assert ch_by_id["ch2"]["has_signal"] is True


class TestHardwareConfig:
    """Tests for hardware configuration tracking."""

    def test_set_hardware_config(self):
        """Should track hardware configuration."""
        monitor = AudioHealthMonitor()
        monitor.set_hardware_config(
            sample_rate=48000,
            buffer_size=1024,
            device_name="Test Device",
            num_channels=4,
            audio_format="int32",
        )

        hardware = monitor.get_status()["hardware"]
        assert hardware["sample_rate"] == 48000
        assert hardware["buffer_size"] == 1024
        assert hardware["device_name"] == "Test Device"
        assert hardware["num_channels"] == 4
        assert hardware["format"] == "int32"


class TestTimingStats:
    """Tests for callback timing statistics."""

    def test_callback_timing(self):
        """Should track callback timing."""
        monitor = AudioHealthMonitor()

        # Simulate callbacks
        monitor.record_callback_timing()
        time.sleep(0.01)  # 10ms
        monitor.record_callback_timing()
        time.sleep(0.01)
        monitor.record_callback_timing()

        timing = monitor.get_status()["timing"]
        assert timing["callback_count"] == 3
        assert timing["callback_interval_ms"] > 0

    def test_timing_min_max(self):
        """Should track min/max callback intervals."""
        monitor = AudioHealthMonitor()

        # First callback
        monitor.record_callback_timing()
        time.sleep(0.005)  # 5ms
        monitor.record_callback_timing()
        time.sleep(0.015)  # 15ms
        monitor.record_callback_timing()

        timing = monitor.get_status()["timing"]
        assert timing["min_interval_ms"] > 0
        assert timing["max_interval_ms"] >= timing["min_interval_ms"]


class TestSystemInfo:
    """Tests for system information retrieval."""

    def test_get_system_info(self):
        """Should return system information."""
        monitor = AudioHealthMonitor()
        system_info = monitor.get_system_info()

        assert hasattr(system_info, "cpu_percent")
        assert hasattr(system_info, "memory_percent")
        assert hasattr(system_info, "load_average")

    def test_system_info_in_status(self):
        """Status should include system information."""
        monitor = AudioHealthMonitor()
        status = monitor.get_status()

        assert "system" in status
        assert "cpu_percent" in status["system"]
        assert "memory_percent" in status["system"]


class TestGetStatus:
    """Tests for the get_status() method."""

    def test_status_structure(self):
        """Status should have expected structure."""
        monitor = AudioHealthMonitor()
        status = monitor.get_status()

        # Required top-level keys
        assert "running" in status
        assert "timestamp" in status
        assert "xrun" in status
        assert "channels" in status
        assert "hardware" in status
        assert "timing" in status
        assert "system" in status
        assert "session" in status

    def test_status_timestamp(self):
        """Status should have valid ISO timestamp."""
        monitor = AudioHealthMonitor()
        status = monitor.get_status()

        assert status["timestamp"].endswith("Z")
        # Should be parseable ISO format
        assert "T" in status["timestamp"]

    def test_session_duration(self):
        """Session should track duration."""
        monitor = AudioHealthMonitor()
        time.sleep(0.1)
        status = monitor.get_status()

        assert status["session"]["duration_seconds"] >= 0.1
        assert "started_at" in status["session"]


class TestGlobalSingleton:
    """Tests for global singleton access."""

    def test_get_audio_health_monitor(self):
        """Should return singleton instance."""
        reset_audio_health_monitor()
        monitor1 = get_audio_health_monitor()
        monitor2 = get_audio_health_monitor()

        assert monitor1 is monitor2

    def test_reset_creates_new_instance(self):
        """Reset should create new instance."""
        monitor1 = get_audio_health_monitor()
        monitor1.record_xrun(is_input_overflow=True)

        reset_audio_health_monitor()
        monitor2 = get_audio_health_monitor()

        assert monitor2.get_xrun_count() == 0


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_xrun_recording(self):
        """Should handle concurrent XRUN recording."""
        import threading

        monitor = AudioHealthMonitor()
        num_threads = 10
        xruns_per_thread = 100

        def record_xruns():
            for _ in range(xruns_per_thread):
                monitor.record_xrun(is_input_overflow=True)

        threads = [threading.Thread(target=record_xruns) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert monitor.get_xrun_count() == num_threads * xruns_per_thread
