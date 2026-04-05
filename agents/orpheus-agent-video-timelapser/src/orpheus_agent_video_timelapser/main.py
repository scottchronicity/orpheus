"""Entrypoint for the Orpheus Video Timelapser agent."""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from orpheus_common.logging import get_logger, setup_logging
from orpheus_common.storage import get_timelapse_path as common_get_timelapse_path

from .config import CameraTimelapseConfig, load_app_config

logger = get_logger(__name__)


def _get_current_time_in_timezone(tz_str: str) -> datetime:
    """
    Get current time in the specified timezone.

    Args:
        tz_str: Timezone string - "UTC", "local", or IANA name like "America/Los_Angeles"

    Returns:
        Current datetime in the specified timezone
    """
    if tz_str == "UTC":
        return datetime.now(timezone.utc)
    elif tz_str == "local":
        # Use local timezone
        return datetime.now().astimezone()
    else:
        # Try zoneinfo (Python 3.9+)
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_str))
        except ImportError:
            # Fall back to pytz if zoneinfo not available
            try:
                import pytz

                tz = pytz.timezone(tz_str)
                return datetime.now(tz)
            except Exception:
                # If timezone library not available, fall back to UTC
                logger.warning(
                    "Timezone not supported, falling back to UTC",
                    timezone=tz_str,
                )
                return datetime.now(timezone.utc)
        except (KeyError, ValueError):
            logger.warning(
                "Invalid timezone, falling back to UTC",
                timezone=tz_str,
            )
            return datetime.now(timezone.utc)


