"""Tests for audio source interfaces."""

from __future__ import annotations

import math
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus_agent_audio_motion.audio_source import (
    INT32_FULL_SCALE,
    ALSAAudioSource,
    AudioFrame,
    AudioSource,
    DefaultAudioInputSource,
    SyntheticAudioSource,
    create_audio_source,
)
from orpheus_agent_audio_motion.config import RuntimeSettings


class TestAudioFrame:
    """Tests for AudioFrame dataclass."""

    def test_audio_frame_creation(self) -> None:
        """AudioFrame should store channel, payload, and timestamp."""
        timestamp = datetime.now(timezone.utc)
        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test_audio_data",
            timestamp=timestamp,
        )
        assert frame.channel_id == "channel_1"
        assert frame.payload == b"test_audio_data"
        assert frame.timestamp == timestamp

    def test_audio_frame_frozen(self) -> None:
        """AudioFrame should be immutable (frozen dataclass)."""
        frame = AudioFrame(
            channel_id="test",
            payload=b"data",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(AttributeError):
            frame.channel_id = "modified"  # type: ignore


class MockAudioSource(AudioSource):
    """Mock implementation for testing the base class."""

    def __init__(self, sample_rate: int, frame_duration_ms: int, max_pending_frames: int) -> None:
        super().__init__(sample_rate, frame_duration_ms, max_pending_frames)
        self._start_called = False
        self._stop_called = False
        self._frames_to_emit = []

    async def _start_internal(self) -> None:
        self._start_called = True

    async def _stop_internal(self) -> None:
        self._stop_called = True

    async def _stream_internal(self) -> AsyncGenerator[AudioFrame, None]:
        for frame in self._frames_to_emit:
            yield frame

    def add_frame(self, frame: AudioFrame) -> None:
        """Add a frame to be emitted by stream."""
        self._frames_to_emit.append(frame)


class TestAudioSource:
    """Tests for AudioSource base class."""

    @pytest.mark.asyncio
    async def test_start_sets_running_flag(self) -> None:
        """Starting should set the running flag."""
        source = MockAudioSource(48000, 100, 50)
        assert not source.is_running()
        await source.start()
        assert source.is_running()
        assert source._start_called

    @pytest.mark.asyncio
    async def test_stop_clears_running_flag(self) -> None:
        """Stopping should clear the running flag."""
        source = MockAudioSource(48000, 100, 50)
        await source.start()
        assert source.is_running()
        await source.stop()
        assert not source.is_running()
        assert source._stop_called

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        """Starting multiple times should be safe."""
        source = MockAudioSource(48000, 100, 50)
        await source.start()
        await source.start()  # Should not raise
        assert source.is_running()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        """Stopping multiple times should be safe."""
        source = MockAudioSource(48000, 100, 50)
        await source.start()
        await source.stop()
        await source.stop()  # Should not raise
        assert not source.is_running()

    @pytest.mark.asyncio
    async def test_stream_frames_requires_start(self) -> None:
        """Streaming should fail if not started."""
        source = MockAudioSource(48000, 100, 50)
        with pytest.raises(RuntimeError, match="must be started"):
            async for _ in source.stream_frames():
                pass

    @pytest.mark.asyncio
    async def test_stream_frames_yields_data(self) -> None:
        """Streaming should yield frames from the source."""
        source = MockAudioSource(48000, 100, 50)
        frame1 = AudioFrame(
            channel_id="ch1",
            payload=b"data1",
            timestamp=datetime.now(timezone.utc),
        )
        frame2 = AudioFrame(
            channel_id="ch2",
            payload=b"data2",
            timestamp=datetime.now(timezone.utc),
        )
        source.add_frame(frame1)
        source.add_frame(frame2)

        await source.start()
        frames = []
        async for frame in source.stream_frames():
            frames.append(frame)

        assert len(frames) == 2
        assert frames[0] == frame1
        assert frames[1] == frame2

    def test_properties(self) -> None:
        """Properties should return configured values."""
        source = MockAudioSource(44100, 50, 100)
        assert source.sample_rate == 44100
        assert source.frame_duration_ms == 50
        assert source.max_pending_frames == 100


class TestSyntheticAudioSource:
    """Tests for SyntheticAudioSource."""

    @pytest.mark.asyncio
    async def test_synthetic_source_creates_frames(self) -> None:
        """Synthetic source should generate audio frames."""
        source = SyntheticAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            signal_type="sine",
            amplitude=0.5,
            channel_id="test_channel",
        )

        await source.start()

        # Collect a few frames
        frames = []
        async for frame in source.stream_frames():
            frames.append(frame)
            if len(frames) >= 3:
                break

        await source.stop()

        assert len(frames) == 3
        assert all(frame.channel_id == "test_channel" for frame in frames)
        assert all(len(frame.payload) > 0 for frame in frames)

    @pytest.mark.asyncio
    async def test_synthetic_source_silence(self) -> None:
        """Synthetic source should generate silence."""
        source = SyntheticAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            signal_type="silence",
        )

        await source.start()

        async for frame in source.stream_frames():
            # Convert bytes back to int16 array
            samples = np.frombuffer(frame.payload, dtype=np.int16)
            assert np.all(samples == 0)
            break

        await source.stop()

    def test_synthetic_source_invalid_signal_type(self) -> None:
        """Synthetic source should reject invalid signal types."""
        with pytest.raises(ValueError, match="Invalid signal_type"):
            SyntheticAudioSource(
                sample_rate=48000,
                frame_duration_ms=100,
                max_pending_frames=10,
                signal_type="invalid",
            )

    @pytest.mark.asyncio
    async def test_synthetic_source_white_noise(self) -> None:
        """Synthetic source should generate white noise."""
        source = SyntheticAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            signal_type="white_noise",
            amplitude=0.1,
        )

        await source.start()

        async for frame in source.stream_frames():
            # Convert bytes back to int16 array and normalize
            samples = np.frombuffer(frame.payload, dtype=np.int16)
            # White noise should have non-zero variance
            assert np.var(samples) > 0
            break

        await source.stop()


