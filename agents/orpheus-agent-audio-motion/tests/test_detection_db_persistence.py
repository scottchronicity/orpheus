"""The audio-motion agent must persist its OWN audio.motion stream.

Regression for the cross-classifier chain-root ownership bug (ADR 0012):

audio.motion is the ROOT of every detection chain — bird-detection,
audio-events, and crow-detection all reference it via ``source_event_id``
/ ``root_event_id``. For the chain to be joinable, the persisted
audio.motion row must carry the SAME ``event_id`` that this agent
publishes to MQTT.

If this agent published without persisting, the UI backend would pick
the stream up as an accidental "recorder" — minting a fresh
``event_id`` on save. The persisted root would then never match what
downstream detections reference, silently breaking correlation,
entity clustering, lineage, and the root_event_id backfill. These tests
pin the correct ownership: the agent persists, with the published id.
"""

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


class _MockDetector(DetectorAlgorithm):
    def __init__(self, settings: dict[str, Any]) -> None:
        super().__init__(settings)
        self.detection_result: Optional[DetectionEvent] = None

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        return self.detection_result


def _make_processor(
    mqtt_client: Mock,
    clip_saver: Mock,
    detection_db: Optional[Mock],
    shadow_stream_publish: bool = False,
) -> ChannelProcessor:
    detector = _MockDetector({})
    detector.detection_result = DetectionEvent(
        channel_id="1",
        timestamp=datetime.now(timezone.utc),
        duration_seconds=2.0,
        peak_energy_db=-20.0,
        average_energy_db=-25.0,
        audio_frames=[b"audio_data"],
        metadata={},
    )
    return ChannelProcessor(
        channel_id="1",
        detector=detector,
        mqtt_client=mqtt_client,
        clip_saver=clip_saver,
        topic_events="orpheus/audio/motion/events",
        topic_status="orpheus/audio/motion/status",
        qos=1,
        location_getter=lambda: None,
        detection_db=detection_db,
        shadow_stream_publish=shadow_stream_publish,
    )


def _frame() -> AudioFrame:
    return AudioFrame(
        channel_id="1", payload=b"test", timestamp=datetime.now(timezone.utc)
    )


class TestAudioMotionPersistence:
    @pytest.mark.asyncio
    async def test_persists_audio_motion_with_published_event_id(self) -> None:
        """The saved audio.motion row carries the SAME event_id that was
        published — the chain root downstream detections reference."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")
        detection_db = Mock()

        processor = _make_processor(mqtt_client, clip_saver, detection_db)
        await processor.handle_frame(_frame())

        # Published exactly once.
        mqtt_client.publish.assert_called_once()
        published_event_id = mqtt_client.publish.call_args.kwargs["payload"]["event_id"]
        assert published_event_id  # non-empty

        # Persisted exactly once, and the saved Detection's event_id matches
        # the published one. This is the whole point — chain joinability.
        detection_db.save.assert_called_once()
        saved = detection_db.save.call_args.args[0]
        assert saved.detection_type == "audio.motion"
        assert saved.event_id == published_event_id
        # audio.motion is its own chain root.
        assert saved.root_event_id == published_event_id

    @pytest.mark.asyncio
    async def test_db_failure_does_not_break_publishing(self) -> None:
        """A DetectionDB error must never stop motion detection / publishing.

        Persistence happens AFTER publish and swallows errors — the head of
        the pipeline must keep running even if the DB is unavailable.
        """
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")
        detection_db = Mock()
        detection_db.save.side_effect = RuntimeError("disk full")

        processor = _make_processor(mqtt_client, clip_saver, detection_db)
        # Must NOT raise despite the DB error.
        await processor.handle_frame(_frame())
        mqtt_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_optional_db_none_still_publishes(self) -> None:
        """detection_db is optional (e.g. in tests) — None must not break publish."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        processor = _make_processor(mqtt_client, clip_saver, None)
        await processor.handle_frame(_frame())
        mqtt_client.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_shadow_stream_publish_by_default(self) -> None:
        """Default (shadow off): stream_publish is never called — byte-identical."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")

        processor = _make_processor(mqtt_client, clip_saver, Mock())
        await processor.handle_frame(_frame())
        mqtt_client.stream_publish.assert_not_called()

    @pytest.mark.asyncio
    async def test_shadow_publishes_to_stream_keyed_by_event_id(self) -> None:
        """Shadow on: the detection is mirrored to the durable stream with
        Nats-Msg-Id == the SAME event_id that was published + saved (dedup-able)."""
        mqtt_client = Mock()
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")
        detection_db = Mock()

        processor = _make_processor(
            mqtt_client, clip_saver, detection_db, shadow_stream_publish=True
        )
        await processor.handle_frame(_frame())

        published_event_id = mqtt_client.publish.call_args.kwargs["payload"]["event_id"]
        mqtt_client.stream_publish.assert_called_once()
        sp = mqtt_client.stream_publish.call_args
        # The dedicated shadow subject — never the live topic (double-delivery guard).
        assert sp.args[0] == "orpheus/domain/audio/motion/events"
        assert sp.kwargs["msg_id"] == published_event_id
        assert sp.args[1]["event_id"] == published_event_id  # same payload identity

    @pytest.mark.asyncio
    async def test_shadow_failure_does_not_break_pipeline(self) -> None:
        """A stream hiccup must never stall the pipeline head: publish + save still
        happen even when shadow stream_publish raises."""
        mqtt_client = Mock()
        mqtt_client.stream_publish.side_effect = RuntimeError("jetstream down")
        clip_saver = Mock(spec=ClipSaver)
        clip_saver.save_clip.return_value = Path("/tmp/test_clip.flac")
        detection_db = Mock()

        processor = _make_processor(
            mqtt_client, clip_saver, detection_db, shadow_stream_publish=True
        )
        await processor.handle_frame(_frame())
        mqtt_client.publish.assert_called_once()
        detection_db.save.assert_called_once()