class VideoTimelapser:
    """Generate timelapse videos from camera snapshots."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        log_level_override: Optional[str] = None,
    ) -> None:
        self._config = load_app_config(config_path)
        self._log_level_override = log_level_override
        self._running = False
        # Track completed jobs: {(camera_name, date_str, interval_num, timelapse_id): True}
        # interval_num allows the same timelapse to run multiple times per day based on lookback_window
        self._completed_jobs: set[tuple[str, str, int, str]] = set()

    def start(self) -> None:
        """Start the agent and block until shutdown is requested."""

        log_level = self._log_level_override or self._config.log_level
        setup_logging(
            "orpheus-agent-video-timelapser",
            level=log_level,
            use_json=self._config.use_json_logging,
        )
        logger.info(
            "Starting Video Timelapser agent",
            storage_base_path=str(self._config.storage_base_path),
            log_level=log_level,
            camera_count=len(self._config.cameras),
        )

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        logger.info("Signal handlers registered")

        if not self._config.cameras:
            logger.warning("No cameras configured for timelapses")
            return

        logger.info(
            "Configured cameras for timelapses",
            camera_count=len(self._config.cameras),
            camera_names=[cam.name for cam in self._config.cameras],
        )

        # Log FULL timelapse schedule for every camera at startup.
        # This is intentionally verbose so that a single `journalctl` grep
        # for "Timelapse schedule" shows the complete picture.
        for camera in self._config.cameras:
            if camera.enabled:
                for tl_idx, tl_config in enumerate(camera.timelapses):
                    logger.info(
                        "Timelapse schedule",
                        camera_name=camera.name,
                        tl_index=tl_idx,
                        label=tl_config.label,
                        start_time=tl_config.start_time,
                        lookback_window=tl_config.lookback_window,
                        sampling_interval=tl_config.sampling_interval,
                        clip_duration=tl_config.clip_duration,
                        retention_days=tl_config.retention_days,
                        timezone=getattr(tl_config, "timezone", "UTC"),
                    )

        self._running = True
        logger.info("Entering main timelapse loop")

        try:
            self._run_timelapse_loop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        except Exception:
            logger.exception("Fatal error in timelapse loop")
            raise
        finally:
            self._running = False
            logger.info("Video Timelapser agent stopped")

    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received", signal=signum)
        self._running = False

    def _run_timelapse_loop(self) -> None:
        """Main loop: wake up every minute and check if timelapse jobs should run.

        Timelapses run on intervals determined by their lookback_window:
        - lookback_window: "24h" → runs once per day
        - lookback_window: "1h" → runs every hour
        - lookback_window: "30m" → runs every 30 minutes

        The start_time determines when the first interval begins each day.

        Job collection and execution are separated into two phases so that
        processing time for earlier cameras does not push later cameras
        past their trigger window.
        """

        while self._running:
            # Phase 1: Collect all jobs that should run this tick.
            # We snapshot the time ONCE per timezone before iterating cameras
            # so that execution time doesn't eat into the 90-second window.
            jobs_to_run: list[
                tuple
            ] = []  # (camera, tl_config, date_str, job_key, tz_str, interval)
            tz_times: dict[str, datetime] = {}  # cache one time snapshot per timezone

            for camera in self._config.cameras:
                if not camera.enabled:
                    continue

                for tl_idx, tl_config in enumerate(camera.timelapses):
                    # Get current time in the timelapse's configured timezone
                    tz_str = getattr(tl_config, "timezone", "UTC")
                    if tz_str not in tz_times:
                        tz_times[tz_str] = _get_current_time_in_timezone(tz_str)
                    local_time = tz_times[tz_str]
                    current_date_str = local_time.strftime("%Y.%m.%d")

                    # Parse start_time
                    start_hour, start_minute = map(int, tl_config.start_time.split(":"))

                    # Calculate seconds since midnight
                    seconds_since_midnight = (
                        local_time.hour * 3600 + local_time.minute * 60 + local_time.second
                    )

                    # Calculate seconds since start_time
                    start_seconds = start_hour * 3600 + start_minute * 60

                    # If we haven't reached start_time yet today, skip
                    if seconds_since_midnight < start_seconds:
                        continue

                    seconds_since_start = seconds_since_midnight - start_seconds

                    # Parse lookback_window to get interval in seconds
                    interval_seconds = self._parse_duration(tl_config.lookback_window)

                    # Calculate which interval we're in (0, 1, 2, ...)
                    current_interval = seconds_since_start // interval_seconds

                    # How many seconds into this interval are we?
                    seconds_into_interval = seconds_since_start % interval_seconds

                    # Only trigger in the first 90 seconds of each interval
                    # (gives buffer for timing jitter, loop wakes every 60s)
                    if seconds_into_interval > 90:
                        continue

                    # Create unique job key including interval number
                    timelapse_id = f"{tl_config.start_time}_{tl_idx}"
                    job_key = (camera.name, current_date_str, current_interval, timelapse_id)

                    # Check if we've already run this interval
                    if job_key in self._completed_jobs:
                        continue

                    jobs_to_run.append(
                        (camera, tl_config, current_date_str, job_key, tz_str, current_interval)
                    )

            # Phase 2: Execute all collected jobs
            tick_start = time.monotonic()
            if jobs_to_run:
                logger.info(
                    "Tick: executing collected jobs",
                    job_count=len(jobs_to_run),
                    jobs=[
                        f"{cam.name}/{tl.label}({tl.lookback_window})"
                        for cam, tl, _d, _k, _tz, _i in jobs_to_run
                    ],
                )
            else:
                logger.debug("Tick: no jobs eligible this cycle")

            for (
                camera,
                tl_config,
                current_date_str,
                job_key,
                tz_str,
                current_interval,
            ) in jobs_to_run:
                if not self._running:
                    break

                label = tl_config.label
                job_start = time.monotonic()
                logger.info(
                    "Starting timelapse generation",
                    camera_name=camera.name,
                    label=label,
                    start_time=tl_config.start_time,
                    lookback_window=tl_config.lookback_window,
                    sampling_interval=tl_config.sampling_interval,
                    interval_number=current_interval,
                    timezone=tz_str,
                    date=current_date_str,
                )

                try:
                    self._generate_timelapse(camera, tl_config, current_date_str)
                    self._completed_jobs.add(job_key)
                    elapsed = time.monotonic() - job_start
                    logger.info(
                        "Timelapse generation completed",
                        camera_name=camera.name,
                        label=label,
                        lookback_window=tl_config.lookback_window,
                        elapsed_seconds=round(elapsed, 2),
                    )
                except Exception:
                    elapsed = time.monotonic() - job_start
                    logger.exception(
                        "Failed to generate timelapse",
                        camera_name=camera.name,
                        label=label,
                        lookback_window=tl_config.lookback_window,
                        start_time=tl_config.start_time,
                        elapsed_seconds=round(elapsed, 2),
                    )

            if jobs_to_run:
                tick_elapsed = time.monotonic() - tick_start
                logger.info(
                    "Tick complete",
                    jobs_executed=len(jobs_to_run),
                    tick_elapsed_seconds=round(tick_elapsed, 2),
                    completed_job_count=len(self._completed_jobs),
                )

            # Clean up old completed jobs - keep jobs from today in any timezone
            # This is approximate; we just prune jobs older than 2 days to be safe
            utc_now = datetime.now(timezone.utc)
            two_days_ago = utc_now - timedelta(days=2)
            two_days_ago_str = two_days_ago.strftime("%Y.%m.%d")

            # Keep jobs from the last 2 days to handle timezone edge cases
            self._completed_jobs = {
                (cam, date, interval, tl_id)
                for cam, date, interval, tl_id in self._completed_jobs
                if date >= two_days_ago_str
            }

            # Sleep for 60 seconds before next check, but check for shutdown every second
            for _ in range(60):
                if not self._running:
                    break
                time.sleep(1.0)

    def _generate_timelapse(
        self,
        camera: CameraTimelapseConfig,
        tl_config,
        date_str: str,
    ) -> None:
        """Generate a timelapse video from snapshots using bucket sampling.

        Bucket sampling selects snapshots at regular time intervals (sampling_interval)
        looking back over a time window (lookback_window).
        """

        # Find snapshot directory for the date
        snapshot_dir = self._config.storage_base_path / "video" / "snapshots" / date_str

        if not snapshot_dir.exists():
            logger.warning(
                "Snapshot directory not found, skipping timelapse",
                camera_name=camera.name,
                snapshot_dir=str(snapshot_dir),
                date_str=date_str,
            )
            return

        # Find all snapshots for this camera
        snapshot_pattern = f"*.{camera.name}.jpg"
        snapshot_files = sorted(snapshot_dir.glob(snapshot_pattern))

        label = tl_config.label
        logger.info(
            "Snapshot discovery",
            camera_name=camera.name,
            label=label,
            lookback_window=tl_config.lookback_window,
            snapshot_dir=str(snapshot_dir),
            total_snapshots_on_disk=len(snapshot_files),
        )

        if len(snapshot_files) == 0:
            logger.warning(
                "No snapshots found for camera, skipping",
                camera_name=camera.name,
                label=label,
                snapshot_dir=str(snapshot_dir),
                glob_pattern=snapshot_pattern,
            )
            return

        # Parse lookback_window and sampling_interval
        lookback_seconds = self._parse_duration(tl_config.lookback_window)
        sampling_seconds = self._parse_duration(tl_config.sampling_interval)

        # Get current time and calculate lookback start time
        current_time = datetime.now(timezone.utc)
        lookback_start = current_time - timedelta(seconds=lookback_seconds)

        # Sample snapshots using bucket sampling
        selected_snapshots = self._bucket_sample_snapshots(
            snapshot_files, lookback_start, current_time, sampling_seconds
        )

        # Compute expected bucket count for diagnostics
        expected_buckets = lookback_seconds // sampling_seconds if sampling_seconds else 0
        logger.info(
            "Bucket sampling results",
            camera_name=camera.name,
            label=label,
            total_snapshots_on_disk=len(snapshot_files),
            snapshots_in_window=len(selected_snapshots),
            expected_buckets=expected_buckets,
            lookback_window=tl_config.lookback_window,
            sampling_interval=tl_config.sampling_interval,
            lookback_start=lookback_start.isoformat(),
            lookback_end=current_time.isoformat(),
        )

        # Check if we have enough snapshots (at least 2 for a meaningful timelapse)
        if len(selected_snapshots) < 2:
            logger.warning(
                "Insufficient snapshots after bucket sampling, skipping timelapse",
                camera_name=camera.name,
                label=label,
                lookback_window=tl_config.lookback_window,
                found=len(selected_snapshots),
                min_required=2,
                expected_buckets=expected_buckets,
            )
            return

        # Load images and get dimensions
        frames = []
        frame_shape = None

        for snapshot_path in selected_snapshots:
            img = cv2.imread(str(snapshot_path))
            if img is None:
                logger.warning(
                    "Failed to read snapshot, skipping",
                    camera_name=camera.name,
                    path=str(snapshot_path),
                )
                continue

            if frame_shape is None:
                frame_shape = img.shape
            elif img.shape != frame_shape:
                logger.warning(
                    "Snapshot has different dimensions, resizing",
                    camera_name=camera.name,
                    path=str(snapshot_path),
                    expected_shape=frame_shape,
                    actual_shape=img.shape,
                )
                # Resize to match first frame
                img = cv2.resize(img, (frame_shape[1], frame_shape[0]))

            frames.append(img)

        if len(frames) < 2:
            logger.warning(
                "Insufficient valid frames after loading images, skipping",
                camera_name=camera.name,
                label=label,
                valid_frames=len(frames),
                min_required=2,
            )
            return

        # Calculate frame rate
        frame_rate = 1.0 / tl_config.clip_duration
        logger.info(
            "Writing timelapse video (mp4v)",
            camera_name=camera.name,
            label=label,
            frame_count=len(frames),
            frame_rate=round(frame_rate, 3),
            clip_duration=tl_config.clip_duration,
            video_duration_seconds=round(len(frames) * tl_config.clip_duration, 1),
        )

        # Generate output path using new filename format
        output_path = self._get_timelapse_path(
            camera.name,
            date_str,
            tl_config.lookback_window,
            tl_config.label,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Timelapse output path",
            camera_name=camera.name,
            label=label,
            output_filename=output_path.name,
            output_dir=str(output_path.parent),
        )

        # Create video writer
        height, width = frame_shape[0], frame_shape[1]

        # On Jetson, avc1/H264 fail silently due to broken GStreamer plugins.
        # Use mp4v which works reliably, then transcode with ffmpeg to H.264.
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, frame_rate, (width, height))

        if not writer.isOpened():
            logger.error(
                "Failed to open video writer",
                camera_name=camera.name,
                output_path=str(output_path),
            )
            return

        try:
            # Write all frames - ensure BGR format (cv2.imread returns BGR)
            for frame in frames:
                # Ensure frame is in correct format for video writer
                if frame.dtype != np.uint8:
                    frame = frame.astype(np.uint8)
                writer.write(frame)

            logger.info(
                "Timelapse video written (mp4v)",
                camera_name=camera.name,
                label=label,
                output_filename=output_path.name,
                frame_count=len(frames),
                frame_rate=round(frame_rate, 3),
            )

        finally:
            writer.release()

        # Verify file was created
        if not output_path.exists():
            logger.error("Video file not created", output_path=str(output_path))
            return None

        # Transcode to H.264 using system ffmpeg for browser playability
        self._transcode_to_h264(output_path, camera.name)

        file_size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Timelapse file complete",
            camera_name=camera.name,
            label=label,
            output_filename=output_path.name,
            size_mb=round(file_size_mb, 2),
        )

    def _transcode_to_h264(self, video_path: Path, camera_name: str) -> bool:
        """
        Transcode mp4v video to H.264 using system ffmpeg for browser playability.

        On Jetson, OpenCV's pip-installed version has broken GStreamer plugins,
        so we use mp4v to create the video, then transcode with system ffmpeg.

        Args:
            video_path: Path to the mp4v video file
            camera_name: Camera name for logging

        Returns:
            True if transcoding succeeded, False otherwise
        """
        # Check if ffmpeg is available
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logger.warning(
                "ffmpeg not found, skipping transcode (video may not play in browser)",
                camera_name=camera_name,
                video_path=str(video_path),
            )
            return False

        # Create temp output path
        temp_path = video_path.with_suffix(".h264.mp4")

        try:
            # Transcode to H.264 with libx264
            # CRF 28 gives good quality for timelapses at ~50% smaller file size
            cmd = [
                ffmpeg_path,
                "-y",  # Overwrite output
                "-i",
                str(video_path),  # Input file
                "-c:v",
                "libx264",  # H.264 codec
                "-preset",
                "fast",  # Balance speed/quality
                "-crf",
                "28",  # Quality (18=high, 23=default, 28=smaller files)
                "-movflags",
                "+faststart",  # Enable streaming
                str(temp_path),
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode != 0:
                logger.error(
                    "ffmpeg transcode failed",
                    camera_name=camera_name,
                    stderr=result.stderr[:500] if result.stderr else "No stderr",
                )
                # Clean up temp file if it exists
                if temp_path.exists():
                    temp_path.unlink()
                return False

            # Replace original with transcoded version
            temp_path.replace(video_path)

            logger.info(
                "Transcoded to H.264",
                camera_name=camera_name,
                video_path=str(video_path),
            )
            return True

        except subprocess.TimeoutExpired:
            logger.error(
                "ffmpeg transcode timed out",
                camera_name=camera_name,
                video_path=str(video_path),
            )
            if temp_path.exists():
                temp_path.unlink()
            return False

        except Exception as e:
            logger.error(
                "ffmpeg transcode error",
                camera_name=camera_name,
                error=str(e),
            )
            if temp_path.exists():
                temp_path.unlink()
            return False

    def _get_timelapse_path(
        self,
        camera_name: str,
        date_str: str,
        lookback_window: str,
        label: str,
    ) -> Path:
        """
        Generate filesystem path for timelapse video using new format.

        Format: /data/orpheus/video/timelapses/{YYYY.MM.DD}/{camera}.{label}.{tier}.{lookback}.{timestamp}.mp4
        Example: orpheus-eye-1.daily.tl0.24h.20260125-230000.mp4
        """
        # Use orpheus-common utility for consistent filename generation
        return common_get_timelapse_path(
            storage_base=self._config.storage_base_path,
            camera_id=camera_name,
            label=label,
            lookback_window=lookback_window,
            date_str=date_str,
        )

    def _parse_duration(self, duration_str: str) -> int:
        """Parse duration string (e.g., '24h', '15m', '7d') to seconds.

        Args:
            duration_str: Duration string like '24h', '15m', '7d'

        Returns:
            Duration in seconds
        """
        if not duration_str:
            return 86400  # Default 24 hours

        unit = duration_str[-1]
        value = int(duration_str[:-1])

        if unit == "s":
            return value
        elif unit == "m":
            return value * 60
        elif unit == "h":
            return value * 3600
        elif unit == "d":
            return value * 86400
        else:
            logger.warning(
                "Invalid duration unit, defaulting to seconds",
                duration_str=duration_str,
                unit=unit,
            )
            return value

    def _bucket_sample_snapshots(
        self,
        snapshot_files: list[Path],
        lookback_start: datetime,
        current_time: datetime,
        sampling_seconds: int,
    ) -> list[Path]:
        """Select snapshots using bucket sampling.

        Divides the time window into buckets of size sampling_seconds, then selects
        the snapshot closest to the center of each bucket.

        Args:
            snapshot_files: Sorted list of snapshot file paths
            lookback_start: Start of the time window
            current_time: End of the time window
            sampling_seconds: Size of each bucket in seconds

        Returns:
            List of selected snapshot paths
        """
        # Parse snapshot timestamps from filenames
        # Supports two formats:
        # 1. ISO 8601: {ISO_timestamp}.{camera_name}.jpg (e.g., 2026-01-24T14-51-31.638521Z.orpheus-eye-1.jpg)
        # 2. Legacy dot-separated: YYYY.MM.DD.HH.MM.SS.camera_name.jpg
        snapshot_times: list[tuple[Path, datetime]] = []

        for snapshot_file in snapshot_files:
            try:
                # Extract timestamp from filename
                filename = snapshot_file.stem  # Remove .jpg extension

                # Split by last dot to separate camera name
                parts = filename.rsplit(".", 1)
                if len(parts) < 2:
                    continue

                timestamp_part = parts[0]  # Everything before the camera name

                # Detect format and parse accordingly
                if "T" in timestamp_part:
                    # ISO 8601 format with 'T' separator
                    # Convert filename format back to ISO 8601
                    # Replace hyphens with colons in time portion, add back 'Z' if present
                    if "Z" in timestamp_part:
                        timestamp_str = timestamp_part.replace("Z", "+00:00")
                    else:
                        timestamp_str = timestamp_part + "+00:00"

                    # Replace dashes with colons in the time part (HH-MM-SS → HH:MM:SS)
                    date_part, time_part = timestamp_str.split("T", 1)
                    # Replace first two dashes in time part (HH-MM-SS)
                    time_part = time_part.replace("-", ":", 2)
                    timestamp_str = f"{date_part}T{time_part}"
                    timestamp = datetime.fromisoformat(timestamp_str)
                else:
                    # Legacy dot-separated format: YYYY.MM.DD.HH.MM.SS
                    # Parse using strptime
                    timestamp = datetime.strptime(timestamp_part, "%Y.%m.%d.%H.%M.%S")
                    # Add UTC timezone (legacy format was always UTC)
                    timestamp = timestamp.replace(tzinfo=timezone.utc)

                # Only include snapshots within the time window
                if lookback_start <= timestamp <= current_time:
                    snapshot_times.append((snapshot_file, timestamp))
            except (ValueError, IndexError) as e:
                logger.debug(
                    "Failed to parse snapshot timestamp, skipping",
                    filename=str(snapshot_file),
                    error=str(e),
                )
                continue

        if not snapshot_times:
            return []

        # Sort by timestamp
        snapshot_times.sort(key=lambda x: x[1])

        # Create time buckets
        selected_snapshots: list[Path] = []
        bucket_start = lookback_start

        while bucket_start < current_time:
            bucket_end = bucket_start + timedelta(seconds=sampling_seconds)
            bucket_center = bucket_start + timedelta(seconds=sampling_seconds / 2)

            # Find snapshot closest to bucket center
            best_snapshot = None
            best_distance = None

            for snapshot_path, snapshot_time in snapshot_times:
                if bucket_start <= snapshot_time < bucket_end:
                    distance = abs((snapshot_time - bucket_center).total_seconds())
                    if best_distance is None or distance < best_distance:
                        best_snapshot = snapshot_path
                        best_distance = distance

            if best_snapshot:
                selected_snapshots.append(best_snapshot)

            bucket_start = bucket_end

        return selected_snapshots


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Run the Orpheus Video Timelapser agent")
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
    log_override = args.log_level.upper() if args.log_level else "INFO"

    try:
        timelapser = VideoTimelapser(config_path=args.config, log_level_override=log_override)
        timelapser.start()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception:
        logger.exception("Unhandled exception")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
