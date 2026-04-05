"""Tests for clip saver."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pytest

from orpheus_agent_video_motion.clip_saver import ClipSaver


def test_clip_saver_initialization():
    """Test ClipSaver initialization."""
    saver = ClipSaver(
        category="video_motion",
        write_format="mp4",
        fps=10,
        width=640,
        height=480,
    )

    assert saver._category == "video_motion"
    assert saver._write_format == "mp4"
    assert saver._fps == 10
    assert saver._width == 640
    assert saver._height == 480


def test_clip_saver_initialization_avi():
    """Test ClipSaver with AVI format."""
    saver = ClipSaver(
        category="video_motion",
        write_format="avi",
        fps=15,
        width=320,
        height=240,
    )

    assert saver._write_format == "avi"
    assert saver._fps == 15


def test_clip_saver_save_clip_mp4():
    """Test saving a video clip in MP4 format."""
    saver = ClipSaver(
        category="test_clips",
        write_format="mp4",
        fps=10,
        width=640,
        height=480,
    )

    # Create test frames
    frames = []
    for i in range(5):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (i * 25, 100, 150)
        frames.append(frame.tobytes())

    test_time = datetime.now(timezone.utc)

    with (
        patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
        patch("cv2.VideoWriter") as mock_writer_class,
    ):
        mock_base = Path("/tmp/test_clips")
        mock_get_path.return_value = mock_base
        mock_ensure.return_value = mock_base / "test-camera"

        mock_writer = Mock()
        mock_writer.isOpened.return_value = True
        mock_writer.write = Mock()
        mock_writer.release = Mock()
        mock_writer_class.return_value = mock_writer

        clip_path = saver.save_clip(
            camera_id="test-camera",
            frames=frames,
            event_time=test_time,
        )

        assert ".mp4" in str(clip_path)
        assert "test-camera" in str(clip_path)
        mock_writer.write.assert_called()
        assert mock_writer.write.call_count == 5
        mock_writer.release.assert_called_once()


def test_clip_saver_save_clip_avi():
    """Test saving a video clip in AVI format."""
    saver = ClipSaver(
        category="test_clips",
        write_format="avi",
        fps=10,
        width=640,
        height=480,
    )

    # Create test frames
    frames = []
    for _i in range(3):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frames.append(frame.tobytes())

    with (
        patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
        patch("cv2.VideoWriter") as mock_writer_class,
    ):
        mock_base = Path("/tmp/test_clips")
        mock_get_path.return_value = mock_base
        mock_ensure.return_value = mock_base / "test-camera"

        mock_writer = Mock()
        mock_writer.isOpened.return_value = True
        mock_writer.write = Mock()
        mock_writer.release = Mock()
        mock_writer_class.return_value = mock_writer

        clip_path = saver.save_clip(
            camera_id="test-camera",
            frames=frames,
        )

        assert ".avi" in str(clip_path)
        mock_writer.write.assert_called()


def test_clip_saver_save_clip_default_time():
    """Test saving clip with default timestamp."""
    saver = ClipSaver(
        category="test_clips",
        write_format="mp4",
        fps=10,
        width=640,
        height=480,
    )

    frames = [np.zeros((480, 640, 3), dtype=np.uint8).tobytes()]

    with (
        patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
        patch("cv2.VideoWriter") as mock_writer_class,
    ):
        mock_base = Path("/tmp/test_clips")
        mock_get_path.return_value = mock_base
        mock_ensure.return_value = mock_base / "test-camera"

        mock_writer = Mock()
        mock_writer.isOpened.return_value = True
        mock_writer_class.return_value = mock_writer

        # Don't provide event_time
        clip_path = saver.save_clip(
            camera_id="test-camera",
            frames=frames,
        )

        assert clip_path is not None


def test_clip_saver_save_clip_writer_failure():
    """Test saving clip when video writer fails to open."""
    saver = ClipSaver(
        category="test_clips",
        write_format="mp4",
        fps=10,
        width=640,
        height=480,
    )

    frames = [np.zeros((480, 640, 3), dtype=np.uint8).tobytes()]

    with (
        patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
        patch("cv2.VideoWriter") as mock_writer_class,
    ):
        mock_base = Path("/tmp/test_clips")
        mock_get_path.return_value = mock_base
        mock_ensure.return_value = mock_base / "test-camera"

        mock_writer = Mock()
        mock_writer.isOpened.return_value = False  # Writer fails
        mock_writer_class.return_value = mock_writer

        with pytest.raises(RuntimeError, match="Failed to open video writer"):
            saver.save_clip(
                camera_id="test-camera",
                frames=frames,
            )


def test_clip_saver_save_clip_different_formats():
    """Test saving clips with different video formats."""
    for fmt in ["mp4", "avi", "mkv"]:
        saver = ClipSaver(
            category="test_clips",
            write_format=fmt,
            fps=10,
            width=640,
            height=480,
        )

        frames = [np.zeros((480, 640, 3), dtype=np.uint8).tobytes()]

        with (
            patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
            patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
            patch("cv2.VideoWriter") as mock_writer_class,
        ):
            mock_base = Path("/tmp/test_clips")
            mock_get_path.return_value = mock_base
            mock_ensure.return_value = mock_base / "test-camera"

            mock_writer = Mock()
            mock_writer.isOpened.return_value = True
            mock_writer_class.return_value = mock_writer

            clip_path = saver.save_clip(
                camera_id="test-camera",
                frames=frames,
            )

            assert f".{fmt}" in str(clip_path)


def test_clip_saver_save_clip_multiple_frames():
    """Test saving clip with many frames."""
    saver = ClipSaver(
        category="test_clips",
        write_format="mp4",
        fps=30,
        width=1920,
        height=1080,
    )

    # Create 30 frames (1 second at 30fps)
    frames = []
    for _i in range(30):
        frame = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
        frames.append(frame.tobytes())

    with (
        patch("orpheus_agent_video_motion.clip_saver.get_video_path") as mock_get_path,
        patch("orpheus_agent_video_motion.clip_saver.ensure_directory") as mock_ensure,
        patch("cv2.VideoWriter") as mock_writer_class,
    ):
        mock_base = Path("/tmp/test_clips")
        mock_get_path.return_value = mock_base
        mock_ensure.return_value = mock_base / "hd-camera"

        mock_writer = Mock()
        mock_writer.isOpened.return_value = True
        mock_writer_class.return_value = mock_writer

        saver.save_clip(
            camera_id="hd-camera",
            frames=frames,
        )

        assert mock_writer.write.call_count == 30


class TestEmbedMetadata:
    """Tests for ClipSaver._embed_metadata."""

    def _make_saver(self):
        return ClipSaver(
            category="video_motion",
            write_format="mp4",
            fps=10,
            width=640,
            height=480,
        )

    def test_success_embeds_metadata_via_ffmpeg(self, tmp_path):
        """subprocess.run succeeds — final_path is returned and tmp file cleaned up."""
        saver = self._make_saver()
        tmp_file = tmp_path / "clip.tmp.mp4"
        tmp_file.write_bytes(b"fake-video-data")
        final_file = tmp_path / "clip.mp4"
        metadata = {"camera": "cam-1", "score": 0.95}

        with patch("orpheus_agent_video_motion.clip_saver.subprocess.run") as mock_run:
            # Simulate ffmpeg creating the final file
            def side_effect(*args, **kwargs):
                final_file.write_bytes(b"tagged-video-data")

            mock_run.side_effect = side_effect

            result = saver._embed_metadata(tmp_file, final_file, metadata)

        assert result == final_file
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-metadata" in cmd
        comment_idx = cmd.index("-metadata") + 1
        assert comment_idx < len(cmd)
        assert json.loads(comment_idx and cmd[comment_idx].split("=", 1)[1]) == metadata

    def test_called_process_error_renames_tmp_to_final(self, tmp_path):
        """subprocess.run raises CalledProcessError — tmp file renamed to final path."""
        saver = self._make_saver()
        tmp_file = tmp_path / "clip.tmp.mp4"
        tmp_file.write_bytes(b"fake-video-data")
        final_file = tmp_path / "clip.mp4"
        metadata = {"event": "motion"}

        with patch("orpheus_agent_video_motion.clip_saver.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                returncode=1, cmd=["ffmpeg"], stderr=b"some error"
            )

            result = saver._embed_metadata(tmp_file, final_file, metadata)

        assert result == final_file
        assert final_file.exists()
        assert final_file.read_bytes() == b"fake-video-data"
        assert not tmp_file.exists()

    def test_file_not_found_error_renames_tmp_to_final(self, tmp_path):
        """subprocess.run raises FileNotFoundError (ffmpeg missing) — tmp renamed."""
        saver = self._make_saver()
        tmp_file = tmp_path / "clip.tmp.mp4"
        tmp_file.write_bytes(b"fake-video-data")
        final_file = tmp_path / "clip.mp4"
        metadata = {"event": "motion"}

        with patch("orpheus_agent_video_motion.clip_saver.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("No such file or directory: 'ffmpeg'")

            result = saver._embed_metadata(tmp_file, final_file, metadata)

        assert result == final_file
        assert final_file.exists()
        assert final_file.read_bytes() == b"fake-video-data"
        assert not tmp_file.exists()


@pytest.mark.skip(reason="Requires video codec installation")
def test_clip_saver_save_clip(tmp_path: Path):
    """Test saving a video clip."""
    saver = ClipSaver(
        category="test_clips",
        write_format="mp4",
        fps=10,
        width=640,
        height=480,
    )

    # Create test frames
    frames = []
    for i in range(10):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:, :] = (i * 25, 100, 150)  # Different color per frame
        frames.append(frame.tobytes())

    # Save clip
    clip_path = saver.save_clip(
        camera_id="test-camera",
        frames=frames,
        event_time=datetime.now(timezone.utc),
    )

    assert clip_path.exists()
    assert clip_path.suffix == ".mp4"
    assert "test-camera" in str(clip_path)
