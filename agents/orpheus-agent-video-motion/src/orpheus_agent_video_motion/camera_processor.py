"""Per-camera processing pipeline for the Video Motion Detector agent."""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from orpheus_common.diagnostics.video_health import get_video_health_monitor
from orpheus_common.logging import get_logger
from orpheus_common.mqtt import MQTTClient
from orpheus_common.utils.buffer import PreRollRingBuffer
from orpheus_common.video.source import VideoFrame

from .clip_saver import ClipSaver
from .detector_algorithm import DetectorAlgorithm

logger = get_logger(__name__)


class CameraProcessor:
    """
    Process video frames for a single camera and publish detection events.

    Orchestrates the detection pipeline for one camera:
    1. Receives video frames from the video source
    2. Appends every frame to the pre-roll ring buffer
    3. Passes frames through the configured detector algorithm
    4. Prepends buffered pre-trigger frames to the detected clip
    5. Saves detected video clips to disk
    6. Publishes detection events to MQTT

    Thread-safe through asyncio lock to prevent concurrent frame processing.
    """

    def __init__(
        self,
        camera_id: str,
        detector: DetectorAlgorithm,
        mqtt_client: MQTTClient,
        clip_saver: ClipSaver,
        topic_events: str,
        topic_status: str,
        qos: int,
        pre_roll_seconds: int = 3,
        fps: int = 10,
    ) -> None:
        """
        Initialize the camera processor.

        Args:
            camera_id: Unique identifier for this camera (e.g., "orpheus-eye-1").
            detector: Detection algorithm instance for motion detection.
            mqtt_client: Connected MQTT client for publishing events.
            clip_saver: ClipSaver instance for persisting video clips.
            topic_events: MQTT topic for detection event messages.
            topic_status: MQTT topic for status/error messages.
            qos: MQTT Quality of Service level (0, 1, or 2).
            pre_roll_seconds: Duration of pre-roll ring buffer in seconds.
            fps: Frames per second used to size the ring buffer.
        """
        self._camera_id = camera_id
        self._detector = detector
        self._mqtt_client = mqtt_client
        self._clip_saver = clip_saver
        self._topic_events = topic_events
        self._topic_status = topic_status
        self._qos = qos
        self._lock = asyncio.Lock()

        # Pre-roll ring buffer: retains the last pre_roll_seconds of frames
        # so that the inciting incident is always captured.
        self._pre_roll_buffer: PreRollRingBuffer[VideoFrame] = PreRollRingBuffer(
            max_seconds=pre_roll_seconds,
            items_per_second=fps,
        )
        logger.debug(
            "Pre-roll ring buffer created",
            camera_id=camera_id,
            pre_roll_seconds=pre_roll_seconds,
            fps=fps,
            capacity=pre_roll_seconds * fps,
        )

    async def handle_frame(self, frame: VideoFrame) -> None:
        """
        Execute the detector for the provided frame and publish results.

        Processes a video frame through the detection algorithm. If motion
        is detected, prepends pre-roll frames, saves the video clip, and
        publishes a detection event to MQTT.

        Args:
            frame: Video frame to process. Frames for other cameras are ignored.

        Note:
            This method is thread-safe and uses a lock to prevent concurrent
            processing of frames on the same camera.
        """
        if frame.camera_id != self._camera_id:
            logger.debug(
                "Discarding frame for %s on processor for %s",
                frame.camera_id,
                self._camera_id,
            )
            return

        # Append every frame to the pre-roll buffer *before* detection so that
        # the buffer always contains audio leading up to the trigger.
        self._pre_roll_buffer.append(frame)

        async with self._lock:
            try:
                logger.debug("Calling detect_motion", camera_id=self._camera_id)
                detection = self._detector.detect_motion(frame)
                logger.debug("detect_motion returned", result="event" if detection else "None")
            except NotImplementedError:
                logger.debug("Detector not yet implemented", camera_id=self._camera_id)
                return
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception(
                    "Detector failure",
                    camera_id=self._camera_id,
                    exc=exc,
                )
                await self._publish_status({"state": "error", "detail": str(exc)})
                return

        if not detection:
            return

        # Record detection in health monitor
        health_monitor = get_video_health_monitor()
        health_monitor.record_detection(detection.camera_id)

        clip_path: Optional[str] = None
        if detection.video_frames:
            try:
                # Prepend pre-roll frames to the detection clip.
                # exclude_last=True avoids duplicating the trigger frame that
                # was already included as the first frame of detection.video_frames.
                pre_roll_snapshot: List[VideoFrame] = self._pre_roll_buffer.get_snapshot(
                    exclude_last=True
                )
                pre_roll_bytes: List[bytes] = [f.payload for f in pre_roll_snapshot]
                all_frames: List[bytes] = pre_roll_bytes + list(detection.video_frames)

                metadata: Any = {
                    "camera_id": detection.camera_id,
                    "timestamp": detection.timestamp.isoformat(),
                    "duration_seconds": detection.duration_seconds,
                    "peak_motion_value": detection.peak_motion_value,
                    "average_motion_value": detection.average_motion_value,
                    "pre_roll_frames": len(pre_roll_bytes),
                    "frame_count": len(all_frames),
                }

                path = self._clip_saver.save_clip(
                    camera_id=detection.camera_id,
                    frames=all_frames,
                    event_time=detection.timestamp,
                    metadata=metadata,
                )
                clip_path = str(path)

                logger.info(
                    "Saved %.1fs clip for camera %s (%d pre-roll + %d detection frames): %s",
                    detection.duration_seconds,
                    detection.camera_id,
                    len(pre_roll_bytes),
                    len(detection.video_frames),
                    clip_path,
                )
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception(
                    "Clip persistence failure",
                    camera_id=self._camera_id,
                    exc=exc,
                )
                await self._publish_status({"state": "warning", "detail": str(exc)})

        payload: Any = {
            "camera_id": detection.camera_id,
            "timestamp": detection.timestamp.isoformat(),
            "duration_seconds": detection.duration_seconds,
            "peak_motion_value": detection.peak_motion_value,
            "average_motion_value": detection.average_motion_value,
            "frame_count": len(detection.video_frames),
            "metadata": detection.metadata,
        }
        if clip_path:
            payload["clip_path"] = clip_path

        logger.info(
            "Publishing detection for %s: %.1fs event (peak motion: %.1f%%)",
            detection.camera_id,
            detection.duration_seconds,
            detection.peak_motion_value,
        )
        self._mqtt_client.publish(topic=self._topic_events, payload=payload, qos=self._qos)

        # Record MQTT message in health monitor
        health_monitor.record_mqtt_message()

    async def _publish_status(self, payload: Any) -> None:
        """
        Publish camera status telemetry to MQTT.

        Args:
            payload: Status message payload. The camera_id will be added.
        """
        payload["camera_id"] = self._camera_id
        self._mqtt_client.publish(topic=self._topic_status, payload=payload, qos=self._qos)
