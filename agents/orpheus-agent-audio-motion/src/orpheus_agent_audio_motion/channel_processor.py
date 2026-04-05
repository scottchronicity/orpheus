"""Per-channel processing pipeline for the Audio Motion Detector agent."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List, Optional

from orpheus_common.detection import Detection
from orpheus_common.events import SpatiotemporalContext
from orpheus_common.logging import get_logger
from orpheus_common.mqtt import MQTTClient
from orpheus_common.utils.buffer import PreRollRingBuffer

from .audio_source import AudioFrame
from .clip_saver import ClipSaver
from .detector_algorithm import DetectorAlgorithm

logger = get_logger(__name__)


class ChannelProcessor:
    """
    Process audio frames for a single channel and publish detection events.

    Orchestrates the detection pipeline for one audio channel:
    1. Receives audio frames from the audio source
    2. Appends every raw audio chunk to the pre-roll ring buffer
    3. Passes frames through the configured detector algorithm
    4. Prepends buffered pre-trigger audio to the detection payload
    5. Saves detected audio clips to disk
    6. Publishes detection events to MQTT

    Thread-safe through asyncio lock to prevent concurrent frame processing.
    """

    def __init__(
        self,
        channel_id: str,
        detector: DetectorAlgorithm,
        mqtt_client: MQTTClient,
        clip_saver: ClipSaver,
        topic_events: str,
        topic_status: str,
        qos: int,
        location_getter: Optional[Callable[[], Optional[Any]]] = None,
        prebuffer_seconds: float = 0.5,
        sample_rate: int = 48000,
        pre_roll_seconds: int = 5,
        chunks_per_second: int = 47,
    ) -> None:
        """
        Initialize the channel processor.

        Args:
            channel_id: Unique identifier for this channel (e.g., "1", "north").
            detector: Detection algorithm instance for motion detection.
            mqtt_client: Connected MQTT client for publishing events.
            clip_saver: ClipSaver instance for persisting audio clips.
            topic_events: MQTT topic for detection event messages.
            topic_status: MQTT topic for status/error messages.
            qos: MQTT Quality of Service level (0, 1, or 2).
            location_getter: Optional callable returning cached GPS location dict.
            prebuffer_seconds: Pre-buffer duration passed to the detector algorithm.
            sample_rate: Audio sample rate in Hz.
            pre_roll_seconds: Duration of the pre-roll ring buffer in seconds.
            chunks_per_second: Number of audio chunks delivered per second, used
                to size the ring buffer.  Compute as
                ``int(1000 / frame_duration_ms)`` from the runtime config.
        """
        self._channel_id = channel_id
        self._detector = detector
        self._mqtt_client = mqtt_client
        self._clip_saver = clip_saver
        self._topic_events = topic_events
        self._topic_status = topic_status
        self._qos = qos
        self._location_getter = location_getter
        self._sample_rate = sample_rate
        self._chunks_per_second = chunks_per_second
        self._lock = asyncio.Lock()

        # Centralised pre-roll ring buffer (DRY: uses orpheus_common utility).
        self._pre_roll_buffer: PreRollRingBuffer[bytes] = PreRollRingBuffer(
            max_seconds=pre_roll_seconds,
            items_per_second=chunks_per_second,
        )
        logger.debug(
            "Pre-roll ring buffer created",
            channel_id=channel_id,
            pre_roll_seconds=pre_roll_seconds,
            chunks_per_second=chunks_per_second,
            capacity=pre_roll_seconds * chunks_per_second,
        )

    async def handle_frame(self, frame: AudioFrame) -> None:
        """
        Execute the detector for the provided frame and publish results.

        Processes an audio frame through the detection algorithm. If motion
        is detected, saves the audio clip and publishes a detection event
        to MQTT.

        Args:
            frame: Audio frame to process. Frames for other channels are ignored.

        Note:
            This method is thread-safe and uses a lock to prevent concurrent
            processing of frames on the same channel.
        """
        if frame.channel_id != self._channel_id:
            logger.debug(
                "Discarding frame for wrong channel",
                frame_channel_id=frame.channel_id,
                processor_channel_id=self._channel_id,
            )
            return

        # Append raw bytes to the pre-roll ring buffer *before* detection so
        # that the inciting incident is always captured.
        self._pre_roll_buffer.append(frame.payload)

        async with self._lock:
            try:
                logger.debug("Calling detect_motion", channel_id=self._channel_id)
                detection = self._detector.detect_motion(frame)
                logger.debug("detect_motion returned", result="event" if detection else "None")
            except NotImplementedError:
                logger.debug("Detector not yet implemented", channel_id=self._channel_id)
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Detector failure", channel_id=self._channel_id, error=str(exc))
                await self._publish_status({"state": "error", "detail": str(exc)})
                return

        if not detection:
            return

        clip_path: Optional[str] = None
        if detection.audio_frames:
            try:
                # 1. Snapshot the pre-roll ring buffer
                pre_roll_chunks: List[bytes] = self._pre_roll_buffer.get_snapshot()

                # 2. Calculate pre-roll duration from actual buffer contents
                pre_roll_ms = self._calculate_pre_roll_ms(pre_roll_chunks)

                # 3. Concatenate pre-roll + detected audio into a single payload
                concatenated_payload = b"".join(pre_roll_chunks + list(detection.audio_frames))

                path = self._clip_saver.save_clip(
                    channel_id=detection.channel_id,
                    payload=concatenated_payload,
                    event_time=detection.timestamp,
                    metadata={"event_type": "motion", "pre_roll_ms": pre_roll_ms},
                )
                clip_path = str(path)

                logger.info(
                    "Saved audio clip",
                    duration_seconds=detection.duration_seconds,
                    channel_id=detection.channel_id,
                    pre_roll_ms=pre_roll_ms,
                    clip_path=clip_path,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception(
                    "Clip persistence failure", channel_id=self._channel_id, error=str(exc)
                )
                await self._publish_status({"state": "warning", "detail": str(exc)})

        # Build spatiotemporal context from cached GPS location
        location = self._location_getter() if self._location_getter else None
        context = SpatiotemporalContext(
            lat=location.get("lat") if location else None,
            lon=location.get("lon") if location else None,
            elevation=location.get("elevation") if location else None,
            sensor_id=f"mic-{self._channel_id}",
        )

        detection_obj = Detection(
            timestamp=detection.timestamp,
            detection_type="audio.motion",
            channel=int(self._channel_id) if self._channel_id.isdigit() else None,
            context=context,
            audio_clip_path=clip_path,
            metadata={
                "channel_id": detection.channel_id,
                "duration_seconds": detection.duration_seconds,
                "peak_energy_db": detection.peak_energy_db,
                "average_energy_db": detection.average_energy_db,
                "frame_count": len(detection.audio_frames),
                **detection.metadata,
            },
        )

        logger.info(
            "Publishing detection event",
            channel_id=detection.channel_id,
            duration_seconds=detection.duration_seconds,
            peak_energy_db=detection.peak_energy_db,
        )
        self._mqtt_client.publish(
            topic=self._topic_events,
            payload=detection_obj.model_dump(mode="json"),
            qos=self._qos,
        )

        # Record MQTT message in health monitor
        from orpheus_common.diagnostics.audio_health import get_audio_health_monitor

        health_monitor = get_audio_health_monitor()
        health_monitor.record_mqtt_message()

    # ------------------------------------------------------------------
    # Pre-roll helpers
    # ------------------------------------------------------------------

    def _calculate_pre_roll_ms(self, chunks: List[bytes]) -> int:
        """
        Return the pre-roll duration in milliseconds.

        Derived from the actual chunk payloads so the value stays accurate
        even if the hardware chunk size changes at runtime.

        Args:
            chunks: Raw audio byte payloads from the ring buffer snapshot.

        Returns:
            Pre-roll duration in milliseconds.
        """
        total_samples = 0
        for chunk in chunks:
            # int32 PCM → 4 bytes per sample
            total_samples += len(chunk) // 4
        if total_samples > 0:
            return int(total_samples / self._sample_rate * 1000)
        return 0

    async def _publish_status(self, payload: Any) -> None:
        """
        Publish channel status telemetry to MQTT.

        Args:
            payload: Status message payload. The channel_id will be added.
        """
        payload["channel_id"] = self._channel_id
        self._mqtt_client.publish(topic=self._topic_status, payload=payload, qos=self._qos)
