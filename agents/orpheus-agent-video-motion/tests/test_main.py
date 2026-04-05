"""Tests for main.py entrypoint and VideoMotionDetector."""

import argparse
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from orpheus_agent_video_motion.config import AppConfig
from orpheus_agent_video_motion.main import (
    VideoMotionDetector,
    main,
    main_async,
    parse_args,
)


def test_parse_args_no_arguments():
    """Test parse_args with no arguments."""
    args = parse_args([])
    assert args.config is None
    assert args.log_level is None


def test_parse_args_with_config():
    """Test parse_args with config path."""
    args = parse_args(["--config", "/tmp/test.yaml"])
    assert args.config == Path("/tmp/test.yaml")
    assert args.log_level is None


def test_parse_args_with_log_level():
    """Test parse_args with log level."""
    args = parse_args(["--log-level", "DEBUG"])
    assert args.config is None
    assert args.log_level == "DEBUG"


def test_parse_args_with_all_arguments():
    """Test parse_args with all arguments."""
    args = parse_args(["--config", "/tmp/test.yaml", "--log-level", "INFO"])
    assert args.config == Path("/tmp/test.yaml")
    assert args.log_level == "INFO"


@pytest.mark.asyncio
async def test_video_motion_detector_initialization():
    """Test VideoMotionDetector initialization."""
    detector = VideoMotionDetector()
    assert detector._config is not None
    assert detector._mqtt_client is None
    assert detector._video_sources == {}
    assert detector._processors == {}
    assert detector._clip_saver is None
    assert not detector._stop_event.is_set()
    assert detector._reconnect_tasks == []
    assert detector._reconnecting == set()
    assert detector._camera_configs == {}


@pytest.mark.asyncio
async def test_video_motion_detector_initialization_with_config():
    """Test VideoMotionDetector initialization with config path."""
    with patch("orpheus_agent_video_motion.main.load_app_config") as mock_load:
        mock_config = Mock()
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector(config_path=Path("/tmp/test.yaml"))
        mock_load.assert_called_once_with(Path("/tmp/test.yaml"))
        assert detector._config == mock_config


@pytest.mark.asyncio
async def test_video_motion_detector_initialization_with_log_override():
    """Test VideoMotionDetector initialization with log level override."""
    detector = VideoMotionDetector(log_level_override="DEBUG")
    assert detector._log_level_override == "DEBUG"


@pytest.mark.asyncio
async def test_video_motion_detector_stop_when_not_started():
    """Test stop when detector was never started."""
    detector = VideoMotionDetector()
    await detector.stop()  # Should not raise


@pytest.mark.asyncio
async def test_video_motion_detector_stop_with_mqtt_connected():
    """Test stop with MQTT client connected."""
    detector = VideoMotionDetector()
    mock_mqtt = Mock()
    mock_mqtt.is_connected = True
    detector._mqtt_client = mock_mqtt

    await detector.stop()
    mock_mqtt.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_video_motion_detector_stop_with_running_video_sources():
    """Test stop with running video sources."""
    detector = VideoMotionDetector()

    mock_source = Mock()
    mock_source.is_running.return_value = True
    mock_source.stop = Mock(return_value=None)

    # Make stop() awaitable
    async def async_stop():
        pass

    mock_source.stop = async_stop

    detector._video_sources = {"camera1": mock_source}

    await detector.stop()


def test_main_success():
    """Test main function successful execution."""
    with patch("orpheus_agent_video_motion.main.asyncio.run") as mock_run:
        mock_run.return_value = None

        result = main([])
        assert result == 0


def test_main_keyboard_interrupt():
    """Test main function handles keyboard interrupt."""
    with patch("orpheus_agent_video_motion.main.asyncio.run") as mock_run:
        mock_run.side_effect = KeyboardInterrupt()

        result = main([])
        assert result == 130


def test_main_exception():
    """Test main function handles exceptions."""
    with patch("orpheus_agent_video_motion.main.asyncio.run") as mock_run:
        mock_run.side_effect = ValueError("Test error")

        result = main([])
        assert result == 1


