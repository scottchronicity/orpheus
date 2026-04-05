"""Video clip persistence helpers for the Video Motion Detector agent."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
from orpheus_common.logging import get_logger
from orpheus_common.storage import ensure_directory, get_video_path

logger = get_logger(__name__)


class ClipSaver:
    """
    Persist video clips associated with motion detection events.

    Responsible for saving video data to disk in the configured format (MP4 or AVI)
    with appropriate directory structure for the video motion detection system.

    When saving MP4 clips with metadata, a lightweight ffmpeg post-processing step
    embeds the detection payload as a ``comment`` tag so that downstream tools can
    read the trigger context directly from the container.

    Attributes:
        _category: Storage category for organizing clips (e.g., "video_motion").
        _write_format: Output format ("mp4" or "avi").
        _fps: Frames per second for proper video encoding.
        _width: Frame width in pixels.
        _height: Frame height in pixels.
    """

    def __init__(self, category: str, write_format: str, fps: int, width: int, height: int) -> None:
        """
        Initialize the clip saver with storage and format settings.

        Args:
            category: Storage category subdirectory (e.g., "video_motion").
            write_format: Video format to use ("mp4" for H.264 compression, "avi" for MJPEG).
            fps: Frames per second matching the video capture settings.
            width: Frame width in pixels.
            height: Frame height in pixels.
        """
        self._category = category
        self._write_format = write_format
        self._fps = fps
        self._width = width
        self._height = height

    def save_clip(
        self,
        camera_id: str,
        frames: List[bytes],
        event_time: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """
        Write a video clip to disk and return the resulting path.

        The clip is saved with a timestamp-based filename in a directory
        structure organized by camera ID. Video frames are expected to be
        in BGR format (OpenCV standard).

        When *metadata* is provided and the output format is MP4, an ffmpeg
        post-processing step embeds the payload as a ``comment`` tag in the
        container.  If ffmpeg is unavailable or fails, the raw clip is kept
        and a warning is logged — the agent is never crashed by metadata
        embedding failures.

        Args:
            camera_id: Identifier of the camera (used for subdirectory).
            frames: List of raw BGR frame bytes.
            event_time: Timestamp for the event. Defaults to current UTC time.
            metadata: Optional dict to embed as JSON in the MP4 comment tag.

        Returns:
            Path to the saved video clip file.
        """
        timestamp = (event_time or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S.%fZ")
        base_dir = get_video_path(category=self._category)
        destination = ensure_directory(base_dir / camera_id)
        filename = f"{timestamp}.{self._write_format}"
        clip_path = destination / filename

        logger.info(
            "Writing video clip %s (%s format, %d frames)",
            clip_path,
            self._write_format,
            len(frames),
        )

        # Determine the actual write target — if we plan to run ffmpeg afterwards
        # we write to a temp file first to avoid partial-write corruption.
        embed_metadata = metadata is not None and self._write_format == "mp4"
        write_path = (destination / f"{timestamp}.tmp.mp4") if embed_metadata else clip_path

        writer = self._open_writer(write_path)

        # Write frames
        for frame_bytes in frames:
            frame_array = np.frombuffer(frame_bytes, dtype=np.uint8).reshape(
                (self._height, self._width, 3)
            )
            writer.write(frame_array)

        writer.release()

        if embed_metadata:
            clip_path = self._embed_metadata(write_path, clip_path, metadata)  # type: ignore[arg-type]

        return clip_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _open_writer(self, path: Path) -> cv2.VideoWriter:
        """Open and return a cv2.VideoWriter for *path*."""
        if self._write_format == "mp4":
            codecs_to_try = [
                ("avc1", "H.264 (avc1)"),
                ("H264", "H.264"),
                ("mp4v", "MPEG-4 Part 2"),
            ]
            writer = None
            for codec, codec_name in codecs_to_try:
                fourcc = cv2.VideoWriter_fourcc(*codec)
                writer = cv2.VideoWriter(
                    str(path),
                    fourcc,
                    self._fps,
                    (self._width, self._height),
                )
                if writer.isOpened():
                    logger.debug("Using video codec", codec=codec_name)
                    break
                writer.release()
                logger.debug("Codec not available, trying next", codec=codec_name)

            if writer is None or not writer.isOpened():
                raise RuntimeError(
                    f"Failed to open video writer for {path} - no compatible codec found"
                )
        else:
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(
                str(path),
                fourcc,
                self._fps,
                (self._width, self._height),
            )
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open video writer for {path}")

        return writer

    def _embed_metadata(self, tmp_path: Path, final_path: Path, metadata: Dict[str, Any]) -> Path:
        """
        Run ffmpeg to copy *tmp_path* into *final_path* with embedded metadata.

        The detection payload is serialised as JSON and stored in the MP4
        ``comment`` tag.  If ffmpeg fails the temporary file is renamed to
        the final path so that the clip is never lost.

        Args:
            tmp_path:   Path to the raw clip written by cv2.VideoWriter.
            final_path: Desired output path with metadata embedded.
            metadata:   Dict to serialise and embed.

        Returns:
            Path to the clip that was successfully written (may be *tmp_path*
            renamed to *final_path* on ffmpeg failure).
        """
        json_comment = json.dumps(metadata, default=str)
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(tmp_path),
                    "-c",
                    "copy",
                    "-metadata",
                    f"comment={json_comment}",
                    str(final_path),
                ],
                check=True,
                capture_output=True,
            )
            logger.debug(
                "Metadata embedded via ffmpeg",
                clip_path=final_path,
                metadata_keys=list(metadata.keys()),
            )
            return final_path
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "ffmpeg metadata embedding failed; keeping raw clip",
                clip_path=final_path,
                returncode=exc.returncode,
                stderr=exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "",
            )
            # Rename the temp file so the clip is not lost.
            tmp_path.rename(final_path)
            return final_path
        except FileNotFoundError:
            logger.warning(
                "ffmpeg not found; skipping metadata embedding",
                clip_path=final_path,
            )
            tmp_path.rename(final_path)
            return final_path
        finally:
            # Always attempt to remove the temp file; it may already be gone
            # if rename succeeded, so ignore errors.
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