class TestALSAAudioSource:
    """Tests for ALSAAudioSource."""

    def test_parse_device_string_with_channel(self) -> None:
        """Should parse ALSA device string with channel."""
        source = ALSAAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            device_configs=[{"id": "1", "device": "alsa://orpheus_umc?channel=2"}],
        )
        assert source._device_name == "orpheus_umc"
        assert source._channel_map[1] == "1"  # channel 2 (1-indexed) -> index 1 (0-indexed)

    def test_parse_device_string_without_channel(self) -> None:
        """Should parse ALSA device string without channel (defaults to 1)."""
        source = ALSAAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            device_configs=[{"id": "channel_1", "device": "alsa://hw:2,0"}],
        )
        assert source._device_name == "hw:2,0"
        assert source._channel_map[0] == "channel_1"  # channel 1 (default) -> index 0

    def test_parse_invalid_device_string(self) -> None:
        """Should reject invalid device strings."""
        with pytest.raises(ValueError, match="Invalid ALSA device string"):
            ALSAAudioSource(
                sample_rate=48000,
                frame_duration_ms=100,
                max_pending_frames=10,
                device_configs=[{"id": "1", "device": "invalid://device"}],
            )

    def test_multi_channel_config(self) -> None:
        """Should handle multiple channels from same device."""
        source = ALSAAudioSource(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=10,
            device_configs=[
                {"id": "channel_1", "device": "alsa://orpheus_umc?channel=1"},
                {"id": "channel_2", "device": "alsa://orpheus_umc?channel=2"},
                {"id": "channel_3", "device": "alsa://orpheus_umc?channel=3"},
                {"id": "channel_4", "device": "alsa://orpheus_umc?channel=4"},
            ],
        )
        assert source._device_name == "orpheus_umc"
        assert source._num_channels == 4
        assert source._channel_map[0] == "channel_1"
        assert source._channel_map[1] == "channel_2"
        assert source._channel_map[2] == "channel_3"
        assert source._channel_map[3] == "channel_4"

    def test_different_devices_rejected(self) -> None:
        """Should reject configs with different base devices."""
        with pytest.raises(ValueError, match="same device"):
            ALSAAudioSource(
                sample_rate=48000,
                frame_duration_ms=100,
                max_pending_frames=10,
                device_configs=[
                    {"id": "1", "device": "alsa://device1?channel=1"},
                    {"id": "2", "device": "alsa://device2?channel=1"},
                ],
            )


