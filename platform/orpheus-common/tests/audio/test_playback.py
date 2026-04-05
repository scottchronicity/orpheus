"""Tests for audio playback functionality."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orpheus_common.audio.playback import (
    AudioPlayer,
    SubprocessAudioPlayer,
    get_audio_player,
)


@pytest.fixture
def test_audio_file(tmp_path: Path) -> Path:
    """Create a temporary test audio file."""
    audio_file = tmp_path / "test.wav"
    audio_file.write_text("fake audio data")
    return audio_file


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig with audio.playback_command."""
    with patch("orpheus_common.audio.playback.OrpheusConfig") as mock_cls:
        config = MagicMock()
        config.audio.playback_command = "ffplay"
        mock_cls.get_instance.return_value = config
        yield config


@pytest.fixture
def mock_subprocess():
    """Mock subprocess for testing without actual audio playback."""
    with patch("orpheus_common.audio.playback.asyncio.create_subprocess_exec") as mock_exec:
        # Create mock process
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.communicate.return_value = (b"", b"")
        mock_exec.return_value = mock_process

        yield {
            "exec": mock_exec,
            "process": mock_process,
        }


class TestAudioPlayer:
    """Tests for AudioPlayer abstract base class."""

    def test_abstract_methods(self):
        """Test that AudioPlayer cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AudioPlayer()


class TestSubprocessAudioPlayer:
    """Tests for SubprocessAudioPlayer implementation."""

    def test_init_with_config(self, mock_config):
        """Test that player initialization uses config.audio.playback_command."""
        player = SubprocessAudioPlayer(config=mock_config)

        assert player._player_cmd == "ffplay"
        assert player._player_args == ["-nodisp", "-autoexit", "-loglevel", "error"]

    def test_init_without_config_uses_singleton(self):
        """Test that player initialization uses OrpheusConfig singleton if config not provided."""
        with patch("orpheus_common.audio.playback.OrpheusConfig") as mock_cls:
            config = MagicMock()
            config.audio.playback_command = "aplay"
            mock_cls.get_instance.return_value = config

            player = SubprocessAudioPlayer()

            assert player._player_cmd == "aplay"
            assert player._player_args == ["-q"]

    def test_init_with_custom_playback_command(self):
        """Test initialization with custom playback command."""
        config = MagicMock()
        config.audio.playback_command = "custom_player"

        player = SubprocessAudioPlayer(config=config)

        assert player._player_cmd == "custom_player"
        assert player._player_args == []  # Unknown player, no default args

    def test_init_raises_if_no_playback_command(self):
        """Test that initialization fails if playback_command is empty."""
        config = MagicMock()
        config.audio.playback_command = ""

        with pytest.raises(RuntimeError, match="No playback command configured"):
            SubprocessAudioPlayer(config=config)

    @pytest.mark.asyncio
    async def test_play_single_file(self, test_audio_file, mock_config, mock_subprocess):
        """Test playing a single audio file."""
        player = SubprocessAudioPlayer(config=mock_config)

        # play() starts task in background
        await player.play(test_audio_file, repeat_count=1, pause_between=0)

        # Wait for playback to complete
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify subprocess was called
        mock_subprocess["exec"].assert_called_once()
        args = mock_subprocess["exec"].call_args[0]
        assert args[0] == "ffplay"
        assert str(test_audio_file) in args

    @pytest.mark.asyncio
    async def test_play_with_repeats(self, test_audio_file, mock_config, mock_subprocess):
        """Test playing with repeats."""
        player = SubprocessAudioPlayer(config=mock_config)

        # Start playback
        await player.play(test_audio_file, repeat_count=3, pause_between=0.01)

        # Wait for completion
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify subprocess was called multiple times
        assert mock_subprocess["exec"].call_count == 3

    @pytest.mark.asyncio
    async def test_play_nonexistent_file(self, tmp_path, mock_config, mock_subprocess):
        """Test that playing nonexistent file raises FileNotFoundError."""
        player = SubprocessAudioPlayer(config=mock_config)
        nonexistent = tmp_path / "does_not_exist.wav"

        with pytest.raises(FileNotFoundError):
            await player.play(nonexistent)

    @pytest.mark.asyncio
    async def test_play_invalid_repeat_count(self, test_audio_file, mock_config, mock_subprocess):
        """Test that invalid repeat_count raises ValueError."""
        player = SubprocessAudioPlayer(config=mock_config)

        with pytest.raises(ValueError, match="repeat_count must be >= 1"):
            await player.play(test_audio_file, repeat_count=0)

    @pytest.mark.asyncio
    async def test_play_invalid_pause_between(self, test_audio_file, mock_config, mock_subprocess):
        """Test that invalid pause_between raises ValueError."""
        player = SubprocessAudioPlayer(config=mock_config)

        with pytest.raises(ValueError, match="pause_between must be >= 0"):
            await player.play(test_audio_file, pause_between=-1)

    @pytest.mark.asyncio
    async def test_stop_during_playback(self, test_audio_file, mock_config, mock_subprocess):
        """Test stopping playback."""
        player = SubprocessAudioPlayer(config=mock_config)

        # Start playback that would normally repeat many times
        await player.play(test_audio_file, repeat_count=10, pause_between=0.5)

        # Wait a bit to ensure it starts
        await asyncio.sleep(0.1)
        assert player.is_playing()

        # Stop playback
        await player.stop()

        # Should not be playing anymore
        assert not player.is_playing()

    @pytest.mark.asyncio
    async def test_play_stops_previous_playback(
        self, test_audio_file, mock_config, mock_subprocess
    ):
        """Test that starting new playback stops previous one."""
        player = SubprocessAudioPlayer()

        # Start first playback
        await player.play(test_audio_file, repeat_count=10, pause_between=0.5)

        await asyncio.sleep(0.1)
        assert player.is_playing()

        # Start second playback (should stop first)
        await player.play(test_audio_file, repeat_count=1, pause_between=0)

        # Wait for completion
        while player.is_playing():
            await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_subprocess_failure_handling(self, test_audio_file, mock_config):
        """Test handling of subprocess failures."""
        with patch("orpheus_common.audio.playback.asyncio.create_subprocess_exec") as mock_exec:
            # Simulate failed subprocess
            mock_process = AsyncMock()
            mock_process.returncode = 1
            mock_process.communicate.return_value = (b"", b"Error: file not supported")
            mock_exec.return_value = mock_process

            player = SubprocessAudioPlayer(config=mock_config)

            # play() returns immediately, actual playback is async
            # We need to wait for the internal task
            play_task = asyncio.create_task(player._play_once(test_audio_file))

            with pytest.raises(RuntimeError, match="Audio player .* failed with code"):
                await play_task

    def test_is_playing_when_idle(self, mock_config, mock_subprocess):
        """Test is_playing returns False when idle."""
        player = SubprocessAudioPlayer()
        assert not player.is_playing()

    @pytest.mark.asyncio
    async def test_stop_when_not_playing(self, mock_config, mock_subprocess):
        """Test that stop() is safe to call when not playing."""
        player = SubprocessAudioPlayer()

        # Should not raise any errors
        await player.stop()
        await player.stop()  # Multiple calls should be safe


class TestGetAudioPlayer:
    """Tests for get_audio_player() global function."""

    def test_returns_singleton(self, mock_config, mock_subprocess):
        """Test that get_audio_player returns same instance."""
        player1 = get_audio_player()
        player2 = get_audio_player()

        assert player1 is player2

    def test_raises_if_no_player_available(self):
        """Test that get_audio_player raises if no player available."""
        # Reset global instance and mock config with empty playback command
        config = MagicMock()
        config.audio.playback_command = ""

        with (
            patch("orpheus_common.audio.playback._audio_player", None),
            patch("orpheus_common.audio.playback.OrpheusConfig") as mock_cls,
        ):
            mock_cls.get_instance.return_value = config
            with pytest.raises(RuntimeError, match="No playback command configured"):
                get_audio_player()


class TestSubprocessAudioPlayerAdvancedFeatures:
    """Tests for advanced playback features (segment extraction, volume control)."""

    @pytest.mark.asyncio
    async def test_play_with_start_time(self, test_audio_file, mock_config, mock_subprocess):
        """Test playback with start_time parameter."""
        player = SubprocessAudioPlayer(config=mock_config)

        await player.play(test_audio_file, start_time=5.0)

        # Wait for playback to complete
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify ffplay was called with -ss flag
        mock_subprocess["exec"].assert_called_once()
        call_args = mock_subprocess["exec"].call_args[0]
        assert "-ss" in call_args
        assert "5.0" in call_args

    @pytest.mark.asyncio
    async def test_play_with_duration(self, test_audio_file, mock_config, mock_subprocess):
        """Test playback with duration parameter."""
        player = SubprocessAudioPlayer(config=mock_config)

        await player.play(test_audio_file, duration=10.0)

        # Wait for playback to complete
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify ffplay was called with -t flag
        mock_subprocess["exec"].assert_called_once()
        call_args = mock_subprocess["exec"].call_args[0]
        assert "-t" in call_args
        assert "10.0" in call_args

    @pytest.mark.asyncio
    async def test_play_with_volume(self, test_audio_file, mock_config, mock_subprocess):
        """Test playback with volume parameter."""
        player = SubprocessAudioPlayer(config=mock_config)

        await player.play(test_audio_file, volume=75)

        # Wait for playback to complete
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify ffplay was called with -volume flag
        mock_subprocess["exec"].assert_called_once()
        call_args = mock_subprocess["exec"].call_args[0]
        assert "-volume" in call_args
        assert "75" in call_args

    @pytest.mark.asyncio
    async def test_play_with_all_advanced_parameters(
        self, test_audio_file, mock_config, mock_subprocess
    ):
        """Test playback with all advanced parameters."""
        player = SubprocessAudioPlayer(config=mock_config)

        await player.play(
            test_audio_file,
            start_time=2.5,
            duration=8.0,
            volume=60,
            repeat_count=2,
            pause_between=1.0,
        )

        # Wait for playback to complete
        while player.is_playing():
            await asyncio.sleep(0.05)

        # Verify ffplay was called with all flags (twice because repeat_count=2)
        assert mock_subprocess["exec"].call_count == 2
        call_args = mock_subprocess["exec"].call_args[0]
        assert "-ss" in call_args
        assert "2.5" in call_args
        assert "-t" in call_args
        assert "8.0" in call_args
        assert "-volume" in call_args
        assert "60" in call_args

    @pytest.mark.asyncio
    async def test_invalid_start_time_negative(self, test_audio_file, mock_config, mock_subprocess):
        """Test that negative start_time raises ValueError."""
        player = SubprocessAudioPlayer()

        with pytest.raises(ValueError, match="start_time must be >= 0"):
            await player.play(test_audio_file, start_time=-5.0)

    @pytest.mark.asyncio
    async def test_invalid_duration_zero(self, test_audio_file, mock_config, mock_subprocess):
        """Test that zero duration raises ValueError."""
        player = SubprocessAudioPlayer()

        with pytest.raises(ValueError, match="duration must be > 0"):
            await player.play(test_audio_file, duration=0.0)

    @pytest.mark.asyncio
    async def test_invalid_duration_negative(self, test_audio_file, mock_config, mock_subprocess):
        """Test that negative duration raises ValueError."""
        player = SubprocessAudioPlayer()

        with pytest.raises(ValueError, match="duration must be > 0"):
            await player.play(test_audio_file, duration=-10.0)

    @pytest.mark.asyncio
    async def test_invalid_volume_negative(self, test_audio_file, mock_config, mock_subprocess):
        """Test that negative volume raises ValueError."""
        player = SubprocessAudioPlayer()

        with pytest.raises(ValueError, match="volume must be between 0 and 100"):
            await player.play(test_audio_file, volume=-10)

    @pytest.mark.asyncio
    async def test_invalid_volume_over_max(self, test_audio_file, mock_config, mock_subprocess):
        """Test that volume over 100 raises ValueError."""
        player = SubprocessAudioPlayer()

        with pytest.raises(ValueError, match="volume must be between 0 and 100"):
            await player.play(test_audio_file, volume=150)

    @pytest.mark.asyncio
    async def test_advanced_features_require_ffplay(self, test_audio_file):
        """Test that advanced features require ffplay backend."""
        # Create config with aplay instead of ffplay
        config = MagicMock()
        config.audio.playback_command = "aplay"

        player = SubprocessAudioPlayer(config=config)

        # Try to use segment extraction with aplay
        with pytest.raises(RuntimeError, match="require ffplay"):
            await player.play(test_audio_file, start_time=5.0)

            # Try to use volume control with aplay
            with pytest.raises(RuntimeError, match="require ffplay"):
                await player.play(test_audio_file, volume=75)
