"""Tests for spatiotemporal context propagation in audio motion agent."""

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

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        return self.detection_result


class TestContextPropagation:
    """Tests verifying spatiotemporal context is stamped on audio events."""

    @pytest.mark.asyncio
    async def test_gps_location_stamped_on_detection(self) -> None:
        """After a GPS update, detection events should include lat/lon in context."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        location_cache: dict[str, Any] = {"lat": 40.7128, "lon": -74.0060}

        detector = MockDetector({})
        event_time = datetime.now(timezone.utc)
        detector.detection_result = DetectionEvent(
            channel_id="1",
            timestamp=event_time,
            duration_seconds=2.0,
            peak_energy_db=-20.0,
            average_energy_db=-25.0,
            audio_frames=[b"audio_data"],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="orpheus/audio/motion/events",
            topic_status="orpheus/audio/motion/status",
            qos=1,
            location_getter=lambda: location_cache,
        )

        frame = AudioFrame(
            channel_id="1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        # Verify MQTT publish was called
        mqtt_client.publish.assert_called_once()
        call_args = mqtt_client.publish.call_args
        payload = call_args.kwargs["payload"]

        # Verify context contains GPS coordinates
        assert payload["context"] is not None
        assert payload["context"]["lat"] == 40.7128
        assert payload["context"]["lon"] == -74.0060
        assert payload["context"]["sensor_id"] == "mic-1"

        # Verify it's a proper Detection model dump
        assert payload["detection_type"] == "audio.motion"
        assert "event_id" in payload

    @pytest.mark.asyncio
    async def test_detection_without_gps_has_null_location(self) -> None:
        """Without GPS data, context should have null lat/lon but still include sensor_id."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        detector = MockDetector({})
        event_time = datetime.now(timezone.utc)
        detector.detection_result = DetectionEvent(
            channel_id="2",
            timestamp=event_time,
            duration_seconds=1.0,
            peak_energy_db=-22.0,
            average_energy_db=-27.0,
            audio_frames=[b"audio_data"],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="2",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="orpheus/audio/motion/events",
            topic_status="orpheus/audio/motion/status",
            qos=1,
            location_getter=lambda: None,  # No GPS data
        )

        frame = AudioFrame(
            channel_id="2",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        mqtt_client.publish.assert_called_once()
        payload = mqtt_client.publish.call_args.kwargs["payload"]

        assert payload["context"]["lat"] is None
        assert payload["context"]["lon"] is None
        assert payload["context"]["sensor_id"] == "mic-2"

    @pytest.mark.asyncio
    async def test_detection_without_location_getter(self) -> None:
        """Without location_getter, context should still be created with null lat/lon."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        detector = MockDetector({})
        event_time = datetime.now(timezone.utc)
        detector.detection_result = DetectionEvent(
            channel_id="1",
            timestamp=event_time,
            duration_seconds=1.0,
            peak_energy_db=-22.0,
            average_energy_db=-27.0,
            audio_frames=[b"audio_data"],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
            # No location_getter passed
        )

        frame = AudioFrame(
            channel_id="1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        mqtt_client.publish.assert_called_once()
        payload = mqtt_client.publish.call_args.kwargs["payload"]

        assert payload["context"]["lat"] is None
        assert payload["context"]["lon"] is None
        assert payload["context"]["sensor_id"] == "mic-1"

    @pytest.mark.asyncio
    async def test_gps_with_elevation(self) -> None:
        """Context should include elevation when provided in GPS data."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        location_cache: dict[str, Any] = {
            "lat": 47.6062,
            "lon": -122.3321,
            "elevation": 56.0,
        }

        detector = MockDetector({})
        detector.detection_result = DetectionEvent(
            channel_id="1",
            timestamp=datetime.now(timezone.utc),
            duration_seconds=1.5,
            peak_energy_db=-18.0,
            average_energy_db=-23.0,
            audio_frames=[b"audio_data"],
            metadata={},
        )

        processor = ChannelProcessor(
            channel_id="1",
            detector=detector,
            mqtt_client=mqtt_client,
            clip_saver=clip_saver,
            topic_events="events",
            topic_status="status",
            qos=1,
            location_getter=lambda: location_cache,
        )

        frame = AudioFrame(
            channel_id="1",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
        )

        await processor.handle_frame(frame)

        payload = mqtt_client.publish.call_args.kwargs["payload"]
        assert payload["context"]["elevation"] == 56.0
