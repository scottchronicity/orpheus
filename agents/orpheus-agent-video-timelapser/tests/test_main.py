"""Tests for main timelapse generation logic."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from orpheus_agent_video_timelapser.main import (
    VideoTimelapser,
    _get_current_time_in_timezone,
    main,
    parse_args,
)


@pytest.fixture
def mock_config():
    """Mock AppConfig for testing."""
    with patch("orpheus_agent_video_timelapser.main.load_app_config") as mock_load:
        config = MagicMock()
        config.storage_base_path = Path("/tmp/test-storage")
        config.log_level = "INFO"
        config.use_json_logging = False

        # Create mock timelapse config
        tl_config = MagicMock()
        tl_config.label = "daily"  # Required for new filename format
        tl_config.start_time = "06:00"
        tl_config.lookback_window = "24h"
        tl_config.sampling_interval = "15m"
        tl_config.retention_days = 90
        tl_config.clip_duration = 2.0

        # Create mock camera with timelapse
        camera = MagicMock()
        camera.name = "test-camera"
        camera.enabled = True
        camera.timelapses = [tl_config]

        config.cameras = [camera]
        mock_load.return_value = config

        yield config


def test_timelapser_initialization(mock_config):
    """Test VideoTimelapser initialization."""
    timelapser = VideoTimelapser()

    assert timelapser is not None
    assert timelapser._running is False
    assert len(timelapser._completed_jobs) == 0


def test_get_timelapse_path(mock_config):
    """Test timelapse path generation with new format."""
    timelapser = VideoTimelapser()

    path = timelapser._get_timelapse_path("test-camera", "2025.01.15", "24h", "daily")

    # New format: camera.label.tier.lookback.timestamp.mp4
    assert path.parent == Path("/tmp/test-storage/video/timelapses/2025.01.15")
    assert "test-camera" in path.name
    assert "daily" in path.name
    assert "tl0" in path.name
    assert "24h" in path.name
    assert path.suffix == ".mp4"


def test_get_timelapse_path_hourly(mock_config):
    """Test timelapse path generation for hourly timelapses."""
    timelapser = VideoTimelapser()

    path = timelapser._get_timelapse_path("cam-1", "2025.01.15", "1h", "hourly")

    assert "hourly" in path.name
    assert "tl3" in path.name  # tl3 = 1h per TIER_LOOKBACK_MAP
    assert "1h" in path.name


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_success(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test successful timelapse generation."""
    # Setup mock storage
    mock_config.storage_base_path = tmp_path

    # Use a fixed "now" time for testing
    fixed_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    # Create date directory matching fixed_now
    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create mock snapshot files with correct format: YYYY.MM.DD.HH.MM.SS.camera_name.jpg
    # Create files within the 24h lookback window (from 12:00 back to previous day 12:00)
    for i in range(24):
        # Create hourly snapshots for the last 24 hours
        hour = i
        snapshot_file = snapshot_dir / f"2025.01.15.{hour:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    # Mock image reading
    mock_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_imread.return_value = mock_frame

    # Mock video writer
    mock_writer_instance = MagicMock()
    mock_writer_instance.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer_instance

    # Create timelapser and generate
    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # Verify video writer was called
    mock_video_writer.assert_called_once()
    # With bucket sampling, we should have written some frames
    assert mock_writer_instance.write.call_count > 0


@patch("orpheus_agent_video_timelapser.main.cv2.imread")
def test_generate_timelapse_insufficient_snapshots(mock_imread, mock_config, tmp_path):
    """Test that timelapse is skipped when insufficient snapshots exist."""
    # Setup mock storage
    mock_config.storage_base_path = tmp_path
    snapshot_dir = tmp_path / "video" / "snapshots" / "2025.01.15"
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create only 5 snapshot files (< 50% of 24 required)
    for i in range(5):
        snapshot_file = snapshot_dir / f"2025-01-15T{i:02d}-00-00.000Z.test-camera.jpg"
        snapshot_file.touch()

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    # Should return early without error
    timelapser._generate_timelapse(camera, tl_config, "2025.01.15")

    # imread should not be called since we return early
    mock_imread.assert_not_called()


