"""Camera credentials live in the RTSP URL, so they must never reach the log."""

import sys
from unittest.mock import MagicMock, patch

import pytest
import structlog

CREDENTIALED_URL = "rtsp://cam-admin:s3cr3tpass@192.168.1.50:554/cam/realmonitor"


@pytest.fixture
def video_source_module():
    """Import the video source with a stub cv2.

    OpenCV is an agent-side dependency, absent from this venv; the redaction
    contract is platform behaviour and has to be pinned where it lives.
    """
    stub = MagicMock()
    stub.CAP_FFMPEG = 1900
    injected = "cv2" not in sys.modules
    if injected:
        sys.modules["cv2"] = stub
    try:
        from orpheus_common.video import source

        yield source
    finally:
        if injected:
            sys.modules.pop("cv2", None)


@pytest.mark.asyncio
async def test_rtsp_credentials_are_not_logged(video_source_module):
    source_module = video_source_module
    source = source_module.RTSPVideoSource(
        camera_id="north",
        rtsp_url=CREDENTIALED_URL,
        fps=5,
        width=640,
        height=480,
        max_pending_frames=2,
    )

    capture = MagicMock()
    capture.isOpened.return_value = True

    with patch.object(
        source_module.cv2, "VideoCapture", return_value=capture
    ), patch.object(source_module.threading, "Thread"), structlog.testing.capture_logs() as logs:
        await source._start_internal()

    emitted = str(logs)
    assert "s3cr3tpass" not in emitted
    assert "cam-admin" not in emitted
    # The host still has to be there or the log is useless for debugging.
    assert "192.168.1.50" in emitted
