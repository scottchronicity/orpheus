"""Main entrypoint for the Orpheus Audio Playback agent."""

import argparse
import asyncio
import contextlib
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional  # noqa: UP035

from orpheus_common import EventBus, create_event_bus
from orpheus_common.actor import (
    build_operational_health,
    health_on_bus_active,
    kv_publish_best_effort,
)
from orpheus_common.audio import MAX_VOLUME, get_audio_player, get_sound_registry
from orpheus_common.config import OrpheusConfig
from orpheus_common.detection import DetectionDB
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.storage import get_data_root

logger = get_logger(__name__)


class AudioPlaybackAgent:
    """Audio playback agent that responds to MQTT playback requests."""

    # MQTT Topics
    TOPIC_REQUEST = "orpheus/audio/playback/request"
    TOPIC_RESPONSE = "orpheus/audio/playback/response"
    TOPIC_HEALTH = "orpheus/audio/playback/health"
    # Playback-window event for corollary discharge: the event-correlator
    # subscribes to this and blanks self-generated detections that overlap our
    # own audio output (see [CORE] Implement Corollary Discharge).
    TOPIC_ACTUATION_AUDIO_PLAYBACK = "orpheus/actuation/audio/playback"

    def __init__(
        self,
        config_path: Optional[Path] = None,
        log_level_override: Optional[str] = None,
    ) -> None:
        """Initialize the audio playback agent.

        Args:
            config_path: Optional path to orpheus.yaml configuration
            log_level_override: Optional log level override
        """
        self._config = OrpheusConfig.get_instance()
        if config_path:
            self._config = OrpheusConfig.load(config_path=config_path)

        self._log_level_override = log_level_override
        self._mqtt_client: Optional[EventBus] = None
        self._stop_event = asyncio.Event()
        self._health_task: Optional[asyncio.Task] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

    async def start(self) -> None:
        """Start the agent and block until shutdown is requested."""
        # Setup logging
        log_level = self._log_level_override or self._config.logging.level
        setup_logging(
            "orpheus-agent-audio-playback",
            level=log_level,
            use_json=False,
        )
        logger.info("Starting Audio Playback agent")

        # Store event loop reference for thread-safe task scheduling
        self._event_loop = asyncio.get_running_loop()
        logger.debug("Event loop stored for MQTT callback scheduling")

        # Setup signal handlers
        loop = self._event_loop
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                logger.debug("Signal handler registration not supported on this platform")

        try:
            await self._initialize_dependencies()

            # Start health status publishing task
            logger.info("Starting health status publishing task")
            self._health_task = asyncio.create_task(self._publish_health_status())

            # Wait for shutdown signal
            logger.info("Audio Playback agent ready and listening for playback requests")
            await self._stop_event.wait()
            logger.info("Shutdown signal received")

        except Exception:
            logger.exception("Failed to initialize agent")
            raise
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        logger.info("Stopping Audio Playback agent")

        # Stop health task
        if self._health_task:
            logger.debug("Stopping health status publishing task")
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task

        # Stop audio playback
        try:
            player = get_audio_player()
            await player.stop(reason="agent_shutdown")
            logger.debug("Audio player stopped")
        except Exception as e:
            logger.warning("Error stopping audio player", error=str(e))

        # Disconnect MQTT
        if self._mqtt_client:
            self._mqtt_client.disconnect()
            logger.debug("MQTT client disconnected")

        logger.info("Audio Playback agent stopped")

    async def _initialize_dependencies(self) -> None:
        """Initialize MQTT client and sound registry."""
        # Initialize MQTT client
        logger.info(
            "Initializing MQTT client for broker",
            broker_host=self._config.mqtt.broker_host,
            broker_port=self._config.mqtt.broker_port,
        )
        self._mqtt_client = create_event_bus(
            self._config,
            client_id="orpheus-agent-audio-playback",
        )

        # Subscribe to playback requests
        self._mqtt_client.subscribe(self.TOPIC_REQUEST, self._handle_playback_request)
        logger.info("Subscribed to MQTT topic", topic=self.TOPIC_REQUEST)

        # Connect to broker
        self._mqtt_client.connect()
        logger.info(
            "Connected to event bus (backplane)",
            broker_host=self._config.mqtt.broker_host,
            broker_port=self._config.mqtt.broker_port,
        )

        # Initialize sound registry
        registry = get_sound_registry()
        sounds = registry.list_sounds()
        logger.info("Sound registry initialized", sound_count=len(sounds), sounds=sounds)

        # Log audio player configuration
        logger.info(
            "Audio playback configured",
            playback_command=self._config.audio.playback_command,
            platform="macOS" if sys.platform == "darwin" else sys.platform,
        )

        logger.info("Audio Playback agent initialization complete")

    def _handle_playback_request(self, _topic: str, payload: Any) -> None:
        """Handle incoming playback request.

        Supports two request formats:
        1. Legacy format: {"sound_name": "...", "repeat_count": 1, "pause_between": 0}
        2. New format: {"file_path": "..." or "detection_id": "...",
                        "repeat_count": 1, "pause_between": 0,
                        "start_time": 0, "duration": 5, "volume": 50}

        Args:
            _topic: MQTT topic (unused)
            payload: Message payload (dict)
        """
        logger.info("Received playback request", topic=_topic)
        logger.debug("Playback request payload", payload=payload)
        try:
            # Validate payload
            if not isinstance(payload, dict):
                logger.error(
                    "Invalid payload format (expected JSON object)",
                    payload_type=type(payload).__name__,
                )
                self._publish_error("Invalid payload format (expected JSON object)")
                return

            # Check if this is a legacy or new format request
            sound_name = payload.get("sound_name")
            file_path = payload.get("file_path")
            detection_id = payload.get("detection_id")

            if sound_name:
                # Legacy format - use existing handler
                self._handle_legacy_request(payload)
            elif file_path or detection_id:
                # New format - use new handler
                self._handle_audio_source_request(payload)
            else:
                logger.error(
                    "Missing audio source: must provide sound_name, file_path, or detection_id"
                )
                self._publish_error(
                    "Missing audio source: must provide sound_name, file_path, or detection_id"
                )

        except Exception as e:
            logger.exception("Error handling playback request", error=str(e))
            self._publish_error(f"Internal error: {e}")

    def _handle_legacy_request(self, payload: Dict[str, Any]) -> None:  # noqa: UP006
        """Handle legacy sound_name-based playback request.

        Args:
            payload: Request payload with sound_name
        """
        sound_name = payload.get("sound_name")
        if not sound_name:
            logger.error("Missing required field: sound_name")
            self._publish_error("Missing required field: sound_name")
            return

        repeat_count = payload.get("repeat_count", 1)
        pause_between = payload.get("pause_between", 0.0)

        # Validate parameters
        try:
            repeat_count = int(repeat_count)
            pause_between = float(pause_between)
        except (TypeError, ValueError) as e:
            logger.exception("Invalid parameter types")
            self._publish_error(f"Invalid parameter types: {e}")
            return

        if repeat_count < 1:
            logger.warning("Invalid repeat_count, must be >= 1", repeat_count=repeat_count)
            self._publish_error("repeat_count must be >= 1")
            return

        if pause_between < 0:
            logger.warning("Invalid pause_between; must be >= 0", pause_between=pause_between)
            self._publish_error("pause_between must be >= 0")
            return

        logger.info(
            "Processing playback request",
            sound_name=sound_name,
            repeat_count=repeat_count,
            pause_between=pause_between,
        )

        # Execute playback synchronously
        self._play_sound(sound_name, repeat_count, pause_between)

    def _play_sound(
        self,
        sound_name: str,
        repeat_count: int,
        pause_between: float,
    ) -> None:
        """Play a sound with given parameters.

        Args:
            sound_name: Name of sound to play
            repeat_count: Number of repeats
            pause_between: Pause duration between repeats
        """
        try:
            # Get sound file path
            registry = get_sound_registry()
            sound_path = registry.get_sound_path(sound_name)

            logger.info("Starting playback", sound_name=sound_name, path=str(sound_path))

            # Schedule playback as background task (don't block MQTT handler)
            # Use event loop reference since MQTT callbacks run in separate thread
            player = get_audio_player()
            if self._event_loop is None:
                error_msg = "Event loop not initialized - agent not started"
                logger.error(error_msg)
                self._publish_error(error_msg, sound_name=sound_name)
                return

            # Use call_soon_threadsafe to schedule task from MQTT thread
            asyncio.run_coroutine_threadsafe(
                self._play_sound_async(player, sound_path, repeat_count, pause_between, sound_name),
                self._event_loop,
            )
            logger.debug(
                "Playback task scheduled",
                sound_name=sound_name,
            )

            # Publish success response immediately (playback runs in background)
            self._publish_response(
                {
                    "status": "success",
                    "sound_name": sound_name,
                    "message": "Playback started",
                }
            )

        except KeyError:
            error_msg = f"Sound not found: {sound_name}"
            logger.warning(error_msg)
            self._publish_error(error_msg, sound_name=sound_name)

        except Exception as e:
            error_msg = f"Playback failed: {e}"
            logger.error(error_msg, exc_info=True)
            self._publish_error(error_msg, sound_name=sound_name)

    async def _play_sound_async(
        self,
        player: Any,
        sound_path: Path,
        repeat_count: int,
        pause_between: float,
        sound_name: str,
    ) -> None:
        """Async wrapper for sound playback.

        This runs as a background task and logs completion/errors.

        Args:
            player: Audio player instance
            sound_path: Path to sound file
            repeat_count: Number of repeats
            pause_between: Pause between repeats
            sound_name: Name of sound (for logging)
        """
        try:
            logger.debug(
                "Background playback task started",
                sound_name=sound_name,
                task_id=id(asyncio.current_task()),
            )
            playback_start = datetime.now(timezone.utc)
            await player.play(sound_path, repeat_count, pause_between)
            self._publish_playback_window(
                playback_start,
                (datetime.now(timezone.utc) - playback_start).total_seconds(),
                sound_name,
            )
            logger.info("Playback completed", sound_name=sound_name)
        except asyncio.CancelledError:
            logger.warning(
                "Playback task cancelled",
                sound_name=sound_name,
            )
            raise
        except Exception as e:
            logger.exception(
                "Playback error in background task",
                sound_name=sound_name,
                error=str(e),
            )

    def _publish_playback_window(
        self, start: datetime, duration_seconds: float, sound_name: str
    ) -> None:
        """Publish a playback-window event so the event-correlator can blank
        self-generated detections (corollary discharge).

        ``duration_seconds`` is the actual measured playback time (player.play
        blocks until done), so no clip-length lookup is needed. Best-effort: a
        publish failure must never affect playback.
        """
        if self._mqtt_client is None:
            return
        event = {
            "start_time": start.isoformat(),
            "duration_seconds": round(duration_seconds, 3),
            "source": "audio_playback_agent",
            "sound_name": sound_name,
        }
        try:
            self._mqtt_client.publish(self.TOPIC_ACTUATION_AUDIO_PLAYBACK, event, qos=1)
        except Exception:  # noqa: BLE001 - telemetry must not break playback
            logger.exception("Failed to publish playback-window event", sound_name=sound_name)

    def _handle_audio_source_request(
        self,
        payload: Dict[str, Any],  # noqa: UP006
    ) -> None:
        """Handle new audio source-based playback request.

        Args:
            payload: Request payload with file_path or detection_id
        """
        # Extract audio source
        file_path = payload.get("file_path")
        detection_id = payload.get("detection_id")

        if not file_path and not detection_id:
            self._publish_error("Must provide file_path or detection_id")
            return

        # Extract common parameters
        repeat_count = payload.get("repeat_count", 1)
        pause_between = payload.get("pause_between", 0.0)
        start_time = payload.get("start_time")
        duration = payload.get("duration")
        volume = payload.get("volume")

        # Validate and convert parameter types
        try:
            repeat_count = int(repeat_count)
            pause_between = float(pause_between)
            if start_time is not None:
                start_time = float(start_time)
            if duration is not None:
                duration = float(duration)
            if volume is not None:
                volume = int(volume)
        except (TypeError, ValueError) as e:
            logger.exception("Invalid parameter types")
            self._publish_error(f"Invalid parameter types: {e}")
            return

        # Validate parameter ranges
        validation_errors = []
        if repeat_count < 1:
            validation_errors.append("repeat_count must be >= 1")
        if pause_between < 0:
            validation_errors.append("pause_between must be >= 0")
        if start_time is not None and start_time < 0:
            validation_errors.append("start_time must be >= 0")
        if duration is not None and duration <= 0:
            validation_errors.append("duration must be > 0")
        if volume is not None and (volume < 0 or volume > MAX_VOLUME):
            validation_errors.append(f"volume must be between 0 and {MAX_VOLUME}")

        if validation_errors:
            self._publish_error("; ".join(validation_errors))
            return

        logger.info(
            "Processing audio source request",
            file_path=file_path,
            detection_id=detection_id,
            repeat_count=repeat_count,
            pause_between=pause_between,
            start_time=start_time,
            duration=duration,
            volume=volume,
        )

        # Execute playback synchronously
        self._play_audio_source(
            file_path,
            detection_id,
            repeat_count,
            pause_between,
            start_time,
            duration,
            volume,
        )

    def _play_audio_source(
        self,
        file_path: Optional[str],
        detection_id: Optional[str],
        repeat_count: int,
        pause_between: float,
        start_time: Optional[float],
        duration: Optional[float],
        volume: Optional[int],
    ) -> None:
        """Play audio from file path or detection ID.

        Args:
            file_path: Optional file path to audio
            detection_id: Optional detection ID to lookup
            repeat_count: Number of repeats
            pause_between: Pause duration between repeats
            start_time: Optional start time for segment extraction
            duration: Optional duration for segment extraction
            volume: Optional volume level (0-100)
        """
        try:
            # Resolve audio path
            audio_path = self._resolve_audio_path(file_path, detection_id)

            logger.info("Starting playback", path=str(audio_path))

            # Play the audio synchronously using asyncio.run
            player = get_audio_player()
            playback_start = datetime.now(timezone.utc)
            asyncio.run(
                player.play(
                    audio_path,
                    repeat_count,
                    pause_between,
                    start_time=start_time,
                    duration=duration,
                    volume=volume,
                )
            )
            self._publish_playback_window(
                playback_start,
                (datetime.now(timezone.utc) - playback_start).total_seconds(),
                str(file_path or detection_id or ""),
            )

            # Publish success response
            response = {
                "status": "success",
                "message": "Playback started",
            }
            if file_path:
                response["file_path"] = file_path
            if detection_id:
                response["detection_id"] = detection_id

            self._publish_response(response)

            logger.info("Playback completed", path=str(audio_path))

        except FileNotFoundError as e:
            error_msg = f"Audio file not found: {e}"
            logger.warning(error_msg)
            self._publish_error(error_msg)

        except ValueError as e:
            error_msg = f"Invalid request: {e}"
            logger.warning(error_msg)
            self._publish_error(error_msg)

        except Exception as e:
            error_msg = f"Playback failed: {e}"
            logger.error(error_msg, exc_info=True)
            self._publish_error(error_msg)

    def _resolve_audio_path(
        self,
        file_path: Optional[str],
        detection_id: Optional[str],
    ) -> Path:
        """Resolve audio path from file_path or detection_id.

        Args:
            file_path: Optional file path (absolute or relative)
            detection_id: Optional detection ID to lookup

        Returns:
            Path to audio file

        Raises:
            ValueError: If both or neither are provided
            FileNotFoundError: If file doesn't exist or detection not found
        """
        if file_path and detection_id:
            raise ValueError("Cannot specify both file_path and detection_id")

        if not file_path and not detection_id:
            raise ValueError("Must specify either file_path or detection_id")

        if file_path:
            # Handle file path
            path = Path(file_path)

            # If relative path, resolve relative to data root
            if not path.is_absolute():
                data_root = get_data_root()
                path = data_root / path
                # Validate resolved path doesn't escape data root via ../ traversal
                try:
                    path_resolved = path.resolve()
                    data_root_resolved = data_root.resolve()
                    if not str(path_resolved).startswith(str(data_root_resolved)):
                        raise ValueError(
                            f"Path traversal detected: {file_path} resolves outside data root"
                        )
                except (OSError, RuntimeError) as e:
                    raise ValueError(f"Invalid file path: {e}") from e

            if not path.exists():
                raise FileNotFoundError(f"Audio file not found: {path}")

            return path

        # Handle detection ID
        if detection_id:
            db = DetectionDB()
            detection = db.get_by_event_id(detection_id)

            if not detection:
                raise FileNotFoundError(f"Detection not found: {detection_id}")

            if not detection.audio_clip_path:
                raise ValueError(f"Detection {detection_id} has no audio clip")

            audio_path = Path(detection.audio_clip_path)

            if not audio_path.exists():
                raise FileNotFoundError(
                    f"Audio file for detection {detection_id} not found: {audio_path}"
                )

            return audio_path

        # This should never be reached due to validation above
        raise ValueError("Internal error: unable to resolve audio path")

    def _publish_response(self, response: Dict[str, Any]) -> None:  # noqa: UP006
        """Publish response message.

        Args:
            response: Response payload
        """
        if self._mqtt_client:
            self._mqtt_client.publish(self.TOPIC_RESPONSE, response, qos=1)

    def _publish_error(
        self,
        error_message: str,
        sound_name: Optional[str] = None,
    ) -> None:
        """Publish error response.

        Args:
            error_message: Error description
            sound_name: Optional sound name for context
        """
        response = {
            "status": "error",
            "error": error_message,
        }
        if sound_name:
            response["sound_name"] = sound_name

        self._publish_response(response)

    async def _publish_health_status(self) -> None:
        """Periodically publish health status to MQTT."""
        publish_interval = 10.0  # Publish every 10 seconds
        # §11 Phase 1b: dual-write health to the operational KV plane (key
        # "audio-playback") IN ADDITION to the bus publish, when health_kv_enabled +
        # KV backend. None ⇒ no-op (default; bus publish unchanged). self._config is
        # the OrpheusConfig singleton (has event_bus). Built once.
        op_health = build_operational_health(self._mqtt_client, self._config)
        # §11 Phase 5a: the ONE shared gate (anti-skew warning included).
        publish_health_to_bus = health_on_bus_active(
            self._config, op_health, agent="audio-playback"
        )

        logger.info("Health status publishing started", interval=publish_interval)

        while not self._stop_event.is_set():
            try:
                # Wait for interval or until stop event is set
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=publish_interval)
                    # Stop event was set, exit loop
                    break
                except asyncio.TimeoutError:
                    # Timeout means we should publish (stop event not set)
                    pass

                # Get current status
                player = get_audio_player()
                registry = get_sound_registry()

                status = {
                    "status": "healthy",
                    "is_playing": player.is_playing(),
                    "available_sounds": registry.list_sounds(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

                if self._mqtt_client and publish_health_to_bus:
                    self._mqtt_client.publish(self.TOPIC_HEALTH, status, qos=0)
                # §11 Phase 1b: dual-write to the operational KV plane (independent of
                # the bus gate above), best-effort.
                kv_publish_best_effort(op_health, "audio-playback", status)

            except asyncio.CancelledError:
                logger.info("Health publishing cancelled, shutting down")
                break
            except Exception as e:
                logger.exception("Failed to publish health status", error=str(e))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Optional argument list

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(description="Run the Orpheus Audio Playback agent")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to orpheus.yaml configuration file",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        help="Override log level (DEBUG, INFO, WARNING, ERROR)",
    )
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> None:
    """Async wrapper for agent startup.

    Args:
        args: Parsed command-line arguments
    """
    log_override = args.log_level.upper() if args.log_level else None
    agent = AudioPlaybackAgent(
        config_path=args.config,
        log_level_override=log_override,
    )
    await agent.start()


def main(argv: Optional[list[str]] = None) -> int:
    """Synchronous entrypoint for shell execution.

    Args:
        argv: Optional argument list

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    args = parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unhandled exception")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
