"""Audio playback abstraction for Orpheus platform.

Provides a flexible interface for playing audio files with support for
different playback backends (subprocess-based players, audio libraries, etc.).
"""

import asyncio
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# Audio playback constants
MAX_VOLUME = 100  # Maximum volume level for audio playback (0-100)


class AudioPlayer(ABC):
    """Abstract base class for audio playback.

    Implementations must support:
    - Playing audio files
    - Repeating playback with pauses
    - Stopping playback
    - Querying playback status
    """

    @abstractmethod
    async def play(
        self,
        audio_file: Path,
        repeat_count: int = 1,
        pause_between: float = 0.0,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
        volume: Optional[int] = None,
    ) -> None:
        """Play an audio file.

        Args:
            audio_file: Path to the audio file to play
            repeat_count: Number of times to play the file (default: 1)
            pause_between: Seconds to pause between repeats (default: 0.0)
            start_time: Optional start time in seconds for segment extraction
            duration: Optional duration in seconds for segment extraction
            volume: Optional volume level (0-100)

        Raises:
            FileNotFoundError: If audio_file does not exist
            RuntimeError: If playback fails
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop any currently playing audio."""
        pass

    @abstractmethod
    def is_playing(self) -> bool:
        """Check if audio is currently playing.

        Returns:
            True if audio is playing, False otherwise
        """
        pass


