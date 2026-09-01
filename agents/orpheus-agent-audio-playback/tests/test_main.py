"""Tests for the audio playback agent main module."""

import asyncio
import contextlib
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orpheus_agent_audio_playback.main import (
    AudioPlaybackAgent,
    main,
    main_async,
    parse_args,
)


class TestAudioPlaybackAgent:
    """Tests for AudioPlaybackAgent class."""

    @pytest.mark.asyncio
    async def test_initialization(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,  # noqa: ARG002
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test agent initialization."""
        agent = AudioPlaybackAgent()

        assert agent._config is not None  # noqa: SLF001
        assert agent._mqtt_client is None  # noqa: SLF001 - Not initialized until start()
        assert not agent._stop_event.is_set()  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_initialize_dependencies(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,
        mock_audio_player,  # noqa: ARG002
    ):
        """Test dependency initialization."""
        agent = AudioPlaybackAgent()

        await agent._initialize_dependencies()  # noqa: SLF001

        # MQTT client should be created and connected
        assert agent._mqtt_client is not None  # noqa: SLF001
        mock_mqtt_client.connect.assert_called_once()
        mock_mqtt_client.subscribe.assert_called_once()

        # Sound registry should be initialized
        mock_sound_registry.list_sounds.assert_called()

    @pytest.mark.asyncio
    async def test_handle_playback_request_valid(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling valid playback request."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001
        # Simulate event loop being set
        agent._event_loop = MagicMock()  # noqa: SLF001

        # Prepare valid request
        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": 3,
            "pause_between": 1.0,
        }

        # Mock asyncio.run_coroutine_threadsafe to avoid actually running playback
        with patch(
            "orpheus_agent_audio_playback.main.asyncio.run_coroutine_threadsafe"
        ) as mock_run_coro:
            mock_future = MagicMock()
            mock_run_coro.return_value = mock_future

            # Handle request (now synchronous)
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify response was published
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][0] == agent.TOPIC_RESPONSE
        assert call_args[0][1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_play_sound_async_publishes_playback_window(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """After a sound plays, a corollary-discharge playback-window event is
        published so the event-correlator can blank self-generated detections."""
        from unittest.mock import AsyncMock

        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        player = MagicMock()
        player.play = AsyncMock(return_value=None)

        await agent._play_sound_async(player, Path("crow.wav"), 1, 0.0, "crow_call")  # noqa: SLF001

        window_calls = [
            c
            for c in mock_mqtt_client.publish.call_args_list
            if c[0][0] == agent.TOPIC_ACTUATION_AUDIO_PLAYBACK
        ]
        assert len(window_calls) == 1
        payload = window_calls[0][0][1]
        assert payload["sound_name"] == "crow_call"
        assert payload["source"] == "audio_playback_agent"
        assert "start_time" in payload
        assert isinstance(payload["duration_seconds"], (int, float))
        assert payload["duration_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_handle_playback_request_missing_sound_name(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request with missing sound_name."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Request without sound_name
        payload = {"repeat_count": 3}

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Should publish error
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "sound_name" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_playback_request_invalid_payload_type(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request with invalid payload type."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Invalid payload (string instead of dict)
        payload = "invalid"

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Should publish error
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "invalid payload" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_playback_request_invalid_repeat_count(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request with invalid repeat_count."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Invalid repeat_count (negative)
        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": 0,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Should publish error
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "repeat_count" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_playback_request_invalid_pause_between(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request with invalid pause_between."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Invalid pause_between (negative)
        payload = {
            "sound_name": "test_tone_1",
            "pause_between": -1.0,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001  # noqa: SLF001

        # Should publish error
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "pause_between" in call_args[0][1]["error"].lower()

    def test_play_sound_success(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test successful sound playback."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001
        # Simulate event loop being set (normally happens in start())
        agent._event_loop = MagicMock()  # noqa: SLF001

        # Mock asyncio.run_coroutine_threadsafe to capture thread-safe scheduling
        with patch(
            "orpheus_agent_audio_playback.main.asyncio.run_coroutine_threadsafe"
        ) as mock_run_coro:
            mock_future = MagicMock()
            mock_run_coro.return_value = mock_future

            agent._play_sound(  # noqa: SLF001
                "test_tone_1", repeat_count=2, pause_between=0.5
            )

            # Verify run_coroutine_threadsafe was called (thread-safe scheduling)
            # This is critical - direct create_task() fails without running event loop
            mock_run_coro.assert_called_once()
            # Verify the event loop was passed
            assert mock_run_coro.call_args[0][1] == agent._event_loop  # noqa: SLF001

        # Verify success response was published
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "success"

    def test_play_sound_not_found(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,
        mock_audio_player,  # noqa: ARG002
    ):
        """Test playback of nonexistent sound."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Configure registry to raise KeyError
        mock_sound_registry.get_sound_path.side_effect = KeyError("unknown_sound")

        agent._play_sound(  # noqa: SLF001
            "unknown_sound", repeat_count=1, pause_between=0
        )

        # Verify error response was published
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "not found" in call_args[0][1]["error"].lower()

    def test_play_sound_playback_error(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling of playback errors."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001
        # Simulate event loop being set
        agent._event_loop = MagicMock()  # noqa: SLF001

        # Configure asyncio.run_coroutine_threadsafe to raise error
        with patch(
            "orpheus_agent_audio_playback.main.asyncio.run_coroutine_threadsafe"
        ) as mock_run_coro:
            mock_run_coro.side_effect = RuntimeError("Playback failed")

            agent._play_sound(  # noqa: SLF001
                "test_tone_1", repeat_count=1, pause_between=0
            )

        # Verify error response was published
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "failed" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_publish_health_status(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,
        mock_audio_player,
    ):
        """Test health status publishing."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Start health publishing task
        health_task = asyncio.create_task(
            agent._publish_health_status()  # noqa: SLF001
        )

        # Give task a moment to start
        await asyncio.sleep(0.1)

        # Stop the task - this will interrupt the sleep
        agent._stop_event.set()  # noqa: SLF001

        # Wait for task to complete (should exit quickly after stop event is set)
        try:
            await asyncio.wait_for(health_task, timeout=2.0)
        except asyncio.TimeoutError:
            # If it times out, cancel it
            health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await health_task

        # Verify the mocks were set up correctly
        # (no actual publish expected since we stopped before first interval)
        assert mock_mqtt_client is not None
        assert mock_sound_registry.list_sounds.return_value == [
            "test_tone_1",
            "test_beep",
            "test_silence",
        ]
        assert mock_audio_player.is_playing.return_value is False

    @pytest.mark.asyncio
    async def test_stop_agent(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,
    ):
        """Test agent shutdown."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001
        agent._health_task = asyncio.create_task(asyncio.sleep(10))  # noqa: SLF001

        await agent.stop()

        # Verify cleanup
        assert agent._health_task.cancelled()  # noqa: SLF001
        mock_audio_player.stop.assert_called_once()
        mock_mqtt_client.disconnect.assert_called_once()

    def test_parse_args_default(self):
        """Test argument parsing with defaults."""
        args = parse_args([])

        assert args.config is None
        assert args.log_level is None

    def test_parse_args_with_options(self):
        """Test argument parsing with options."""
        args = parse_args(["--config", "test.yaml", "--log-level", "DEBUG"])

        assert args.config == Path("test.yaml")
        assert args.log_level == "DEBUG"

    def test_main_success(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,  # noqa: ARG002
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test main() function success path."""
        with patch("orpheus_agent_audio_playback.main.asyncio.run") as mock_run:
            # Mock asyncio.run to avoid actually running the agent
            mock_run.return_value = None

            exit_code = main([])

            assert exit_code == 0
            mock_run.assert_called_once()

    def test_main_keyboard_interrupt(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,  # noqa: ARG002
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test main() handles KeyboardInterrupt."""
        with patch("orpheus_agent_audio_playback.main.asyncio.run") as mock_run:
            mock_run.side_effect = KeyboardInterrupt()

            exit_code = main([])

            assert exit_code == 130

    def test_main_exception(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,  # noqa: ARG002
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test main() handles exceptions."""
        with patch("orpheus_agent_audio_playback.main.asyncio.run") as mock_run:
            mock_run.side_effect = Exception("Test error")

            exit_code = main([])

            assert exit_code == 1

    @pytest.mark.asyncio
    async def test_start_with_config_path(
        self,
        mock_orpheus_config,
        mock_mqtt_client,  # noqa: ARG002
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test agent start with config path override."""
        with patch("orpheus_agent_audio_playback.main.OrpheusConfig.load") as mock_load:
            mock_load.return_value = mock_orpheus_config
            agent = AudioPlaybackAgent(config_path=Path("test.yaml"))

            # Verify config was loaded with path
            mock_load.assert_called_once()
            assert agent._config is not None  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_start_method_complete_flow(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,
    ):
        """Test complete start method flow including signal handlers."""
        agent = AudioPlaybackAgent()

        # Create a task that will set the stop event after a short delay
        async def set_stop_event():
            await asyncio.sleep(0.1)
            agent._stop_event.set()  # noqa: SLF001

        # Start both the agent and the stop event setter
        stop_task = asyncio.create_task(set_stop_event())

        # The start method should complete after stop event is set
        await agent.start()

        # Wait for stop task to complete
        await stop_task

        # Verify agent initialized and stopped properly
        mock_mqtt_client.connect.assert_called_once()
        mock_audio_player.stop.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_with_player_error(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,
    ):
        """Test agent stop handles player errors gracefully."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Configure player to raise error on stop
        mock_audio_player.stop.side_effect = RuntimeError("Stop failed")

        # Should not raise exception
        await agent.stop()

        # Verify disconnect was still called
        mock_mqtt_client.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_invalid_parameter_types(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request with non-convertible parameter types."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Invalid types that can't be converted
        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": "not_a_number",
            "pause_between": "not_a_float",
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Should publish error about invalid types
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "parameter" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_handle_request_with_exception(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,
        mock_audio_player,  # noqa: ARG002
    ):
        """Test handling request when internal exception occurs."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Make sound registry raise unexpected exception
        mock_sound_registry.get_sound_path.side_effect = RuntimeError("Unexpected error")

        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": 1,
            "pause_between": 0,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Should publish error
        assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_publish_health_status_actual_publish(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test health status actually publishes to MQTT."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Start health publishing task
        health_task = asyncio.create_task(
            agent._publish_health_status()  # noqa: SLF001
        )

        # Wait long enough for at least one publish (interval is 10s, but we'll force it)
        # We'll wait 0.1s then stop the event
        await asyncio.sleep(0.1)
        agent._stop_event.set()  # noqa: SLF001

        # Wait for task to complete
        try:
            await asyncio.wait_for(health_task, timeout=2.0)
        except asyncio.TimeoutError:
            health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await health_task

        # Health task should have been cancelled properly
        assert health_task.done()

    @pytest.mark.asyncio
    async def test_main_async_function(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test main_async function."""
        args = Namespace(config=None, log_level="INFO")

        # Create task that will stop the agent after a short delay
        async def run_with_timeout():
            task = asyncio.create_task(main_async(args))
            await asyncio.sleep(0.2)
            # The agent should be running, let's wait a bit more then stop it
            # by setting its stop event (we can't access it directly, so we cancel)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        await run_with_timeout()

        # Verify initialization happened
        mock_mqtt_client.connect.assert_called()


class TestNewAudioSourceFeatures:
    """Tests for new audio source playback features."""

    @pytest.mark.asyncio
    async def test_play_by_file_path_absolute(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test playing audio by absolute file path."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Create a test audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "repeat_count": 1,
        }

        # Mock asyncio.run to avoid actually running playback
        with patch("orpheus_agent_audio_playback.main.asyncio.run"):
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify success response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "success"

    @pytest.mark.asyncio
    async def test_play_by_file_path_relative(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test playing audio by relative file path."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Mock get_data_root to return tmp_path
        with patch("orpheus_agent_audio_playback.main.get_data_root") as mock_data_root:
            mock_data_root.return_value = tmp_path

            # Create a test audio file in data root
            audio_file = tmp_path / "audio" / "test.wav"
            audio_file.parent.mkdir(parents=True)
            audio_file.write_text("fake audio")

            payload = {
                "file_path": "audio/test.wav",
                "repeat_count": 1,
            }

            # Mock asyncio.run to avoid actually running playback
            with patch("orpheus_agent_audio_playback.main.asyncio.run"):
                agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

            # Verify success response
            assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_play_by_detection_id(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test playing audio by detection ID."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Create a test audio file
        audio_file = tmp_path / "detection_audio.wav"
        audio_file.write_text("fake audio")

        # Mock DetectionDB
        with patch("orpheus_agent_audio_playback.main.DetectionDB") as mock_db_class:
            mock_db = MagicMock()
            mock_detection = MagicMock()
            mock_detection.audio_clip_path = str(audio_file)
            mock_db.get_by_event_id.return_value = mock_detection
            mock_db_class.return_value = mock_db

            payload = {
                "detection_id": "test-detection-123",
                "repeat_count": 1,
            }

            # Mock asyncio.run to avoid actually running playback
            with patch("orpheus_agent_audio_playback.main.asyncio.run"):
                agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

            # Verify detection was looked up
            mock_db.get_by_event_id.assert_called_once_with("test-detection-123")

            # Verify success response
            assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_play_with_segment_extraction(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test playing audio with segment extraction."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Create a test audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "start_time": 5.0,
            "duration": 10.0,
            "repeat_count": 1,
        }

        # Mock asyncio.run to avoid actually running playback
        with patch("orpheus_agent_audio_playback.main.asyncio.run"):
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify success response
        assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_play_with_volume_control(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test playing audio with volume control."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Create a test audio file
        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "volume": 50,
            "repeat_count": 1,
        }

        # Mock asyncio.run to avoid actually running playback
        with patch("orpheus_agent_audio_playback.main.asyncio.run"):
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify success response
        assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_play_file_not_found(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test error handling when file is not found."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        payload = {
            "file_path": "/nonexistent/path/audio.wav",
            "repeat_count": 1,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "not found" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_play_detection_not_found(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test error handling when detection is not found."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Mock DetectionDB to return None
        with patch("orpheus_agent_audio_playback.main.DetectionDB") as mock_db_class:
            mock_db = MagicMock()
            mock_db.get_by_event_id.return_value = None
            mock_db_class.return_value = mock_db

            payload = {
                "detection_id": "nonexistent-detection",
                "repeat_count": 1,
            }

            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

            # Verify error response
            assert mock_mqtt_client.publish.called
            call_args = mock_mqtt_client.publish.call_args
            assert call_args[0][1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_volume(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test validation of invalid volume parameter."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "volume": 150,  # Invalid: > 100
            "repeat_count": 1,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "volume" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_invalid_start_time(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test validation of invalid start_time parameter."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "start_time": -5.0,  # Invalid: negative
            "repeat_count": 1,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_invalid_duration(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test validation of invalid duration parameter."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "duration": 0.0,  # Invalid: must be > 0
            "repeat_count": 1,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_missing_audio_source(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test error when no audio source is provided."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        payload = {
            "repeat_count": 1,
            # Missing: sound_name, file_path, and detection_id
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "audio source" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_backward_compatibility_sound_name(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test backward compatibility with sound_name requests."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Legacy format request
        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": 2,
            "pause_between": 0.5,
        }

        # Mock asyncio.run to avoid actually running playback
        with patch("orpheus_agent_audio_playback.main.asyncio.run"):
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify success response
        assert mock_mqtt_client.publish.called

    @pytest.mark.asyncio
    async def test_detection_without_audio_clip(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test error when detection has no audio clip."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Mock DetectionDB with detection that has no audio_clip_path
        with patch("orpheus_agent_audio_playback.main.DetectionDB") as mock_db_class:
            mock_db = MagicMock()
            mock_detection = MagicMock()
            mock_detection.audio_clip_path = None  # No audio clip
            mock_db.get_by_event_id.return_value = mock_detection
            mock_db_class.return_value = mock_db

            payload = {
                "detection_id": "test-detection-no-audio",
                "repeat_count": 1,
            }

            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

            # Verify error response
            assert mock_mqtt_client.publish.called
            call_args = mock_mqtt_client.publish.call_args
            assert call_args[0][1]["status"] == "error"

    @pytest.mark.asyncio
    async def test_both_file_path_and_detection_id(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test error when both file_path and detection_id are provided."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        audio_file = tmp_path / "test.wav"
        audio_file.write_text("fake audio")

        payload = {
            "file_path": str(audio_file),
            "detection_id": "some-detection-id",
            "repeat_count": 1,
        }

        agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify error response
        assert mock_mqtt_client.publish.called
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "error"
        assert "both" in call_args[0][1]["error"].lower()

    @pytest.mark.asyncio
    async def test_path_traversal_protection(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
        tmp_path,
    ):
        """Test error when relative path uses traversal to escape data root."""
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001

        # Mock get_data_root to return a specific directory
        with patch("orpheus_agent_audio_playback.main.get_data_root") as mock_data_root:
            data_root = tmp_path / "data_root"
            data_root.mkdir()
            mock_data_root.return_value = data_root

            # Try to use ../ to escape the data root
            payload = {
                "file_path": "../../../etc/passwd",  # Path traversal attempt
                "repeat_count": 1,
            }

            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

            # Verify error response about path traversal
            assert mock_mqtt_client.publish.called
            call_args = mock_mqtt_client.publish.call_args
            assert call_args[0][1]["status"] == "error"
            error_lower = call_args[0][1]["error"].lower()
            assert "traversal" in error_lower or "invalid" in error_lower

    def test_mqtt_callback_without_event_loop(
        self,
        mock_orpheus_config,  # noqa: ARG002
        mock_mqtt_client,
        mock_sound_registry,  # noqa: ARG002
        mock_audio_player,  # noqa: ARG002
    ):
        """Test MQTT callback can be invoked directly without RuntimeError.

        This test verifies the fix for the "no running event loop" error.
        The callback should work when called from a thread without an event loop.
        """
        agent = AudioPlaybackAgent()
        agent._mqtt_client = mock_mqtt_client  # noqa: SLF001
        # Simulate event loop being set (normally happens in start())
        agent._event_loop = MagicMock()  # noqa: SLF001

        # Prepare valid request
        payload = {
            "sound_name": "test_tone_1",
            "repeat_count": 1,
            "pause_between": 0.0,
        }

        # Mock asyncio.run_coroutine_threadsafe to avoid actual playback
        with patch(
            "orpheus_agent_audio_playback.main.asyncio.run_coroutine_threadsafe"
        ) as mock_run_coro:
            mock_future = MagicMock()
            mock_run_coro.return_value = mock_future

            # This should not raise "RuntimeError: no running event loop"
            # because _handle_playback_request uses run_coroutine_threadsafe
            agent._handle_playback_request(agent.TOPIC_REQUEST, payload)  # noqa: SLF001

        # Verify response was published successfully
        mock_mqtt_client.publish.assert_called()
        call_args = mock_mqtt_client.publish.call_args
        assert call_args[0][1]["status"] == "success"
