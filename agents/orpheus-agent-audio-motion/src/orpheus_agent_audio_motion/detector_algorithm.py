"""Detection algorithm implementations for the Audio Motion Detector agent."""

from __future__ import annotations

import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

import numpy as np
from orpheus_common.logging import get_logger

from .audio_source import AudioFrame

logger = get_logger(__name__)


class RecordingState(Enum):
    """States for the stateful recording state machine."""

    IDLE = "idle"
    TRIGGERED = "triggered"
    RECORDING = "recording"
    COMPLETE = "complete"


@dataclass(frozen=True)
class DetectionEvent:
    """Structured motion detection output representing a complete audio event."""

    channel_id: str
    timestamp: datetime  # Start time of event
    duration_seconds: float
    peak_energy_db: float
    average_energy_db: float
    audio_frames: list[bytes]  # All frames for this event
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
        self._release_threshold_db = float(
            settings.get("release_threshold_db", settings.get("threshold_db", -25.0) - 5.0)
        )
        self._holdoff_seconds = float(settings.get("holdoff_seconds", 1.0))
        self._min_duration_seconds = float(settings.get("min_duration_seconds", 0.3))
        self._max_duration_seconds = float(settings.get("max_duration_seconds", 30.0))
        self._prebuffer_seconds = float(settings.get("prebuffer_seconds", 0.5))

        # State machine variables
        self._state = RecordingState.IDLE
        self._recording_buffer: list[
            tuple[datetime, bytes, float]
        ] = []  # (timestamp, payload, energy_db)
        self._prebuffer: deque = deque()  # Circular buffer for pre-trigger frames
        self._silence_frames = 0
        self._event_start_time: Optional[datetime] = None
        self._peak_energy_db = -96.0
        self._state_lock = threading.Lock()
        self._frame_count = 0  # For periodic debug logging

        logger.info(
            "Detector initialized with stateful recording",
            release_threshold_db=self._release_threshold_db,
            holdoff_seconds=self._holdoff_seconds,
            min_duration_seconds=self._min_duration_seconds,
            max_duration_seconds=self._max_duration_seconds,
            prebuffer_seconds=self._prebuffer_seconds,
        )

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        """
        Process audio frame through stateful recording state machine.

        Args:
            frame: Audio frame to analyze.

        Returns:
            DetectionEvent if recording completed, None otherwise.
        """

        if self._frame_count == 0:
            logger.debug(
                "DETECT_MOTION: First call for channel",
                channel_id=frame.channel_id,
            )

        energy_db = self._calculate_energy_db(frame.payload)
        trigger_threshold = self._get_trigger_threshold()

        # Periodic energy logging every 100 frames
        self._frame_count += 1
        if self._frame_count % 100 == 0:
            logger.debug(
                "ENERGY sample",
                channel_id=frame.channel_id,
                energy_db=energy_db,
                trigger_threshold_db=trigger_threshold,
            )

        with self._state_lock:
            return self._process_frame(frame, energy_db, trigger_threshold)

    def _process_frame(
        self, frame: AudioFrame, energy_db: float, trigger_threshold: float
    ) -> Optional[DetectionEvent]:
        """
        State machine logic for processing a single frame.

        Must be called while holding self._state_lock.
        """
        if self._state == RecordingState.IDLE:
            return self._handle_idle_state(frame, energy_db, trigger_threshold)
        elif self._state == RecordingState.TRIGGERED:
            return self._handle_triggered_state(frame, energy_db)
        elif self._state == RecordingState.RECORDING:
            return self._handle_recording_state(frame, energy_db)
        elif self._state == RecordingState.COMPLETE:
            return self._handle_complete_state(frame)

        return None

    def _handle_idle_state(
        self, frame: AudioFrame, energy_db: float, trigger_threshold: float
    ) -> Optional[DetectionEvent]:
        """Handle IDLE state: maintain pre-buffer, watch for trigger."""
        # Maintain pre-buffer
        self._prebuffer.append((frame.timestamp, frame.payload, energy_db))

        # Check if trigger exceeded
        if energy_db > trigger_threshold:
            logger.info(
                "Channel triggered",
                channel_id=frame.channel_id,
                state_from="IDLE",
                state_to="TRIGGERED",
                energy_db=energy_db,
                trigger_threshold_db=trigger_threshold,
            )
            self._state = RecordingState.TRIGGERED
            return self._handle_triggered_state(frame, energy_db)

        return None

    def _handle_triggered_state(self, frame: AudioFrame, energy_db: float) -> DetectionEvent | None:
        """Handle TRIGGERED state: initialize recording with pre-buffer."""
        # Initialize recording
        self._recording_buffer = list(self._prebuffer)  # Include pre-buffer
        self._recording_buffer.append((frame.timestamp, frame.payload, energy_db))
        self._event_start_time = self._recording_buffer[0][0]  # Use first frame timestamp
        self._peak_energy_db = max(
            energy_db, max((e for _, _, e in self._prebuffer), default=-96.0)
        )
        self._silence_frames = 0

        logger.info(
            "Channel recording started",
            channel_id=frame.channel_id,
            state_from="TRIGGERED",
            state_to="RECORDING",
            prebuffer_seconds=self._prebuffer_seconds,
        )

        self._state = RecordingState.RECORDING
        return None

    def _handle_recording_state(self, frame: AudioFrame, energy_db: float) -> DetectionEvent | None:
        """Handle RECORDING state: accumulate frames, check for end conditions."""
        # Add frame to buffer
        self._recording_buffer.append((frame.timestamp, frame.payload, energy_db))

        # Update peak energy
        if energy_db > self._peak_energy_db:
            self._peak_energy_db = energy_db

        # Check silence holdoff
        if energy_db < self._release_threshold_db:
            self._silence_frames += 1
        else:
            self._silence_frames = 0

        # Calculate current duration
        current_duration = (frame.timestamp - self._event_start_time).total_seconds()

        # Check for end conditions
        # int32 = 4 bytes per sample
        sample_rate = self._settings.get("sample_rate", 48000)
        frame_duration_seconds = len(frame.payload) / 4 / sample_rate
        silence_duration = self._silence_frames * frame_duration_seconds

        if silence_duration >= self._holdoff_seconds:
            logger.info(
                "Channel recording complete (silence holdoff)",
                channel_id=frame.channel_id,
                state_from="RECORDING",
                state_to="COMPLETE",
                silence_holdoff_seconds=silence_duration,
            )
            self._state = RecordingState.COMPLETE
            return self._handle_complete_state(frame)

        if current_duration >= self._max_duration_seconds:
            logger.info(
                "Channel recording complete (max duration)",
                channel_id=frame.channel_id,
                state_from="RECORDING",
                state_to="COMPLETE",
                duration_seconds=current_duration,
            )
            self._state = RecordingState.COMPLETE
            return self._handle_complete_state(frame)

        return None

    def _handle_complete_state(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        """Handle COMPLETE state: emit event and reset to IDLE."""
        # Calculate event metrics
        duration_seconds = (self._recording_buffer[-1][0] - self._event_start_time).total_seconds()

        # Check minimum duration
        if duration_seconds < self._min_duration_seconds:
            logger.info(
                "Event rejected (too short)",
                channel_id=frame.channel_id,
                duration_seconds=duration_seconds,
                min_duration_seconds=self._min_duration_seconds,
            )
            self._reset_to_idle(frame)
            return None

        # Calculate average energy
        energies = [e for _, _, e in self._recording_buffer]
        average_energy_db = sum(energies) / len(energies) if energies else -96.0

        # Extract audio frames
        audio_frames = [payload for _, payload, _ in self._recording_buffer]

        # Create detection event
        event = DetectionEvent(
            channel_id=frame.channel_id,
            timestamp=self._event_start_time,
            duration_seconds=duration_seconds,
            peak_energy_db=self._peak_energy_db,
            average_energy_db=average_energy_db,
            audio_frames=audio_frames,
            metadata={
                "algorithm": self.__class__.__name__,
                "trigger_threshold_db": self._get_trigger_threshold(),
                "release_threshold_db": self._release_threshold_db,
                "frame_count": len(self._recording_buffer),
                "prebuffer_frames": len(self._prebuffer),
            },
        )

        logger.info(
            "Event saved",
            channel_id=frame.channel_id,
            duration_seconds=duration_seconds,
            peak_db=self._peak_energy_db,
            avg_db=average_energy_db,
            frame_count=len(self._recording_buffer),
        )

        # Reset to IDLE
        self._reset_to_idle(frame)

        return event

    def _reset_to_idle(self, frame: AudioFrame) -> None:
        """Reset state machine to IDLE and clear buffers."""
        self._state = RecordingState.IDLE
        self._recording_buffer = []
        self._silence_frames = 0
        self._event_start_time = None
        self._peak_energy_db = -96.0

        # Clear and reinitialize pre-buffer with current frame
        self._prebuffer.clear()
        energy_db = self._calculate_energy_db(frame.payload)
        self._prebuffer.append((frame.timestamp, frame.payload, energy_db))

    def _get_trigger_threshold(self) -> float:
        """
        Get the current trigger threshold.

        Subclasses should override this for adaptive behavior.
        """
        raise NotImplementedError("Subclasses must implement _get_trigger_threshold")

    def _update_prebuffer_size(self, sample_rate: int, frame_duration_ms: int) -> None:
        """
        Calculate and set pre-buffer size based on configuration.

        Should be called by subclasses during initialization.
        """
        frame_duration_seconds = frame_duration_ms / 1000.0
        prebuffer_frames = int(self._prebuffer_seconds / frame_duration_seconds)
        self._prebuffer = deque(maxlen=max(1, prebuffer_frames))

    @property
    def settings(self) -> dict[str, Any]:
        """Expose underlying detector settings."""
        return self._settings

    @staticmethod
    def _calculate_energy_db(payload: bytes) -> float:
        """
        Calculate RMS energy in dB from PCM audio bytes.

        Args:
            payload: Raw PCM audio data (int16 or int32).

        Returns:
            RMS energy in dB (relative to full scale).
        """
        # Try int32 first (Behringer UMC404HD uses S32_LE format)
        # If payload size suggests int16, fall back to that
        if len(payload) % 4 == 0:
            # Likely int32 format
            samples = np.frombuffer(payload, dtype=np.int32)
            full_scale = 2147483648.0  # 2^31 for int32
        elif len(payload) % 2 == 0:
            # Likely int16 format
            samples = np.frombuffer(payload, dtype=np.int16)
            full_scale = 32768.0  # 2^15 for int16
        else:
            return -96.0  # Invalid data

        if len(samples) == 0:
            return -96.0  # Silence floor

        # Calculate RMS
        rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2))

        # Avoid log(0)
        if rms < 1e-10:
            return -96.0

        # Convert to dB (relative to full scale)
        db = 20 * math.log10(rms / full_scale)

        return db