def test_main_with_arguments():
    """Test main function with command line arguments."""
    with patch("orpheus_agent_video_motion.main.asyncio.run") as mock_run:
        mock_run.return_value = None

        result = main(["--config", "/tmp/test.yaml", "--log-level", "DEBUG"])
        assert result == 0


@pytest.mark.asyncio
async def test_main_async_with_args():
    """Test main_async function."""
    args = argparse.Namespace(config=None, log_level=None)

    with patch("orpheus_agent_video_motion.main.VideoMotionDetector") as mock_detector_class:
        mock_detector = Mock()
        mock_detector.start = Mock(return_value=None)

        # Make start() awaitable
        async def async_start():
            pass

        mock_detector.start = async_start

        mock_detector_class.return_value = mock_detector

        await main_async(args)
    """Test stop with running video sources."""
    detector = VideoMotionDetector()

    mock_source = AsyncMock()
    mock_source.is_running.return_value = True
    detector._video_sources = {"camera1": mock_source}

    await detector.stop()
    mock_source.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_video_motion_detector_stop_with_cleanup_task():
    """Test stop with active cleanup task."""
    detector = VideoMotionDetector()

    # Create a real async task
    async def dummy_task():
        await asyncio.sleep(10)

    task = asyncio.create_task(dummy_task())
    detector._cleanup_task = task

    await detector.stop()
    assert task.cancelled()


@pytest.mark.asyncio
async def test_video_motion_detector_stop_with_stream_tasks():
    """Test stop with active stream tasks."""
    detector = VideoMotionDetector()

    # Create real async tasks
    async def dummy_task():
        await asyncio.sleep(10)

    task1 = asyncio.create_task(dummy_task())
    task2 = asyncio.create_task(dummy_task())
    detector._stream_tasks = [task1, task2]

    await detector.stop()

    assert task1.cancelled()
    assert task2.cancelled()
    assert detector._stream_tasks == []


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_dependencies_no_cameras():
    """Test initialization fails when no enabled cameras with RTSP URLs."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
    ):
        # Create mock config with no cameras
        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = []
        mock_config.mqtt = Mock(broker_host="localhost", broker_port=1883, qos=1, keepalive=60)
        mock_config.storage = Mock(category="video_motion", write_format="mp4")
        mock_config.runtime = Mock(fps=20, width=640, height=480)
        mock_load.return_value = mock_config

        # Mock MQTT client to prevent actual connection attempts
        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        detector = VideoMotionDetector()

        with pytest.raises(RuntimeError, match="No enabled cameras with RTSP URLs"):
            await detector._initialize_dependencies()


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_dependencies_disabled_camera():
    """Test initialization raises when all cameras are disabled."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
    ):
        # Mock config with disabled camera
        mock_camera = Mock()
        mock_camera.enabled = False
        mock_camera.id = "camera1"
        mock_camera.rtsp_url = "rtsp://localhost/stream"

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera]
        mock_config.mqtt = Mock(broker_host="localhost", broker_port=1883, qos=1, keepalive=60)
        mock_config.storage = Mock(category="video_motion", write_format="mp4")
        mock_config.runtime = Mock(fps=20, width=640, height=480)
        mock_load.return_value = mock_config

        # Mock MQTT client to prevent actual connection attempts
        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        detector = VideoMotionDetector()

        with pytest.raises(RuntimeError, match="No enabled cameras with RTSP URLs"):
            await detector._initialize_dependencies()


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_dependencies_missing_rtsp():
    """Test initialization skips camera with missing RTSP URL."""
    with patch("orpheus_agent_video_motion.main.load_app_config") as mock_load:
        # Mock config with camera missing RTSP URL
        mock_camera = Mock()
        mock_camera.enabled = True
        mock_camera.id = "camera1"
        mock_camera.rtsp_url = None

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera]
        mock_config.mqtt = Mock(broker_host="localhost", broker_port=1883, qos=1, keepalive=60)
        mock_load.return_value = mock_config

        VideoMotionDetector()