@patch("orpheus_agent_video_timelapser.main.cv2.imread")
def test_generate_timelapse_missing_directory(mock_imread, mock_config, tmp_path):
    """Test that timelapse is skipped when snapshot directory doesn't exist."""
    # Setup mock storage without creating snapshot directory
    mock_config.storage_base_path = tmp_path

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    # Should return early without error
    timelapser._generate_timelapse(camera, tl_config, "2025.01.15")

    # imread should not be called
    mock_imread.assert_not_called()


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_uses_last_n_snapshots(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test that bucket sampling selects snapshots within the lookback window."""
    # Setup mock storage
    mock_config.storage_base_path = tmp_path

    # Use a fixed "now" time for testing
    fixed_now = datetime(2025, 1, 15, 23, 59, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create 100 snapshot files spread across the day (more granular than sampling interval)
    # Each file is ~15 minutes apart
    for i in range(100):
        hour = (i * 15) // 60
        minute = (i * 15) % 60
        if hour < 24:  # Only create files for valid hours
            snapshot_file = snapshot_dir / f"2025.01.15.{hour:02d}.{minute:02d}.00.test-camera.jpg"
            snapshot_file.touch()

    # Mock image reading
    mock_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_imread.return_value = mock_frame

    # Mock video writer
    mock_writer_instance = MagicMock()
    mock_writer_instance.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer_instance

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # Verify frames were written via bucket sampling
    # With 15m sampling interval over 24h, we expect ~96 buckets, but actual count
    # depends on which files fall into the lookback window
    assert mock_writer_instance.write.call_count > 0
    # Should be significantly less than 100 raw files due to bucket sampling
    assert mock_writer_instance.write.call_count <= 96


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_calculates_frame_rate(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test that frame rate is correctly calculated from clip_duration."""
    # Setup mock storage
    mock_config.storage_base_path = tmp_path

    # Use a fixed "now" time for testing
    fixed_now = datetime(2025, 1, 15, 23, 59, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create snapshot files with correct format within lookback window
    for i in range(24):
        hour = i
        snapshot_file = snapshot_dir / f"2025.01.15.{hour:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    # Mock image reading
    mock_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_imread.return_value = mock_frame

    # Mock video writer
    mock_writer_instance = MagicMock()
    mock_writer_instance.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer_instance

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]
    tl_config.clip_duration = 2.0  # Each image shown for 2 seconds

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # Frame rate should be 1 / 2.0 = 0.5 fps
    # Verify VideoWriter was called with correct frame rate
    assert mock_video_writer.called
    call_args = mock_video_writer.call_args
    if call_args is not None:
        frame_rate = call_args[0][2]  # Third argument is frame rate
        assert frame_rate == 0.5


def test_signal_handler(mock_config):
    """Test that signal handler stops the agent."""
    timelapser = VideoTimelapser()
    timelapser._running = True

    timelapser._signal_handler(15, None)

    assert timelapser._running is False


def test_parse_args():
    """Test argument parsing."""

    # Test default args
    args = parse_args([])
    assert args.config is None
    assert args.log_level is None

    # Test with custom config
    args = parse_args(["--config", "/tmp/test.yaml"])
    assert args.config == Path("/tmp/test.yaml")

    # Test with log level
    args = parse_args(["--log-level", "DEBUG"])
    assert args.log_level == "DEBUG"


# =============================================================================
# Tests for _get_current_time_in_timezone
# =============================================================================


def test_get_current_time_in_timezone_utc():
    """Test getting current time in UTC timezone."""
    result = _get_current_time_in_timezone("UTC")
    assert result.tzinfo == timezone.utc
    assert isinstance(result, datetime)


def test_get_current_time_in_timezone_local():
    """Test getting current time in local timezone."""
    result = _get_current_time_in_timezone("local")
    assert result.tzinfo is not None
    assert isinstance(result, datetime)


def test_get_current_time_in_timezone_iana_name():
    """Test getting current time with IANA timezone name."""
    result = _get_current_time_in_timezone("America/New_York")
    assert result.tzinfo is not None
    assert isinstance(result, datetime)


def test_get_current_time_in_timezone_invalid_falls_back_to_utc():
    """Test that invalid timezone falls back to UTC."""
    result = _get_current_time_in_timezone("Invalid/Timezone")
    # Should fall back to UTC without raising
    assert isinstance(result, datetime)
    assert result.tzinfo == timezone.utc


# =============================================================================
# Tests for _parse_duration
# =============================================================================


def test_parse_duration_seconds(mock_config):
    """Test parsing duration in seconds."""
    timelapser = VideoTimelapser()
    assert timelapser._parse_duration("30s") == 30
    assert timelapser._parse_duration("120s") == 120


def test_parse_duration_minutes(mock_config):
    """Test parsing duration in minutes."""
    timelapser = VideoTimelapser()
    assert timelapser._parse_duration("15m") == 900
    assert timelapser._parse_duration("60m") == 3600


def test_parse_duration_hours(mock_config):
    """Test parsing duration in hours."""
    timelapser = VideoTimelapser()
    assert timelapser._parse_duration("24h") == 86400
    assert timelapser._parse_duration("48h") == 172800


def test_parse_duration_days(mock_config):
    """Test parsing duration in days."""
    timelapser = VideoTimelapser()
    assert timelapser._parse_duration("7d") == 604800
    assert timelapser._parse_duration("1d") == 86400


def test_parse_duration_empty_defaults_to_24h(mock_config):
    """Test that empty duration defaults to 24 hours."""
    timelapser = VideoTimelapser()
    assert timelapser._parse_duration("") == 86400


def test_parse_duration_invalid_unit(mock_config):
    """Test that invalid unit falls back to treating as seconds."""
    timelapser = VideoTimelapser()
    # Invalid unit 'x' should log warning and treat value as seconds
    result = timelapser._parse_duration("30x")
    assert result == 30


# =============================================================================
# Tests for _bucket_sample_snapshots
# =============================================================================


def test_bucket_sample_snapshots_basic(mock_config, tmp_path):
    """Test basic bucket sampling."""
    timelapser = VideoTimelapser()

    # Create mock snapshot files
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    snapshot_files = []
    for hour in range(24):
        f = snapshot_dir / f"2025.01.15.{hour:02d}.00.00.test-camera.jpg"
        f.touch()
        snapshot_files.append(f)
    snapshot_files.sort()

    lookback_start = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2025, 1, 15, 23, 59, 59, tzinfo=timezone.utc)
    sampling_seconds = 3600  # 1 hour buckets

    result = timelapser._bucket_sample_snapshots(
        snapshot_files, lookback_start, current_time, sampling_seconds
    )

    # Should have roughly 24 buckets, but actual count depends on bucket boundaries
    assert len(result) > 0
    assert len(result) <= 24