class TestCreateAudioSource:
    """Tests for create_audio_source factory."""

    @pytest.mark.asyncio
    async def test_factory_creates_synthetic_source(self, monkeypatch) -> None:
        """Factory should create synthetic source when env var is set."""
        monkeypatch.setenv("ORPHEUS_AUDIO_SOURCE_TYPE", "synthetic")

        settings = RuntimeSettings(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=50,
            working_directory=Path("/tmp"),
        )

        source = await create_audio_source(settings)
        assert isinstance(source, SyntheticAudioSource)

    @pytest.mark.asyncio
    async def test_factory_creates_default_source_when_no_config(self, monkeypatch) -> None:
        """Factory should create default source when no device configured."""
        # Ensure synthetic mode is off
        monkeypatch.delenv("ORPHEUS_AUDIO_SOURCE_TYPE", raising=False)

        settings = RuntimeSettings(
            sample_rate=48000,
            frame_duration_ms=100,
            max_pending_frames=50,
            working_directory=Path("/tmp"),
        )

        # Mock OrpheusConfig to raise an exception, forcing fallback to default
        def mock_get_instance():
            raise RuntimeError("Config not available in test")

        monkeypatch.setattr(
            "orpheus_common.config.OrpheusConfig.get_instance",
            mock_get_instance,
        )

        # This will fall back to default if config loading fails
        source = await create_audio_source(settings)
        assert isinstance(source, DefaultAudioInputSource)


class TestDefaultAudioInputSourceCallback:
    """Tests for DefaultAudioInputSource audio callback logic."""

    @pytest.mark.asyncio
    async def test_callback_records_peak_level_for_nonzero_signal(self) -> None:
        """Callback should compute peak dB level and pass it to the health monitor."""
        captured_callback = {}

        class MockStream:
            def __init__(self, **kwargs):
                captured_callback["fn"] = kwargs["callback"]

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        mock_health = MagicMock()

        with patch("orpheus_agent_audio_motion.audio_source.sd.InputStream", MockStream):
            with patch(
                "orpheus_agent_audio_motion.audio_source.get_audio_health_monitor",
                return_value=mock_health,
            ):
                source = DefaultAudioInputSource(
                    sample_rate=48000,
                    frame_duration_ms=21,
                    max_pending_frames=10,
                    channel_id="test_ch",
                )
                await source.start()

        assert "fn" in captured_callback, "callback was not captured from InputStream"
        callback = captured_callback["fn"]

        # Simulate a non-zero signal at half full scale (int32)
        amplitude = INT32_FULL_SCALE / 2
        indata = np.full((1024, 1), amplitude, dtype=np.float64)
        callback(indata, 1024, None, None)

        # The peak amplitude dB should be ~-6 dBFS (half scale)
        expected_db = 20 * math.log10(amplitude / INT32_FULL_SCALE)
        mock_health.record_channel_level.assert_called_once_with(
            "test_ch", pytest.approx(expected_db, abs=0.1)
        )

        await source.stop()

    @pytest.mark.asyncio
    async def test_callback_uses_minus100_for_silence(self) -> None:
        """Callback should report -100 dB when signal is exactly zero."""
        captured_callback = {}

        class MockStream:
            def __init__(self, **kwargs):
                captured_callback["fn"] = kwargs["callback"]

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        mock_health = MagicMock()

        with patch("orpheus_agent_audio_motion.audio_source.sd.InputStream", MockStream):
            with patch(
                "orpheus_agent_audio_motion.audio_source.get_audio_health_monitor",
                return_value=mock_health,
            ):
                source = DefaultAudioInputSource(
                    sample_rate=48000,
                    frame_duration_ms=21,
                    max_pending_frames=10,
                    channel_id="silence_ch",
                )
                await source.start()

        callback = captured_callback["fn"]

        # All-zero signal → peak is 0 → level_db should be -100.0
        indata = np.zeros((1024, 1), dtype=np.float64)
        callback(indata, 1024, None, None)

        mock_health.record_channel_level.assert_called_once_with("silence_ch", -100.0)

        await source.stop()