@pytest.mark.asyncio
async def test_video_motion_detector_consume_frames_no_processor():
    """Test consume frames when processor not found."""
    detector = VideoMotionDetector()
    detector._processors = {}  # No processors
    detector._stop_event.set()  # Stop immediately

    from orpheus_common.video.source import VideoFrame

    async def mock_stream():
        yield VideoFrame(
            camera_id="unknown-camera",
            payload=b"test",
            timestamp=datetime.now(timezone.utc),
            width=640,
            height=480,
        )

    mock_source = Mock()
    mock_source.stream_frames = mock_stream

    # Should complete without error
    await detector._consume_frames("camera1", mock_source)


@pytest.mark.asyncio
async def test_video_motion_detector_consume_frames_with_exception():
    """Test consume frames handles exceptions without killing the agent."""
    detector = VideoMotionDetector()

    async def mock_stream_with_error():
        raise ValueError("Test error")
        yield  # pragma: no cover

    mock_source = Mock()
    mock_source.stream_frames = mock_stream_with_error

    with patch.object(detector, "_schedule_reconnect") as mock_reconnect:
        await detector._consume_frames("camera1", mock_source)
        # Single camera failure should NOT set the stop event (agent stays alive)
        assert not detector._stop_event.is_set()
        # Stream death should schedule a reconnect
        mock_reconnect.assert_called_once_with("camera1")


@pytest.mark.asyncio
async def test_video_motion_detector_consume_frames_cancellation():
    """Test consume frames handles cancellation."""
    detector = VideoMotionDetector()

    async def mock_stream_cancelled():
        raise asyncio.CancelledError()
        yield  # pragma: no cover

    mock_source = Mock()
    mock_source.stream_frames = mock_stream_cancelled

    with patch.object(detector, "_schedule_reconnect"):
        with pytest.raises(asyncio.CancelledError):
            await detector._consume_frames("camera1", mock_source)


@pytest.mark.asyncio
async def test_video_motion_detector_periodic_cleanup_no_files():
    """Test periodic cleanup when no files need removal."""
    with patch("orpheus_agent_video_motion.main.load_app_config") as mock_load:
        # Create mock config
        mock_storage = Mock()
        mock_storage.retain_days = 7
        mock_storage.check_interval_hours = 0.001

        mock_config = Mock(spec=AppConfig)
        mock_config.storage = mock_storage
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector()

    # Create a task and cancel it after short time
    cleanup_task = asyncio.create_task(detector._periodic_cleanup())

    # Let it run briefly
    await asyncio.sleep(0.01)

    # Cancel the task - it will catch CancelledError and break cleanly
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass  # Expected to be caught by the method itself


@pytest.mark.asyncio
async def test_video_motion_detector_periodic_cleanup_with_exception():
    """Test periodic cleanup handles exceptions gracefully."""
    with patch("orpheus_agent_video_motion.main.load_app_config") as mock_load:
        # Create mock config
        mock_storage = Mock()
        mock_storage.retain_days = 7
        mock_storage.check_interval_hours = 0.001

        mock_config = Mock(spec=AppConfig)
        mock_config.storage = mock_storage
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector()

    with patch("orpheus_agent_video_motion.main.StorageCleanup") as mock_cleanup_class:
        mock_cleanup = Mock()
        mock_cleanup.cleanup.side_effect = Exception("Test error")
        mock_cleanup_class.return_value = mock_cleanup

        # Create task and let it run
        cleanup_task = asyncio.create_task(detector._periodic_cleanup())
        await asyncio.sleep(0.01)

        # Cancel the task - it will catch CancelledError and break cleanly
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass  # Expected to be caught by the method itself


@pytest.mark.asyncio
async def test_main_async_keyboard_interrupt():
    """Test main_async handles keyboard interrupt."""
    args = argparse.Namespace(config=None, log_level=None)

    with patch("orpheus_agent_video_motion.main.VideoMotionDetector") as mock_detector_class:
        mock_detector = AsyncMock()
        mock_detector.start.side_effect = KeyboardInterrupt()
        mock_detector_class.return_value = mock_detector

        with pytest.raises(KeyboardInterrupt):
            await main_async(args)


