"""Tests for channel processing pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from unittest.mock import Mock

import pytest

from orpheus_agent_audio_motion.audio_source import AudioFrame
from orpheus_agent_audio_motion.channel_processor import ChannelProcessor
from orpheus_agent_audio_motion.clip_saver import ClipSaver
from orpheus_agent_audio_motion.detector_algorithm import (
    DetectionEvent,
    DetectorAlgorithm,
)


class MockDetector(DetectorAlgorithm):
    """Mock detector for testing."""

    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self.detection_result: Optional[DetectionEvent] = None
        self.should_raise = False

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        if self.should_raise:
            raise RuntimeError("Mock detector error")
        return self.detection_result


class TestChannelProcessor:
    """Tests for ChannelProcessor."""

    @pytest.mark.asyncio
    async def test_handle_frame_ignores_wrong_channel(self) -> None:
        """Processor should ignore frames for other channels."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        detector = MockDetector({})

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
        )

        frame = AudioFrame(
            channel_id="channel_2",  # Different channel
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should not publish anything
        mqtt_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_frame_no_detection(self) -> None:
        """Processor should not publish when no detection occurs."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        detector = MockDetector({})
        detector.detection_result = None  # No detection

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
        )

        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should not publish anything
        mqtt_client.publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_frame_with_detection(self) -> None:
        """Processor should publish detection events to MQTT."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/clip.wav")

        detector = MockDetector({})
        event_time = datetime.now(timezone.utc)
        detector.detection_result = DetectionEvent(
            channel_id="channel_1",
            timestamp=event_time,
            duration_seconds=1.5,
            peak_energy_db=-25.0,
            average_energy_db=-30.0,
            audio_frames=[b"audio_data"],
            metadata={"test": "data"},
        )

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="test/events",
            topic_status="test/status",
            qos=2,
        )

        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should save clip (concatenated audio_frames)
        clip_saver.save_clip.assert_called_once()
        call_args = clip_saver.save_clip.call_args
        assert call_args.kwargs["channel_id"] == "channel_1"
        assert call_args.kwargs["payload"] == b"testaudio_data"  # Prebuffer + detection frames
        assert call_args.kwargs["event_time"] == event_time

        # Should publish event
        mqtt_client.publish.assert_called_once()
        call_args = mqtt_client.publish.call_args
        assert call_args.kwargs["topic"] == "test/events"
        payload = call_args.kwargs["payload"]
        assert payload["detection_type"] == "audio.motion"
        assert payload["audio_clip_path"] == "/tmp/clip.wav"
        assert payload["metadata"]["channel_id"] == "channel_1"
        assert payload["metadata"]["duration_seconds"] == 1.5
        assert payload["metadata"]["peak_energy_db"] == -25.0
        assert payload["metadata"]["average_energy_db"] == -30.0
        assert payload["metadata"]["test"] == "data"
        assert payload["context"]["sensor_id"] == "mic-channel_1"
        assert call_args.kwargs["qos"] == 2

    @pytest.mark.asyncio
    async def test_handle_frame_detection_without_clip(self) -> None:
        """Processor should handle detections without clip payloads."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        detector = MockDetector({})
        event_time = datetime.now(timezone.utc)
        detector.detection_result = DetectionEvent(
            channel_id="channel_1",
            timestamp=event_time,
            duration_seconds=0.8,
            peak_energy_db=-28.0,
            average_energy_db=-32.0,
            audio_frames=[],  # No audio frames
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
        )

        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should not save clip (no audio frames)
        clip_saver.save_clip.assert_not_called()

        # Should publish event without clip_path
        mqtt_client.publish.assert_called_once()
        call_args = mqtt_client.publish.call_args
        payload = call_args.kwargs["payload"]
        assert payload["audio_clip_path"] is None
        assert payload["metadata"]["frame_count"] == 0
        assert payload["detection_type"] == "audio.motion"

    @pytest.mark.asyncio
    async def test_handle_frame_detector_error(self) -> None:
        """Processor should handle detector errors gracefully."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        detector = MockDetector({})
        detector.should_raise = True  # Force error

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
        )

        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should publish status error
        mqtt_client.publish.assert_called_once()
        call_args = mqtt_client.publish.call_args
        assert call_args.kwargs["topic"] == "status"
        payload = call_args.kwargs["payload"]
        assert payload["state"] == "error"

    @pytest.mark.asyncio
    async def test_handle_frame_clip_save_error(self) -> None:
        """Processor should handle clip save errors gracefully."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.side_effect = OSError("Disk full")

        detector = MockDetector({})
        detector.detection_result = DetectionEvent(
            channel_id="channel_1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=2.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[b"audio"],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="channel_1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
        )

        frame = AudioFrame(
            channel_id="channel_1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Should publish both status warning and event
        assert mqtt_client.publish.call_count == 2