class TestALSAAudioSourceCallback:
    """Tests for ALSAAudioSource multi-channel audio callback logic."""

    @pytest.mark.asyncio
    async def test_callback_records_peak_level_per_channel(self) -> None:
        """ALSA callback should compute peak dB per channel and report to health monitor."""
        captured_callback = {}

        class MockStream:
            def __init__(self, **kwargs):
                captured_callback["fn"] = kwargs["callback"]

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        mock_health = MagicMock()
        mock_device_info = {"max_input_channels": 4}

        with patch("orpheus_agent_audio_motion.audio_source.sd.InputStream", MockStream):
            with patch("orpheus_agent_audio_motion.audio_source.sd.query_devices") as mock_qd:
                with patch(
                    "orpheus_agent_audio_motion.audio_source.get_audio_health_monitor",
                    return_value=mock_health,
                ):
                    # query_devices called twice: first to find device, then to get info
                    mock_qd.side_effect = [
                        [{"name": "orpheus_umc", "max_input_channels": 4}],
                        mock_device_info,
                    ]
                    source = ALSAAudioSource(
                        sample_rate=48000,
                        frame_duration_ms=21,
                        max_pending_frames=10,
                        device_configs=[
                            {"id": "1", "device": "alsa://orpheus_umc?channel=1"},
                            {"id": "2", "device": "alsa://orpheus_umc?channel=2"},
                        ],
                    )
                    await source.start()

        assert "fn" in captured_callback
        callback = captured_callback["fn"]

        # Two-channel frame: ch0 at half scale, ch1 at quarter scale
        indata = np.zeros((1024, 2), dtype=np.int32)
        indata[:, 0] = int(INT32_FULL_SCALE / 2)
        indata[:, 1] = int(INT32_FULL_SCALE / 4)

        callback(indata, 1024, None, None)

        calls = {
            call.args[0]: call.args[1] for call in mock_health.record_channel_level.call_args_list
        }
        expected_ch0 = 20 * math.log10((INT32_FULL_SCALE / 2) / INT32_FULL_SCALE)
        expected_ch1 = 20 * math.log10((INT32_FULL_SCALE / 4) / INT32_FULL_SCALE)
        assert calls["1"] == pytest.approx(expected_ch0, abs=0.1)
        assert calls["2"] == pytest.approx(expected_ch1, abs=0.1)

        await source.stop()

    @pytest.mark.asyncio
    async def test_callback_silence_reports_minus100(self) -> None:
        """ALSA callback should report -100 dB for a silent channel."""
        captured_callback = {}

        class MockStream:
            def __init__(self, **kwargs):
                captured_callback["fn"] = kwargs["callback"]

            def start(self):
                pass

            def stop(self):
                pass

            def close(self):
                pass

        mock_health = MagicMock()
        mock_device_info = {"max_input_channels": 2}

        with patch("orpheus_agent_audio_motion.audio_source.sd.InputStream", MockStream):
            with patch("orpheus_agent_audio_motion.audio_source.sd.query_devices") as mock_qd:
                with patch(
                    "orpheus_agent_audio_motion.audio_source.get_audio_health_monitor",
                    return_value=mock_health,
                ):
                    mock_qd.side_effect = [
                        [{"name": "orpheus_umc", "max_input_channels": 2}],
                        mock_device_info,
                    ]
                    source = ALSAAudioSource(
                        sample_rate=48000,
                        frame_duration_ms=21,
                        max_pending_frames=10,
                        device_configs=[{"id": "1", "device": "alsa://orpheus_umc?channel=1"}],
                    )
                    await source.start()

        callback = captured_callback["fn"]

        indata = np.zeros((1024, 1), dtype=np.int32)
        callback(indata, 1024, None, None)

        mock_health.record_channel_level.assert_called_once_with("1", -100.0)

        await source.stop()