@pytest.mark.asyncio
async def test_main_async_exception():
    """Test main_async handles generic exceptions."""
    args = argparse.Namespace(config=None, log_level=None)

    with patch("orpheus_agent_video_motion.main.VideoMotionDetector") as mock_detector_class:
        mock_detector = AsyncMock()
        mock_detector.start.side_effect = ValueError("Test error")
        mock_detector_class.return_value = mock_detector

        with pytest.raises(ValueError):
            await main_async(args)


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_with_enabled_camera():
    """Test initialization succeeds with enabled camera."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
        patch("orpheus_agent_video_motion.main.ClipSaver"),
        patch("orpheus_agent_video_motion.main.RTSPVideoSource") as mock_video_source_class,
        patch("orpheus_agent_video_motion.main.create_detector") as mock_create_detector,
        patch("orpheus_agent_video_motion.main.CameraProcessor") as mock_processor_class,
        patch("orpheus_common.config.OrpheusConfig") as mock_orpheus_config,
    ):
        # Mock camera config
        mock_camera = Mock()
        mock_camera.enabled = True
        mock_camera.id = "camera1"
        mock_camera.rtsp_url = "rtsp://test.url/stream"

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera]
        mock_config.mqtt = Mock(
            broker_host="localhost",
            broker_port=1883,
            qos=1,
            keepalive=60,
            topic_events="test/events",
            topic_status="test/status",
        )
        mock_config.storage = Mock(category="video_motion", write_format="mp4")
        mock_config.runtime = Mock(fps=10, width=640, height=480, max_pending_frames=50)
        mock_load.return_value = mock_config

        # Mock MQTT
        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        # Mock video source
        mock_source = AsyncMock()
        mock_source.start = AsyncMock()
        mock_video_source_class.return_value = mock_source

        # Mock detector
        mock_detector = Mock()
        mock_create_detector.return_value = mock_detector

        # Mock processor
        mock_processor = Mock()
        mock_processor_class.return_value = mock_processor

        # Mock OrpheusConfig
        mock_orpheus_inst = Mock()
        mock_orpheus_inst.video.motion_detection = None
        mock_orpheus_config.get_instance.return_value = mock_orpheus_inst

        detector = VideoMotionDetector()
        await detector._initialize_dependencies()

        assert len(detector._processors) == 1
        assert "camera1" in detector._processors


@pytest.mark.asyncio
async def test_video_motion_detector_consume_frames_with_processor():
    """Test consume frames processes frames through processor."""
    detector = VideoMotionDetector()

    from orpheus_common.video.source import VideoFrame

    # Create processor
    mock_processor = AsyncMock()
    mock_processor.handle_frame = AsyncMock()
    detector._processors = {"test-camera": mock_processor}

    frame_count = 0

    async def mock_stream():
        nonlocal frame_count
        for _i in range(3):
            frame_count += 1
            yield VideoFrame(
                camera_id="test-camera",
                payload=b"test",
                timestamp=datetime.now(timezone.utc),
                width=640,
                height=480,
            )

    mock_source = Mock()
    mock_source.stream_frames = mock_stream

    # Create a task to stop after a short time
    async def stop_after_delay():
        await asyncio.sleep(0.1)
        detector._stop_event.set()

    stop_task = asyncio.create_task(stop_after_delay())

    await detector._consume_frames("test-camera", mock_source)

    await stop_task

    # Verify processor was called
    assert mock_processor.handle_frame.call_count == 3


@pytest.mark.asyncio
async def test_video_motion_detector_periodic_cleanup_with_files_removed():
    """Test periodic cleanup when files are removed."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.main.StorageCleanup") as mock_cleanup_class,
    ):
        # Create mock config
        mock_storage = Mock()
        mock_storage.retain_days = 7
        mock_storage.check_interval_hours = 0.001
        mock_storage.max_size_gb = 50
        mock_storage.cleanup_strategy = "oldest"

        mock_config = Mock(spec=AppConfig)
        mock_config.storage = mock_storage
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector()

        # Mock cleanup result
        mock_result = Mock()
        mock_result.files_removed = 5
        mock_result.bytes_freed = 1024 * 1024 * 100  # 100 MB
        mock_result.manifest_path = Path("/tmp/manifest.json")
        mock_result.errors = []

        mock_cleanup = Mock()
        mock_cleanup.cleanup.return_value = mock_result
        mock_cleanup_class.return_value = mock_cleanup

        mock_get_path.return_value = Path("/tmp/video_motion")

        # Create task and let it run
        cleanup_task = asyncio.create_task(detector._periodic_cleanup())
        await asyncio.sleep(0.02)

        # Cancel the task
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_camera_exception():
    """Test initialization continues when camera initialization fails."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
        patch("orpheus_agent_video_motion.main.ClipSaver"),
        patch("orpheus_agent_video_motion.main.RTSPVideoSource") as mock_video_source_class,
        patch("orpheus_common.config.OrpheusConfig") as mock_orpheus_config,
    ):
        # Mock two cameras, one will fail
        mock_camera1 = Mock()
        mock_camera1.enabled = True
        mock_camera1.id = "camera1"
        mock_camera1.rtsp_url = "rtsp://test.url/stream1"

        mock_camera2 = Mock()
        mock_camera2.enabled = True
        mock_camera2.id = "camera2"
        mock_camera2.rtsp_url = "rtsp://test.url/stream2"

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera1, mock_camera2]
        mock_config.mqtt = Mock(
            broker_host="localhost",
            broker_port=1883,
            qos=1,
            keepalive=60,
            topic_events="test/events",
            topic_status="test/status",
        )
        mock_config.storage = Mock(category="video_motion", write_format="mp4")
        mock_config.runtime = Mock(fps=10, width=640, height=480, max_pending_frames=50)
        mock_load.return_value = mock_config

        # Mock MQTT
        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        # First camera fails, second succeeds
        mock_source2 = AsyncMock()
        mock_source2.start = AsyncMock()

        call_count = [0]

        def video_source_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # First camera
                raise RuntimeError("Failed to create source")
            return mock_source2

        mock_video_source_class.side_effect = video_source_side_effect

        # Mock OrpheusConfig
        mock_orpheus_inst = Mock()
        mock_orpheus_inst.video.motion_detection = None
        mock_orpheus_config.get_instance.return_value = mock_orpheus_inst

        detector = VideoMotionDetector()

        # Should not raise — both processors are registered, camera1 just goes offline
        with patch("orpheus_agent_video_motion.main.create_detector"):
            with patch("orpheus_agent_video_motion.main.CameraProcessor"):
                await detector._initialize_dependencies()

        # Both processors registered; only camera2 has a live video source
        assert len(detector._processors) == 2
        assert "camera1" in detector._processors
        assert "camera2" in detector._processors
        assert "camera1" not in detector._video_sources
        assert "camera2" in detector._video_sources

        # camera1 should have a reconnect task scheduled
        assert len(detector._reconnect_tasks) == 1
        # Clean up reconnect task
        for task in detector._reconnect_tasks:
            task.cancel()
        await asyncio.gather(*detector._reconnect_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_video_motion_detector_start_initialization_failure():
    """Test start handles initialization failure."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.setup_logging"),
    ):
        mock_config = Mock(spec=AppConfig)
        mock_config.logging = Mock(level="INFO", use_json=False)
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector()

        # Mock _initialize_dependencies to raise
        async def mock_init_fail():
            raise RuntimeError("Init failed")

        detector._initialize_dependencies = mock_init_fail

        with pytest.raises(RuntimeError, match="Init failed"):
            await detector.start()


