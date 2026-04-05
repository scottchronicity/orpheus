"""Tests for main agent logic."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus_agent_video_snapshotter.config import CameraSnapshotConfig
from orpheus_agent_video_snapshotter.main import VideoSnapshotter


@pytest.fixture
def mock_camera_config() -> CameraSnapshotConfig:
    """Create a mock camera configuration."""
    return CameraSnapshotConfig(
        name="test-camera",
        rtsp_url="rtsp://192.168.1.100/cam/realmonitor",
        interval="5s",
        enabled=True,
    )


@pytest.fixture
def mock_app_config(tmp_path: Path):
    """Mock application configuration."""
    config = MagicMock()
    config.cameras = [
        CameraSnapshotConfig(
            name="camera-1",
            rtsp_url="rtsp://192.168.1.100/cam/realmonitor",
            interval="5s",
            enabled=True,
        ),
        CameraSnapshotConfig(
            name="camera-2",
            rtsp_url="rtsp://192.168.1.101/cam/realmonitor",
            interval="10s",
            enabled=True,
        ),
    ]
    config.storage_base_path = tmp_path / "storage"
    config.log_level = "INFO"
    config.use_json_logging = False
    config.retention_days = 547
    return config


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_snapshotter_init(mock_load_config, mock_app_config):
    """Test VideoSnapshotter initialization."""
    mock_load_config.return_value = mock_app_config

    snapshotter = VideoSnapshotter()

    assert snapshotter is not None
    assert snapshotter._running is False
    assert len(snapshotter._last_snapshot_times) == 0


@patch("orpheus_agent_video_snapshotter.main.cv2.VideoCapture")
@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_capture_snapshot_success(mock_load_config, mock_video_capture, mock_app_config, tmp_path):
    """Test successful snapshot capture."""
    mock_load_config.return_value = mock_app_config

    # Mock VideoCapture
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap.read.return_value = (True, mock_frame)
    mock_video_capture.return_value = mock_cap

    # Mock cv2.imwrite and Path.stat
    with patch("orpheus_agent_video_snapshotter.main.cv2.imwrite") as mock_imwrite:
        mock_imwrite.return_value = True

        # Mock the stat call on the saved path
        mock_stat = MagicMock()
        mock_stat.st_size = 1024  # 1KB file size
        with patch.object(Path, "stat", return_value=mock_stat):
            snapshotter = VideoSnapshotter()
            camera = mock_app_config.cameras[0]

            snapshotter._capture_snapshot(camera)

            # Verify VideoCapture was opened with RTSP URL
            mock_video_capture.assert_called_once_with(camera.rtsp_url)

            # Verify frame was read
            mock_cap.read.assert_called_once()

            # Verify imwrite was called
            assert mock_imwrite.call_count == 1
            call_args = mock_imwrite.call_args[0]
            assert camera.name in call_args[0]  # Path contains camera name
            assert isinstance(call_args[1], np.ndarray)  # Frame data

            # Verify capture was released
            mock_cap.release.assert_called_once()


@patch("orpheus_agent_video_snapshotter.main.cv2.VideoCapture")
@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_capture_snapshot_stream_open_failure(
    mock_load_config, mock_video_capture, mock_app_config
):
    """Test handling of RTSP stream open failure."""
    mock_load_config.return_value = mock_app_config

    # Mock VideoCapture failing to open
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = False
    mock_video_capture.return_value = mock_cap

    snapshotter = VideoSnapshotter()
    camera = mock_app_config.cameras[0]

    # Should not raise exception
    snapshotter._capture_snapshot(camera)

    # Verify read was not called
    mock_cap.read.assert_not_called()


@patch("orpheus_agent_video_snapshotter.main.cv2.VideoCapture")
@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_capture_snapshot_read_failure(mock_load_config, mock_video_capture, mock_app_config):
    """Test handling of frame read failure."""
    mock_load_config.return_value = mock_app_config

    # Mock VideoCapture with failed read
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (False, None)
    mock_video_capture.return_value = mock_cap

    with patch("orpheus_agent_video_snapshotter.main.cv2.imwrite") as mock_imwrite:
        snapshotter = VideoSnapshotter()
        camera = mock_app_config.cameras[0]

        snapshotter._capture_snapshot(camera)

        # Verify imwrite was not called
        mock_imwrite.assert_not_called()

        # Verify capture was still released
        mock_cap.release.assert_called_once()


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_get_snapshot_path(mock_load_config, mock_app_config):
    """Test snapshot path generation."""
    mock_load_config.return_value = mock_app_config

    snapshotter = VideoSnapshotter()
    # Use proper ISO format with colons (which get sanitized to dashes in filename)
    timestamp = "2025-01-15T10:30:45.123Z"

    path = snapshotter._get_snapshot_path("test-camera", timestamp)

    # Verify path structure
    assert "video/snapshots" in str(path)
    assert "2025.01.15" in str(path)
    assert "test-camera" in str(path)
    assert path.suffix == ".jpg"


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_get_snapshot_path_with_invalid_timestamp(mock_load_config, mock_app_config):
    """Test snapshot path generation with invalid timestamp (should not crash)."""
    mock_load_config.return_value = mock_app_config

    snapshotter = VideoSnapshotter()

    # Should use current time as fallback
    path = snapshotter._get_snapshot_path("test-camera", "invalid-timestamp")

    assert path.suffix == ".jpg"
    assert "test-camera" in str(path)


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_parse_args_default(mock_load_config):
    """Test argument parsing with defaults."""
    from orpheus_agent_video_snapshotter.main import parse_args

    args = parse_args([])

    assert args.config is None
    assert args.log_level is None


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_parse_args_with_options(mock_load_config):
    """Test argument parsing with options."""
    from orpheus_agent_video_snapshotter.main import parse_args

    args = parse_args(["--config", "/tmp/config.yaml", "--log-level", "DEBUG"])

    assert args.config == Path("/tmp/config.yaml")
    assert args.log_level == "DEBUG"


@patch("orpheus_agent_video_snapshotter.main.cv2.VideoCapture")
@patch("orpheus_agent_video_snapshotter.main.load_app_config")
@patch("orpheus_agent_video_snapshotter.main.time.sleep")
def test_snapshot_loop_respects_intervals(
    mock_sleep, mock_load_config, mock_video_capture, mock_app_config
):
    """Test that snapshot loop respects configured intervals."""
    mock_load_config.return_value = mock_app_config

    # Mock VideoCapture
    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    mock_cap.read.return_value = (True, mock_frame)
    mock_video_capture.return_value = mock_cap

    with patch("orpheus_agent_video_snapshotter.main.cv2.imwrite") as mock_imwrite:
        mock_imwrite.return_value = True

        # Mock Path.stat for file size check
        mock_stat = MagicMock()
        mock_stat.st_size = 1024
        with patch.object(Path, "stat", return_value=mock_stat):
            snapshotter = VideoSnapshotter()
            snapshotter._running = True

            # Simulate a few loop iterations
            loop_count = 0

            def sleep_side_effect(duration):
                nonlocal loop_count
                loop_count += 1
                if loop_count >= 3:
                    snapshotter._running = False

            mock_sleep.side_effect = sleep_side_effect

            # Mock time.time() - first call returns 100 (large enough to trigger capture
            # since last_snapshot_times starts empty, so time_since_last >= interval)
            with patch("orpheus_agent_video_snapshotter.main.time.time") as mock_time:
                # Returns increasing times; first capture triggers immediately
                mock_time.side_effect = [100, 100, 101, 101, 102, 102, 103, 103]

                snapshotter._run_snapshot_loop()

            # Should have captured snapshots when intervals elapsed
            assert mock_imwrite.call_count > 0


@patch("orpheus_agent_video_snapshotter.main.load_app_config")
def test_signal_handler(mock_load_config, mock_app_config):
    """Test signal handler stops agent."""
    mock_load_config.return_value = mock_app_config

    snapshotter = VideoSnapshotter()
    snapshotter._running = True

    snapshotter._signal_handler(15, None)  # SIGTERM

    assert snapshotter._running is False


@patch("orpheus_agent_video_snapshotter.main.cleanup_old_files_by_age")
@patch("orpheus_agent_video_snapshotter.main.load_app_config")
@patch("orpheus_agent_video_snapshotter.main.time.sleep")
def test_cleanup_called_with_correct_args(
    mock_sleep, mock_load_config, mock_cleanup, mock_app_config
):
    """Test that cleanup utility is called with correct path and retention_days."""
    mock_load_config.return_value = mock_app_config

    snapshotter = VideoSnapshotter()
    snapshotter._running = True

    loop_count = 0

    def sleep_side_effect(duration):
        nonlocal loop_count
        loop_count += 1
        if loop_count >= 2:
            snapshotter._running = False

    mock_sleep.side_effect = sleep_side_effect

    # Start last_cleanup_time at 0 so cleanup triggers on first iteration
    with patch("orpheus_agent_video_snapshotter.main.time.time") as mock_time:
        mock_time.return_value = 99999.0  # Large value ensures cleanup interval elapsed

        snapshotter._run_snapshot_loop()

    mock_cleanup.assert_called_once_with(
        path=mock_app_config.storage_base_path / "video" / "snapshots",
        max_age_days=mock_app_config.retention_days,
        dry_run=False,
    )
