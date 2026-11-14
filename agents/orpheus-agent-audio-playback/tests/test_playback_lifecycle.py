"""Playback lifecycle: completion, failure and the corollary-discharge window.

``player.play()`` returns once playback has started. These tests pin the agent
to waiting for the end (``player.wait()``) so that the published playback
window covers the audio actually played, player failures (an unavailable
Bluetooth speaker, a missing audio server) reach the requester, and
file_path / detection_id playback is not cancelled the moment it starts.
"""

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from orpheus_common.audio.playback import SubprocessAudioPlayer

from orpheus_agent_audio_playback.main import AudioPlaybackAgent


def _published(mqtt: MagicMock, topic: str) -> list:
    return [c[0][1] for c in mqtt.publish.call_args_list if c[0][0] == topic]


def _player(wait_side_effect=None, wait_delay: float = 0.0, wait_result: bool = True):
    player = MagicMock()
    player.play = AsyncMock(return_value=None)

    async def wait():
        await asyncio.sleep(wait_delay)
        if wait_side_effect is not None:
            raise wait_side_effect
        return wait_result

    player.wait = wait
    return player


@pytest.fixture
def agent(mock_orpheus_config, mock_mqtt_client):  # noqa: ARG001
    a = AudioPlaybackAgent()
    a._mqtt_client = mock_mqtt_client  # noqa: SLF001
    return a


@pytest.mark.asyncio
async def test_window_covers_the_whole_playback(agent, mock_mqtt_client):
    await agent._play_sound_async(_player(wait_delay=0.3), Path("crow.wav"), 1, 0.0, "crow_call")  # noqa: SLF001

    (window,) = _published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
    assert window["duration_seconds"] >= 0.3
    assert window["sound_name"] == "crow_call"
    assert _published(mock_mqtt_client, agent.TOPIC_RESPONSE) == []


@pytest.mark.asyncio
async def test_player_failure_is_reported_and_still_windowed(agent, mock_mqtt_client):
    failure = RuntimeError("Audio player 'ffplay' failed with code 1: Connection refused")
    await agent._play_sound_async(  # noqa: SLF001
        _player(wait_side_effect=failure, wait_delay=0.1), Path("crow.wav"), 1, 0.0, "crow_call"
    )

    (error,) = _published(mock_mqtt_client, agent.TOPIC_RESPONSE)
    assert error["status"] == "error"
    assert "Connection refused" in error["error"]
    assert error["sound_name"] == "crow_call"
    # Some audio may have played before the failure, so the window is kept.
    (window,) = _published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
    assert window["duration_seconds"] >= 0.1


@pytest.mark.asyncio
async def test_playback_stopped_early_is_windowed_without_error(agent, mock_mqtt_client):
    await agent._play_sound_async(_player(wait_result=False), Path("crow.wav"), 1, 0.0, "crow_call")  # noqa: SLF001

    assert len(_published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK)) == 1
    assert _published(mock_mqtt_client, agent.TOPIC_RESPONSE) == []


@pytest.mark.asyncio
async def test_playback_that_never_started_is_not_windowed(agent, mock_mqtt_client):
    player = _player()
    player.play = AsyncMock(
        side_effect=RuntimeError("Segment extraction and volume control require ffplay")
    )
    await agent._play_sound_async(player, Path("crow.wav"), 1, 0.0, "crow_call")  # noqa: SLF001

    assert _published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK) == []
    (error,) = _published(mock_mqtt_client, agent.TOPIC_RESPONSE)
    assert "require ffplay" in error["error"]


def test_audio_source_request_without_running_agent_is_an_error(agent, mock_mqtt_client, tmp_path):
    clip = tmp_path / "clip.wav"
    clip.write_text("fake audio")
    agent._handle_playback_request(agent.TOPIC_REQUEST, {"file_path": str(clip)})  # noqa: SLF001

    (error,) = _published(mock_mqtt_client, agent.TOPIC_RESPONSE)
    assert error["status"] == "error"
    assert "not started" in error["error"]


@pytest.mark.asyncio
async def test_audio_source_playback_runs_to_completion(agent, mock_mqtt_client, tmp_path):
    """Regression: the request handler used asyncio.run(player.play(...)),
    whose throwaway loop cancelled playback, and killed the player process,
    about 10 ms after it started. A real subprocess player must now finish."""
    marker = tmp_path / "played"
    script = tmp_path / "fakeplay"
    script.write_text(f"#!/bin/sh\nsleep 0.3\necho done > {marker}\n")
    script.chmod(0o755)
    config = MagicMock()
    config.audio.playback_command = str(script)
    player = SubprocessAudioPlayer(config=config)

    clip = tmp_path / "clip.wav"
    clip.write_text("fake audio")
    agent._event_loop = asyncio.get_running_loop()  # noqa: SLF001

    with patch("orpheus_agent_audio_playback.main.get_audio_player", return_value=player):
        # The event bus delivers requests on its own dispatch thread.
        t = threading.Thread(
            target=agent._handle_playback_request,  # noqa: SLF001
            args=(agent.TOPIC_REQUEST, {"file_path": str(clip)}),
        )
        t.start()
        t.join()
        for _ in range(100):
            if _published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK):
                break
            await asyncio.sleep(0.05)

    assert marker.read_text().strip() == "done"
    (window,) = _published(mock_mqtt_client, agent.TOPIC_ACTUATION_AUDIO_PLAYBACK)
    assert window["duration_seconds"] >= 0.3
    (response,) = _published(mock_mqtt_client, agent.TOPIC_RESPONSE)
    assert response["status"] == "success"


@pytest.mark.asyncio
async def test_audio_source_player_failure_is_reported(agent, mock_mqtt_client, tmp_path):
    script = tmp_path / "fakeplay"
    script.write_text(
        "#!/bin/sh\necho 'pa_context_connect() failed: Connection refused' >&2\nexit 1\n"
    )
    script.chmod(0o755)
    config = MagicMock()
    config.audio.playback_command = str(script)
    player = SubprocessAudioPlayer(config=config)

    clip = tmp_path / "clip.wav"
    clip.write_text("fake audio")
    agent._event_loop = asyncio.get_running_loop()  # noqa: SLF001

    with patch("orpheus_agent_audio_playback.main.get_audio_player", return_value=player):
        await asyncio.get_running_loop().run_in_executor(
            None,
            agent._handle_playback_request,  # noqa: SLF001
            agent.TOPIC_REQUEST,
            {"file_path": str(clip)},
        )
        for _ in range(100):
            if len(_published(mock_mqtt_client, agent.TOPIC_RESPONSE)) >= 2:
                break
            await asyncio.sleep(0.05)

    started, failed = _published(mock_mqtt_client, agent.TOPIC_RESPONSE)
    assert started["status"] == "success"
    assert failed["status"] == "error"
    assert "Connection refused" in failed["error"]
    assert failed["source"] == str(clip)