@pytest.mark.asyncio
async def test_video_motion_detector_cleanup_with_errors():
    """Test periodic cleanup when errors occur."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.main.StorageCleanup") as mock_cleanup_class,
    ):
        mock_storage = Mock()
        mock_storage.retain_days = 7
        mock_storage.check_interval_hours = 0.001

        mock_config = Mock(spec=AppConfig)
        mock_config.storage = mock_storage
        mock_config.cameras = []
        mock_load.return_value = mock_config

        detector = VideoMotionDetector()

        # Mock cleanup result with errors
        mock_result = Mock()
        mock_result.files_removed = 2
        mock_result.bytes_freed = 1024 * 1024
        mock_result.manifest_path = None
        mock_result.errors = ["Error 1", "Error 2", "Error 3"]

        mock_cleanup = Mock()
        mock_cleanup.cleanup.return_value = mock_result
        mock_cleanup_class.return_value = mock_cleanup

        mock_get_path.return_value = Path("/tmp/video_motion")

        cleanup_task = asyncio.create_task(detector._periodic_cleanup())
        await asyncio.sleep(0.02)

        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_video_motion_detector_start_complete_flow():
    """Test complete start flow including initialization and tasks."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
        patch("orpheus_agent_video_motion.main.RTSPVideoSource") as mock_video_source_class,
        patch("orpheus_agent_video_motion.main.create_detector") as mock_create_detector,
        patch("orpheus_agent_video_motion.main.ClipSaver") as mock_clip_saver_class,
        patch("orpheus_agent_video_motion.main.get_video_health_monitor") as mock_health_monitor,
    ):
        # Setup mocks
        mock_camera = Mock()
        mock_camera.enabled = True
        mock_camera.id = "camera1"
        mock_camera.rtsp_url = "rtsp://test"

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera]
        mock_config.mqtt = Mock(broker_host="localhost", broker_port=1883, qos=1, keepalive=60)
        mock_config.storage = Mock(
            category="video_motion",
            write_format="mp4",
            retain_days=7,
            max_size_gb=50,
            cleanup_strategy="oldest",
            check_interval_hours=6,
        )
        mock_config.runtime = Mock(fps=20, width=640, height=480)
        mock_config.logging = Mock(level="INFO", use_json=False)
        mock_load.return_value = mock_config

        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        mock_source = AsyncMock()
        mock_source.start = AsyncMock()
        mock_source.is_running.return_value = False

        async def mock_stream():
            yield  # pragma: no cover

        mock_source.stream_frames = mock_stream
        mock_video_source_class.return_value = mock_source

        mock_detector = Mock()
        mock_create_detector.return_value = mock_detector

        mock_clip_saver = Mock()
        mock_clip_saver_class.return_value = mock_clip_saver

        mock_health = Mock()
        mock_health.get_status.return_value = {"running": True, "cameras": []}
        mock_health_monitor.return_value = mock_health

        detector = VideoMotionDetector()

        # Start and quickly stop
        async def stop_after_delay():
            await asyncio.sleep(0.1)
            detector._stop_event.set()

        stop_task = asyncio.create_task(stop_after_delay())
        await detector.start()
        await stop_task

        # Verify initialization happened
        mock_mqtt.connect.assert_called_once()


