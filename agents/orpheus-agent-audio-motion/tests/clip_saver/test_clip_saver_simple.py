"""Tests for clip persistence functionality."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from orpheus_agent_audio_motion.clip_saver import ClipSaver


class TestClipSaver:
    """Tests for ClipSaver class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_initialization(self) -> None:
        """ClipSaver should initialize with category, format, and sample rate."""
        saver = ClipSaver(category="test_category", write_format="wav", sample_rate=48000)
        assert saver._category == "test_category"
        assert saver._write_format == "wav"
        assert saver._sample_rate == 48000

    def test_save_clip_creates_file(self, temp_dir: Path) -> None:
        """save_clip should write audio data to disk."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="wav", sample_rate=48000)
            # Create valid int32 PCM audio data (100 samples) for 24-bit audio
            import numpy as np

            audio_samples = np.random.randint(-8388608, 8388607, 100, dtype=np.int32)
            payload = audio_samples.tobytes()
            event_time = datetime(2025, 11, 29, 12, 30, 45, 123456)

            result_path = saver.save_clip(
                channel_id="channel_1",
                payload=payload,
                event_time=event_time,
            )

            # Check file was created
            assert result_path.exists()
            assert result_path.is_file()

            # Check file is valid WAV with proper header (not just raw bytes)
            import soundfile as sf

            data, sample_rate = sf.read(result_path)
            assert sample_rate == 48000
            assert len(data) == 100

            # Check filename format
            assert result_path.name == "20251129T123045.123456Z.wav"
            assert "channel_1" in str(result_path)

    def test_save_clip_without_event_time(self, temp_dir: Path) -> None:
        """save_clip should use current time if event_time is None."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            saver = ClipSaver(category="test", write_format="wav", sample_rate=44100)
            # Create valid int32 PCM audio data for 24-bit audio
            import numpy as np

            audio_samples = np.random.randint(-8388608, 8388607, 50, dtype=np.int32)
            payload = audio_samples.tobytes()

            result_path = saver.save_clip(
                channel_id="channel_2",
                payload=payload,
                event_time=None,
            )

            # Should have created a file
            assert result_path.exists()
            # Filename should have timestamp format
            assert result_path.suffix == ".wav"

    def test_save_clip_different_formats(self, temp_dir: Path) -> None:
        """save_clip should respect the write_format setting."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            import numpy as np

            # Create valid int16 PCM audio data
            audio_samples = np.random.randint(-32768, 32767, 50, dtype=np.int16)
            payload = audio_samples.tobytes()

            # Test wav and flac (mp3 not supported by soundfile with default settings)
            for fmt in ["wav", "flac"]:
                saver = ClipSaver(category="test", write_format=fmt, sample_rate=48000)
                result_path = saver.save_clip(
                    channel_id="test_ch",
                    payload=payload,
                    event_time=datetime.now(timezone.utc),
                )
                assert result_path.suffix == f".{fmt}"

    def test_save_clip_creates_channel_directory(self, temp_dir: Path) -> None:
        """save_clip should create channel subdirectory if it doesn't exist."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            import numpy as np

            # Create valid int16 PCM audio data
            audio_samples = np.random.randint(-32768, 32767, 50, dtype=np.int16)
            payload = audio_samples.tobytes()

            saver = ClipSaver(category="test", write_format="wav", sample_rate=48000)
            result_path = saver.save_clip(
                channel_id="new_channel",
                payload=payload,
                event_time=datetime.now(timezone.utc),
            )

            # Channel directory should exist
            channel_dir = result_path.parent
            assert channel_dir.exists()
            assert channel_dir.is_dir()
            assert "new_channel" in str(channel_dir)

    def test_save_clip_flac_format_validation(self, temp_dir: Path) -> None:
        """save_clip should write valid FLAC files with proper compression."""
        with patch("orpheus_agent_audio_motion.clip_saver.get_audio_path") as mock_path:
            mock_path.return_value = temp_dir

            import numpy as np
            import soundfile as sf

            # Create valid int32 PCM audio data for 24-bit audio
            audio_samples = np.random.randint(-8388608, 8388607, 1000, dtype=np.int32)
            payload = audio_samples.tobytes()

            saver = ClipSaver(category="test", write_format="flac", sample_rate=48000)
            result_path = saver.save_clip(
                channel_id="flac_test",
                payload=payload,
                event_time=datetime.now(timezone.utc),
            )

            # Check file was created with .flac extension
            assert result_path.exists()
            assert result_path.suffix == ".flac"

            # Verify file is valid FLAC and can be read back
            data, sample_rate = sf.read(result_path)
            assert sample_rate == 48000
            assert len(data) == 1000

            # FLAC should be smaller than equivalent WAV due to compression
            # (not checking exact size as it depends on data, but file should exist and be valid)
