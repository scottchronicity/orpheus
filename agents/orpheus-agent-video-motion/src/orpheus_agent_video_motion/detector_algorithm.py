"""Detection algorithm implementations for the Video Motion Detector agent."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

import cv2
import numpy as np
from orpheus_common.diagnostics.video_health import get_video_health_monitor
from orpheus_common.logging import get_logger
from orpheus_common.video.source import VideoFrame

logger = get_logger(__name__)


class RecordingState(Enum):
    """States for the stateful recording state machine."""

    IDLE = "idle"
    TRIGGERED = "triggered"
    RECORDING = "recording"
    COMPLETE = "complete"


@dataclass(frozen=True)
class DetectionEvent:
    """Structured motion detection output representing a complete video event."""

    camera_id: str
    timestamp: datetime  # Start time of event
    duration_seconds: float
    peak_motion_value: float
    average_motion_value: float
    video_frames: list[bytes]  # All frames for this event
    metadata: dict[str, Any] = field(default_factory=dict)


class DetectorAlgorithm:
    """Base class for motion detection algorithms with stateful recording."""

    def __init__(self, settings: dict[str, Any]) -> None:
        """
        Initialize detector with configuration settings.

        Args:
            settings: Dictionary containing algorithm-specific parameters.
        """
        self._settings = settings

        # Stateful recording configuration
        self._motion_threshold = float(settings.get("motion_threshold", 25.0))
        self._release_threshold = float(
            settings.get("release_threshold", self._motion_threshold * 0.5)
        )
        self._holdoff_seconds = float(settings.get("holdoff_seconds", 2.0))
        self._min_duration_seconds = float(settings.get("min_duration_seconds", 0.5))
        self._max_duration_seconds = float(settings.get("max_duration_seconds", 30.0))
        self._prebuffer_seconds = float(settings.get("prebuffer_seconds", 1.0))

        # Get FPS from settings
        self._fps = int(settings.get("fps", 10))

        # Calculate prebuffer size in frames
        self._prebuffer_size = int(self._prebuffer_seconds * self._fps)

        # State machine variables
        self._state = RecordingState.IDLE
        # Recording buffer stores frames during active recording
        # Size is bounded by max_duration_seconds * fps (e.g., 30s * 10fps = 300 frames max)
        self._recording_buffer: list[
            tuple[datetime, bytes, float]
        ] = []  # (timestamp, payload, motion)
        self._prebuffer: deque = deque(maxlen=self._prebuffer_size)
        self._silence_frames = 0
        self._event_start_time: Optional[datetime] = None
        self._peak_motion_value = 0.0
        self._state_lock = threading.Lock()
        self._frame_count = 0

        # Background subtractor for motion detection
        self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
            history=500,
            varThreshold=16,
            detectShadows=False,
        )
        self._last_frame: Optional[np.ndarray] = None

        logger.info(
            "Detector initialized with stateful recording: "
            "motion_threshold=%.1f, release_threshold=%.1f, holdoff=%.1f s, "
            "min_duration=%.1f s, max_duration=%.1f s, prebuffer=%.1f s",
            self._motion_threshold,
            self._release_threshold,
            self._holdoff_seconds,
            self._min_duration_seconds,
            self._max_duration_seconds,
            self._prebuffer_seconds,
        )

    def detect_motion(self, frame: VideoFrame) -> Optional[DetectionEvent]:
        """
        Process video frame through stateful recording state machine.

        Args:
            frame: Video frame to analyze.

        Returns:
            DetectionEvent if recording completed, None otherwise.
        """
        self._frame_count += 1

        with self._state_lock:
            # Compute motion value
            motion_value = self._compute_motion(frame)

            # Record frame processing in health monitor
            health_monitor = get_video_health_monitor()
            health_monitor.record_frame(frame.camera_id, motion_value)

            # Update prebuffer (always maintain recent frames)
            self._prebuffer.append((frame.timestamp, frame.payload, motion_value))

            # State machine logic
            if self._state == RecordingState.IDLE:
                if motion_value >= self._motion_threshold:
                    logger.info(
                        "Motion detected on camera %s: %.1f >= %.1f (threshold)",
                        frame.camera_id,
                        motion_value,
                        self._motion_threshold,
                    )
                    self._state = RecordingState.TRIGGERED
                    self._event_start_time = frame.timestamp
                    self._peak_motion_value = motion_value
                    self._silence_frames = 0

                    # Start recording buffer with prebuffer frames
                    self._recording_buffer = list(self._prebuffer)

            elif self._state == RecordingState.TRIGGERED:
                # Add frame to recording buffer
                self._recording_buffer.append((frame.timestamp, frame.payload, motion_value))
                self._peak_motion_value = max(self._peak_motion_value, motion_value)

                # Transition to RECORDING state
                self._state = RecordingState.RECORDING
                self._silence_frames = 0

            elif self._state == RecordingState.RECORDING:
                # Add frame to recording buffer
                self._recording_buffer.append((frame.timestamp, frame.payload, motion_value))
                self._peak_motion_value = max(self._peak_motion_value, motion_value)

                # Check for end conditions
                if motion_value < self._release_threshold:
                    self._silence_frames += 1
                else:
                    self._silence_frames = 0

                # Calculate holdoff in frames
                holdoff_frames = int(self._holdoff_seconds * self._fps)

                # Check if we should complete recording
                duration = (frame.timestamp - self._event_start_time).total_seconds()

                if self._silence_frames >= holdoff_frames:
                    # Motion ended, check duration
                    if duration >= self._min_duration_seconds:
                        logger.info(
                            "Recording complete on camera %s: %.1f s, peak motion=%.1f",
                            frame.camera_id,
                            duration,
                            self._peak_motion_value,
                        )
                        event = self._finalize_event(frame.camera_id)
                        return event
                    else:
                        logger.debug(
                            "Recording too short on camera %s: %.1f s < %.1f s (min)",
                            frame.camera_id,
                            duration,
                            self._min_duration_seconds,
                        )
                        self._reset_state()

                elif duration >= self._max_duration_seconds:
                    logger.info(
                        "Recording reached max duration on camera %s: %.1f s",
                        frame.camera_id,
                        duration,
                    )
                    event = self._finalize_event(frame.camera_id)
                    return event

            return None

    def _compute_motion(self, frame: VideoFrame) -> float:
        """
        Compute motion value for a video frame.

        Args:
            frame: Video frame to analyze.

        Returns:
            Motion value (higher = more motion).
        """
        # Convert frame bytes to numpy array
        frame_array = np.frombuffer(frame.payload, dtype=np.uint8).reshape(
            (frame.height, frame.width, 3)
        )

        # Convert to grayscale
        gray = cv2.cvtColor(frame_array, cv2.COLOR_BGR2GRAY)

        # Apply Gaussian blur to reduce noise
        gray = cv2.GaussianBlur(gray, (21, 21), 0)

        # Apply background subtraction
        fg_mask = self._bg_subtractor.apply(gray)

        # Threshold the mask
        _, thresh = cv2.threshold(fg_mask, 25, 255, cv2.THRESH_BINARY)

        # Dilate to fill gaps
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        thresh = cv2.dilate(thresh, kernel, iterations=2)

        # Count non-zero pixels (motion pixels)
        motion_pixels = cv2.countNonZero(thresh)

        # Normalize to percentage of frame
        total_pixels = frame.width * frame.height
        motion_percent = (motion_pixels / total_pixels) * 100.0

        return motion_percent

    def _finalize_event(self, camera_id: str) -> DetectionEvent:
        """
        Create DetectionEvent from current recording buffer.

        Args:
            camera_id: Camera identifier.

        Returns:
            DetectionEvent with all recorded frames.
        """
        # Calculate average motion
        motion_values = [motion for _, _, motion in self._recording_buffer]
        avg_motion = sum(motion_values) / len(motion_values) if motion_values else 0.0

        # Extract just the frame payloads
        video_frames = [payload for _, payload, _ in self._recording_buffer]

        # Calculate duration
        if self._event_start_time and self._recording_buffer:
            last_timestamp = self._recording_buffer[-1][0]
            duration = (last_timestamp - self._event_start_time).total_seconds()
        else:
            duration = 0.0

        event = DetectionEvent(
            camera_id=camera_id,
            timestamp=self._event_start_time or datetime.now(timezone.utc),
            duration_seconds=duration,
            peak_motion_value=self._peak_motion_value,
            average_motion_value=avg_motion,
            video_frames=video_frames,
            metadata={
                "frame_count": len(video_frames),
                "algorithm": "background_subtraction",
            },
        )

        self._reset_state()
        return event

    def _reset_state(self) -> None:
        """Reset state machine to IDLE."""
        self._state = RecordingState.IDLE
        self._recording_buffer = []
        self._silence_frames = 0
        self._event_start_time = None
        self._peak_motion_value = 0.0


def create_detector(algorithm: str, settings: dict[str, Any]) -> DetectorAlgorithm:
    """
    Factory function to create a detector algorithm.

    Args:
        algorithm: Algorithm name (currently only "background_subtraction" supported).
        settings: Algorithm configuration.

    Returns:
        DetectorAlgorithm instance.
    """
    if algorithm in ("background_subtraction", "motion_detection"):
        return DetectorAlgorithm(settings)
    else:
        logger.warning("Unknown algorithm, using background_subtraction", algorithm=algorithm)
        return DetectorAlgorithm(settings)