@pytest.mark.asyncio
async def test_video_motion_detector_stop_all_components():
    """Test stop method handles all components."""
    detector = VideoMotionDetector()

    # Setup components
    detector._health_task = asyncio.create_task(asyncio.sleep(10))
    detector._cleanup_task = asyncio.create_task(asyncio.sleep(10))

    mock_reconnect_task = asyncio.create_task(asyncio.sleep(10))
    detector._reconnect_tasks = [mock_reconnect_task]

    mock_stream_task = asyncio.create_task(asyncio.sleep(10))
    detector._stream_tasks = [mock_stream_task]

    mock_source = AsyncMock()
    mock_source.is_running.return_value = True
    mock_source.stop = AsyncMock()
    detector._video_sources = {"camera1": mock_source}

    mock_mqtt = Mock()
    mock_mqtt.is_connected = True
    detector._mqtt_client = mock_mqtt

    await detector.stop()

    # Verify all components stopped
    assert detector._health_task.cancelled()
    assert detector._cleanup_task.cancelled()
    assert mock_reconnect_task.cancelled()
    assert mock_stream_task.cancelled()
    mock_source.stop.assert_called_once()
    mock_mqtt.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_video_motion_detector_consume_frames_with_logging():
    """Test consume frames with frame count logging."""
    detector = VideoMotionDetector()

    from orpheus_common.video.source import VideoFrame

    # Create frames generator
    async def mock_stream():
        for _ in range(305):  # More than 300 to trigger debug log
            if detector._stop_event.is_set():
                break
            yield VideoFrame(
                camera_id="camera1",
                payload=b"test",
                timestamp=datetime.now(timezone.utc),
                width=640,
                height=480,
            )

    mock_source = Mock()
    mock_source.stream_frames = mock_stream

    mock_processor = AsyncMock()
    detector._processors = {"camera1": mock_processor}

    # Start consuming, but stop after a short delay
    async def stop_after_delay():
        await asyncio.sleep(0.05)
        detector._stop_event.set()

    stop_task = asyncio.create_task(stop_after_delay())
    await detector._consume_frames("camera1", mock_source)
    await stop_task

    # Should have processed some frames
    assert mock_processor.handle_frame.called


