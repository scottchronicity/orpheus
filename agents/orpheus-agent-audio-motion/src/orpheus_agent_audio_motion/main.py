"""Entrypoint for the Orpheus Audio Motion Detector agent."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from orpheus_common.diagnostics.audio_health import get_audio_health_monitor
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.mqtt import MQTTClient
from orpheus_common.storage import get_audio_path
from orpheus_common.storage.cleanup import CleanupPolicy, StorageCleanup

from .audio_source import AudioSource, create_audio_source
from .channel_processor import ChannelProcessor
from .clip_saver import ClipSaver
from .config import load_app_config
from .detector_algorithm import create_detector

logger = get_logger(__name__)


class AudioMotionDetector:
    """Coordinate audio capture, detection, and broker publication."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        log_level_override: Optional[str] = None,
    ) -> None:
        self._config = load_app_config(config_path)
        self._log_level_override = log_level_override
        self._mqtt_client: Optional[MQTTClient] = None
        self._audio_source: Optional[AudioSource] = None
        self._processors: dict[str, ChannelProcessor] = {}
        self._clip_saver: Optional[ClipSaver] = None
        self._stop_event = asyncio.Event()
        self._stream_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._location_lock = threading.Lock()
        self._location_cache: Optional[dict[str, Any]] = None

    async def start(self) -> None:
        """Start the agent and block until shutdown is requested."""

        log_level = self._log_level_override or self._config.logging.level
        setup_logging(
            "orpheus-agent-audio-motion",
            level=log_level,
            use_json=self._config.logging.use_json,
        )
        logger.info("Starting Audio Motion Detector agent")

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                logger.debug("Signal handler registration not supported on this platform")

        try:
            await self._initialize_dependencies()

            # Log retention policy on startup
            logger.info(
                "Storage retention policy",
                max_age_days=self._config.storage.retain_days,
                max_size_gb=getattr(self._config.storage, "max_size_gb", 50),
                strategy=getattr(self._config.storage, "cleanup_strategy", "oldest"),
                check_interval_hours=getattr(self._config.storage, "check_interval_hours", 1),
            )

            # Start cleanup task
            self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
            logger.debug("Cleanup task started")

            # Start health status publishing task
            self._health_task = asyncio.create_task(self._publish_health_status())
            logger.info("Health status publishing task started")

        except NotImplementedError as exc:
            logger.error("Audio source initialization failed", error=str(exc))
            await self.stop()
            raise
        except Exception:
            logger.exception("Failed to initialize agent dependencies")
            await self.stop()
            raise

        self._stream_task = asyncio.create_task(self._consume_frames())
        await self._stop_event.wait()
        logger.info("Shutdown signal received")
        await self.stop()

    async def stop(self) -> None:
        """Stop the agent gracefully."""

        if self._health_task:
            logger.info("Stopping health status publishing")
            self._health_task.cancel()
            try:
                await asyncio.wait_for(self._health_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if self._cleanup_task:
            logger.info("Stopping cleanup task")
            self._cleanup_task.cancel()
            try:
                await asyncio.wait_for(self._cleanup_task, timeout=5.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        if self._stream_task:
            self._stream_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._stream_task
            self._stream_task = None

        if self._audio_source and self._audio_source.is_running():
            await self._audio_source.stop()

        if self._mqtt_client and getattr(self._mqtt_client, "is_connected", False):
            self._mqtt_client.disconnect()

    async def _initialize_dependencies(self) -> None:
        """Construct shared dependencies and ensure connectivity."""

        logger.info("Initializing MQTT client")
        self._mqtt_client = MQTTClient(
            broker_host=self._config.mqtt.broker_host,
            broker_port=self._config.mqtt.broker_port,
            qos=self._config.mqtt.qos,
            keepalive=self._config.mqtt.keepalive,
            client_id="orpheus-orpheus-agent-audio-motion",
        )
        self._mqtt_client.connect()

        # Subscribe to GPS location updates for spatiotemporal context
        self._mqtt_client.subscribe(
            "orpheus/state/location",
            self._on_location_update,
        )
        logger.info("Subscribed to GPS location updates")

        logger.info("Initializing ClipSaver")
        self._clip_saver = ClipSaver(
            category=self._config.storage.category,
            write_format=self._config.storage.write_format,
            sample_rate=self._config.runtime.sample_rate,
        )

        logger.info("Creating audio source")
        self._audio_source = await create_audio_source(self._config.runtime)
        logger.info("Starting audio source", source_type=type(self._audio_source).__name__)
        await self._audio_source.start()
        logger.info("Audio source started successfully")

        # Load OrpheusConfig to get per-channel detection settings
        from orpheus_common.config import AudioDetectionConfig, OrpheusConfig

        orpheus_config = OrpheusConfig.get_instance()

        # Log effective runtime configuration for visibility
        active_channel_count = len([c for c in orpheus_config.audio.channels if c.enabled])
        logger.info(
            "Audio Agent startup configuration",
            sample_rate=orpheus_config.audio.sample_rate,
            device_name=getattr(orpheus_config.audio, "device_name", "default"),
            frame_duration_ms=self._config.runtime.frame_duration_ms,
            active_channels=active_channel_count,
        )

        assert self._clip_saver is not None

        logger.info("Configuring channel processors", num_channels=len(self._config.channels))
        for channel in self._config.channels:
            if not channel.enabled:
                logger.info("Skipping disabled channel", channel_id=channel.id)
                continue

            # Get THIS channel's detection config from orpheus_config
            channel_config = next(
                (c for c in orpheus_config.audio.channels if str(c.id) == channel.id), None
            )

            if not channel_config or not channel_config.detection:
                logger.warning(
                    "Channel missing detection config, using defaults", channel_id=channel.id
                )
                detection = AudioDetectionConfig()  # Use dataclass defaults
            else:
                detection = channel_config.detection

            # Build detector settings from channel's detection config
            detector_settings = {
                "threshold_db": detection.threshold_db,
                "margin_db": detection.margin_db,
                "release_threshold_db": detection.release_threshold_db,
                "holdoff_seconds": detection.holdoff_seconds,
                "min_duration_seconds": detection.min_duration_seconds,
                "max_duration_seconds": detection.max_duration_seconds,
                "prebuffer_seconds": detection.prebuffer_seconds,
                "sample_rate": self._config.runtime.sample_rate,
                "frame_duration_ms": self._config.runtime.frame_duration_ms,
            }

            # For adaptive threshold, add window settings
            if detection.algorithm == "adaptive_threshold":
                detector_settings["window_seconds"] = detection.window_seconds
                detector_settings["update_interval_seconds"] = detection.update_interval_seconds

            logger.info(
                "Configuring channel processor",
                channel_id=channel.id,
                channel_label=channel.label,
                algorithm=detection.algorithm,
                threshold_db=detection.threshold_db,
                margin_db=detection.margin_db,
                holdoff_seconds=detection.holdoff_seconds,
            )

            chunks_per_second = max(1, int(1000.0 / self._config.runtime.frame_duration_ms))
            processor = ChannelProcessor(
                channel_id=channel.id,
                detector=create_detector(detection.algorithm, detector_settings),
                mqtt_client=self._mqtt_client,
                clip_saver=self._clip_saver,
                topic_events=self._config.mqtt.topic_events,
                topic_status=self._config.mqtt.topic_status,
                qos=self._config.mqtt.qos,
                location_getter=self._get_location,
                prebuffer_seconds=detection.prebuffer_seconds,
                sample_rate=self._config.runtime.sample_rate,
                pre_roll_seconds=detection.pre_roll_seconds,
                chunks_per_second=chunks_per_second,
            )
            self._processors[channel.id] = processor

        logger.info(
            "Processors initialized",
            num_processors=len(self._processors),
            channel_ids=list(self._processors.keys()),
        )
        if not self._processors:
            raise RuntimeError("No enabled channels configured; at least one channel is required")

    def _on_location_update(self, _topic: str, payload: dict[str, Any]) -> None:
        """Handle GPS location update from orpheus/state/location."""
        with self._location_lock:
            self._location_cache = payload
        logger.debug(
            "Location cache updated",
            lat=payload.get("lat"),
            lon=payload.get("lon"),
        )

    def _get_location(self) -> Optional[dict[str, Any]]:
        """Return the last known GPS location (thread-safe)."""
        with self._location_lock:
            return self._location_cache

    async def _consume_frames(self) -> None:
        """Continuously consume frames from the audio source."""

        assert self._audio_source is not None
        frame_count = 0
        logger.info("Starting audio frame processing loop")
        try:
            async for frame in self._audio_source.stream_frames():
                frame_count += 1
                if frame_count == 1:
                    logger.info("First frame received", channel_id=frame.channel_id)
                if frame_count % 1000 == 0:
                    logger.debug("Processed frames", count=frame_count, channel_id=frame.channel_id)
                if self._stop_event.is_set():
                    break
                processor = self._processors.get(frame.channel_id)
                if not processor:
                    if frame_count <= 5:
                        logger.warning(
                            "No processor for channel",
                            channel_id=frame.channel_id,
                            available_channels=list(self._processors.keys()),
                        )
                    continue
                await processor.handle_frame(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Fatal error in processing loop", error=str(exc), exc_info=True)
            self._stop_event.set()
        finally:
            self._stop_event.set()

    async def _periodic_cleanup(self) -> None:
        """Periodically check and cleanup old audio files."""
        check_interval_hours = getattr(self._config.storage, "check_interval_hours", 1)
        check_interval_seconds = check_interval_hours * 3600

        logger.info(
            "Cleanup task started",
            check_interval_hours=check_interval_hours,
            retain_days=self._config.storage.retain_days,
        )

        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(check_interval_seconds)

                logger.info("Running storage cleanup check...")

                policy = CleanupPolicy(
                    max_size_gb=getattr(self._config.storage, "max_size_gb", 50.0),
                    max_age_days=self._config.storage.retain_days,
                    cleanup_strategy=getattr(self._config.storage, "cleanup_strategy", "oldest"),
                    cleanup_trigger_percent=getattr(
                        self._config.storage, "cleanup_trigger_percent", 90.0
                    ),
                    cleanup_amount_percent=getattr(
                        self._config.storage, "cleanup_amount_percent", 25.0
                    ),
                    min_file_age_hours=getattr(self._config.storage, "min_file_age_hours", 1.0),
                    file_pattern="*.flac",
                )

                storage_path = get_audio_path(category="audio_motion")
                cleanup = StorageCleanup(policy)
                result = cleanup.cleanup(storage_path, dry_run=False)

                if result.files_removed > 0:
                    logger.info(
                        "Cleanup completed",
                        files_removed=result.files_removed,
                        bytes_freed_mb=result.bytes_freed / (1024**2),
                        bytes_freed_gb=result.bytes_freed / (1024**3),
                    )
                    if result.manifest_path:
                        logger.info("Deletion manifest saved", manifest_path=result.manifest_path)
                else:
                    logger.info("Cleanup check complete: no action needed (usage below threshold)")

                if result.errors:
                    logger.warning(
                        "Cleanup encountered errors",
                        error_count=len(result.errors),
                        sample_errors=result.errors[:3],
                    )

            except asyncio.CancelledError:
                logger.info("Cleanup task cancelled, shutting down")
                break
            except Exception as e:
                logger.exception("Storage cleanup failed", error=str(e))
                logger.info("Will retry cleanup", retry_hours=check_interval_hours)

    async def _publish_health_status(self) -> None:
        """Periodically publish audio health status to MQTT."""
        publish_interval = 5.0  # Publish every 5 seconds

        logger.info("Health status publishing started", interval_seconds=publish_interval)

        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(publish_interval)

                # Get current health status from monitor
                health_monitor = get_audio_health_monitor()
                status = health_monitor.get_status()

                # Publish to MQTT
                if self._mqtt_client:
                    self._mqtt_client.publish(
                        "orpheus/system/audio/health",
                        status,
                        qos=0,  # Use QoS 0 for frequent status updates
                    )
                    logger.debug(
                        "Published health status",
                        running=status.get("running"),
                        num_channels=len(status.get("channels", [])),
                        xruns=status.get("xrun", {}).get("total", 0),
                    )
                else:
                    logger.warning("MQTT client not available, skipping health publish")

            except asyncio.CancelledError:
                logger.info("Health publishing cancelled, shutting down")
                break
            except Exception as e:
                logger.error("Failed to publish health status", error=str(e), exc_info=True)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Run the Orpheus Audio Motion Detector agent")
    parser.add_argument(
        "--config",
        type=Path,
        help=(
            "Path to orpheus.yaml configuration file "
            "(optional, uses OrpheusConfig singleton by default)"
        ),
    )
    parser.add_argument("--log-level", type=str, help="Override log level (DEBUG, INFO, ...)")
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> None:
    """Async wrapper for agent startup."""

    log_override = args.log_level.upper() if args.log_level else None
    detector = AudioMotionDetector(config_path=args.config, log_level_override=log_override)
    await detector.start()


def main(argv: Optional[list[str]] = None) -> int:
    """Synchronous entrypoint for shell execution."""

    args = parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except NotImplementedError as exc:
        logger.error("Agent missing implementation detail", error=str(exc))
        return 78
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unhandled exception", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