def test_bucket_sample_snapshots_empty_list(mock_config):
    """Test bucket sampling with empty snapshot list."""
    timelapser = VideoTimelapser()

    lookback_start = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    sampling_seconds = 3600

    result = timelapser._bucket_sample_snapshots([], lookback_start, current_time, sampling_seconds)

    assert result == []


def test_bucket_sample_snapshots_files_outside_window(mock_config, tmp_path):
    """Test that files outside the time window are excluded."""
    timelapser = VideoTimelapser()

    # Create snapshot file from a different day (outside lookback window)
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    old_file = snapshot_dir / "2025.01.10.12.00.00.test-camera.jpg"
    old_file.touch()

    # Lookback window is Jan 14-15 (old file is Jan 10)
    lookback_start = datetime(2025, 1, 14, 0, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    sampling_seconds = 3600

    result = timelapser._bucket_sample_snapshots(
        [old_file], lookback_start, current_time, sampling_seconds
    )

    assert result == []


def test_bucket_sample_snapshots_invalid_filename(mock_config, tmp_path):
    """Test that files with invalid filename format are skipped."""
    timelapser = VideoTimelapser()

    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()

    # Create file with invalid format
    invalid_file = snapshot_dir / "invalid-format.test-camera.jpg"
    invalid_file.touch()

    # Create valid file
    valid_file = snapshot_dir / "2025.01.15.12.00.00.test-camera.jpg"
    valid_file.touch()

    lookback_start = datetime(2025, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
    current_time = datetime(2025, 1, 15, 23, 59, 59, tzinfo=timezone.utc)
    sampling_seconds = 3600

    result = timelapser._bucket_sample_snapshots(
        [invalid_file, valid_file], lookback_start, current_time, sampling_seconds
    )

    # Should include only the valid file
    assert len(result) == 1
    assert valid_file in result


# =============================================================================
# Tests for start() method
# =============================================================================


@patch("orpheus_agent_video_timelapser.main.setup_logging")
@patch("orpheus_agent_video_timelapser.main.signal.signal")
def test_start_no_cameras(mock_signal, mock_setup_logging, mock_config):
    """Test start() exits early when no cameras configured."""
    mock_config.cameras = []

    timelapser = VideoTimelapser()
    timelapser.start()

    # Should have returned without starting the loop
    assert timelapser._running is False


@patch("orpheus_agent_video_timelapser.main.setup_logging")
@patch("orpheus_agent_video_timelapser.main.signal.signal")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
def test_start_with_cameras(mock_sleep, mock_signal, mock_setup_logging, mock_config):
    """Test start() with configured cameras."""

    # Make the loop exit after one iteration
    def stop_after_one_iteration(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one_iteration

    timelapser = VideoTimelapser()
    timelapser.start()

    # Signal handlers should be registered
    assert mock_signal.call_count >= 2


@patch("orpheus_agent_video_timelapser.main.setup_logging")
@patch("orpheus_agent_video_timelapser.main.signal.signal")
def test_start_keyboard_interrupt(mock_signal, mock_setup_logging, mock_config):
    """Test start() handles KeyboardInterrupt."""
    timelapser = VideoTimelapser()

    with patch.object(timelapser, "_run_timelapse_loop", side_effect=KeyboardInterrupt):
        timelapser.start()

    assert timelapser._running is False


@patch("orpheus_agent_video_timelapser.main.setup_logging")
@patch("orpheus_agent_video_timelapser.main.signal.signal")
def test_start_exception(mock_signal, mock_setup_logging, mock_config):
    """Test start() re-raises unexpected exceptions."""
    timelapser = VideoTimelapser()

    with patch.object(timelapser, "_run_timelapse_loop", side_effect=RuntimeError("Test error")):
        with pytest.raises(RuntimeError):
            timelapser.start()


# =============================================================================
# Tests for _run_timelapse_loop
# =============================================================================


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_triggers_job(mock_get_time, mock_sleep, mock_datetime, mock_config):
    """Test that timelapse loop triggers job when time matches."""
    # Setup mock time that should trigger the 06:00 job (within first 90 seconds)
    mock_time = datetime(2025, 1, 15, 6, 0, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    # Mock datetime.now for cleanup code
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    iteration_count = [0]

    def stop_after_iterations(*args):
        iteration_count[0] += 1
        if iteration_count[0] > 1:
            timelapser._running = False

    mock_sleep.side_effect = stop_after_iterations

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should have tried to generate timelapse
        assert mock_generate.called


@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_skips_completed_jobs(mock_get_time, mock_sleep, mock_config):
    """Test that completed jobs are not re-run."""
    # Time at 06:30 - should be in interval 0 for hourly timelapse starting at 06:00
    mock_time = datetime(2025, 1, 15, 6, 30, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True
    # Mark job as already completed for interval 0 of timelapse index 0
    timelapser._completed_jobs.add(("test-camera", "2025.01.15", 0, "06:00_0"))

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should NOT have generated timelapse (already ran for this interval)
        assert not mock_generate.called


@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_handles_generate_exception(mock_get_time, mock_sleep, mock_config):
    """Test that exceptions in _generate_timelapse are caught."""
    mock_time = datetime(2025, 1, 15, 6, 30, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    iteration_count = [0]

    def stop_after_iterations(*args):
        iteration_count[0] += 1
        if iteration_count[0] > 1:
            timelapser._running = False

    mock_sleep.side_effect = stop_after_iterations

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse", side_effect=Exception("Test error")):
        # Should not raise - exception is caught
        timelapser._run_timelapse_loop()


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_prunes_old_jobs(mock_get_time, mock_sleep, mock_datetime, mock_config):
    """Test that old completed jobs are pruned."""
    # Current time for the timelapse check (before 06:00 so no job triggers)
    mock_time = datetime(2025, 1, 15, 5, 30, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    # Also mock datetime.now for the pruning logic
    mock_datetime.now.return_value = datetime(2025, 1, 15, 5, 30, 0, tzinfo=timezone.utc)
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True
    # Add old job from 5 days ago (should be pruned)
    timelapser._completed_jobs.add(("test-camera", "2025.01.10", 0, "06:00_0"))
    # Add recent job (should be kept - within 2 days of Jan 15)
    timelapser._completed_jobs.add(("test-camera", "2025.01.14", 0, "06:00_0"))

    with patch.object(timelapser, "_generate_timelapse"):
        timelapser._run_timelapse_loop()

    # Old job should be pruned, recent job kept
    assert ("test-camera", "2025.01.10", 0, "06:00_0") not in timelapser._completed_jobs
    assert ("test-camera", "2025.01.14", 0, "06:00_0") in timelapser._completed_jobs


@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_skips_disabled_cameras(mock_get_time, mock_sleep, mock_config):
    """Test that disabled cameras are skipped."""
    mock_time = datetime(2025, 1, 15, 6, 30, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    # Disable the camera
    mock_config.cameras[0].enabled = False

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should NOT have generated timelapse for disabled camera
        assert not mock_generate.called


# =============================================================================
# Tests for interval-based scheduling (lookback_window as repeat interval)
# =============================================================================


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_hourly_interval(mock_get_time, mock_sleep, mock_datetime, mock_config):
    """Test that hourly timelapse runs each hour based on lookback_window."""
    # Configure hourly timelapse
    mock_config.cameras[0].timelapses[0].start_time = "00:00"
    mock_config.cameras[0].timelapses[0].lookback_window = "1h"

    # At 02:00:30 - should be in interval 2 (0, 1, 2)
    mock_time = datetime(2025, 1, 15, 2, 0, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    # Mock datetime.now for cleanup code to prevent pruning test data
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should trigger for interval 2
        assert mock_generate.called
        # Job should be recorded with interval 2
        assert ("test-camera", "2025.01.15", 2, "00:00_0") in timelapser._completed_jobs


@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_hourly_skips_mid_interval(mock_get_time, mock_sleep, mock_config):
    """Test that timelapse doesn't trigger mid-interval (>90 seconds in)."""
    # Configure hourly timelapse
    mock_config.cameras[0].timelapses[0].start_time = "00:00"
    mock_config.cameras[0].timelapses[0].lookback_window = "1h"

    # At 02:05:00 - 5 minutes into interval 2 (>90 seconds)
    mock_time = datetime(2025, 1, 15, 2, 5, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should NOT trigger (too far into interval)
        assert not mock_generate.called


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_daily_runs_once(mock_get_time, mock_sleep, mock_datetime, mock_config):
    """Test that 24h lookback runs once per day."""
    # Configure daily timelapse
    mock_config.cameras[0].timelapses[0].start_time = "06:00"
    mock_config.cameras[0].timelapses[0].lookback_window = "24h"

    # At 06:00:30 - should be in interval 0 (only interval for 24h)
    mock_time = datetime(2025, 1, 15, 6, 0, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    # Mock datetime.now for cleanup code to prevent pruning test data
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should trigger for interval 0
        assert mock_generate.called
        # Job should be recorded with interval 0
        assert ("test-camera", "2025.01.15", 0, "06:00_0") in timelapser._completed_jobs


@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_before_start_time(mock_get_time, mock_sleep, mock_config):
    """Test that timelapse doesn't run before start_time."""
    # Configure timelapse starting at 06:00
    mock_config.cameras[0].timelapses[0].start_time = "06:00"
    mock_config.cameras[0].timelapses[0].lookback_window = "1h"

    # At 05:30 - before start_time
    mock_time = datetime(2025, 1, 15, 5, 30, 0, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should NOT trigger (before start_time)
        assert not mock_generate.called


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_run_timelapse_loop_30min_interval(mock_get_time, mock_sleep, mock_datetime, mock_config):
    """Test that 30m lookback runs every 30 minutes."""
    # Configure 30-minute timelapse
    mock_config.cameras[0].timelapses[0].start_time = "00:00"
    mock_config.cameras[0].timelapses[0].lookback_window = "30m"

    # At 01:30:30 - should be in interval 3 (0:00, 0:30, 1:00, 1:30)
    mock_time = datetime(2025, 1, 15, 1, 30, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    # Mock datetime.now for cleanup code to prevent pruning test data
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # Should trigger for interval 3
        assert mock_generate.called
        # Job should be recorded with interval 3
        assert ("test-camera", "2025.01.15", 3, "00:00_0") in timelapser._completed_jobs


# =============================================================================
# Tests for main() function
# =============================================================================


def test_main_success(mock_config):
    """Test main() returns 0 on success."""
    with patch.object(VideoTimelapser, "start"):
        result = main([])
        assert result == 0


def test_main_keyboard_interrupt(mock_config):
    """Test main() returns 130 on KeyboardInterrupt."""
    with patch.object(VideoTimelapser, "start", side_effect=KeyboardInterrupt):
        result = main([])
        assert result == 130


def test_main_exception(mock_config):
    """Test main() returns 1 on unhandled exception."""
    with patch.object(VideoTimelapser, "start", side_effect=RuntimeError("Test")):
        result = main([])
        assert result == 1


def test_main_with_log_level(mock_config):
    """Test main() with log level override."""
    with patch.object(VideoTimelapser, "start") as mock_start:
        result = main(["--log-level", "debug"])
        assert result == 0
        mock_start.assert_called_once()


# =============================================================================
# Tests for video writer error handling
# =============================================================================


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_no_valid_frames(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test timelapse skipped when no valid frames after loading."""
    mock_config.storage_base_path = tmp_path

    fixed_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create snapshot files
    for i in range(24):
        snapshot_file = snapshot_dir / f"2025.01.15.{i:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    # Return None for all imread calls (simulating unreadable images)
    mock_imread.return_value = None

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # Video writer should not be called
    mock_video_writer.assert_not_called()


@patch("orpheus_agent_video_timelapser.main.VideoTimelapser._transcode_to_h264")
@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_transcodes_to_h264(
    mock_video_writer, mock_imread, mock_datetime, mock_transcode, mock_config, tmp_path
):
    """Test that mp4v video is transcoded to H.264 after generation."""
    mock_config.storage_base_path = tmp_path

    fixed_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for i in range(24):
        snapshot_file = snapshot_dir / f"2025.01.15.{i:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    mock_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_imread.return_value = mock_frame

    # Create output directory for timelapse
    timelapse_dir = tmp_path / "video" / "timelapses" / date_str
    timelapse_dir.mkdir(parents=True, exist_ok=True)

    # Track the output path that VideoWriter receives
    created_file_path = [None]

    def video_writer_side_effect(path, *args):
        created_file_path[0] = Path(path)
        # Create the file so existence check passes
        Path(path).touch()
        mock_writer = MagicMock()
        mock_writer.isOpened.return_value = True
        return mock_writer

    mock_video_writer.side_effect = video_writer_side_effect

    # Transcode succeeds
    mock_transcode.return_value = True

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # VideoWriter should have been called once with mp4v
    assert mock_video_writer.call_count == 1

    # Transcode should have been called with the output path
    mock_transcode.assert_called_once()


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_writer_fails(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test error handling when video writer fails to open."""
    mock_config.storage_base_path = tmp_path

    fixed_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for i in range(24):
        snapshot_file = snapshot_dir / f"2025.01.15.{i:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    mock_frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    mock_imread.return_value = mock_frame

    # VideoWriter fails to open
    mock_writer = MagicMock()
    mock_writer.isOpened.return_value = False
    mock_video_writer.return_value = mock_writer

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    # Should not raise, just return early
    timelapser._generate_timelapse(camera, tl_config, date_str)

    # Should have tried once with mp4v codec
    assert mock_video_writer.call_count == 1


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_resizes_mismatched_frames(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test that frames with different dimensions are resized."""
    mock_config.storage_base_path = tmp_path

    fixed_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    mock_datetime.now.return_value = fixed_now
    mock_datetime.strptime = datetime.strptime

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    for i in range(10):
        snapshot_file = snapshot_dir / f"2025.01.15.{i:02d}.00.00.test-camera.jpg"
        snapshot_file.touch()

    # Return different sized frames
    frame1 = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame2 = np.zeros((720, 1280, 3), dtype=np.uint8)

    # First frame is normal, subsequent frames are different size
    mock_imread.side_effect = [frame1] + [frame2] * 9

    mock_writer = MagicMock()
    mock_writer.isOpened.return_value = True
    mock_video_writer.return_value = mock_writer

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]
    tl_config = camera.timelapses[0]

    with patch("orpheus_agent_video_timelapser.main.cv2.resize") as mock_resize:
        mock_resize.return_value = frame1  # Resized to match first frame
        timelapser._generate_timelapse(camera, tl_config, date_str)

        # resize should have been called for mismatched frames
        assert mock_resize.call_count > 0


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.cv2.imread")
@patch("orpheus_agent_video_timelapser.main.cv2.VideoWriter")
def test_generate_timelapse_no_snapshots_found(
    mock_video_writer, mock_imread, mock_datetime, mock_config, tmp_path
):
    """Test timelapse skipped when no snapshots found for camera."""
    mock_config.storage_base_path = tmp_path

    date_str = "2025.01.15"
    snapshot_dir = tmp_path / "video" / "snapshots" / date_str
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # Create snapshots for a DIFFERENT camera
    for i in range(10):
        snapshot_file = snapshot_dir / f"2025.01.15.{i:02d}.00.00.other-camera.jpg"
        snapshot_file.touch()

    timelapser = VideoTimelapser()
    camera = mock_config.cameras[0]  # test-camera
    tl_config = camera.timelapses[0]

    timelapser._generate_timelapse(camera, tl_config, date_str)

    # No images should be read
    mock_imread.assert_not_called()
    mock_video_writer.assert_not_called()


# =============================================================================
# Tests for race condition fix (collect-then-execute pattern)
# =============================================================================


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_race_condition_all_cameras_collected_with_single_time_snapshot(
    mock_get_time, mock_sleep, mock_datetime, mock_config
):
    """Regression test: all cameras must be collected with a SINGLE time snapshot.

    Before the fix, _get_current_time_in_timezone was called once per camera
    inside the loop. Processing camera-1's timelapse could take 20+ seconds,
    pushing camera-4 past the 90-second eligibility window. This caused
    later cameras to systematically generate fewer timelapses.

    Evidence from production:
        eye-1: 2149 files, eye-2: 2086, eye-3: 1964, eye-4: 1847

    The fix snapshots time ONCE per timezone before iterating cameras.
    This test verifies that _get_current_time_in_timezone is called at
    most once per timezone per tick, not once per camera.
    """
    # Setup 4 cameras, all using same timezone
    cameras = []
    for i in range(1, 5):
        tl = MagicMock()
        tl.label = "hourly"
        tl.start_time = "00:00"
        tl.lookback_window = "1h"
        tl.sampling_interval = "5m"
        tl.retention_days = 30
        tl.clip_duration = 1.25
        tl.timezone = "America/Detroit"
        cam = MagicMock()
        cam.name = f"eye-{i}"
        cam.enabled = True
        cam.timelapses = [tl]
        cameras.append(cam)
    mock_config.cameras = cameras

    # Time at 02:00:30 — within the 90s window for interval 2
    mock_time = datetime(2025, 1, 15, 2, 0, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse") as mock_generate:
        timelapser._run_timelapse_loop()

        # All 4 cameras should have been collected and executed
        assert mock_generate.call_count == 4, (
            f"Expected all 4 cameras to generate, got {mock_generate.call_count}. "
            "Race condition: later cameras missed the window."
        )

    # _get_current_time_in_timezone should be called ONCE for the shared timezone,
    # not 4 times (once per camera). The tz_times cache ensures this.
    assert mock_get_time.call_count == 1, (
        f"Expected 1 timezone lookup (cached), got {mock_get_time.call_count}. "
        "Time should be snapshotted once per timezone, not per camera."
    )


@patch("orpheus_agent_video_timelapser.main.datetime")
@patch("orpheus_agent_video_timelapser.main.time.sleep")
@patch("orpheus_agent_video_timelapser.main._get_current_time_in_timezone")
def test_race_condition_multiple_timezones_each_snapshotted_once(
    mock_get_time, mock_sleep, mock_datetime, mock_config
):
    """Verify that with multiple timezones, each is snapshotted exactly once."""
    cameras = []
    # Camera 1 & 2 in Detroit, Camera 3 & 4 in UTC
    for i, tz in enumerate(["America/Detroit", "America/Detroit", "UTC", "UTC"], start=1):
        tl = MagicMock()
        tl.label = "hourly"
        tl.start_time = "00:00"
        tl.lookback_window = "1h"
        tl.sampling_interval = "5m"
        tl.retention_days = 30
        tl.clip_duration = 1.25
        tl.timezone = tz
        cam = MagicMock()
        cam.name = f"eye-{i}"
        cam.enabled = True
        cam.timelapses = [tl]
        cameras.append(cam)
    mock_config.cameras = cameras

    mock_time = datetime(2025, 1, 15, 2, 0, 30, tzinfo=timezone.utc)
    mock_get_time.return_value = mock_time
    mock_datetime.now.return_value = mock_time
    mock_datetime.strptime = datetime.strptime

    def stop_after_one(*args):
        timelapser._running = False

    mock_sleep.side_effect = stop_after_one

    timelapser = VideoTimelapser()
    timelapser._running = True

    with patch.object(timelapser, "_generate_timelapse"):
        timelapser._run_timelapse_loop()

    # Should call once for "America/Detroit" and once for "UTC" = 2 total
    assert mock_get_time.call_count == 2, (
        f"Expected 2 timezone lookups (one per unique tz), got {mock_get_time.call_count}"
    )