@pytest.mark.asyncio
async def test_video_motion_detector_publish_health_status():
    """Test health status publishing."""
    with patch("orpheus_agent_video_motion.main.get_video_health_monitor") as mock_health_monitor:
        detector = VideoMotionDetector()

        mock_mqtt = Mock()
        detector._mqtt_client = mock_mqtt

        mock_health = Mock()
        mock_health.get_status.return_value = {"running": True, "cameras": [{"camera_id": "cam1"}]}
        mock_health_monitor.return_value = mock_health

        # Start task and let it publish once
        health_task = asyncio.create_task(detector._publish_health_status())

        await asyncio.sleep(0.1)
        detector._stop_event.set()

        try:
            await asyncio.wait_for(health_task, timeout=2.0)
        except asyncio.TimeoutError:
            health_task.cancel()
            try:
                await health_task
            except asyncio.CancelledError:
                pass

        # Task should be done
        assert health_task.done()


@pytest.mark.asyncio
async def test_video_motion_detector_initialize_camera_failure():
    """Test initialization handles camera setup failure gracefully."""
    with (
        patch("orpheus_agent_video_motion.main.load_app_config") as mock_load,
        patch("orpheus_agent_video_motion.main.MQTTClient") as mock_mqtt_class,
        patch("orpheus_agent_video_motion.main.RTSPVideoSource") as mock_video_source_class,
        patch("orpheus_agent_video_motion.main.ClipSaver") as mock_clip_saver_class,
        patch("orpheus_common.config.OrpheusConfig") as mock_orpheus_config,
    ):
        mock_camera = Mock()
        mock_camera.enabled = True
        mock_camera.id = "camera1"
        mock_camera.rtsp_url = "rtsp://test"

        mock_config = Mock(spec=AppConfig)
        mock_config.cameras = [mock_camera]
        mock_config.mqtt = Mock(broker_host="localhost", broker_port=1883, qos=1, keepalive=60)
        mock_config.storage = Mock(category="video_motion", write_format="mp4")
        mock_config.runtime = Mock(fps=20, width=640, height=480, max_pending_frames=50)
        mock_load.return_value = mock_config

        mock_mqtt = Mock()
        mock_mqtt.connect = Mock()
        mock_mqtt_class.return_value = mock_mqtt

        # Make RTSP source creation fail
        mock_video_source_class.side_effect = RuntimeError("Camera init failed")

        mock_clip_saver = Mock()
        mock_clip_saver_class.return_value = mock_clip_saver

        mock_orpheus_inst = Mock()
        mock_orpheus_inst.video.motion_detection = None
        mock_orpheus_config.get_instance.return_value = mock_orpheus_inst

        detector = VideoMotionDetector()

        # Should not raise — RTSP failure is graceful; camera goes offline
        with patch("orpheus_agent_video_motion.main.create_detector"):
            with patch("orpheus_agent_video_motion.main.CameraProcessor"):
                await detector._initialize_dependencies()

        # Processor is registered but camera has no live video source
        assert "camera1" in detector._processors
        assert "camera1" not in detector._video_sources

        # Camera should have a reconnect task scheduled
        assert len(detector._reconnect_tasks) == 1
        # Clean up reconnect task
        for task in detector._reconnect_tasks:
            task.cancel()
        await asyncio.gather(*detector._reconnect_tasks, return_exceptions=True)


# --- RTSP reconnect tests ---


@pytest.mark.asyncio
async def test_schedule_reconnect_skips_when_stopped():
    """Test _schedule_reconnect does nothing when stop event is set."""
    detector = VideoMotionDetector()
    detector._stop_event.set()

    detector._schedule_reconnect("camera1")

    assert detector._reconnect_tasks == []
    assert "camera1" not in detector._reconnecting


