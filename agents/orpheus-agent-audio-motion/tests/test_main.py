"""Tests for the AudioMotionDetector main class."""

import asyncio
import os
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
async def test_agent_does_not_delete_recordings(tmp_path, mock_config):
    """The agent records; orpheus-storage-sweep is the only component that deletes
    under the data root. The clip here predates every retention window and
    retain_days is 0, so any trim the agent still ran would take it."""
    clip_dir = tmp_path / "audio_motion"
    clip_dir.mkdir()
    expired_clip = clip_dir / "2020-01-01T00-00-00Z.flac"
    expired_clip.write_bytes(b"clip")
    os.utime(expired_clip, (0, 0))

    mock_config.storage.retain_days = 0

    # Captured before the patch below, which lands on the real asyncio module:
    # collapsing the agent's timers means a reinstated cleanup pass reaches its
    # first sweep within the loop turns this test drives, instead of sleeping
    # past the assertion.
    yield_once = asyncio.sleep

    async def no_wait(_delay):
        await yield_once(0)

    with patch("orpheus_agent_audio_motion.main.load_app_config", return_value=mock_config), patch(
        "orpheus_agent_audio_motion.main.setup_logging"
    ), patch(
        "orpheus_agent_audio_motion.main.get_audio_path", return_value=clip_dir
    ), patch(
        "orpheus_agent_audio_motion.main.get_audio_health_monitor"
    ) as mock_monitor, patch(
        "orpheus_agent_audio_motion.main.build_operational_health", return_value=None
    ), patch(
        "orpheus_common.config.OrpheusConfig.get_instance"
    ), patch(
        "orpheus_agent_audio_motion.main.asyncio.sleep", no_wait
    ):
        mock_monitor.return_value.get_status.return_value = {"status": "online"}

        detector = AudioMotionDetector()
        with patch.object(
            detector, "_initialize_dependencies", new_callable=AsyncMock
        ), patch.object(detector, "_consume_frames", new_callable=AsyncMock):
            start_task = asyncio.create_task(detector.start())
            for _ in range(20):
                await yield_once(0)
            detector._stop_event.set()
            await start_task

    assert expired_clip.exists()


@pytest.mark.asyncio
async def test_stop_cancels_the_background_tasks(mock_config):
    """A task left running past stop() keeps the process alive and keeps
    publishing after the agent has said it is down."""
    with patch("orpheus_agent_audio_motion.main.load_app_config", return_value=mock_config), patch(
        "orpheus_agent_audio_motion.main.setup_logging"
    ), patch("orpheus_agent_audio_motion.main.get_audio_path"), patch(
        "orpheus_agent_audio_motion.main.get_audio_health_monitor"
    ) as mock_monitor, patch(
        "orpheus_agent_audio_motion.main.build_operational_health", return_value=None
    ), patch(
        "orpheus_agent_audio_motion.main.health_on_bus_active", return_value=False
    ), patch("orpheus_common.config.OrpheusConfig.get_instance"):
        mock_monitor.return_value.get_status.return_value = {"status": "online"}

        detector = AudioMotionDetector()
        with patch.object(
            detector, "_initialize_dependencies", new_callable=AsyncMock
        ), patch.object(detector, "_consume_frames", new_callable=AsyncMock):
            start_task = asyncio.create_task(detector.start())
            # Enough turns for the health loop to reach its first sleep, so
            # "not done" below means genuinely parked rather than not started.
            for _ in range(5):
                await asyncio.sleep(0)
            health_task = detector._health_task
            assert health_task is not None
            assert not health_task.done(), "health loop died on its own; test proves nothing"

            detector._stop_event.set()
            await start_task

    # Done, not cancelled: the loop catches CancelledError and returns, so a
    # cancelled() assertion would be false even when stop() worked.
    assert health_task.done()
    assert detector._stream_task is None


@pytest.mark.asyncio
async def test_event_bus_built_from_shared_orpheus_config():
    """create_event_bus must receive the OrpheusConfig SINGLETON (which carries the
    operator's event_bus.* section), NOT the agent-local AppConfig — the AppConfig
    has no event_bus attribute, so handing it to the factory silently killed every
    event_bus knob (backend, nats_url, connect_required, …)."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config, patch(
        "orpheus_agent_audio_motion.main.create_event_bus"
    ) as mock_bus_factory, patch(
        "orpheus_agent_audio_motion.main.ClipSaver"
    ), patch(
        "orpheus_agent_audio_motion.main.create_audio_source", new_callable=AsyncMock
    ) as mock_source_factory, patch(
        "orpheus_agent_audio_motion.main.DetectionDB"
    ), patch(
        "orpheus_common.config.OrpheusConfig.get_instance"
    ) as mock_get_instance:
        mock_config = Mock()
        mock_config.storage.category = "audio_motion"
        mock_config.storage.write_format = "flac"
        mock_config.runtime.sample_rate = 48000
        mock_config.runtime.frame_duration_ms = 200
        mock_config.mqtt.qos = 1
        mock_config.channels = []
        mock_load_config.return_value = mock_config

        shared_config = Mock()
        shared_config.audio.channels = []
        mock_get_instance.return_value = shared_config
        mock_source_factory.return_value = AsyncMock()

        detector = AudioMotionDetector()
        with patch.object(detector, "_setup_event_sourcing_shadow", return_value=False):
            # No enabled channels raises AFTER the bus is built — expected here.
            with pytest.raises(RuntimeError, match="No enabled channels"):
                await detector._initialize_dependencies()

        assert mock_bus_factory.call_args[0][0] is shared_config
        assert mock_bus_factory.call_args[0][0] is not detector._config


@pytest.mark.asyncio
@pytest.mark.parametrize("shadow", [True, False])
async def test_health_status_carries_event_sourcing_shadow_flag(shadow):
    """The health payload surfaces whether the event-sourcing shadow is actually
    recording (additive key, same as the classifier agents) — a silent self-disable
    on mqtt / stream_ensure error is otherwise invisible on Diagnostics."""
    with patch("orpheus_agent_audio_motion.main.load_app_config") as mock_load_config, patch(
        "orpheus_agent_audio_motion.main.get_audio_health_monitor"
    ) as mock_monitor, patch(
        "orpheus_agent_audio_motion.main.build_operational_health", return_value=None
    ), patch(
        "orpheus_common.config.OrpheusConfig.get_instance"
    ) as mock_get_instance, patch(
        "orpheus_agent_audio_motion.main.asyncio.sleep"
    ) as mock_sleep:
        mock_sleep.side_effect = [None, None, asyncio.CancelledError()]
        mock_config = Mock()
        mock_config.channels = []
        mock_load_config.return_value = mock_config
        mock_get_instance.return_value = Mock()
        mock_monitor.return_value.get_status.return_value = {"status": "online"}

        detector = AudioMotionDetector()
        detector._stop_event = asyncio.Event()
        detector._mqtt_client = Mock()
        detector._shadow_stream_publish = shadow

        await detector._publish_health_status()

        topic, payload = detector._mqtt_client.publish.call_args[0][:2]
        assert topic == "orpheus/system/audio/health"
        assert payload["event_sourcing_shadow"] is shadow
        assert payload["status"] == "online"  # existing keys untouched
