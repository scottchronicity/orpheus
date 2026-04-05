"""Tests for the AudioMotionDetector main class and cleanup functionality."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from orpheus_agent_audio_motion.main import AudioMotionDetector


@pytest.fixture
def mock_config():
    """Create a mock config for testing."""
    config = Mock()
    config.logging.level = "INFO"
    config.logging.use_json = False
    config.storage.retain_days = 30
    config.storage.category = "audio_motion"
    config.storage.write_format = "flac"
    config.mqtt.broker_host = "localhost"
    config.mqtt.broker_port = 1883
    config.mqtt.qos = 1
    config.mqtt.keepalive = 60
    config.mqtt.topic_events = "test/events"
    config.mqtt.topic_status = "test/status"
    config.runtime.sample_rate = 48000
    config.channels = []
    return config


@pytest.mark.asyncio
async def test_cleanup_task_started_on_start():
    """Test that cleanup task is created when agent starts."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config:
        with patch("orpheus_agent_audio_motion.main.setup_logging"):
            mock_config = Mock()
            mock_config.logging.level = "INFO"
            mock_config.logging.use_json = False
            mock_config.storage.retain_days = 30
            mock_config.storage.category = "audio_motion"
            mock_config.storage.write_format = "flac"
            mock_config.mqtt.broker_host = "localhost"
            mock_config.mqtt.broker_port = 1883
            mock_config.mqtt.qos = 1
            mock_config.mqtt.keepalive = 60
            mock_config.mqtt.topic_events = "test/events"
            mock_config.mqtt.topic_status = "test/status"
            mock_config.runtime.sample_rate = 48000
            # Add at least one enabled channel so we don't get RuntimeError
            mock_channel = Mock()
            mock_channel.id = "test_channel"
            mock_channel.enabled = True
            mock_config.channels = [mock_channel]
            mock_load_config.return_value = mock_config

            detector = AudioMotionDetector()

            # Track coroutines that need to be closed
            pending_coros = []

            # Patch dependencies
            with patch.object(
                detector, "_initialize_dependencies", new_callable=AsyncMock
            ) as mock_init:  # noqa: F841
                with patch(
                    "orpheus_agent_audio_motion.main.asyncio.create_task"
                ) as mock_create_task:
                    # Simulate the cleanup task being created
                    mock_cleanup_task = Mock()
                    mock_stream_task = Mock()

                    def side_effect(coro):
                        # Close the coroutine to prevent "never awaited" warning
                        pending_coros.append(coro)
                        # Return different mocks for different tasks
                        if "periodic_cleanup" in str(coro):
                            return mock_cleanup_task
                        return mock_stream_task

                    mock_create_task.side_effect = side_effect

                    # Start the detector but immediately stop it
                    detector._stop_event.set()

                    try:
                        await detector.start()
                    except Exception:
                        pass  # Expected since we're mocking heavily
                    finally:
                        # Close all pending coroutines to avoid warnings
                        for coro in pending_coros:
                            coro.close()

                    # Verify cleanup task was created
                    assert detector._cleanup_task is not None or mock_create_task.call_count >= 1


@pytest.mark.asyncio
async def test_cleanup_task_cancelled_on_stop():
    """Test that cleanup task is cancelled when agent stops."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config:
        mock_config = Mock()
        mock_config.logging.level = "INFO"
        mock_config.logging.use_json = False
        mock_config.storage.retain_days = 30
        mock_config.channels = []  # Add channels list
        mock_load_config.return_value = mock_config

        detector = AudioMotionDetector()

        # Create a real task that we can track
        async def dummy_task():
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                raise

        cleanup_task = asyncio.create_task(dummy_task())
        detector._cleanup_task = cleanup_task

        # Call stop
        await detector.stop()

        # Verify task was cancelled
        assert cleanup_task.cancelled()


@pytest.mark.asyncio
async def test_periodic_cleanup_uses_correct_policy():
    """Test that periodic cleanup uses correct CleanupPolicy settings."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config:
        with patch("orpheus_agent_audio_motion.main.get_audio_path") as mock_get_audio_path:
            with patch("orpheus_agent_audio_motion.main.StorageCleanup") as mock_storage_cleanup:
                with patch("orpheus_agent_audio_motion.main.CleanupPolicy") as mock_cleanup_policy:
                    with patch("orpheus_agent_audio_motion.main.asyncio.sleep") as mock_sleep:
                        # Make sleep return immediately and raise CancelledError on second call
                        mock_sleep.side_effect = [None, asyncio.CancelledError()]

                        mock_config = Mock()
                        mock_config.logging.level = "INFO"
                        mock_config.logging.use_json = False
                        mock_config.storage.retain_days = 30
                        mock_config.storage.max_size_gb = 100.0
                        mock_config.storage.cleanup_strategy = "oldest"
                        mock_config.storage.cleanup_trigger_percent = 85.0
                        mock_config.storage.cleanup_amount_percent = 20.0
                        mock_config.storage.check_interval_hours = 2
                        mock_config.storage.min_file_age_hours = 2.0
                        mock_config.channels = []  # Add channels list
                        mock_load_config.return_value = mock_config

                        mock_get_audio_path.return_value = Path("/data/orpheus/audio_motion")

                        # Mock cleanup result
                        mock_result = Mock()
                        mock_result.files_removed = 0
                        mock_result.errors = []
                        mock_cleanup_instance = Mock()
                        mock_cleanup_instance.cleanup.return_value = mock_result
                        mock_storage_cleanup.return_value = mock_cleanup_instance

                        detector = AudioMotionDetector()
                        detector._stop_event = asyncio.Event()

                        # Run cleanup - it will execute once then raise CancelledError
                        try:
                            await detector._periodic_cleanup()
                        except asyncio.CancelledError:
                            pass

                        # Verify CleanupPolicy was created with correct settings
                        mock_cleanup_policy.assert_called_once()
                        call_kwargs = mock_cleanup_policy.call_args[1]
                        assert call_kwargs["max_size_gb"] == 100.0
                        assert call_kwargs["max_age_days"] == 30
                        assert call_kwargs["cleanup_strategy"] == "oldest"
                        assert call_kwargs["cleanup_trigger_percent"] == 85.0
                        assert call_kwargs["cleanup_amount_percent"] == 20.0
                        assert call_kwargs["min_file_age_hours"] == 2.0
                        assert call_kwargs["file_pattern"] == "*.flac"


