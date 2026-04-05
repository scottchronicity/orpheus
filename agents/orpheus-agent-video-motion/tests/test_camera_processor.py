"""Tests for camera processor."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from orpheus_common.video.source import VideoFrame

from orpheus_agent_video_motion.camera_processor import CameraProcessor
from orpheus_agent_video_motion.detector_algorithm import DetectionEvent, DetectorAlgorithm


@pytest.mark.asyncio
async def test_camera_processor_initialization():
    """Test CameraProcessor initialization."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    assert processor._camera_id == "test-camera"
    assert processor._detector == mock_detector
    assert processor._mqtt_client == mock_mqtt
    assert processor._qos == 1


@pytest.mark.asyncio
async def test_camera_processor_ignores_wrong_camera():
    """Test that processor ignores frames from other cameras."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="camera1",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    # Create frame for different camera
    frame = VideoFrame(
        camera_id="camera2",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Detector should not be called
    mock_detector.detect_motion.assert_not_called()


@pytest.mark.asyncio
async def test_camera_processor_handles_no_detection():
    """Test processor handles case when no motion is detected."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.return_value = None  # No detection
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Detector should be called, but nothing published
    mock_detector.detect_motion.assert_called_once()
    mock_mqtt.publish.assert_not_called()


@pytest.mark.asyncio
async def test_camera_processor_publishes_detection():
    """Test processor publishes detection event."""
    # Create mock detection event
    mock_detection = DetectionEvent(
        camera_id="test-camera",
        timestamp=datetime.now(timezone.utc),
        duration_seconds=2.5,
        peak_motion_value=35.0,
        average_motion_value=28.0,
        video_frames=[b"frame1", b"frame2"],
        metadata={"algorithm": "test"},
    )

    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.return_value = mock_detection
    mock_mqtt = Mock()
    mock_clip_saver = Mock()
    mock_clip_saver.save_clip.return_value = Path("/tmp/test.mp4")

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Check that clip was saved
    mock_clip_saver.save_clip.assert_called_once()

    # Check that MQTT was published
    mock_mqtt.publish.assert_called_once()
    call_args = mock_mqtt.publish.call_args
    assert call_args[1]["topic"] == "test/events"
    assert call_args[1]["qos"] == 1


@pytest.mark.asyncio
async def test_camera_processor_handles_detector_not_implemented():
    """Test processor handles NotImplementedError from detector."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.side_effect = NotImplementedError("Not implemented")
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    # Should handle gracefully
    await processor.handle_frame(frame)

    # Should not publish anything
    mock_mqtt.publish.assert_not_called()


@pytest.mark.asyncio
async def test_camera_processor_handles_detector_exception():
    """Test processor handles detector exceptions."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.side_effect = RuntimeError("Detector error")
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Should publish error status
    assert mock_mqtt.publish.call_count == 1
    call_args = mock_mqtt.publish.call_args
    assert call_args[1]["topic"] == "test/status"
    payload = call_args[1]["payload"]
    assert payload["state"] == "error"


@pytest.mark.asyncio
async def test_camera_processor_handles_clip_save_failure():
    """Test processor handles clip save failures."""
    mock_detection = DetectionEvent(
        camera_id="test-camera",
        timestamp=datetime.now(timezone.utc),
        duration_seconds=2.5,
        peak_motion_value=35.0,
        average_motion_value=28.0,
        video_frames=[b"frame1", b"frame2"],
        metadata={"algorithm": "test"},
    )

    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.return_value = mock_detection
    mock_mqtt = Mock()
    mock_clip_saver = Mock()
    mock_clip_saver.save_clip.side_effect = RuntimeError("Save failed")

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Should still publish event (without clip path) and status
    assert mock_mqtt.publish.call_count == 2

    # Check first call is status
    status_call = mock_mqtt.publish.call_args_list[0]
    assert status_call[1]["topic"] == "test/status"
    assert status_call[1]["payload"]["state"] == "warning"

    # Check second call is event
    event_call = mock_mqtt.publish.call_args_list[1]
    assert event_call[1]["topic"] == "test/events"


@pytest.mark.asyncio
async def test_camera_processor_detection_without_frames():
    """Test processor handles detection event with no video frames."""
    mock_detection = DetectionEvent(
        camera_id="test-camera",
        timestamp=datetime.now(timezone.utc),
        duration_seconds=2.5,
        peak_motion_value=35.0,
        average_motion_value=28.0,
        video_frames=[],  # No frames
        metadata={"algorithm": "test"},
    )

    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.return_value = mock_detection
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    await processor.handle_frame(frame)

    # Should not try to save clip
    mock_clip_saver.save_clip.assert_not_called()

    # Should still publish event
    mock_mqtt.publish.assert_called_once()
    call_args = mock_mqtt.publish.call_args
    assert call_args[1]["topic"] == "test/events"
    assert "clip_path" not in call_args[1]["payload"]


@pytest.mark.asyncio
async def test_camera_processor_publish_status():
    """Test processor can publish status messages."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=2,
    )

    await processor._publish_status({"state": "healthy"})

    mock_mqtt.publish.assert_called_once()
    call_args = mock_mqtt.publish.call_args
    assert call_args[1]["topic"] == "test/status"
    assert call_args[1]["qos"] == 2
    payload = call_args[1]["payload"]
    assert payload["state"] == "healthy"
    assert payload["camera_id"] == "test-camera"


@pytest.mark.asyncio
async def test_camera_processor_concurrent_frame_handling():
    """Test processor handles concurrent frames with lock."""
    mock_detector = Mock(spec=DetectorAlgorithm)
    mock_detector.detect_motion.return_value = None
    mock_mqtt = Mock()
    mock_clip_saver = Mock()

    processor = CameraProcessor(
        camera_id="test-camera",
        detector=mock_detector,
        mqtt_client=mock_mqtt,
        clip_saver=mock_clip_saver,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    frame1 = VideoFrame(
        camera_id="test-camera",
        payload=b"test1",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    frame2 = VideoFrame(
        camera_id="test-camera",
        payload=b"test2",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    # Process frames concurrently
    import asyncio

    await asyncio.gather(processor.handle_frame(frame1), processor.handle_frame(frame2))

    # Both frames should be processed
    assert mock_detector.detect_motion.call_count == 2
