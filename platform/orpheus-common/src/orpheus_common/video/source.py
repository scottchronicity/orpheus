"""Video source interfaces for the Orpheus platform."""

from __future__ import annotations

import asyncio
import threading
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timezone
from queue import Empty, Queue
from typing import Optional

import cv2

from orpheus_common.logging import get_logger
from orpheus_common.utils.urls import redact_url_credentials

logger = get_logger(__name__)


@dataclass(frozen=True)
class VideoFrame:
    """Container for a single video frame."""

    camera_id: str
    payload: bytes  # Raw BGR frame data
    timestamp: datetime
    width: int
    height: int


class VideoSource(ABC):
    """Abstract base class for video capture backends."""

    def __init__(self, fps: int, width: int, height: int, max_pending_frames: int) -> None:
        self._fps = fps
        self._width = width
        self._height = height
        self._max_pending_frames = max_pending_frames
        self._running = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start video acquisition for the source."""
        async with self._lock:
            if self._running:
                logger.debug("Video source already running")
                return
            await self._start_internal()
            self._running = True
            logger.info(
                "Video source started (fps=%s, resolution=%dx%d)",
                self._fps,
                self._width,
                self._height,
            )

    async def stop(self) -> None:
        """Stop video acquisition and release resources."""
        async with self._lock:
            if not self._running:
                logger.debug("Video source already stopped")
                return
            await self._stop_internal()
            self._running = False
            logger.info("Video source stopped")

    async def stream_frames(self) -> AsyncGenerator[VideoFrame, None]:
        """Yield video frames asynchronously until the source is stopped."""
        if not self._running:
            raise RuntimeError("Video source must be started before streaming frames")
        async for frame in self._stream_internal():
            yield frame

    @abstractmethod
    async def _start_internal(self) -> None:
        """Backend-specific start hook."""

    @abstractmethod
    async def _stop_internal(self) -> None:
        """Backend-specific stop hook."""

    @abstractmethod
    async def _stream_internal(self) -> AsyncGenerator[VideoFrame, None]:
        """Backend-specific frame generator."""

    @property
    def fps(self) -> int:
        """Return the configured frames per second."""
        return self._fps

    @property
    def width(self) -> int:
        """Return the frame width."""
        return self._width

    @property
    def height(self) -> int:
        """Return the frame height."""
        return self._height

    def is_running(self) -> bool:
        """Check if the video source is currently running."""
        return self._running


class RTSPVideoSource(VideoSource):
    """RTSP video source implementation for IP cameras."""

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        fps: int,
        width: int,
        height: int,
        max_pending_frames: int,
    ) -> None:
        super().__init__(fps, width, height, max_pending_frames)
        self._camera_id = camera_id
        self._rtsp_url = rtsp_url
        self._capture: Optional[cv2.VideoCapture] = None
        self._frame_queue: Queue[Optional[VideoFrame]] = Queue(maxsize=max_pending_frames)
        self._capture_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    async def _start_internal(self) -> None:
        """Start RTSP capture."""
        logger.info(
            "Starting RTSP capture",
            camera_id=self._camera_id,
            rtsp_url=redact_url_credentials(self._rtsp_url),
        )
        self._stop_event.clear()

        # Open RTSP stream with OpenCV
        logger.info("Opening RTSP stream", camera_id=self._camera_id)
        self._capture = cv2.VideoCapture(self._rtsp_url, cv2.CAP_FFMPEG)

        if not self._capture.isOpened():
            logger.error("Failed to open RTSP stream", camera_id=self._camera_id)
            raise RuntimeError(f"Failed to open RTSP stream for camera {self._camera_id}")

        logger.info("RTSP stream opened successfully", camera_id=self._camera_id)

        # Set capture properties
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 3)  # Minimize buffering
        self._capture.set(cv2.CAP_PROP_FPS, self._fps)
        self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        logger.info(
            "RTSP capture properties set for camera %s: fps=%d, resolution=%dx%d",
            self._camera_id,
            self._fps,
            self._width,
            self._height,
        )

        # Start capture thread
        logger.info("Starting capture thread", camera_id=self._camera_id)
        self._capture_thread = threading.Thread(
            target=self._capture_loop,
            name=f"rtsp-capture-{self._camera_id}",
            daemon=True,
        )
        self._capture_thread.start()

        logger.info("RTSP capture started", camera_id=self._camera_id)

    async def _stop_internal(self) -> None:
        """Stop RTSP capture."""
        self._stop_event.set()

        # Wait for capture thread to finish
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=5.0)

        # Release capture
        if self._capture:
            self._capture.release()
            self._capture = None

        logger.info("RTSP capture stopped", camera_id=self._camera_id)

    def _capture_loop(self) -> None:
        """Background thread that captures frames from RTSP stream."""
        frame_interval = 1.0 / self._fps
        frame_count = 0

        logger.info("Capture loop started", camera_id=self._camera_id)
        while not self._stop_event.is_set() and self._capture:
            try:
                ret, frame = self._capture.read()

                if not ret or frame is None:
                    logger.warning("Failed to read frame", camera_id=self._camera_id)
                    continue

                frame_count += 1
                if frame_count == 1:
                    logger.info(
                        "First frame captured from camera %s (size: %dx%d)",
                        self._camera_id,
                        frame.shape[1],
                        frame.shape[0],
                    )
                if frame_count % 500 == 0:
                    logger.debug(
                        "Captured frames", frame_count=frame_count, camera_id=self._camera_id
                    )

                # Resize frame if needed
                if frame.shape[1] != self._width or frame.shape[0] != self._height:
                    frame = cv2.resize(frame, (self._width, self._height))

                # Convert frame to bytes
                payload = frame.tobytes()

                video_frame = VideoFrame(
                    camera_id=self._camera_id,
                    payload=payload,
                    timestamp=datetime.now(timezone.utc),
                    width=self._width,
                    height=self._height,
                )

                # Try to put frame in queue (drop if full)
                try:
                    self._frame_queue.put_nowait(video_frame)
                except Exception:
                    logger.debug("Frame queue full, dropping frame", camera_id=self._camera_id)

                # Sleep to maintain target FPS
                self._stop_event.wait(frame_interval)

            except Exception as e:
                logger.error("Error in capture loop", camera_id=self._camera_id, error=str(e))
                self._stop_event.wait(1.0)  # Wait before retrying

        logger.info(
            "Capture loop ended for camera %s (captured %d frames)", self._camera_id, frame_count
        )

    async def _stream_internal(self) -> AsyncGenerator[VideoFrame, None]:
        """Async generator that yields frames from the queue."""
        while self._running:
            try:
                # Non-blocking get with timeout
                frame = await asyncio.get_event_loop().run_in_executor(
                    None, self._frame_queue.get, True, 0.1
                )

                if frame is None:  # Sentinel value for shutdown
                    break

                yield frame

            except Empty:
                await asyncio.sleep(0.01)  # Short sleep if queue is empty
            except Exception as e:
                logger.error("Error streaming frame", camera_id=self._camera_id, error=str(e))
                await asyncio.sleep(0.1)