class FixedThresholdDetector(DetectorAlgorithm):
    """
    Fixed threshold detector with stateful recording.

    Triggers when energy exceeds (threshold_db + margin_db).
    """

    def __init__(self, settings: dict[str, Any]) -> None:
        """
        Initialize fixed threshold detector.

        Args:
            settings: Must contain 'threshold_db' and 'margin_db'.
        """
        super().__init__(settings)
        self._threshold_db = float(settings.get("threshold_db", -25.0))
        self._margin_db = float(settings.get("margin_db", 3.0))

        # Initialize pre-buffer size (assume 16kHz, 100ms frames as defaults)
        sample_rate = settings.get("sample_rate", 16000)
        frame_duration_ms = settings.get("frame_duration_ms", 100)
        self._update_prebuffer_size(sample_rate, frame_duration_ms)

        logger.info(
            "FixedThresholdDetector initialized",
            threshold_db=self._threshold_db,
            margin_db=self._margin_db,
        )

    def _get_trigger_threshold(self) -> float:
        """Return fixed trigger threshold."""
        return self._threshold_db + self._margin_db


class AdaptiveThresholdDetector(DetectorAlgorithm):
    """
    Adaptive threshold detector with stateful recording.

    Maintains a rolling window of energy samples and periodically
    recalculates the threshold as the mean of the window.
    """

    def __init__(self, settings: dict[str, Any]) -> None:
        """
        Initialize adaptive threshold detector.

        Args:
            settings: Must contain 'threshold_db' (initial), 'margin_db',
                     'window_seconds', 'update_interval_seconds'.
        """
        super().__init__(settings)
        self._threshold_db = float(settings.get("threshold_db", -25.0))
        self._margin_db = float(settings.get("margin_db", 3.0))
        self._window_seconds = float(settings.get("window_seconds", 30.0))
        self._update_interval_seconds = float(settings.get("update_interval_seconds", 5.0))

        # Rolling window of (timestamp, energy_db) tuples
        self._energy_history: deque = deque()
        self._last_update_time = datetime.now(timezone.utc)

        # Initialize pre-buffer size
        sample_rate = settings.get("sample_rate", 16000)
        frame_duration_ms = settings.get("frame_duration_ms", 100)
        self._update_prebuffer_size(sample_rate, frame_duration_ms)

        logger.info(
            "AdaptiveThresholdDetector initialized",
            initial_threshold_db=self._threshold_db,
            margin_db=self._margin_db,
            window_seconds=self._window_seconds,
            update_interval_seconds=self._update_interval_seconds,
        )

    def detect_motion(self, frame: AudioFrame) -> Optional[DetectionEvent]:
        """
        Detect motion using adaptive threshold with stateful recording.

        Args:
            frame: Audio frame to analyze.

        Returns:
            DetectionEvent if recording completed, None otherwise.
        """

        if not hasattr(self, "_adaptive_frame_count"):
            self._adaptive_frame_count = 0

        if self._adaptive_frame_count == 0:
            logger.debug(
                "ADAPTIVE DETECT_MOTION: First call for channel",
                channel_id=frame.channel_id,
            )

        energy_db = self._calculate_energy_db(frame.payload)
        current_time = frame.timestamp

        # Periodic energy logging every 100 frames
        self._adaptive_frame_count += 1
        if self._adaptive_frame_count % 100 == 0:
            trigger_threshold = self._get_trigger_threshold()
            logger.debug(
                "ENERGY sample (adaptive)",
                channel_id=frame.channel_id,
                energy_db=energy_db,
                threshold_db=self._threshold_db,
                trigger_threshold_db=trigger_threshold,
            )

        with self._state_lock:
            # Update energy history (only when idle to avoid bias during recording)
            if self._state == RecordingState.IDLE:
                self._energy_history.append((current_time, energy_db))

                # Trim old samples outside the window
                cutoff_time = current_time - timedelta(seconds=self._window_seconds)
                while self._energy_history and self._energy_history[0][0] < cutoff_time:
                    self._energy_history.popleft()

                # Check if it's time to update threshold
                time_since_update = (current_time - self._last_update_time).total_seconds()
                if time_since_update >= self._update_interval_seconds:
                    self._update_threshold()
                    self._last_update_time = current_time

            # Process through state machine
            return self._process_frame(frame, energy_db, self._get_trigger_threshold())

    def _get_trigger_threshold(self) -> float:
        """Return adaptive trigger threshold."""
        return self._threshold_db + self._margin_db

    def _update_threshold(self) -> None:
        """
        Recalculate threshold as the mean of energy samples in the window.

        Must be called while holding self._state_lock.
        """
        if not self._energy_history:
            return

        # Calculate mean energy
        energies = [e for _, e in self._energy_history]
        new_threshold = sum(energies) / len(energies)

        # Limit how much threshold can change in one update (prevent sudden jumps)
        max_change = 10.0  # dB
        change = new_threshold - self._threshold_db
        if abs(change) > max_change:
            change = max_change if change > 0 else -max_change

        old_threshold = self._threshold_db
        self._threshold_db = old_threshold + change

        logger.info(
            "Adaptive threshold updated",
            old_db=old_threshold,
            new_db=self._threshold_db,
            sample_count=len(self._energy_history),
        )