class SubprocessAudioPlayer(AudioPlayer):
    """Audio player implementation using subprocess and external audio tools.

    Uses the playback command specified in OrpheusConfig.audio.playback_command.
    Supports: aplay (ALSA), ffplay (ffmpeg), paplay (PulseAudio), afplay (macOS).
    """

    # Player-specific default arguments
    _PLAYER_ARGS = {
        "ffplay": ["-nodisp", "-autoexit", "-loglevel", "error"],
        "aplay": ["-q"],
        "paplay": [],
        "afplay": [],
    }

    def __init__(self, config: Optional[OrpheusConfig] = None) -> None:
        """Initialize the subprocess audio player.

        Args:
            config: Optional OrpheusConfig instance. If None, uses singleton.

        Raises:
            RuntimeError: If player command is not configured
        """
        self._process: Optional[subprocess.Popen] = None
        self._current_task: Optional[asyncio.Task] = None

        if config is None:
            config = OrpheusConfig.get_instance()

        self._player_cmd = config.audio.playback_command
        if not self._player_cmd:
            raise RuntimeError(
                "No playback command configured. Set audio.playback_command in config."
            )

        # Get default args for this player (if known)
        self._player_args = self._PLAYER_ARGS.get(self._player_cmd, [])

        logger.info(
            "Initialized audio player",
            player_cmd=self._player_cmd,
            player_args=self._player_args,
        )

    async def play(
        self,
        audio_file: Path,
        repeat_count: int = 1,
        pause_between: float = 0.0,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
        volume: Optional[int] = None,
    ) -> None:
        """Play an audio file using subprocess.

        Args:
            audio_file: Path to the audio file to play
            repeat_count: Number of times to play the file (default: 1)
            pause_between: Seconds to pause between repeats (default: 0.0)
            start_time: Optional start time in seconds for segment extraction
            duration: Optional duration in seconds for segment extraction
            volume: Optional volume level (0-100), only supported with ffplay

        Raises:
            FileNotFoundError: If audio_file does not exist
            RuntimeError: If playback fails
            ValueError: If parameters are invalid
        """
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        if repeat_count < 1:
            raise ValueError(f"repeat_count must be >= 1, got {repeat_count}")

        if pause_between < 0:
            raise ValueError(f"pause_between must be >= 0, got {pause_between}")

        if start_time is not None and start_time < 0:
            raise ValueError(f"start_time must be >= 0, got {start_time}")

        if duration is not None and duration <= 0:
            raise ValueError(f"duration must be > 0, got {duration}")

        if volume is not None and (volume < 0 or volume > MAX_VOLUME):
            raise ValueError(f"volume must be between 0 and {MAX_VOLUME}, got {volume}")

        # Validate segment/volume features with player
        if start_time is not None or duration is not None or volume is not None:
            if self._player_cmd != "ffplay":
                raise RuntimeError(
                    f"Segment extraction and volume control require ffplay, "
                    f"but using {self._player_cmd}"
                )

        # Stop any current playback
        await self.stop()

        # Build extra arguments for ffplay
        extra_args: list[str] = []
        if self._player_cmd == "ffplay":
            if start_time is not None:
                extra_args.extend(["-ss", str(start_time)])
            if duration is not None:
                extra_args.extend(["-t", str(duration)])
            if volume is not None:
                # ffplay volume is 0-100, map directly
                extra_args.extend(["-volume", str(volume)])

            # Always assert a volume for headless playback. Default to 100.
            actual_volume = volume if volume is not None else 100
            extra_args.extend(["-volume", str(actual_volume)])

        # Start new playback task
        self._current_task = asyncio.create_task(
            self._play_with_repeats(audio_file, repeat_count, pause_between, extra_args)
        )

        logger.info(
            "Started playback",
            audio_file=audio_file.name,
            repeat_count=repeat_count,
            pause_between_s=pause_between,
            start_time=start_time,
            duration=duration,
            volume=volume,
        )

    async def _play_with_repeats(
        self,
        audio_file: Path,
        repeat_count: int,
        pause_between: float,
        extra_args: Optional[list[str]] = None,
    ) -> None:
        """Internal method to handle repeated playback.

        Args:
            audio_file: Path to audio file
            repeat_count: Number of repeats
            pause_between: Pause duration between repeats
            extra_args: Optional extra arguments for the player
        """
        if extra_args is None:
            extra_args = []

        try:
            for i in range(repeat_count):
                if i > 0 and pause_between > 0:
                    logger.debug("Pausing between repeats", pause_between_s=pause_between)
                    await asyncio.sleep(pause_between)

                logger.debug(
                    "Playing iteration",
                    iteration=i + 1,
                    total=repeat_count,
                    file=audio_file.name,
                )

                if extra_args:
                    await self._play_once_with_args(audio_file, extra_args)
                else:
                    await self._play_once(audio_file)

            logger.info(
                "Playback sequence completed",
                file=audio_file.name,
                repeat_count=repeat_count,
            )

        except asyncio.CancelledError:
            logger.warning(
                "Playback cancelled by stop() call",
                file=audio_file.name,
                completed_iterations=i if "i" in locals() else 0,
            )
            raise
        except Exception as e:
            logger.exception(
                "Playback error",
                error=str(e),
                error_type=type(e).__name__,
                file=audio_file.name,
            )
            raise
        finally:
            self._current_task = None

    async def _play_once(self, audio_file: Path) -> None:
        """Play audio file once using subprocess."""
        await self._play_once_with_args(audio_file, [])

    async def _play_once_with_args(
        self,
        audio_file: Path,
        extra_args: list[str],
    ) -> None:
        """Play audio file once with additional command-line arguments.

        Args:
            audio_file: Path to audio file
            extra_args: Additional arguments to pass to the player (e.g., for seeking, volume)

        Raises:
            RuntimeError: If playback fails
        """
        assert self._player_cmd is not None
        assert self._player_args is not None

        cmd = [self._player_cmd] + self._player_args + extra_args + [str(audio_file)]

        logger.info(
            "Executing audio playback command",
            player=self._player_cmd,
            command=" ".join(cmd),
            file=audio_file.name,
        )

        try:
            # Run player process
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for completion
            stdout, stderr = await self._process.communicate()

            if self._process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace").strip()
                stdout_msg = stdout.decode("utf-8", errors="replace").strip()
                logger.error(
                    "Audio player failed",
                    player_cmd=self._player_cmd,
                    return_code=self._process.returncode,
                    stderr=error_msg or "(empty)",
                    stdout=stdout_msg or "(empty)",
                    file=str(audio_file),
                )
                raise RuntimeError(
                    f"Audio player '{self._player_cmd}' failed with code "
                    f"{self._process.returncode}: {error_msg or '(no error message)'}"
                )
            else:
                logger.info(
                    "Audio playback completed successfully",
                    player=self._player_cmd,
                    file=audio_file.name,
                    return_code=self._process.returncode,
                )

        finally:
            self._process = None

    async def stop(self, reason: str = "user_requested") -> None:
        """Stop any currently playing audio.

        Args:
            reason: Reason for stopping (for logging/debugging)
        """
        if not self.is_playing() and self._process is None:
            logger.debug("Stop called but nothing is playing", reason=reason)
            return

        logger.info("Stopping audio playback", reason=reason, was_playing=self.is_playing())

        # Cancel ongoing task
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()
            try:
                await self._current_task
            except asyncio.CancelledError:
                # Task cancellation is expected here; ignore the exception.
                pass

        # Terminate subprocess if running
        if self._process and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.warning("Error stopping playback", error=str(e))

    def is_playing(self) -> bool:
        """Check if audio is currently playing.

        Returns:
            True if audio is playing, False otherwise
        """
        return self._current_task is not None and not self._current_task.done()


# Global instance (lazy-initialized)
_audio_player: Optional[AudioPlayer] = None


def get_audio_player(config: Optional[OrpheusConfig] = None) -> AudioPlayer:
    """Get the global audio player instance.

    Args:
        config: Optional OrpheusConfig instance. If None, uses singleton.

    Returns:
        AudioPlayer: The global audio player instance

    Raises:
        RuntimeError: If no audio player could be initialized
    """
    global _audio_player

    if _audio_player is None:
        _audio_player = SubprocessAudioPlayer(config=config)

    return _audio_player
