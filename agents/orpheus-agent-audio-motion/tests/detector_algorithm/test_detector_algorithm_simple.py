"""Tests for the motion detector algorithm implementations."""

from __future__ import annotations

import struct
import threading
import time
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from orpheus_agent_audio_motion.audio_source import AudioFrame
from orpheus_agent_audio_motion.detector_algorithm import (
    AdaptiveThresholdDetector,
    DetectorAlgorithm,
    FixedThresholdDetector,
    create_detector,
)


def generate_pcm_audio(amplitude: float, num_samples: int = 1024) -> bytes:
    """
    Generate synthetic PCM int16 audio for testing.

    Args:
        amplitude: Signal amplitude (0.0 to 1.0 of full scale).
        num_samples: Number of samples to generate.

    Returns:
        PCM bytes (int16 little-endian).
    """
    # Generate sine wave at amplitude
    samples = (amplitude * 32767 * np.sin(2 * np.pi * 440 * np.arange(num_samples) / 48000)).astype(
        np.int16
    )
    return samples.tobytes()


class TestDetectorAlgorithmBase:
    """Tests for base DetectorAlgorithm class."""

    def test_base_class_raises_not_implemented(self) -> None:
        """Base class should raise NotImplementedError on detect_motion."""
        detector = DetectorAlgorithm(settings={})
        frame = AudioFrame(
            channel_id="test_channel",
            payload=b"\x00\x00",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(NotImplementedError):
            detector.detect_motion(frame)

    def test_settings_property(self) -> None:
        """Settings property should return the provided settings dict."""
        settings = {"threshold_db": -20.0, "margin_db": 5.0}
        detector = DetectorAlgorithm(settings=settings)
        assert detector.settings == settings

    def test_calculate_energy_db_silence(self) -> None:
        """Silence (zeros) should return floor value."""
        silence = b"\x00\x00" * 1024
        energy_db = DetectorAlgorithm._calculate_energy_db(silence)
        assert energy_db == -96.0

    def test_calculate_energy_db_full_scale(self) -> None:
        """Full-scale signal should be close to 0 dB."""
        # Generate full-scale int16 values
        full_scale = struct.pack("<" + "h" * 1024, *([32767] * 1024))
        energy_db = DetectorAlgorithm._calculate_energy_db(full_scale)
        # Full scale RMS should be very close to 0 dB
        assert -1.0 < energy_db < 1.0

    def test_calculate_energy_db_half_scale(self) -> None:
        """Half-scale signal should be approximately -6 dB."""
        half_scale = struct.pack("<" + "h" * 1024, *([16384] * 1024))
        energy_db = DetectorAlgorithm._calculate_energy_db(half_scale)
        # Half amplitude = -6 dB
        assert -7.0 < energy_db < -5.0

    def test_calculate_energy_db_empty_payload(self) -> None:
        """Empty payload should return silence floor."""
        energy_db = DetectorAlgorithm._calculate_energy_db(b"")
        assert energy_db == -96.0


class TestFixedThresholdDetector:
    """Tests for FixedThresholdDetector."""

    def test_initialization_with_defaults(self) -> None:
        """Detector should initialize with default settings."""
        detector = FixedThresholdDetector(settings={})
        assert detector.settings == {}
        assert detector._threshold_db == -25.0
        assert detector._margin_db == 3.0

    def test_initialization_with_custom_settings(self) -> None:
        """Detector should use provided settings."""
        settings = {"threshold_db": -30.0, "margin_db": 5.0}
        detector = FixedThresholdDetector(settings=settings)
        assert detector._threshold_db == -30.0
        assert detector._margin_db == 5.0

    def test_no_detection_below_threshold(self) -> None:
        """Quiet signal should not trigger detection."""
        detector = FixedThresholdDetector(settings={"threshold_db": -20.0, "margin_db": 3.0})
        # Generate very quiet signal (well below -23 dB trigger level)
        quiet_audio = generate_pcm_audio(amplitude=0.001, num_samples=1024)
        frame = AudioFrame(
            channel_id="test_ch",
            payload=quiet_audio,
            timestamp=datetime.now(timezone.utc),
        )
        result = detector.detect_motion(frame)
        assert result is None

    def test_detection_above_threshold(self) -> None:
        """Loud signal should trigger detection with stateful recording."""
        detector = FixedThresholdDetector(
            settings={
                "threshold_db": -30.0,
                "margin_db": 3.0,
                "holdoff_seconds": 0.1,  # Short holdoff for test
                "min_duration_seconds": 0.01,  # Very short minimum
            }
        )

        base_time = datetime.now(timezone.utc)
        result = None

        # Send loud frames to trigger and record
        for i in range(5):
            loud_audio = generate_pcm_audio(amplitude=0.5, num_samples=1024)
            frame = AudioFrame(
                channel_id="test_ch",
                payload=loud_audio,
                timestamp=base_time + timedelta(milliseconds=i * 21),
            )
            result = detector.detect_motion(frame)
            if result:
                break

        # Send quiet frames to trigger holdoff and completion
        if not result:
            for i in range(10):
                quiet_audio = generate_pcm_audio(amplitude=0.001, num_samples=1024)
                frame = AudioFrame(
                    channel_id="test_ch",
                    payload=quiet_audio,
                    timestamp=base_time + timedelta(milliseconds=(5 + i) * 21),
                )
                result = detector.detect_motion(frame)
                if result:
                    break

        assert result is not None
        assert result.channel_id == "test_ch"
        assert result.duration_seconds > 0
        assert result.peak_energy_db > -30.0
        assert len(result.audio_frames) > 0

    def test_confidence_calculation(self) -> None:
        """Peak energy should increase with signal strength."""
        peak_energies = []

        for amplitude in [0.1, 0.3, 0.5, 0.7]:
            detector = FixedThresholdDetector(
                settings={
                    "threshold_db": -40.0,
                    "margin_db": 0.0,
                    "holdoff_seconds": 0.05,
                    "min_duration_seconds": 0.01,
                }
            )

            base_time = datetime.now(timezone.utc)
            result = None

            # Send loud frames
            for i in range(5):
                audio = generate_pcm_audio(amplitude=amplitude, num_samples=1024)
                frame = AudioFrame(
                    channel_id="test_ch",
                    payload=audio,
                    timestamp=base_time + timedelta(milliseconds=i * 21),
                )
                detector.detect_motion(frame)

            # Send quiet frames to complete event
            for i in range(10):
                quiet_audio = generate_pcm_audio(amplitude=0.001, num_samples=1024)
                frame = AudioFrame(
                    channel_id="test_ch",
                    payload=quiet_audio,
                    timestamp=base_time + timedelta(milliseconds=(5 + i) * 21),
                )
                result = detector.detect_motion(frame)
                if result:
                    break

            if result:
                peak_energies.append(result.peak_energy_db)

        # Peak energies should be monotonically increasing
        assert len(peak_energies) > 0
        assert peak_energies == sorted(peak_energies)


class TestAdaptiveThresholdDetector:
    """Tests for AdaptiveThresholdDetector."""

    def test_initialization_with_defaults(self) -> None:
        """Detector should initialize with default settings."""
        detector = AdaptiveThresholdDetector(settings={})
        assert detector._threshold_db == -25.0
        assert detector._margin_db == 3.0
        assert detector._window_seconds == 30.0
        assert detector._update_interval_seconds == 5.0
        assert len(detector._energy_history) == 0

    def test_initialization_with_custom_settings(self) -> None:
        """Detector should use provided settings."""
        settings = {
            "threshold_db": -35.0,
            "margin_db": 5.0,
            "window_seconds": 60.0,
            "update_interval_seconds": 10.0,
        }
        detector = AdaptiveThresholdDetector(settings=settings)
        assert detector._threshold_db == -35.0
        assert detector._margin_db == 5.0
        assert detector._window_seconds == 60.0
        assert detector._update_interval_seconds == 10.0

    def test_builds_energy_history(self) -> None:
        """Detector should accumulate energy samples in history."""
        detector = AdaptiveThresholdDetector(
            settings={"window_seconds": 10.0, "update_interval_seconds": 100.0}
        )

        # Send several frames
        for i in range(5):
            audio = generate_pcm_audio(amplitude=0.1, num_samples=512)
            frame = AudioFrame(
                channel_id="test_ch",
                payload=audio,
                timestamp=datetime.now(timezone.utc),
            )
            detector.detect_motion(frame)

        assert len(detector._energy_history) == 5

    def test_trims_old_samples(self) -> None:
        """Detector should remove samples outside the window."""
        detector = AdaptiveThresholdDetector(
            settings={"window_seconds": 1.0, "update_interval_seconds": 100.0}
        )

        base_time = datetime.now(timezone.utc)

        # Add samples spanning 3 seconds
        for i in range(6):
            audio = generate_pcm_audio(amplitude=0.1, num_samples=512)
            frame = AudioFrame(
                channel_id="test_ch",
                payload=audio,
                timestamp=base_time + timedelta(seconds=i * 0.5),
            )
            detector.detect_motion(frame)

        # Only samples from the last 1 second should remain (last 2-3 samples)
        assert len(detector._energy_history) <= 3

    def test_threshold_updates_periodically(self) -> None:
        """Threshold should update after update_interval_seconds."""
        base_time = datetime.now(timezone.utc)
        detector = AdaptiveThresholdDetector(
            settings={
                "threshold_db": -30.0,  # High threshold so quiet signals don't trigger
                "margin_db": 10.0,
                "window_seconds": 2.0,
                "update_interval_seconds": 0.5,
            }
        )
        # Set last_update_time to base_time so our frame timestamps work correctly
        detector._last_update_time = base_time

        initial_threshold = detector._threshold_db

        # Send frames over 2.5 seconds with moderate energy (won't trigger recording)
        # Use quieter amplitude so we stay in IDLE state and build energy history
        for i in range(25):
            audio = generate_pcm_audio(amplitude=0.01, num_samples=512)  # Very quiet
            frame = AudioFrame(
                channel_id="test_ch",
                payload=audio,
                timestamp=base_time + timedelta(milliseconds=i * 100),
            )
            detector.detect_motion(frame)

        # Threshold should have been updated at least once
        # With consistent low-energy signals, threshold should adapt downward
        assert detector._threshold_db != initial_threshold
        assert len(detector._energy_history) > 0, "Energy history should have samples"

    def test_threshold_adapts_to_noise_floor(self) -> None:
        """Adaptive threshold should adjust based on ambient noise."""
        base_time = datetime.now(timezone.utc)
        detector = AdaptiveThresholdDetector(
            settings={
                "threshold_db": -30.0,  # Start high
                "margin_db": 10.0,  # High margin so quiet signals don't trigger
                "window_seconds": 1.0,
                "update_interval_seconds": 0.2,
            }
        )
        # Set last_update_time to base_time so our frame timestamps work correctly
        detector._last_update_time = base_time

        # Send consistent very low-level noise (won't trigger recording)
        for i in range(20):
            audio = generate_pcm_audio(amplitude=0.001, num_samples=512)  # Very quiet
            frame = AudioFrame(
                channel_id="test_ch",
                payload=audio,
                timestamp=base_time + timedelta(milliseconds=i * 100),
            )
            detector.detect_motion(frame)

        # Threshold should have adapted down toward the noise floor
        # Since we're sending consistent quiet signals, threshold should decrease
        assert detector._threshold_db < -30.0
        assert len(detector._energy_history) > 0, "Energy history should have samples"

    def test_thread_safety(self) -> None:
        """Multiple threads should be able to call detect_motion safely."""
        detector = AdaptiveThresholdDetector(settings={"update_interval_seconds": 0.1})

        results = []
        errors = []

        def worker():
            try:
                for _ in range(20):
                    audio = generate_pcm_audio(amplitude=0.2, num_samples=256)
                    frame = AudioFrame(
                        channel_id="test_ch",
                        payload=audio,
                        timestamp=datetime.now(timezone.utc),
                    )
                    result = detector.detect_motion(frame)
                    results.append(result)
                    time.sleep(0.01)
            except Exception as e:
                errors.append(e)

        # Spawn multiple threads
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        assert len(errors) == 0
        assert len(results) == 60  # 3 threads × 20 frames

    def test_max_threshold_change_limit(self) -> None:
        """Threshold changes should be limited to prevent sudden jumps."""
        detector = AdaptiveThresholdDetector(
            settings={
                "threshold_db": -50.0,
                "window_seconds": 1.0,
                "update_interval_seconds": 0.5,
            }
        )

        base_time = datetime.now(timezone.utc)

        # Send very quiet signals to build history
        for i in range(5):
            audio = generate_pcm_audio(amplitude=0.001, num_samples=512)
            frame = AudioFrame(
                channel_id="test_ch",
                payload=audio,
                timestamp=base_time + timedelta(seconds=i * 0.6),
            )
            detector.detect_motion(frame)

        # With 5 frames at 0.6s intervals (3s total) and 0.5s update interval,
        # we can have up to 6 updates. Max change is 10 dB per update.
        # Starting at -50.0, worst case is -50 - (6 * 10) = -110 dB
        # But in practice, it should converge towards the actual signal level
        assert detector._threshold_db < -50.0  # Should have decreased
        assert detector._threshold_db > -100.0  # But not too much


class TestCreateDetector:
    """Tests for the create_detector factory function."""

    def test_create_fixed_threshold_detector(self) -> None:
        """Factory should create FixedThresholdDetector."""
        detector = create_detector("fixed_threshold", {"threshold_db": -20.0})
        assert isinstance(detector, FixedThresholdDetector)

    def test_create_adaptive_threshold_detector(self) -> None:
        """Factory should create AdaptiveThresholdDetector."""
        detector = create_detector("adaptive_threshold", {"threshold_db": -30.0})
        assert isinstance(detector, AdaptiveThresholdDetector)

    def test_create_detector_case_insensitive(self) -> None:
        """Algorithm names should be case-insensitive."""
        detector1 = create_detector("FIXED_THRESHOLD", {})
        detector2 = create_detector("Fixed_Threshold", {})
        detector3 = create_detector("AdApTiVe_ThReShOlD", {})

        assert isinstance(detector1, FixedThresholdDetector)
        assert isinstance(detector2, FixedThresholdDetector)
        assert isinstance(detector3, AdaptiveThresholdDetector)

    def test_create_detector_unknown_algorithm(self) -> None:
        """Factory should raise ValueError for unknown algorithms."""
        with pytest.raises(ValueError, match="Unknown detector algorithm"):
            create_detector("nonexistent_algorithm", {})
