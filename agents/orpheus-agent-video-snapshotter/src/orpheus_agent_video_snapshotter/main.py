"""Entrypoint for the Orpheus Video Snapshotter agent."""

import argparse
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.utils.time import parse_duration_string, utc_now_iso
from orpheus_common.utils.urls import redact_url_credentials

from .config import CameraSnapshotConfig, load_app_config

logger = get_logger(__name__)


class VideoSnapshotter:
    """Capture periodic snapshots from IP cameras."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        log_level_override: Optional[str] = None,
    ) -> None:
        self._config = load_app_config(config_path)
        self._log_level_override = log_level_override
        self._running = False
        self._last_snapshot_times = {}

    def start(self) -> None:
        """Start the agent and block until shutdown is requested."""

        log_level = self._log_level_override or self._config.log_level
        setup_logging(
            "orpheus-agent-video-snapshotter",
            level=log_level,
            use_json=self._config.use_json_logging,
        )
        logger.info("Starting Video Snapshotter agent")

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        logger.info("Signal handlers registered")

        if not self._config.cameras:
            logger.warning("No cameras configured for snapshots")
            return

        logger.info(
            "Configured cameras for snapshots",
            camera_count=len(self._config.cameras),
            camera_names=[cam.name for cam in self._config.cameras],
        )

        # Log snapshot intervals
        for camera in self._config.cameras:
            if camera.enabled:
                try:
                    interval_seconds = parse_duration_string(camera.interval)
                    logger.info(
                        "Camera snapshot schedule",
                        camera_name=camera.name,
                        interval=camera.interval,
                        interval_seconds=interval_seconds,
                    )
                except ValueError as e:
                    logger.error(
                        "Invalid snapshot interval for camera",
                        camera_name=camera.name,
                        interval=camera.interval,
                        error=str(e),
                    )

        # This agent used to delete its own snapshots on an age window. It no
        # longer deletes anything; orpheus-storage-sweep owns every deletion
        # under the data root. Saying so at startup means an operator who set
        # video_snapshotter.retention_days finds out that it is inert here,
        # rather than discovering it from a directory that never shrinks.
        logger.info(
            "Snapshot retention is enforced by orpheus-storage-sweep "
            "(video_snapshotter.retention_days is no longer applied; set "
            "storage.retention.categories.snapshots instead)",
            retention_days=self._config.retention_days,
        )

        self._running = True
        logger.info("Entering main snapshot loop")

        try:
            self._run_snapshot_loop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception:
            logger.exception("Fatal error in snapshot loop")
            raise
        finally:
            self._running = False
            logger.info("Video Snapshotter agent stopped")

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received", signal=signum)
        self._running = False

    def _run_snapshot_loop(self) -> None:
        """Main loop: check each camera and capture if interval elapsed."""

        while self._running:
            current_time = time.time()

            for camera in self._config.cameras:
                if not camera.enabled:
                    continue

                try:
                    # Parse interval duration
                    interval_seconds = parse_duration_string(camera.interval)
                    if interval_seconds <= 0:
                        continue

                    # Check if it's time to capture
                    last_time = self._last_snapshot_times.get(camera.name, 0)
                    time_since_last = current_time - last_time

                    if time_since_last >= interval_seconds:
                        logger.debug(
                            "Capturing snapshot",
                            camera_name=camera.name,
                            time_since_last=f"{time_since_last:.1f}s",
                        )
                        self._capture_snapshot(camera)
                        self._last_snapshot_times[camera.name] = current_time

                except ValueError as e:
                    logger.error(
                        "Invalid interval for camera",
                        camera_name=camera.name,
                        interval=camera.interval,
                        error=str(e),
                    )
                except Exception:
                    logger.exception("Failed to capture snapshot", camera_name=camera.name)

            # This agent captures; it does not delete. Snapshots are trimmed by
            # orpheus-storage-sweep, which is the only component that deletes
            # under the data root — see docs/designs/storage-retention.md.

            # Sleep briefly to avoid tight loop
            time.sleep(1.0)

    def _capture_snapshot(self, camera: CameraSnapshotConfig) -> None:
        """Capture a single snapshot from camera and save to disk."""

        logger.debug(
            "Opening RTSP stream",
            camera_name=camera.name,
            rtsp_url=redact_url_credentials(camera.rtsp_url),
        )

        # Open RTSP stream with minimal timeout
        cap = cv2.VideoCapture(camera.rtsp_url)
        if not cap.isOpened():
            logger.error("Failed to open RTSP stream", camera_name=camera.name)
            return

        try:
            # Read a single frame
            ret, frame = cap.read()
            if not ret or frame is None:
                logger.error("Failed to read frame from stream", camera_name=camera.name)
                return

            # Verify frame is valid
            if not isinstance(frame, np.ndarray) or frame.size == 0:
                logger.error("Invalid frame data", camera_name=camera.name)
                return

            # Generate timestamp and path
            timestamp = utc_now_iso()
            save_path = self._get_snapshot_path(camera.name, timestamp)

            # Ensure directory exists
            save_path.parent.mkdir(parents=True, exist_ok=True)

            # Save as JPEG
            success = cv2.imwrite(str(save_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if success:
                file_size = save_path.stat().st_size
                logger.info(
                    "Snapshot saved",
                    camera_name=camera.name,
                    path=str(save_path),
                    size_kb=file_size // 1024,
                )
            else:
                logger.error("Failed to write snapshot file", camera_name=camera.name)

        finally:
            # Always release the capture
            cap.release()
            logger.debug("RTSP stream closed", camera_name=camera.name)

    def _get_snapshot_path(self, camera_name: str, timestamp_iso: str) -> Path:
        """
        Generate filesystem path for snapshot.

        Format: /data/orpheus/video/snapshots/{YYYY.MM.DD}/{UTC_ISO_TIMESTAMP}.{cam_name}.jpg
        """
        # Parse timestamp to get date components
        try:
            dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            # Fallback to current time if parsing fails
            dt = datetime.now(timezone.utc)

        # Create date-based directory structure
        date_dir = dt.strftime("%Y.%m.%d")

        # Sanitize timestamp for filename (replace colons with dashes)
        filename_timestamp = timestamp_iso.replace(":", "-")

        # Construct full path
        snapshot_dir = self._config.storage_base_path / "video" / "snapshots" / date_dir
        filename = f"{filename_timestamp}.{camera_name}.jpg"

        return snapshot_dir / filename


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Run the Orpheus Video Snapshotter agent")
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


def main(argv: Optional[list] = None) -> int:
    """Synchronous entrypoint for shell execution."""

    args = parse_args(argv)
    log_override = args.log_level.upper() if args.log_level else None

    try:
        snapshotter = VideoSnapshotter(config_path=args.config, log_level_override=log_override)
        snapshotter.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unhandled exception")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
