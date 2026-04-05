"""Tests for the ChannelProcessor time-aware pre-roll ring buffer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import Mock

import numpy as np
import pytest

from orpheus_agent_audio_motion.audio_source import AudioFrame
from orpheus_agent_audio_motion.channel_processor import ChannelProcessor
from orpheus_agent_audio_motion.clip_saver import ClipSaver
from orpheus_agent_audio_motion.detector_algorithm import (
    DetectionEvent,
    DetectorAlgorithm,
)


def _make_frame(channel_id: str = "ch1", n_samples: int = 1008) -> AudioFrame:
    """Create a realistic AudioFrame with int32 PCM payload."""
    samples = np.zeros(n_samples, dtype=np.int32)
    return AudioFrame(
        channel_id=channel_id,
        payload=samples.tobytes(),
        timestamp=datetime.now(timezone.utc),
    )


class _StubDetector(DetectorAlgorithm):
    """Minimal detector stub for testing."""

    def __init__(self) -> None:
        super().__init__({})
        self.detection_result: Optional[DetectionEvent] = None

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        return self.detection_result

    def _get_trigger_threshold(self) -> float:
        return -25.0


class TestPrebufferRingBuffer:
    """Verify that the ChannelProcessor pre-roll ring buffer works correctly."""

    def _make_processor(
        self,
        detector: _StubDetector,
        prebuffer_seconds: float = 0.5,
        sample_rate: int = 48000,
        pre_roll_seconds: int = 5,
        chunks_per_second: int = 47,
    ) -> ChannelProcessor:
        return ChannelProcessor(
            channel_id="ch1",
            detector=detector,
            mqtt_client=Mock(),
            clip_saver=Mock(spec=ClipSaver),
            topic_events="events",
            topic_status="status",
            qos=1,
            prebuffer_seconds=prebuffer_seconds,
            sample_rate=sample_rate,
            pre_roll_seconds=pre_roll_seconds,
            chunks_per_second=chunks_per_second,
        )

    @pytest.mark.asyncio
    async def test_ring_buffer_capacity_based_on_constructor_params(self) -> None:
        """Buffer capacity is pre_roll_seconds * chunks_per_second."""
        from orpheus_common.utils.buffer import PreRollRingBuffer

        detector = _StubDetector()
        processor = self._make_processor(detector, pre_roll_seconds=3, chunks_per_second=10)

        assert isinstance(processor._pre_roll_buffer, PreRollRingBuffer)
        assert processor._pre_roll_buffer._max_len == 30  # 3s * 10 chunks/s

    @pytest.mark.asyncio
    async def test_ring_buffer_different_capacities_for_different_params(self) -> None:
        """Two processors with different params should have different capacities."""
        det1 = _StubDetector()
        det2 = _StubDetector()

        p_small = self._make_processor(det1, pre_roll_seconds=2, chunks_per_second=10)
        p_large = self._make_processor(det2, pre_roll_seconds=5, chunks_per_second=47)

        assert p_small._pre_roll_buffer._max_len == 20
        assert p_large._pre_roll_buffer._max_len == 235

    @pytest.mark.asyncio
    async def test_ring_buffer_evicts_oldest_frames(self) -> None:
        """After exceeding capacity, the oldest chunks should be evicted."""
        detector = _StubDetector()
        # capacity = 1s * 1 chunk/s = 1 slot
        processor = self._make_processor(detector, pre_roll_seconds=1, chunks_per_second=1)
        payload_a = np.zeros(1, dtype=np.int32).tobytes()
        payload_b = np.ones(1, dtype=np.int32).tobytes()
        payload_c = np.full(1, 2, dtype=np.int32).tobytes()

        now = datetime.now(timezone.utc)
        frame_a = AudioFrame(channel_id="ch1", payload=payload_a, timestamp=now)
        frame_b = AudioFrame(channel_id="ch1", payload=payload_b, timestamp=now)
        frame_c = AudioFrame(channel_id="ch1", payload=payload_c, timestamp=now)

        await processor.handle_frame(frame_a)
        await processor.handle_frame(frame_b)
        await processor.handle_frame(frame_c)

        # Only the most recent chunk should remain (capacity=1)
        snapshot = processor._pre_roll_buffer.get_snapshot()
        assert len(snapshot) == 1
        assert snapshot[0] == payload_c

    @pytest.mark.asyncio
    async def test_ring_buffer_ignores_wrong_channel(self) -> None:
        """Frames for other channels should not enter the ring buffer."""
        detector = _StubDetector()
        processor = self._make_processor(detector)

        wrong = AudioFrame(
            channel_id="other",
            payload=np.zeros(1008, dtype=np.int32).tobytes(),
            timestamp=datetime.now(timezone.utc),
        )
        await processor.handle_frame(wrong)

        assert len(processor._pre_roll_buffer) == 0


class TestPreRollMetadata:
    """Verify that pre_roll_ms, event_type, and prepended prebuffer bytes
    are correctly passed to ClipSaver."""

    @pytest.mark.asyncio
    async def test_prebuffer_bytes_prepended_to_detection_frames(self) -> None:
        """The payload passed to save_clip must include prebuffer + detection bytes."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/clip.flac")

        detector = _StubDetector()

        # 1008 samples @ 48 kHz → 21 ms per frame
        frame_payload = np.zeros(1008, dtype=np.int32).tobytes()
        detection_frame_count = 3

        detector.detection_result = DetectionEvent(
            channel_id="ch1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=1.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[frame_payload] * detection_frame_count,
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="ch1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
            prebuffer_seconds=0.5,
            sample_rate=48000,
        )

        # Feed 2 frames into the prebuffer BEFORE the detection fires
        prebuffer_frame_count = 2
        for _ in range(prebuffer_frame_count):
            detector.detection_result = None  # no detection yet
            await processor.handle_frame(_make_frame())

        # Now trigger the detection on the 3rd frame
        detector.detection_result = DetectionEvent(
            channel_id="ch1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=1.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[frame_payload] * detection_frame_count,
            metadata={},
        )
        await processor.handle_frame(_make_frame())

        clip_saver.save_clip.assert_called_once()
        call_kwargs = clip_saver.save_clip.call_args.kwargs

        # The prebuffer contains 3 frames: the 2 pre-detection frames plus
        # the trigger frame itself (pushed to prebuffer before detect_motion runs).
        expected_prebuffer_frames = prebuffer_frame_count + 1
        expected_total = (expected_prebuffer_frames + detection_frame_count) * len(frame_payload)
        assert len(call_kwargs["payload"]) == expected_total

    @pytest.mark.asyncio
    async def test_pre_roll_ms_based_on_actual_prebuffer(self) -> None:
        """pre_roll_ms should reflect the actual ring buffer contents."""
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/clip.flac")

        detector = _StubDetector()

        # 1008 samples @ 48 kHz → 21 ms per frame
        frame_payload = np.zeros(1008, dtype=np.int32).tobytes()

        processor = ChannelProcessor(
            channel_id="ch1",
            detector=detector,
            mqtt_client=Mock(),
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
            prebuffer_seconds=0.5,
            sample_rate=48000,
        )

        # Feed 2 frames before detection
        for _ in range(2):
            detector.detection_result = None
            await processor.handle_frame(_make_frame())

        # Trigger detection on 3rd frame
        detector.detection_result = DetectionEvent(
            channel_id="ch1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=1.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[frame_payload],
            metadata={},
        )
        await processor.handle_frame(_make_frame())

        clip_saver.save_clip.assert_called_once()
        meta = clip_saver.save_clip.call_args.kwargs["metadata"]
        assert meta["event_type"] == "motion"
        # 3 frames in prebuffer × 1008 samples / 48000 Hz × 1000 = 63 ms
        assert meta["pre_roll_ms"] == 63

    @pytest.mark.asyncio
    async def test_pre_roll_ms_includes_trigger_frame(self) -> None:
        """When detection fires on the first frame, prebuffer contains that frame."""
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/clip.flac")

        detector = _StubDetector()
        detector.detection_result = DetectionEvent(
            channel_id="ch1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=1.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[b"\x00" * 4032],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="ch1",
            detector=detector,
            mqtt_client=Mock(),
            clip_saver=clip_saver,
            topic_events="e",
            topic_status="s",
            qos=1,
            prebuffer_seconds=0.5,
            sample_rate=48000,
        )

        # First frame triggers detection immediately → prebuffer has 1 frame
        await processor.handle_frame(_make_frame())

        meta = clip_saver.save_clip.call_args.kwargs["metadata"]
        # Prebuffer has 1 frame of 1008 samples → 1008/48000*1000 = 21 ms
        assert meta["pre_roll_ms"] == 21
