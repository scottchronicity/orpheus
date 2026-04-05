"""Tests for video source."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

import numpy as np
import pytest
from orpheus_common.video.source import (
    RTSPVideoSource,
    VideoFrame,
)

from orpheus_agent_video_motion.config import RuntimeSettings


def test_video_frame_dataclass():
    """Test VideoFrame dataclass."""
    frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test_data",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    assert frame.camera_id == "test-camera"
    assert frame.payload == b"test_data"
    assert frame.width == 640
    assert frame.height == 480


def test_rtsp_video_source_initialization():
    """Test RTSPVideoSource initialization."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    assert source._camera_id == "test-camera"
    assert source.fps == 10
    assert source.width == 640
    assert source.height == 480
    assert source.is_running() is False


@pytest.mark.asyncio
async def test_video_source_start():
    """Test starting video source."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        mock_capture_class.return_value = mock_capture

        await source.start()

        assert source.is_running() is True
        mock_capture.set.assert_called()


@pytest.mark.asyncio
async def test_video_source_start_already_running():
    """Test starting video source when already running."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        mock_capture_class.return_value = mock_capture

        await source.start()
        assert source.is_running() is True

        # Try starting again
        await source.start()
        assert source.is_running() is True


@pytest.mark.asyncio
async def test_video_source_start_failure():
    """Test video source start failure when stream cannot be opened."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = False
        mock_capture_class.return_value = mock_capture

        with pytest.raises(RuntimeError, match="Failed to open RTSP stream"):
            await source.start()


@pytest.mark.asyncio
async def test_video_source_stop():
    """Test stopping video source."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        mock_capture.release = Mock()
        mock_capture_class.return_value = mock_capture

        await source.start()
        assert source.is_running() is True

        await source.stop()
        assert source.is_running() is False
        mock_capture.release.assert_called_once()


@pytest.mark.asyncio
async def test_video_source_stop_already_stopped():
    """Test stopping video source when already stopped."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    await source.stop()
    assert source.is_running() is False


@pytest.mark.asyncio
async def test_video_source_stream_frames_not_started():
    """Test streaming frames before starting raises error."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with pytest.raises(RuntimeError, match="must be started before streaming"):
        async for _ in source.stream_frames():
            pass


@pytest.mark.asyncio
async def test_video_source_stream_frames():
    """Test streaming frames from video source."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    # Create a test frame
    test_frame = VideoFrame(
        camera_id="test-camera",
        payload=b"test_data",
        timestamp=datetime.now(timezone.utc),
        width=640,
        height=480,
    )

    # Put frame in queue
    source._frame_queue = Queue(maxsize=50)
    source._frame_queue.put(test_frame)
    source._running = True

    frames_received = []
    async for frame in source.stream_frames():
        frames_received.append(frame)
        break  # Only get one frame

    assert len(frames_received) == 1
    assert frames_received[0].camera_id == "test-camera"

    await source.stop()


@pytest.mark.asyncio
async def test_video_source_capture_loop_frame_resize():
    """Test capture loop resizes frames when needed."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=320,  # Different from captured frame
        height=240,
        max_pending_frames=50,
    )

    # Create a larger test frame
    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        mock_capture.read.side_effect = [(True, test_frame), (False, None)]
        mock_capture_class.return_value = mock_capture

        with patch("cv2.resize") as mock_resize:
            mock_resize.return_value = np.zeros((240, 320, 3), dtype=np.uint8)

            await source.start()

            # Wait briefly for capture thread to process
            await asyncio.sleep(0.1)

            await source.stop()

            # Verify resize was called
            mock_resize.assert_called()


@pytest.mark.asyncio
async def test_video_source_capture_loop_read_failure():
    """Test capture loop handles read failures."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        # Simulate failed read
        mock_capture.read.return_value = (False, None)
        mock_capture_class.return_value = mock_capture

        await source.start()

        # Wait briefly for capture thread to process
        await asyncio.sleep(0.1)

        await source.stop()


@pytest.mark.asyncio
async def test_video_source_capture_loop_exception():
    """Test capture loop handles exceptions."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        # Simulate exception during read
        mock_capture.read.side_effect = Exception("Test error")
        mock_capture_class.return_value = mock_capture

        await source.start()

        # Wait briefly for capture thread to handle error
        await asyncio.sleep(0.1)

        await source.stop()


@pytest.mark.asyncio
async def test_video_source_capture_loop_queue_full():
    """Test capture loop drops frames when queue is full."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=1,  # Very small queue
    )

    test_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    with patch("cv2.VideoCapture") as mock_capture_class:
        mock_capture = Mock()
        mock_capture.isOpened.return_value = True
        # Return multiple frames
        mock_capture.read.return_value = (True, test_frame)
        mock_capture_class.return_value = mock_capture

        await source.start()

        # Wait for queue to fill up
        await asyncio.sleep(0.2)

        await source.stop()


@pytest.mark.asyncio
async def test_create_video_source():
    """Test direct instantiation of RTSPVideoSource."""
    runtime = RuntimeSettings(
        fps=15,
        width=800,
        height=600,
        max_pending_frames=100,
        working_directory=Path("/tmp"),
    )

    source = RTSPVideoSource(
        camera_id="factory-camera",
        rtsp_url="rtsp://test.url/stream",
        fps=runtime.fps,
        width=runtime.width,
        height=runtime.height,
        max_pending_frames=runtime.max_pending_frames,
    )

    assert isinstance(source, RTSPVideoSource)
    assert source._camera_id == "factory-camera"
    assert source.fps == 15
    assert source.width == 800
    assert source.height == 600


@pytest.mark.skip(reason="Requires actual RTSP stream")
@pytest.mark.asyncio
async def test_rtsp_video_source_start_stop():
    """Test starting and stopping RTSP source."""
    source = RTSPVideoSource(
        camera_id="test-camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
    )

    # This would require an actual RTSP stream to test properly
    # Just verify the interface is correct
    assert hasattr(source, "start")
    assert hasattr(source, "stop")
    assert hasattr(source, "stream_frames")
