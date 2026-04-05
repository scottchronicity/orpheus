"""Audio clip persistence helpers for the Audio Motion Detector agent."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import soundfile as sf
from mutagen.flac import FLAC
from orpheus_common.logging import get_logger
from orpheus_common.storage import ensure_directory, get_audio_path

logger = get_logger(__name__)


class ClipSaver:
    """
    Persist audio clips associated with motion detection events.

    Responsible for saving audio data to disk in the configured format (FLAC or WAV)
    with appropriate directory structure for the audio motion detection system.

    Attributes:
        _category: Storage category for organizing clips (e.g., "audio_motion").
        _write_format: Output format ("flac" or "wav").
        _sample_rate: Sample rate in Hz for proper audio encoding.
    """

    def __init__(self, category: str, write_format: str, sample_rate: int) -> None:
        """
        Initialize the clip saver with storage and format settings.

        Args:
            category: Storage category subdirectory (e.g., "audio_motion").
            write_format: Audio format to use ("flac" for lossless compression, "wav" for raw).
            sample_rate: Sample rate in Hz matching the audio capture settings.
        """
        self._category = category
        self._write_format = write_format
        self._sample_rate = sample_rate

    def save_clip(
        self,
        channel_id: str,
        payload: bytes,
        event_time: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Path:
        """
        Write an audio clip to disk and return the resulting path.

        The clip is saved with a timestamp-based filename in a directory
        structure organized by channel ID. Audio data is expected to be
        in int32 PCM format (24-bit audio in 32-bit container).

        Args:
            channel_id: Identifier of the audio channel (used for subdirectory).
            payload: Raw PCM audio bytes in int32 format.
            event_time: Timestamp for the event. Defaults to current UTC time.
            metadata: Optional dict to embed as Vorbis comments in FLAC files.
                Expected keys include ``event_type`` and ``pre_roll_ms``.

        Returns:
            Path to the saved audio clip file.

        Example:
            >>> saver = ClipSaver(
            ...     category="audio_motion",
            ...     write_format="flac",
            ...     sample_rate=48000,
            ... )
            >>> clip_path = saver.save_clip(
            ...     channel_id="1",
            ...     payload=audio_bytes,
            ...     event_time=datetime.now(timezone.utc),
            ...     metadata={"event_type": "motion", "pre_roll_ms": 500},
            ... )
        """
        # Convert bytes to numpy array (int32 PCM - 24-bit audio in 32-bit container)
        audio_data = np.frombuffer(payload, dtype=np.int32)

        timestamp = (event_time or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%S.%fZ")
        base_dir = get_audio_path(category=self._category)
        destination = ensure_directory(base_dir / channel_id)
        filename = f"{timestamp}.{self._write_format}"
        clip_path = destination / filename

        logger.info("Writing audio clip", clip_path=clip_path, format=self._write_format)

        # Write with proper format using soundfile
        # This adds WAV/FLAC headers automatically
        if self._write_format == "flac":
            # FLAC with compression (lossless) - PCM_24 for 24-bit depth
            sf.write(clip_path, audio_data, self._sample_rate, format="FLAC", subtype="PCM_24")
            # Embed metadata as Vorbis comments when provided
            if metadata:
                self._embed_flac_metadata(clip_path, metadata)
        else:  # wav or any other format defaults to WAV
            # WAV uncompressed - PCM_24 for 24-bit depth
            sf.write(clip_path, audio_data, self._sample_rate, format="WAV", subtype="PCM_24")

        return clip_path

    @staticmethod
    def _embed_flac_metadata(clip_path: Path, metadata: dict[str, Any]) -> None:
        """
        Embed metadata as a JSON Vorbis comment in a FLAC file.

        The metadata is serialised to JSON and stored in the
        ``ORPHEUS_META`` Vorbis comment tag so that downstream agents
        can read it back without additional out-of-band information.

        Args:
            clip_path: Path to the FLAC file.
            metadata: Metadata dict (e.g. ``{"event_type": "motion", "pre_roll_ms": 500}``).
        """
        try:
            audio = FLAC(str(clip_path))
            audio["ORPHEUS_META"] = json.dumps(metadata)
            audio.save()
            logger.debug("Embedded FLAC metadata", clip_path=str(clip_path), metadata=metadata)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning(
                "Failed to embed FLAC metadata",
                clip_path=str(clip_path),
                error=str(exc),
            )
