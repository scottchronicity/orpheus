"""Tests for FLAC metadata (Vorbis comment) embedding in ClipSaver."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from mutagen.flac import FLAC

from orpheus_agent_audio_motion.clip_saver import ClipSaver


class TestFlacMetadata:
    """Verify that ClipSaver embeds pre-roll metadata in FLAC Vorbis comments."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_flac_contains_orpheus_meta_tag(self, temp_dir: Path) -> None:
        """FLAC files should contain an ORPHEUS_META Vorbis comment."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="flac", sample_rate=48000)
            audio_samples = np.random.randint(-8388608, 8388607, 1000, dtype=np.int32)

            clip_path = saver.save_clip(
                channel_id="ch1",
                payload=audio_samples.tobytes(),
                event_time=datetime.now(timezone.utc),
                metadata={"event_type": "motion", "pre_roll_ms": 500},
            )

            # Read back the Vorbis comments
            flac = FLAC(str(clip_path))
            assert "orpheus_meta" in flac  # mutagen normalises tag names to lowercase
            meta = json.loads(flac["orpheus_meta"][0])
            assert meta["event_type"] == "motion"
            assert meta["pre_roll_ms"] == 500

    def test_flac_metadata_with_zero_pre_roll(self, temp_dir: Path) -> None:
        """pre_roll_ms=0 should still be written correctly."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="flac", sample_rate=48000)
            audio_samples = np.random.randint(-8388608, 8388607, 500, dtype=np.int32)

            clip_path = saver.save_clip(
                channel_id="ch1",
                payload=audio_samples.tobytes(),
                event_time=datetime.now(timezone.utc),
                metadata={"event_type": "motion", "pre_roll_ms": 0},
            )

            flac = FLAC(str(clip_path))
            meta = json.loads(flac["orpheus_meta"][0])
            assert meta["pre_roll_ms"] == 0

    def test_wav_does_not_embed_metadata(self, temp_dir: Path) -> None:
        """WAV files should be unaffected – no FLAC metadata attempt."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="wav", sample_rate=48000)
            audio_samples = np.random.randint(-8388608, 8388607, 500, dtype=np.int32)

            clip_path = saver.save_clip(
                channel_id="ch1",
                payload=audio_samples.tobytes(),
                event_time=datetime.now(timezone.utc),
                metadata={"event_type": "motion", "pre_roll_ms": 500},
            )

            # File should exist and be valid WAV
            assert clip_path.exists()
            assert clip_path.suffix == ".wav"

    def test_flac_no_metadata_when_none(self, temp_dir: Path) -> None:
        """When metadata is None, no Vorbis comment should be added."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="flac", sample_rate=48000)
            audio_samples = np.random.randint(-8388608, 8388607, 500, dtype=np.int32)

            clip_path = saver.save_clip(
                channel_id="ch1",
                payload=audio_samples.tobytes(),
                event_time=datetime.now(timezone.utc),
                metadata=None,
            )

            flac = FLAC(str(clip_path))
            assert "orpheus_meta" not in flac

    def test_existing_clip_saver_api_unchanged(self, temp_dir: Path) -> None:
        """Calling save_clip without metadata should still work (backward compat)."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="flac", sample_rate=48000)
            audio_samples = np.random.randint(-8388608, 8388607, 500, dtype=np.int32)

            # Call without metadata kwarg (old API)
            clip_path = saver.save_clip(
                channel_id="ch1",
                payload=audio_samples.tobytes(),
                event_time=datetime.now(timezone.utc),
            )

            assert clip_path.exists()
            assert clip_path.suffix == ".flac"