@pytest.mark.asyncio
async def test_schedule_reconnect_skips_duplicate():
    """Test _schedule_reconnect skips if camera is already reconnecting."""
    detector = VideoMotionDetector()
    detector._reconnecting.add("camera1")

    detector._schedule_reconnect("camera1")

    assert detector._reconnect_tasks == []


@pytest.mark.asyncio
async def test_schedule_reconnect_creates_task():
    """Test _schedule_reconnect creates a reconnect task."""
    detector = VideoMotionDetector()
    detector._camera_configs["camera1"] = Mock(rtsp_url="rtsp://test")

    detector._schedule_reconnect("camera1")

    assert len(detector._reconnect_tasks) == 1
    # Clean up
    for task in detector._reconnect_tasks:
        task.cancel()
    await asyncio.gather(*detector._reconnect_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_camera_no_config():
    """Test _reconnect_camera exits cleanly when camera config is missing."""
    detector = VideoMotionDetector()

    await detector._reconnect_camera("camera1")

    assert "camera1" not in detector._reconnecting


@pytest.mark.asyncio
async def test_reconnect_camera_stops_on_shutdown():
    """Test _reconnect_camera exits when stop event is set."""
    detector = VideoMotionDetector()
    detector._camera_configs["camera1"] = Mock(rtsp_url="rtsp://test")
    detector._stop_event.set()

    await detector._reconnect_camera("camera1")

    assert "camera1" not in detector._reconnecting


@pytest.mark.asyncio
async def test_reconnect_camera_success_on_first_retry():
    """Test _reconnect_camera connects and spawns consume_frames task."""
    detector = VideoMotionDetector()
    detector._RECONNECT_INITIAL_DELAY = 0.01  # Speed up test

    mock_camera = Mock(rtsp_url="rtsp://test/stream")
    detector._camera_configs["camera1"] = mock_camera

    mock_source = AsyncMock()
    detector._video_sources["camera1"] = mock_source

    with (
        patch.object(detector, "_connect_camera", new_callable=AsyncMock) as mock_connect,
        patch.object(detector, "_consume_frames", new_callable=AsyncMock),
    ):
        await detector._reconnect_camera("camera1")

        mock_connect.assert_called_once_with("camera1", "rtsp://test/stream")

    assert "camera1" not in detector._reconnecting
    # A stream task should have been spawned
    assert len(detector._stream_tasks) == 1
    # Clean up
    for task in detector._stream_tasks:
        task.cancel()
    await asyncio.gather(*detector._stream_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_camera_retries_on_failure():
    """Test _reconnect_camera retries with increasing delay on failure."""
    detector = VideoMotionDetector()
    detector._RECONNECT_INITIAL_DELAY = 0.01
    detector._RECONNECT_MAX_DELAY = 0.1

    mock_camera = Mock(rtsp_url="rtsp://test/stream")
    detector._camera_configs["camera1"] = mock_camera

    call_count = 0

    async def fail_then_succeed(camera_id, rtsp_url):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Camera offline")
        detector._video_sources[camera_id] = AsyncMock()

    with (
        patch.object(detector, "_connect_camera", side_effect=fail_then_succeed),
        patch.object(detector, "_consume_frames", new_callable=AsyncMock),
    ):
        await detector._reconnect_camera("camera1")

    assert call_count == 3
    assert "camera1" not in detector._reconnecting
    # Clean up
    for task in detector._stream_tasks:
        task.cancel()
    await asyncio.gather(*detector._stream_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_reconnect_camera_guard_prevents_duplicate():
    """Test that _reconnect_camera exits if another reconnect is already active."""
    detector = VideoMotionDetector()
    detector._camera_configs["camera1"] = Mock(rtsp_url="rtsp://test")
    # Simulate another reconnect already running
    detector._reconnecting.add("camera1")

    await detector._reconnect_camera("camera1")

    # Should still be in _reconnecting (not removed, because we exited early)
    assert "camera1" in detector._reconnecting