def create_detector(algorithm: str, settings: dict[str, Any]) -> DetectorAlgorithm:
    """
    Factory function to create detector instances.

    Args:
        algorithm: Algorithm name ('fixed_threshold' or 'adaptive_threshold').
        settings: Algorithm-specific configuration.

    Returns:
        Detector instance.

    Raises:
        ValueError: If algorithm name is unknown.
    """
    logger.debug(
        "Creating detector",
        algorithm=algorithm,
        settings_keys=list(settings.keys()),
    )
    algorithm_lower = algorithm.lower()

    if algorithm_lower == "fixed_threshold":
        logger.debug("Creating FixedThresholdDetector")
        detector = FixedThresholdDetector(settings)
        logger.debug(
            "Created FixedThresholdDetector",
            detector_class=type(detector).__name__,
        )
        return detector
    elif algorithm_lower == "adaptive_threshold":
        logger.debug("Creating AdaptiveThresholdDetector")
        detector = AdaptiveThresholdDetector(settings)
        logger.debug(
            "Created AdaptiveThresholdDetector",
            detector_class=type(detector).__name__,
        )
        return detector
    else:
        raise ValueError(
            f"Unknown detector algorithm: {algorithm}. "
            f"Valid options: 'fixed_threshold', 'adaptive_threshold'"
        )
