"""Entrypoint for the Orpheus Video Motion Detector agent."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import signal
import sys
from pathlib import Path
from typing import Optional

from orpheus_common import EventBus, create_event_bus
from orpheus_common.actor import (
    build_operational_health,
    health_on_bus_active,
    kv_publish_best_effort,
)
from orpheus_common.diagnostics.video_health import get_video_health_monitor
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.storage import get_video_path
from orpheus_common.video.source import RTSPVideoSource, VideoSource

from .camera_processor import CameraProcessor
from .clip_saver import ClipSaver
from .config import load_app_config
from .detector_algorithm import create_detector

logger = get_logger(__name__)


class VideoMotionDetector:
    """Coordinate video capture, detection, and broker publication."""

    # Exponential backoff parameters for RTSP reconnection
    _RECONNECT_INITIAL_DELAY = 5.0  # seconds
    _RECONNECT_MAX_DELAY = 3600.0  # 1 hour cap, then reset

    def __init__(
        self,
        config_path: Optional[Path] = None,
        log_level_override: Optional[str] = None,
    ) -> None:
        self._config = load_app_config(config_path)
        self._log_level_override = log_level_override
        self._mqtt_client: Optional[EventBus] = None
        self._video_sources: dict[str, VideoSource] = {}
        self._processors: dict[str, CameraProcessor] = {}
        self._clip_saver: Optional[ClipSaver] = None
        self._stop_event = asyncio.Event()
        self._stream_tasks: list[asyncio.Task] = []
        self._reconnect_tasks: list[asyncio.Task] = []
        self._reconnecting: set[str] = set()  # cameras with active reconnect task
        self._health_task: Optional[asyncio.Task] = None
        # Per-camera config lookup for reconnection
        self._camera_configs: dict[str, object] = {}

    async def start(self) -> None:
        """Start the agent and block until shutdown is requested."""

        log_level = self._log_level_override or self._config.logging.level
        setup_logging(
            "orpheus-agent-video-motion",
            level=log_level,
            use_json=self._config.logging.use_json,
        )
        logger.info("Starting Video Motion Detector agent")
        logger.info("Logging configured", log_level=log_level)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._stop_event.set)
            except NotImplementedError:
                logger.debug("Signal handler registration not supported on this platform")
        logger.info("Signal handlers registered")

        try:
            logger.info("Initializing dependencies...")
            await self._initialize_dependencies()
            logger.info("Dependencies initialized successfully")

            # This agent records; it does not delete. orpheus-storage-sweep
            # owns every deletion under the data root, so that one component
            # can weigh categories against each other and against the shared
            # disk — neither of which an agent trimming its own directory can
            # see. See docs/designs/storage-retention.md.
            logger.info(
                "Storage retention is enforced by orpheus-storage-sweep "
                "(storage.retain_days is no longer applied here; set "
                "storage.retention.categories.video_motion instead)",
                clip_directory=str(get_video_path(category="video_motion")),
                retain_days=self._config.storage.retain_days,
            )

            # Start health status publishing task
            logger.info("Starting health status publishing task...")
            self._health_task = asyncio.create_task(self._publish_health_status())
            logger.debug("Health task created", task=self._health_task)

        except Exception:
            logger.exception("Failed to initialize agent dependencies")
            await self.stop()
            raise

        # Start stream tasks for all cameras
        logger.info("Starting stream tasks", camera_count=len(self._video_sources))
        for camera_id, video_source in self._video_sources.items():
            logger.debug("Creating stream task", camera_id=camera_id)
            task = asyncio.create_task(self._consume_frames(camera_id, video_source))
            self._stream_tasks.append(task)
        logger.info("All stream tasks started, agent ready for motion detection")

        await self._stop_event.wait()
        logger.info("Shutdown signal received")
        await self.stop()

    async def stop(self) -> None:
        """Stop the agent gracefully."""
        logger.info("Stopping Video Motion Detector agent")

        if self._health_task:
            logger.debug("Stopping health status publishing")
            self._health_task.cancel()
            try:
                await asyncio.wait_for(self._health_task, timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                # Suppress expected exceptions when cancelling the health task during shutdown
                pass

        # Cancel reconnect tasks
        logger.debug("Stopping reconnect tasks", task_count=len(self._reconnect_tasks))
        for task in self._reconnect_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._reconnect_tasks = []

        # Cancel all stream tasks
        logger.debug("Stopping stream tasks", task_count=len(self._stream_tasks))
        for task in self._stream_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._stream_tasks = []

        # Stop all video sources
        logger.debug("Stopping video sources", source_count=len(self._video_sources))
        for video_source in self._video_sources.values():
            if video_source.is_running():
                await video_source.stop()

        if self._mqtt_client and getattr(self._mqtt_client, "is_connected", False):
            self._mqtt_client.disconnect()
            logger.debug("MQTT client disconnected")

        logger.info("Video Motion Detector agent stopped")

    async def _initialize_dependencies(self) -> None:
        """Construct shared dependencies and ensure connectivity."""

        # The OrpheusConfig singleton carries the operator's event_bus.* section
        # (backend, nats_url, connect_required, …). The agent-local AppConfig has
        # NO event_bus attribute, so handing it to the factory silently fell back
        # to the nats defaults — every event_bus knob in orpheus.yaml was dead.
        from orpheus_common.config import OrpheusConfig  # noqa: PLC0415

        orpheus_cfg = OrpheusConfig.get_instance()

        logger.info(
            "Creating MQTT client for broker %s:%d",
            self._config.mqtt.broker_host,
            self._config.mqtt.broker_port,
        )
        self._mqtt_client = create_event_bus(
            orpheus_cfg,
            client_id="orpheus-agent-video-motion",
            qos=self._config.mqtt.qos,
        )
        logger.debug(
            "Connecting to MQTT at %s:%d",
            self._config.mqtt.broker_host,
            self._config.mqtt.broker_port,
        )
        self._mqtt_client.connect()
        logger.info("MQTT connected successfully")

        logger.debug("Creating ClipSaver")
        self._clip_saver = ClipSaver(
            category=self._config.storage.category,
            write_format=self._config.storage.write_format,
            fps=self._config.runtime.fps,
            width=self._config.runtime.width,
            height=self._config.runtime.height,
        )
        logger.debug("ClipSaver created successfully")

        assert self._clip_saver is not None

        # Get detection settings from OrpheusConfig (loaded above)
        video_detection = (
            orpheus_cfg.video.motion_detection.detection
            if orpheus_cfg.video.motion_detection
            else None
        )

        # Register processors for each enabled camera (does not require connectivity)
        enabled_cameras = [c for c in self._config.cameras if c.enabled and c.rtsp_url]
        if not enabled_cameras:
            raise RuntimeError(
                "No enabled cameras with RTSP URLs in config; check cameras section in orpheus.yaml"
            )

        logger.info("Registering processors", camera_count=len(enabled_cameras))
        for camera in enabled_cameras:
            self._camera_configs[camera.id] = camera
            try:
                detector_settings = {
                    "motion_threshold": video_detection.motion_threshold
                    if video_detection
                    else 25.0,
                    "release_threshold": video_detection.release_threshold
                    if video_detection
                    else 12.5,
                    "holdoff_seconds": video_detection.holdoff_seconds if video_detection else 2.0,
                    "min_duration_seconds": video_detection.min_duration_seconds
                    if video_detection
                    else 0.5,
                    "max_duration_seconds": video_detection.max_duration_seconds
                    if video_detection
                    else 30.0,
                    "prebuffer_seconds": video_detection.prebuffer_seconds
                    if video_detection
                    else 1.0,
                    "fps": self._config.runtime.fps,
                }

                logger.info(
                    "Camera %s: configured with background_subtraction detector "
                    "(threshold=%.1f%%, release=%.1f%%, holdoff=%.1fs)",
                    camera.id,
                    detector_settings["motion_threshold"],
                    detector_settings["release_threshold"],
                    detector_settings["holdoff_seconds"],
                )

                health_monitor = get_video_health_monitor()
                health_monitor.set_camera_thresholds(
                    camera.id,
                    detector_settings["motion_threshold"],
                    detector_settings["release_threshold"],
                )

                processor = CameraProcessor(
                    camera_id=camera.id,
                    detector=create_detector("background_subtraction", detector_settings),
                    mqtt_client=self._mqtt_client,
                    clip_saver=self._clip_saver,
                    topic_events=self._config.mqtt.topic_events,
                    topic_status=self._config.mqtt.topic_status,
                    qos=self._config.mqtt.qos,
                    pre_roll_seconds=video_detection.pre_roll_seconds if video_detection else 3,
                    fps=self._config.runtime.fps,
                )
                self._processors[camera.id] = processor
                logger.info("Processor registered", camera_id=camera.id)
            except Exception as e:
                logger.exception("Failed to register processor", camera_id=camera.id, error=str(e))

        # Now try to connect RTSP streams (cameras may be offline)
        logger.info("Connecting to camera RTSP streams...")
        connected = 0
        for camera in enabled_cameras:
            if camera.id not in self._processors:
                continue  # processor registration failed
            try:
                await self._connect_camera(camera.id, camera.rtsp_url)
                connected += 1
            except Exception as e:
                logger.warning(
                    "Camera offline or unreachable — will retry with backoff",
                    camera_id=camera.id,
                    error=str(e),
                )
                self._schedule_reconnect(camera.id)

        # Configure health monitor with hardware settings
        health_monitor = get_video_health_monitor()
        health_monitor.set_hardware_config(
            fps=self._config.runtime.fps,
            width=self._config.runtime.width,
            height=self._config.runtime.height,
            num_cameras=len(self._processors),
        )
        health_monitor.set_running(True)

        logger.info(
            "Initialization complete",
            processors=len(self._processors),
            connected=connected,
            total_configured=len(enabled_cameras),
        )
        if connected == 0:
            logger.warning(
                "No cameras reachable — agent is running but idle. "
                "Check camera credentials/network and restart the agent."
            )

    async def _connect_camera(self, camera_id: str, rtsp_url: str) -> None:
        """Create and start an RTSP video source for a camera."""
        video_source = RTSPVideoSource(
            camera_id=camera_id,
            rtsp_url=rtsp_url,
            fps=self._config.runtime.fps,
            width=self._config.runtime.width,
            height=self._config.runtime.height,
            max_pending_frames=self._config.runtime.max_pending_frames,
        )
        await video_source.start()
        self._video_sources[camera_id] = video_source
        logger.info("RTSP connected", camera_id=camera_id)

    def _schedule_reconnect(self, camera_id: str) -> None:
        """Launch a reconnect task for a camera if one isn't already running."""
        if self._stop_event.is_set():
            return
        if camera_id in self._reconnecting:
            logger.debug("Reconnect already in progress, skipping", camera_id=camera_id)
            return
        task = asyncio.create_task(self._reconnect_camera(camera_id))
        self._reconnect_tasks.append(task)

    async def _reconnect_camera(self, camera_id: str) -> None:
        """Retry RTSP connection with exponential backoff up to 1 hour, then reset."""
        if camera_id in self._reconnecting:
            return  # another task beat us
        self._reconnecting.add(camera_id)

        delay = self._RECONNECT_INITIAL_DELAY
        camera = self._camera_configs.get(camera_id)
        if not camera:
            logger.error("No config for camera, cannot reconnect", camera_id=camera_id)
            self._reconnecting.discard(camera_id)
            return

        try:
            while not self._stop_event.is_set():
                logger.info(
                    "Reconnecting in %.0fs",
                    delay,
                    camera_id=camera_id,
                )
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
                    # stop_event was set — agent is shutting down
                    return
                except asyncio.TimeoutError:
                    pass  # timeout expired, time to retry

                try:
                    await self._connect_camera(camera_id, camera.rtsp_url)
                    # Success — start consuming frames
                    task = asyncio.create_task(
                        self._consume_frames(camera_id, self._video_sources[camera_id])
                    )
                    self._stream_tasks.append(task)
                    logger.info("Reconnected successfully", camera_id=camera_id)
                    return
                except Exception as e:
                    next_delay = min(delay * 2, self._RECONNECT_MAX_DELAY)
                    logger.warning(
                        "Reconnect failed",
                        camera_id=camera_id,
                        error=str(e),
                        next_retry_seconds=next_delay,
                    )
                    delay = next_delay
                    if delay >= self._RECONNECT_MAX_DELAY:
                        # Hit the cap — reset to initial so we cycle again
                        delay = self._RECONNECT_INITIAL_DELAY
                        logger.info(
                            "Backoff reached max (1h), resetting to %.0fs",
                            delay,
                            camera_id=camera_id,
                        )
        finally:
            self._reconnecting.discard(camera_id)

    async def _consume_frames(self, camera_id: str, video_source: VideoSource) -> None:
        """Continuously consume frames from a video source."""

        frame_count = 0
        logger.info("Starting frame consumption", camera_id=camera_id)
        try:
            async for frame in video_source.stream_frames():
                frame_count += 1
                if frame_count == 1:
                    logger.info("First frame received", camera_id=camera_id)
                if frame_count % 300 == 0:  # Log every 300 frames (~10s at 30fps)
                    logger.debug("Processed frames", frame_count=frame_count, camera_id=camera_id)

                if self._stop_event.is_set():
                    break

                processor = self._processors.get(frame.camera_id)
                if not processor:
                    if frame_count <= 5:
                        logger.warning(
                            "No processor registered for camera '%s'. Available: %s",
                            frame.camera_id,
                            list(self._processors.keys()),
                        )
                    continue

                await processor.handle_frame(frame)
        except asyncio.CancelledError:
            logger.info("Frame consumption cancelled", camera_id=camera_id)
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Fatal error in processing loop", camera_id=camera_id, error=str(exc))
        finally:
            logger.warning("Stream ended for camera", camera_id=camera_id)
            self._schedule_reconnect(camera_id)

    async def _publish_health_status(self) -> None:
        """Periodically publish video health status to MQTT."""
        publish_interval = 5.0  # Publish every 5 seconds
        # §11 Phase 1b: dual-write health to the operational KV plane (key "video")
        # IN ADDITION to the bus publish, when health_kv_enabled + KV backend. None ⇒
        # no-op (default; the bus publish is unchanged). Built once. The gate reads
        # event_bus from the OrpheusConfig singleton (self._config is the narrower
        # video AppConfig, which has no event_bus section).
        from orpheus_common.config import OrpheusConfig  # noqa: PLC0415

        orpheus_config = OrpheusConfig.get_instance()
        op_health = build_operational_health(self._mqtt_client, orpheus_config)
        # §11 Phase 5a: the ONE shared gate (anti-skew warning included).
        publish_health_to_bus = health_on_bus_active(orpheus_config, op_health, agent="video")

        logger.info("Health status publishing started", interval=publish_interval)

        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(publish_interval)

                # Get current health status from monitor
                health_monitor = get_video_health_monitor()
                status = health_monitor.get_status()

                if self._mqtt_client and publish_health_to_bus:
                    self._mqtt_client.publish(
                        "orpheus/system/video/health",
                        status,
                        qos=0,  # Use QoS 0 for frequent status updates
                    )
                # §11 Phase 1b: dual-write to the operational KV plane (independent of
                # the bus gate above), best-effort.
                kv_publish_best_effort(op_health, "video", status)

            except asyncio.CancelledError:
                logger.info("Health publishing cancelled, shutting down")
                break
            except Exception as e:
                logger.exception("Failed to publish health status", error=str(e))


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Run the Orpheus Video Motion Detector agent")
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
    detector = VideoMotionDetector(config_path=args.config, log_level_override=log_override)
    await detector.start()


def main(argv: Optional[list[str]] = None) -> int:
    """Synchronous entrypoint for shell execution."""

    args = parse_args(argv)
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as exc:  # pylint: disable=broad-except
        logger.exception("Unhandled exception", error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
