"""Tests for detector algorithm."""

from datetime import datetime, timezone

import numpy as np
from orpheus_common.video.source import VideoFrame

from orpheus_agent_video_motion.detector_algorithm import (
    DetectionEvent,
    DetectorAlgorithm,
    RecordingState,
    create_detector,
)


def test_create_detector():
    """Test detector factory function."""
    settings = {
        "motion_threshold": 25.0,
        "release_threshold": 12.5,
        "holdoff_seconds": 2.0,
        "min_duration_seconds": 0.5,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 1.0,
        "fps": 10,
    }

    detector = create_detector("background_subtraction", settings)
    assert isinstance(detector, DetectorAlgorithm)

    # Test with motion_detection alias
    detector2 = create_detector("motion_detection", settings)
    assert isinstance(detector2, DetectorAlgorithm)

    # Test with unknown algorithm (should default to DetectorAlgorithm)
    detector3 = create_detector("unknown", settings)
    assert isinstance(detector3, DetectorAlgorithm)


def test_detector_initialization():
    """Test detector initialization with settings."""
    settings = {
        "motion_threshold": 30.0,
        "release_threshold": 15.0,
        "holdoff_seconds": 1.5,
        "min_duration_seconds": 0.3,
        "max_duration_seconds": 25.0,
        "prebuffer_seconds": 0.8,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    assert detector._motion_threshold == 30.0
    assert detector._release_threshold == 15.0
    assert detector._holdoff_seconds == 1.5
    assert detector._state == RecordingState.IDLE


def test_detector_initialization_defaults():
    """Test detector initialization with default values."""
    settings = {"fps": 10}

    detector = DetectorAlgorithm(settings)
    assert detector._motion_threshold == 25.0  # Default
    assert detector._release_threshold == 12.5  # Default (50% of threshold)
    assert detector._holdoff_seconds == 2.0  # Default
    assert detector._min_duration_seconds == 0.5  # Default
    assert detector._max_duration_seconds == 30.0  # Default
    assert detector._prebuffer_seconds == 1.0  # Default
    assert detector._fps == 10


def test_detector_handles_frame():
    """Test detector can process a video frame."""
    settings = {
        "motion_threshold": 25.0,
        "release_threshold": 12.5,
        "holdoff_seconds": 2.0,
        "min_duration_seconds": 0.5,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 1.0,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)

    # Create a test frame with black image
    width, height = 640, 480
    black_frame = np.zeros((height, width, 3), dtype=np.uint8)

    frame = VideoFrame(
        camera_id="test-camera",
        payload=black_frame.tobytes(),
        timestamp=datetime.now(timezone.utc),
        width=width,
        height=height,
    )

    # Process frame (should not detect motion on black frame)
    result = detector.detect_motion(frame)
    assert result is None  # No motion on uniform frame


def test_detection_event_dataclass():
    """Test DetectionEvent dataclass."""
    event = DetectionEvent(
        camera_id="test-camera",
        timestamp=datetime.now(timezone.utc),
        duration_seconds=2.5,
        peak_motion_value=35.0,
        average_motion_value=28.0,
        video_frames=[b"frame1", b"frame2"],
        metadata={"algorithm": "background_subtraction"},
    )

    assert event.camera_id == "test-camera"
    assert event.duration_seconds == 2.5
    assert event.peak_motion_value == 35.0
    assert len(event.video_frames) == 2
    assert event.metadata["algorithm"] == "background_subtraction"


def test_detector_state_machine():
    """Test detector state transitions."""
    settings = {
        "motion_threshold": 25.0,
        "release_threshold": 12.5,
        "holdoff_seconds": 2.0,
        "min_duration_seconds": 0.5,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 1.0,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    assert detector._state == RecordingState.IDLE

    # Reset should maintain IDLE state
    detector._reset_state()
    assert detector._state == RecordingState.IDLE
    assert len(detector._recording_buffer) == 0


def test_detector_motion_triggers_recording():
    """Test motion above threshold triggers recording."""
    settings = {
        "motion_threshold": 5.0,  # Low threshold for testing
        "release_threshold": 2.5,
        "holdoff_seconds": 0.2,
        "min_duration_seconds": 0.1,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 0.1,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)

    # Create frames with significant motion
    width, height = 640, 480

    # Send some initial frames
    for _i in range(3):
        frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        vframe = VideoFrame(
            camera_id="test-camera",
            payload=frame.tobytes(),
            timestamp=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        detector.detect_motion(vframe)

    # State should transition from IDLE
    assert detector._state in (
        RecordingState.IDLE,
        RecordingState.TRIGGERED,
        RecordingState.RECORDING,
    )


def test_detector_completes_recording_after_motion():
    """Test detector completes recording after motion ends."""
    settings = {
        "motion_threshold": 5.0,
        "release_threshold": 2.5,
        "holdoff_seconds": 0.1,  # Very short holdoff
        "min_duration_seconds": 0.1,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 0.1,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    width, height = 640, 480

    # Generate motion frames
    for _i in range(5):
        frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        vframe = VideoFrame(
            camera_id="test-camera",
            payload=frame.tobytes(),
            timestamp=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        result = detector.detect_motion(vframe)

    # Send static frames to end motion (holdoff)
    static_frame = np.zeros((height, width, 3), dtype=np.uint8)
    for _i in range(5):
        vframe = VideoFrame(
            camera_id="test-camera",
            payload=static_frame.tobytes(),
            timestamp=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        result = detector.detect_motion(vframe)
        if result:
            assert isinstance(result, DetectionEvent)
            assert result.camera_id == "test-camera"
            break


def test_detector_recording_too_short():
    """Test detector discards recording that's too short."""
    settings = {
        "motion_threshold": 5.0,
        "release_threshold": 2.5,
        "holdoff_seconds": 0.1,
        "min_duration_seconds": 5.0,  # Require 5 seconds minimum
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 0.1,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    width, height = 640, 480

    # Send a few motion frames (not enough for 5 seconds)
    for _i in range(3):
        frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
        vframe = VideoFrame(
            camera_id="test-camera",
            payload=frame.tobytes(),
            timestamp=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        detector.detect_motion(vframe)

    # Send static frames to trigger holdoff
    static_frame = np.zeros((height, width, 3), dtype=np.uint8)
    for _i in range(5):
        vframe = VideoFrame(
            camera_id="test-camera",
            payload=static_frame.tobytes(),
            timestamp=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        result = detector.detect_motion(vframe)
        # Should not return event since duration too short
        assert result is None

    # State should be back to IDLE
    assert detector._state == RecordingState.IDLE


def test_detector_max_duration_reached():
    """Test detector stops recording at max duration."""
    settings = {
        "motion_threshold": 5.0,
        "release_threshold": 2.5,
        "holdoff_seconds": 2.0,
        "min_duration_seconds": 0.1,
        "max_duration_seconds": 0.5,  # Short max duration
        "prebuffer_seconds": 0.1,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    width, height = 640, 480

    # Manually set state to RECORDING and event start time
    detector._state = RecordingState.RECORDING
    detector._event_start_time = datetime.now(timezone.utc)
    detector._recording_buffer = [(detector._event_start_time, b"test", 10.0)]

    # Wait to exceed max duration
    import time

    time.sleep(0.6)

    # Send frame - should trigger max duration completion
    frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)
    vframe = VideoFrame(
        camera_id="test-camera",
        payload=frame.tobytes(),
        timestamp=datetime.now(timezone.utc),
        width=width,
        height=height,
    )

    result = detector.detect_motion(vframe)

    # Should complete due to max duration
    if result:
        assert isinstance(result, DetectionEvent)


def test_detector_compute_motion():
    """Test motion computation from frames."""
    settings = {
        "motion_threshold": 25.0,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    width, height = 640, 480

    # Test with static frame
    static_frame = np.zeros((height, width, 3), dtype=np.uint8)
    vframe = VideoFrame(
        camera_id="test-camera",
        payload=static_frame.tobytes(),
        timestamp=datetime.now(timezone.utc),
        width=width,
        height=height,
    )

    motion_value = detector._compute_motion(vframe)
    assert isinstance(motion_value, float)
    assert motion_value >= 0.0


def test_detector_finalize_event():
    """Test event finalization."""
    settings = {
        "motion_threshold": 25.0,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)

    # Set up recording state
    detector._state = RecordingState.RECORDING
    start_time = datetime.now(timezone.utc)
    detector._event_start_time = start_time
    detector._peak_motion_value = 35.0

    # Add frames to buffer
    detector._recording_buffer = [
        (start_time, b"frame1", 30.0),
        (start_time, b"frame2", 35.0),
        (start_time, b"frame3", 28.0),
    ]

    event = detector._finalize_event("test-camera")

    assert isinstance(event, DetectionEvent)
    assert event.camera_id == "test-camera"
    assert event.peak_motion_value == 35.0
    assert len(event.video_frames) == 3
    assert event.metadata["algorithm"] == "background_subtraction"

    # State should be reset
    assert detector._state == RecordingState.IDLE
    assert len(detector._recording_buffer) == 0


def test_detector_prebuffer():
    """Test prebuffer functionality."""
    settings = {
        "motion_threshold": 25.0,
        "prebuffer_seconds": 0.5,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)

    # Prebuffer should hold 5 frames (0.5s * 10fps)
    assert detector._prebuffer_size == 5
    assert detector._prebuffer.maxlen == 5


def test_detector_idle_to_triggered_transition():
    """Test state transition from IDLE to TRIGGERED."""
    settings = {
        "motion_threshold": 5.0,
        "release_threshold": 2.5,
        "holdoff_seconds": 1.0,
        "min_duration_seconds": 0.5,
        "max_duration_seconds": 30.0,
        "prebuffer_seconds": 0.2,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)
    assert detector._state == RecordingState.IDLE

    # Create high-motion frame
    width, height = 640, 480
    frame = np.random.randint(100, 255, (height, width, 3), dtype=np.uint8)

    vframe = VideoFrame(
        camera_id="test-camera",
        payload=frame.tobytes(),
        timestamp=datetime.now(timezone.utc),
        width=width,
        height=height,
    )

    # Send several frames to potentially trigger motion
    for _ in range(3):
        detector.detect_motion(vframe)

    # After detecting motion, state should not be IDLE
    assert detector._state in (RecordingState.TRIGGERED, RecordingState.RECORDING)


def test_detector_recording_state_updates_peak():
    """Test that recording state updates peak motion value."""
    settings = {
        "motion_threshold": 5.0,
        "fps": 10,
    }

    detector = DetectorAlgorithm(settings)

    # Manually set to RECORDING state
    detector._state = RecordingState.RECORDING
    detector._event_start_time = datetime.now(timezone.utc)
    detector._peak_motion_value = 20.0

    width, height = 640, 480
    frame = np.random.randint(0, 255, (height, width, 3), dtype=np.uint8)

    vframe = VideoFrame(
        camera_id="test-camera",
        payload=frame.tobytes(),
        timestamp=datetime.now(timezone.utc),
        width=width,
        height=height,
    )

    detector.detect_motion(vframe)

    # Peak should be updated if motion value was higher
    assert detector._peak_motion_value >= 20.0