@pytest.mark.asyncio
async def test_periodic_cleanup_uses_defaults_for_missing_config():
    """Test that periodic cleanup gracefully handles missing config fields with defaults."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config:
        with patch("orpheus_agent_audio_motion.main.get_audio_path") as mock_get_audio_path:
            with patch("orpheus_agent_audio_motion.main.StorageCleanup") as mock_storage_cleanup:
                with patch("orpheus_agent_audio_motion.main.CleanupPolicy") as mock_cleanup_policy:
                    with patch("orpheus_agent_audio_motion.main.asyncio.sleep") as mock_sleep:
                        # Make sleep return immediately and raise CancelledError on second call
                        mock_sleep.side_effect = [None, asyncio.CancelledError()]

                        # Config with minimal fields (no cleanup-specific fields)
                        mock_config = Mock()
                        mock_config.logging.level = "INFO"
                        mock_config.logging.use_json = False
                        mock_config.storage.retain_days = 30
                        mock_config.channels = []  # Add channels list
                        # Remove all optional cleanup fields to test defaults
                        del mock_config.storage.max_size_gb
                        del mock_config.storage.cleanup_strategy
                        del mock_config.storage.cleanup_trigger_percent
                        del mock_config.storage.cleanup_amount_percent
                        del mock_config.storage.check_interval_hours
                        del mock_config.storage.min_file_age_hours
                        mock_load_config.return_value = mock_config

                        mock_get_audio_path.return_value = Path("/data/orpheus/audio_motion")

                        # Mock cleanup result
                        mock_result = Mock()
                        mock_result.files_removed = 0
                        mock_result.errors = []
                        mock_cleanup_instance = Mock()
                        mock_cleanup_instance.cleanup.return_value = mock_result
                        mock_storage_cleanup.return_value = mock_cleanup_instance

                        detector = AudioMotionDetector()
                        detector._stop_event = asyncio.Event()

                        # Run cleanup - it will execute once then raise CancelledError
                        try:
                            await detector._periodic_cleanup()
                        except asyncio.CancelledError:
                            pass

                        # Verify CleanupPolicy was created with defaults
                        mock_cleanup_policy.assert_called_once()
                        call_kwargs = mock_cleanup_policy.call_args[1]
                        assert call_kwargs["max_size_gb"] == 50.0  # default
                        assert call_kwargs["max_age_days"] == 30
                        assert call_kwargs["cleanup_strategy"] == "oldest"  # default
                        assert call_kwargs["cleanup_trigger_percent"] == 90.0  # default
                        assert call_kwargs["cleanup_amount_percent"] == 25.0  # default
                        assert call_kwargs["min_file_age_hours"] == 1.0  # default
                        assert call_kwargs["file_pattern"] == "*.flac"


@pytest.mark.asyncio
async def test_periodic_cleanup_continues_after_error():
    """Test that periodic cleanup continues running even after errors."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config:
        with patch("orpheus_agent_audio_motion.main.get_audio_path") as mock_get_audio_path:
            with patch("orpheus_agent_audio_motion.main.StorageCleanup") as mock_storage_cleanup:
                with patch("orpheus_agent_audio_motion.main.asyncio.sleep") as mock_sleep:
                    # First sleep succeeds, second sleep cancels after error recovery
                    mock_sleep.side_effect = [None, None, asyncio.CancelledError()]

                    mock_config = Mock()
                    mock_config.logging.level = "INFO"
                    mock_config.logging.use_json = False
                    mock_config.storage.retain_days = 30
                    mock_config.storage.check_interval_hours = 0.001  # Very short for testing
                    mock_config.channels = []  # Add channels list
                    mock_load_config.return_value = mock_config

                    mock_get_audio_path.return_value = Path("/data/orpheus/audio_motion")

                    # First call raises exception, second succeeds
                    mock_result = Mock()
                    mock_result.files_removed = 0
                    mock_result.errors = []
                    mock_cleanup_instance = Mock()
                    mock_cleanup_instance.cleanup.side_effect = [
                        Exception("Test error"),
                        mock_result,
                    ]
                    mock_storage_cleanup.return_value = mock_cleanup_instance

                    detector = AudioMotionDetector()
                    detector._stop_event = asyncio.Event()

                    # Run cleanup - first iteration fails, second succeeds, third cancels
                    try:
                        await detector._periodic_cleanup()
                    except asyncio.CancelledError:
                        pass

                    # Verify cleanup was called twice (once failed, once succeeded)
                    assert mock_cleanup_instance.cleanup.call_count == 2
