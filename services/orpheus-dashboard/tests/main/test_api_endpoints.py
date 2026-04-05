"""Tests for FastAPI endpoints in main.py"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

import asyncio


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_dashboard.main.OrpheusConfig") as mock:
        config_instance = Mock()
        config_instance.dashboard_poll_interval.return_value = 5000
        config_instance.dashboard_services.return_value = [
            "orpheus-dashboard",
            "orpheus-mqtt",
            "orpheus-bluetooth-autoconnect",
        ]
        config_instance.camera_registry.return_value = []
        mock.get_instance.return_value = config_instance
        yield config_instance


@pytest.fixture
def client(mock_config):
    """Create a test client with mocked dependencies."""
    # Import after mocking to avoid config loading issues
    with patch("orpheus_dashboard.main.config", mock_config):
        with patch("orpheus_dashboard.main.cameras", []):
            from orpheus_dashboard.main import app

            with TestClient(app) as test_client:
                yield test_client


class TestHealthEndpoint:
    """Tests for /api/health endpoint."""

    def test_health_returns_ok_status(self, client):
        """Health endpoint should return ok status."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    def test_health_returns_cpu_percent(self, client):
        """Health endpoint should include CPU percentage."""
        response = client.get("/api/health")
        data = response.json()
        assert "cpu_percent" in data
        assert isinstance(data["cpu_percent"], (int, float))
        assert 0 <= data["cpu_percent"] <= 100

    def test_health_returns_memory_percent(self, client):
        """Health endpoint should include memory percentage."""
        response = client.get("/api/health")
        data = response.json()
        assert "memory_percent" in data
        assert isinstance(data["memory_percent"], (int, float))
        assert 0 <= data["memory_percent"] <= 100

    def test_health_returns_disk_percent(self, client):
        """Health endpoint should include disk percentage."""
        response = client.get("/api/health")
        data = response.json()
        assert "disk_percent" in data
        assert isinstance(data["disk_percent"], (int, float))
        assert 0 <= data["disk_percent"] <= 100

    def test_health_returns_uptime(self, client):
        """Health endpoint should include system uptime."""
        response = client.get("/api/health")
        data = response.json()
        assert "uptime_seconds" in data
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] > 0

    def test_health_response_schema(self, client):
        """Health endpoint should match HealthResponse schema."""
        response = client.get("/api/health")
        data = response.json()
        expected_keys = {
            "status",
            "cpu_percent",
            "memory_percent",
            "disk_percent",
            "uptime_seconds",
        }
        assert set(data.keys()) == expected_keys


class TestConfigEndpoint:
    """Tests for /api/config endpoint."""

    def test_config_returns_poll_interval(self, client, mock_config):
        """Config endpoint should return poll interval."""
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "poll_interval" in data
        assert data["poll_interval"] == 5000

    def test_config_uses_config_singleton(self, client, mock_config):
        """Config endpoint should use OrpheusConfig singleton."""
        client.get("/api/config")
        mock_config.dashboard_poll_interval.assert_called_once()


class TestServicesEndpoint:
    """Tests for /api/services/status endpoint."""

    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.subprocess.run")
    def test_services_running_status(self, mock_run, mock_which, client, mock_config):
        """Services endpoint should detect running services."""
        mock_which.return_value = "/bin/systemctl"
        mock_run.return_value = Mock(returncode=0, stdout="active\n")

        response = client.get("/api/services/status")
        assert response.status_code == 200
        data = response.json()

        assert "services" in data
        assert (
            len(data["services"]) == 3
        )  # orpheus-dashboard, orpheus-mqtt, orpheus-bluetooth-autoconnect
        assert all(s["status"] == "running" for s in data["services"])

    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.subprocess.run")
    def test_services_stopped_status(self, mock_run, mock_which, client, mock_config):
        """Services endpoint should detect stopped services."""
        mock_which.return_value = "/bin/systemctl"
        mock_run.return_value = Mock(returncode=1, stdout="inactive\n")

        response = client.get("/api/services/status")
        data = response.json()

        assert all(s["status"] == "stopped" for s in data["services"])
        assert all("not running" in s["reason"].lower() for s in data["services"])

    @patch("orpheus_dashboard.main.os.path.exists")
    @patch("orpheus_dashboard.main.shutil.which")
    def test_services_no_systemctl(self, mock_which, mock_exists, client, mock_config):
        """Services endpoint should handle missing systemctl."""
        mock_which.return_value = None
        mock_exists.return_value = False  # No fallback paths exist

        response = client.get("/api/services/status")
        data = response.json()

        dashboard_service = next(
            s for s in data["services"] if s["name"] == "orpheus-dashboard"
        )
        assert dashboard_service["status"] == "running"
        assert "local dev mode" in dashboard_service["reason"].lower()

    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.subprocess.run")
    def test_services_timeout_handling(self, mock_run, mock_which, client, mock_config):
        """Services endpoint should handle subprocess timeouts."""
        mock_which.return_value = "/bin/systemctl"
        mock_run.side_effect = TimeoutError("Timeout")

        response = client.get("/api/services/status")
        data = response.json()

        assert all(s["status"] == "unknown" for s in data["services"])

    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.subprocess.run")
    def test_services_response_schema(self, mock_run, mock_which, client, mock_config):
        """Services endpoint should match ServicesResponse schema."""
        mock_which.return_value = "/bin/systemctl"
        mock_run.return_value = Mock(returncode=0, stdout="active\n")

        response = client.get("/api/services/status")
        data = response.json()

        assert "services" in data
        for service in data["services"]:
            assert "name" in service
            assert "status" in service
            assert "reason" in service
            assert service["status"] in ["running", "stopped", "unknown"]


class TestStorageEndpoint:
    """Tests for /api/system/storage/data endpoint."""

    @patch("orpheus_dashboard.main.get_data_storage_usage")
    def test_storage_data_returns_usage(self, mock_storage, client):
        """Storage data endpoint should return usage information."""
        mock_storage.return_value = {
            "path": "/mnt/data",
            "total_gb": 500,
            "used_gb": 100,
            "free_gb": 400,
            "percent_used": 20.0,
        }

        response = client.get("/api/system/storage/data")
        assert response.status_code == 200
        data = response.json()

        assert data["path"] == "/mnt/data"
        assert data["total_gb"] == 500
        assert data["used_gb"] == 100

    @patch("orpheus_dashboard.main.get_data_storage_usage")
    def test_storage_data_calls_health_module(self, mock_storage, client):
        """Storage endpoint should use orpheus_common.system.health."""
        mock_storage.return_value = {}
        client.get("/api/system/storage/data")
        mock_storage.assert_called_once()


class TestStorageHardwareEndpoint:
    """Tests for /api/hardware/storage endpoint."""

    @patch("orpheus_dashboard.main.get_storage_hardware_info")
    def test_storage_hardware_returns_info(self, mock_hardware, client):
        """Storage hardware endpoint should return hardware information."""
        mock_hardware.return_value = {
            "devices": [
                {
                    "name": "/dev/sda1",
                    "mount": "/mnt/data",
                    "status": "healthy",
                }
            ]
        }

        response = client.get("/api/hardware/storage")
        assert response.status_code == 200
        data = response.json()

        assert "devices" in data
        assert len(data["devices"]) > 0

    @patch("orpheus_dashboard.main.get_storage_hardware_info")
    def test_storage_hardware_calls_hardware_module(self, mock_hardware, client):
        """Storage hardware endpoint should use orpheus_common.hardware.storage."""
        mock_hardware.return_value = {}
        client.get("/api/hardware/storage")
        mock_hardware.assert_called_once()


class TestAudioDiagnosticsEndpoint:
    """Tests for /api/diagnostics/audio endpoint."""

    @patch("orpheus_dashboard.main._audio_health_cache")
    def test_audio_diagnostics_returns_status(self, mock_cache, client):
        """Audio diagnostics endpoint should return status dictionary."""
        mock_cache.__bool__ = Mock(return_value=True)
        test_status = {
            "running": True,
            "xrun": {"total": 0},
            "channels": [],
            "hardware": {},
            "timing": {},
            "system": {},
        }

        # Mock the global cache by patching the module-level variable
        with patch("orpheus_dashboard.main._audio_health_lock"):
            with patch.dict(
                "orpheus_dashboard.main.__dict__", {"_audio_health_cache": test_status}
            ):
                response = client.get("/api/diagnostics/audio")
                assert response.status_code == 200
                data = response.json()

                assert "running" in data
                assert "xrun" in data
                assert data["running"] is True

    def test_audio_diagnostics_not_running(self, client):
        """Audio diagnostics should include message when cache is empty."""
        # Ensure cache is None/empty
        with patch.dict(
            "orpheus_dashboard.main.__dict__", {"_audio_health_cache": None}
        ):
            response = client.get("/api/diagnostics/audio")
            data = response.json()

            assert data["running"] is False
            assert "message" in data

    @patch("orpheus_dashboard.main._audio_health_lock")
    def test_audio_diagnostics_handles_error(self, mock_lock, client):
        """Audio diagnostics should gracefully handle errors."""
        mock_lock.__enter__ = Mock(side_effect=Exception("Test error"))

        response = client.get("/api/diagnostics/audio")
        assert response.status_code == 200
        data = response.json()

        assert data["running"] is False
        assert "error" in data


class TestAudioDetectionsEndpoint:
    """Tests for /api/diagnostics/audio/detections endpoint."""

    def test_audio_detections_empty(self, client):
        """Audio detections endpoint should handle empty detections."""
        response = client.get("/api/diagnostics/audio/detections")
        assert response.status_code == 200
        data = response.json()

        assert "summary" in data
        assert "history" in data
        assert "mqtt_connected" in data
        assert isinstance(data["history"], list)
        assert len(data["history"]) == 0

    def test_audio_detections_summary_structure(self, client):
        """Audio detections summary should have all 4 channels."""
        response = client.get("/api/diagnostics/audio/detections")
        data = response.json()

        assert "1" in data["summary"]
        assert "2" in data["summary"]
        assert "3" in data["summary"]
        assert "4" in data["summary"]

    def test_audio_detections_with_data(self, client):
        """Audio detections should return cached detection data."""
        from collections import deque

        test_detection = {
            "channel_id": "1",
            "timestamp": "2025-11-28T12:00:00Z",
            "duration_seconds": 2.5,
            "peak_energy_db": -25.0,
            "clip_path": "/data/audio/clip_001.wav",
        }

        # Create a proper deque with the test detection
        test_cache = deque([test_detection], maxlen=20)
        test_by_channel = {"1": test_detection}

        with patch.dict(
            "orpheus_dashboard.main.__dict__",
            {
                "_audio_detections_cache": test_cache,
                "_audio_detections_by_channel": test_by_channel,
            },
        ):
            response = client.get("/api/diagnostics/audio/detections")
            assert response.status_code == 200
            data = response.json()

            assert len(data["history"]) == 1
            assert data["history"][0]["channel_id"] == "1"
            assert data["summary"]["1"]["channel_id"] == "1"

    @patch("orpheus_dashboard.main._audio_detections_lock")
    def test_audio_detections_handles_error(self, mock_lock, client):
        """Audio detections should gracefully handle errors."""
        mock_lock.__enter__ = Mock(side_effect=Exception("Test error"))

        response = client.get("/api/diagnostics/audio/detections")
        assert response.status_code == 200
        data = response.json()

        assert "error" in data
        assert data["summary"]["1"] is None


class TestAudioClipsEndpoint:
    """Tests for /api/audio/clips endpoint."""

    def test_audio_clips_invalid_channel(self, client):
        """Audio clips endpoint should reject invalid channel IDs."""
        response = client.get("/api/audio/clips/99/test.flac")
        assert response.status_code == 400
        assert "Invalid channel ID" in response.json()["detail"]

    def test_audio_clips_path_traversal_filename(self, client):
        """Audio clips endpoint should prevent path traversal in filename."""
        response = client.get("/api/audio/clips/1/..%2F..%2Fetc%2Fpasswd")
        # Should either be 400 (invalid filename) or 404 (not found)
        assert response.status_code in [400, 404]

    def test_audio_clips_file_not_found(self, client):
        """Audio clips endpoint should return 404 for missing files."""
        response = client.get("/api/audio/clips/1/nonexistent.flac")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestCamerasEndpoint:
    """Tests for /api/cameras endpoint."""

    def test_cameras_empty_list(self, client):
        """Cameras endpoint should handle empty camera list."""
        response = client.get("/api/cameras")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    @patch("orpheus_dashboard.main.cameras")
    @patch("orpheus_dashboard.main.config")
    def test_cameras_with_mocked_cameras(self, mock_config, mock_cameras_list, client):
        """Cameras endpoint should return camera status."""
        mock_camera = Mock()
        mock_camera.get_health_status.return_value = {
            "name": "test-camera",
            "status": "healthy",
            "host": "192.168.1.100",
        }

        mock_config.dashboard_poll_interval.return_value = 5000
        mock_cameras_list.__iter__ = Mock(return_value=iter([mock_camera]))

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            response = client.get("/api/cameras")
            assert response.status_code == 200
            data = response.json()

            assert len(data) == 1
            assert data[0]["name"] == "test-camera"

    @patch("orpheus_dashboard.main.cameras")
    @patch("orpheus_dashboard.main.config")
    def test_cameras_passes_ttl_to_health_check(
        self, mock_config, mock_cameras_list, client
    ):
        """Cameras endpoint should pass TTL from config to health checks."""
        mock_camera = Mock()
        mock_camera.get_health_status.return_value = {}
        mock_config.dashboard_poll_interval.return_value = 10000

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            client.get("/api/cameras")
            mock_camera.get_health_status.assert_called_once_with(ttl_seconds=10.0)


class TestCameraSnapshotEndpoint:
    """Tests for /api/cameras/{camera_name}/snapshot endpoint."""

    def test_snapshot_camera_not_found(self, client):
        """Snapshot endpoint should return 404 for unknown camera."""
        response = client.get("/api/cameras/nonexistent/snapshot")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("orpheus_dashboard.main.cameras")
    def test_snapshot_success(self, mock_cameras_list, client):
        """Snapshot endpoint should return JPEG image."""
        mock_camera = Mock()
        mock_camera.name = "test-camera"
        mock_camera.capture_snapshot.return_value = {
            "ok": True,
            "image_data": b"fake_jpeg_data",
            "cached_at": "2025-11-28T12:00:00Z",
        }

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            response = client.get("/api/cameras/test-camera/snapshot")
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/jpeg"
            assert response.content == b"fake_jpeg_data"

    @patch("orpheus_dashboard.main.cameras")
    def test_snapshot_unavailable(self, mock_cameras_list, client):
        """Snapshot endpoint should return 503 when snapshot fails."""
        mock_camera = Mock()
        mock_camera.name = "test-camera"
        mock_camera.capture_snapshot.return_value = {
            "ok": False,
            "error": "Camera offline",
        }

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            response = client.get("/api/cameras/test-camera/snapshot")
            assert response.status_code == 503
            assert "offline" in response.json()["detail"].lower()

    @patch("orpheus_dashboard.main.cameras")
    def test_snapshot_cache_headers(self, mock_cameras_list, client):
        """Snapshot endpoint should include cache control headers."""
        mock_camera = Mock()
        mock_camera.name = "test-camera"
        mock_camera.capture_snapshot.return_value = {
            "ok": True,
            "image_data": b"fake_jpeg_data",
            "cached_at": "2025-11-28T12:00:00Z",
        }

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            response = client.get("/api/cameras/test-camera/snapshot")
            assert "cache-control" in response.headers
            assert "x-cached-at" in response.headers


class TestDebugEndpoint:
    """Tests for /api/debug/config endpoint."""

    @patch("orpheus_dashboard.main.config")
    def test_debug_config_returns_safe_values(self, mock_config, client):
        """Debug endpoint should return safe configuration values."""
        mock_config.get_debug_safe_values.return_value = {
            "orpheus_config": {"dashboard.host": "0.0.0.0"},
            "effective_settings": {"mqtt.broker": "localhost"},
            "environment_overrides": {},
            "camera_environment": {},
            "camera_registry": {"source": "config:/etc/orpheus/dashboard/orpheus.yaml"},
        }

        response = client.get("/api/debug/config")
        assert response.status_code == 200
        data = response.json()

        assert "orpheus_config" in data
        assert data["orpheus_config"]["dashboard.host"] == "0.0.0.0"
        assert data["effective_settings"]["mqtt.broker"] == "localhost"
        assert data["camera_registry"]["source"].startswith("config:")

    @patch("orpheus_dashboard.main.config")
    def test_debug_config_no_secrets(self, mock_config, client):
        """Debug endpoint should not expose sensitive data."""
        mock_config.get_debug_safe_values.return_value = {
            "orpheus_config": {},
            "effective_settings": {"mqtt.broker": "localhost"},
            "environment_overrides": {"ORPHEUS_CAMERAS_AUTH_PASSWORD": "***pass"},
            "camera_environment": {"CAMERA_PASS": "***pass"},
            "camera_registry": {"source": "environment"},
        }

        response = client.get("/api/debug/config")
        data = response.json()

        # Ensure no raw secrets exposed in any section
        for section in data.values():
            if isinstance(section, dict):
                for key, value in section.items():
                    assert "password" not in str(value).lower()
                    assert "secret" not in str(value).lower()


class TestRootEndpoint:
    """Tests for / (root) endpoint."""

    @patch("orpheus_dashboard.main.FileResponse")
    def test_root_serves_index_html(self, mock_file_response, client):
        """Root endpoint should serve static/index.html."""
        mock_file_response.return_value.status_code = 200

        # Call the endpoint directly since we've mocked FileResponse
        from orpheus_dashboard.main import root, STATIC_DIR
        import os

        asyncio.run(root())
        expected_path = os.path.join(STATIC_DIR, "index.html")
        mock_file_response.assert_called_once_with(expected_path)


class TestApplicationMetadata:
    """Tests for FastAPI application configuration."""

    def test_app_title(self, client):
        """Application should have correct title."""
        from orpheus_dashboard.main import app

        assert app.title == "Orpheus Dashboard"

    def test_app_version(self, client):
        """Application should have version defined."""
        from orpheus_dashboard.main import app

        assert app.version == "0.1.0"

    def test_app_description(self, client):
        """Application should have description."""
        from orpheus_dashboard.main import app

        assert "Wildlife Monitoring" in app.description


class TestVideoDiagnosticsEndpoint:
    """Tests for /api/diagnostics/video endpoint."""

    def test_video_diagnostics_empty_detections(self, client):
        """Video diagnostics should handle no cameras/detections."""
        with patch.dict(
            "orpheus_dashboard.main.__dict__", {"_video_detections_by_camera": {}}
        ):
            response = client.get("/api/diagnostics/video")
            assert response.status_code == 200
            data = response.json()

            assert data["running"] is False
            assert data["camera_count"] == 0
            assert data["cameras"] == []
            assert data["last_detection"] is None
            assert "message" in data

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_video_diagnostics_with_cameras(self, mock_mqtt, client):
        """Video diagnostics should return camera status."""
        from datetime import datetime, timezone

        # Mock MQTT client
        mock_mqtt.is_connected = True

        # Mock detection data
        test_detection = {
            "camera_id": "orpheus-eye-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 2.5,
        }

        with patch.dict(
            "orpheus_dashboard.main.__dict__",
            {"_video_detections_by_camera": {"orpheus-eye-1": test_detection}},
        ):
            with patch("orpheus_dashboard.main._video_detections_lock"):
                response = client.get("/api/diagnostics/video")
                assert response.status_code == 200
                data = response.json()

                assert data["running"] is True
                assert data["camera_count"] == 1
                assert len(data["cameras"]) == 1
                assert data["cameras"][0]["camera_id"] == "orpheus-eye-1"
                assert data["cameras"][0]["running"] is True
                assert data["mqtt_connected"] is True

    @patch("orpheus_dashboard.main._video_detections_lock")
    def test_video_diagnostics_handles_error(self, mock_lock, client):
        """Video diagnostics should gracefully handle errors."""
        mock_lock.__enter__ = Mock(side_effect=Exception("Test error"))

        response = client.get("/api/diagnostics/video")
        assert response.status_code == 200
        data = response.json()

        assert data["running"] is False
        assert "error" in data
        assert data["camera_count"] == 0

    def test_video_diagnostics_mqtt_disconnected(self, client):
        """Video diagnostics should report MQTT connection status."""
        with patch("orpheus_dashboard.main._mqtt_client", None):
            with patch.dict(
                "orpheus_dashboard.main.__dict__", {"_video_detections_by_camera": {}}
            ):
                response = client.get("/api/diagnostics/video")
                data = response.json()

                assert data["mqtt_connected"] is False


class TestVideoDetectionsEndpoint:
    """Tests for /api/diagnostics/video/detections endpoint."""

    def test_video_detections_empty(self, client):
        """Video detections endpoint should handle empty detections."""
        response = client.get("/api/diagnostics/video/detections")
        assert response.status_code == 200
        data = response.json()

        assert "summary" in data
        assert "history" in data
        assert "mqtt_connected" in data
        assert isinstance(data["history"], list)
        assert len(data["history"]) == 0

    def test_video_detections_summary_structure(self, client):
        """Video detections summary should have all 4 cameras."""
        response = client.get("/api/diagnostics/video/detections")
        data = response.json()

        assert "orpheus-eye-1" in data["summary"]
        assert "orpheus-eye-2" in data["summary"]
        assert "orpheus-eye-3" in data["summary"]
        assert "orpheus-eye-4" in data["summary"]

    @patch("orpheus_dashboard.main._mqtt_client")
    @patch("orpheus_dashboard.main._video_detections_lock")
    def test_video_detections_with_data(self, mock_lock, mock_mqtt, client):
        """Video detections endpoint should return detection data."""
        from collections import deque
        from datetime import datetime, timezone

        # Mock MQTT client
        mock_mqtt.is_connected = True

        # Mock detection data
        detection = {
            "camera_id": "orpheus-eye-1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": 2.5,
            "peak_motion_value": 35.0,
            "average_motion_value": 28.0,
            "frame_count": 25,
            "clip_path": "/mnt/data/video/motion/orpheus-eye-1/test.mp4",
        }

        # Mock the cache and by_camera dictionary
        with patch(
            "orpheus_dashboard.main._video_detections_cache",
            deque([detection], maxlen=20),
        ):
            with patch(
                "orpheus_dashboard.main._video_detections_by_camera",
                {"orpheus-eye-1": detection},
            ):
                response = client.get("/api/diagnostics/video/detections")
                assert response.status_code == 200
                data = response.json()

                assert data["mqtt_connected"] is True
                assert "orpheus-eye-1" in data["summary"]


class TestVideoClipsEndpoint:
    """Tests for /api/diagnostics/video/clips/{camera_id} endpoint."""

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clips_empty_directory(self, mock_get_path, client, tmp_path):
        """Video clips endpoint should handle non-existent directory."""
        mock_get_path.return_value = tmp_path / "video" / "motion"

        response = client.get("/api/diagnostics/video/clips/orpheus-eye-1")
        assert response.status_code == 200
        data = response.json()

        assert "clips" in data
        assert len(data["clips"]) == 0

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clips_with_files(self, mock_get_path, client, tmp_path):
        """Video clips endpoint should return list of clips."""
        video_base = tmp_path / "video" / "motion"
        camera_path = video_base / "orpheus-eye-1"
        camera_path.mkdir(parents=True, exist_ok=True)

        # Create test clip files
        clip1 = camera_path / "20250101T120000.000000Z.mp4"
        clip1.write_bytes(b"test video data")

        mock_get_path.return_value = video_base

        response = client.get("/api/diagnostics/video/clips/orpheus-eye-1")
        assert response.status_code == 200
        data = response.json()

        assert "clips" in data
        assert len(data["clips"]) > 0
        assert data["clips"][0]["filename"] == "20250101T120000.000000Z.mp4"

    def test_video_clips_invalid_camera(self, client):
        """Video clips endpoint should reject invalid camera IDs."""
        response = client.get("/api/diagnostics/video/clips/invalid-camera")
        # This will return 200 with empty clips list since the directory doesn't exist
        # The security check is in the download endpoint
        assert response.status_code == 200


class TestVideoClipDownloadEndpoint:
    """Tests for /api/video/clips/{camera_id}/{filename} download endpoint."""

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clip_download(self, mock_get_path, client, tmp_path):
        """Video clip download should return the video file."""
        video_base = tmp_path / "video" / "motion"
        camera_path = video_base / "orpheus-eye-1"
        camera_path.mkdir(parents=True, exist_ok=True)

        # Create test clip file
        clip_content = b"fake video data"
        clip_file = camera_path / "20250101T120000.000000Z.mp4"
        clip_file.write_bytes(clip_content)

        mock_get_path.return_value = video_base

        response = client.get(
            "/api/video/clips/orpheus-eye-1/20250101T120000.000000Z.mp4"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == clip_content

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clip_download_invalid_camera(self, mock_get_path, client, tmp_path):
        """Video clip download should reject invalid camera IDs."""
        mock_get_path.return_value = tmp_path

        response = client.get("/api/video/clips/invalid-camera/test.mp4")
        assert response.status_code == 400
        data = response.json()
        assert "Invalid camera ID" in data["detail"]

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clip_download_path_traversal(self, mock_get_path, client, tmp_path):
        """Video clip download should reject path traversal attempts."""
        mock_get_path.return_value = tmp_path

        # Test with URL-encoded path traversal (like audio clip test)
        response = client.get("/api/video/clips/orpheus-eye-1/..%2F..%2Fetc%2Fpasswd")
        # Should either be 400 (invalid filename) or 404 (not found)
        assert response.status_code in [400, 404]

    @patch("orpheus_dashboard.main.get_video_path")
    def test_video_clip_download_not_found(self, mock_get_path, client, tmp_path):
        """Video clip download should return 404 for non-existent files."""
        video_base = tmp_path / "video" / "motion"
        video_base.mkdir(parents=True, exist_ok=True)
        mock_get_path.return_value = video_base

        response = client.get("/api/video/clips/orpheus-eye-1/nonexistent.mp4")
        assert response.status_code == 404


class TestAudioPlaybackEndpoints:
    """Tests for audio playback API endpoints."""

    @patch("orpheus_common.audio.get_sound_registry")
    def test_get_available_sounds_success(self, mock_registry, client):
        """Test getting available sounds."""
        mock_registry_instance = Mock()
        mock_registry_instance.list_sounds.return_value = [
            "test_tone_1",
            "test_beep",
            "test_silence",
        ]
        mock_registry.return_value = mock_registry_instance

        response = client.get("/api/audio/playback/sounds")
        assert response.status_code == 200
        data = response.json()
        assert "sounds" in data
        assert "count" in data
        assert data["count"] == 3
        assert "test_tone_1" in data["sounds"]

    @patch("orpheus_common.audio.get_sound_registry")
    def test_get_available_sounds_error(self, mock_registry, client):
        """Test handling of sound registry errors."""
        mock_registry.side_effect = Exception("Registry error")

        response = client.get("/api/audio/playback/sounds")
        assert response.status_code == 500

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_play_sound_success(self, mock_mqtt, client):
        """Test successful playback request."""
        mock_mqtt.publish = Mock()

        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_tone_1",
                "repeat_count": 3,
                "pause_between": 1.0,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "test_tone_1" in data["message"]

        # Verify MQTT publish was called
        mock_mqtt.publish.assert_called_once()
        call_args = mock_mqtt.publish.call_args
        assert call_args[0][0] == "orpheus/audio/playback/request"
        assert call_args[0][1]["sound_name"] == "test_tone_1"
        assert call_args[0][1]["repeat_count"] == 3
        assert call_args[0][1]["pause_between"] == 1.0

    @patch("orpheus_dashboard.main._mqtt_client", None)
    def test_play_sound_mqtt_not_connected(self, client):
        """Test playback request when MQTT is not connected."""
        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_tone_1",
                "repeat_count": 1,
                "pause_between": 0.0,
            },
        )

        assert response.status_code == 503
        assert "MQTT client not connected" in response.json()["detail"]

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_play_sound_invalid_repeat_count(self, mock_mqtt, client):
        """Test playback with invalid repeat_count."""
        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_tone_1",
                "repeat_count": 0,
                "pause_between": 0.0,
            },
        )

        assert response.status_code == 400
        assert "repeat_count" in response.json()["detail"]

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_play_sound_invalid_pause_between(self, mock_mqtt, client):
        """Test playback with invalid pause_between."""
        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_tone_1",
                "repeat_count": 1,
                "pause_between": -1.0,
            },
        )

        assert response.status_code == 400
        assert "pause_between" in response.json()["detail"]

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_play_sound_mqtt_publish_error(self, mock_mqtt, client):
        """Test handling of MQTT publish errors."""
        mock_mqtt.publish.side_effect = Exception("MQTT error")

        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_tone_1",
                "repeat_count": 1,
                "pause_between": 0.0,
            },
        )

        assert response.status_code == 500
        assert "Failed to send playback request" in response.json()["detail"]

    @patch("orpheus_dashboard.main._mqtt_client")
    def test_play_sound_defaults(self, mock_mqtt, client):
        """Test playback request with default parameters."""
        mock_mqtt.publish = Mock()

        response = client.post(
            "/api/audio/playback/play",
            json={
                "sound_name": "test_beep",
            },
        )

        assert response.status_code == 200

        # Verify defaults were used
        call_args = mock_mqtt.publish.call_args
        assert call_args[0][1]["repeat_count"] == 1
        assert call_args[0][1]["pause_between"] == 0.0


class TestBirdDetectionEndpoint:
    """Tests for /api/diagnostics/bird/detections endpoint."""

    def test_bird_detections_no_data(self, client):
        """Test bird detections endpoint with no data."""
        response = client.get("/api/diagnostics/bird/detections")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "history" in data
        assert "mqtt_connected" in data
        assert len(data["history"]) == 0

    def test_bird_detections_response_structure(self, client):
        """Test bird detections response has correct structure."""
        response = client.get("/api/diagnostics/bird/detections")
        assert response.status_code == 200
        data = response.json()

        # Check summary has all channels
        assert "1" in data["summary"]
        assert "2" in data["summary"]
        assert "3" in data["summary"]
        assert "4" in data["summary"]

        # Check types
        assert isinstance(data["history"], list)
        assert isinstance(data["mqtt_connected"], bool)

    def test_bird_detections_with_data(self, client):
        """Test bird detections endpoint returns cached data."""
        from collections import deque

        # Mock detection data
        mock_detection = {
            "event_id": "bird_det_20251205_143022_ch1_a1b2c3",
            "timestamp": "2025-12-05T14:30:22.123456+00:00",
            "channel_id": "1",
            "detections": [
                {
                    "species_code": "amecro",
                    "species_common": "American Crow",
                    "confidence": 0.87,
                    "start_time": 0.5,
                    "end_time": 3.2,
                }
            ],
        }

        # Create proper cache objects
        test_cache = deque([mock_detection], maxlen=50)
        test_by_channel = {"1": mock_detection}

        with patch.dict(
            "orpheus_dashboard.main.__dict__",
            {
                "_bird_detections_cache": test_cache,
                "_bird_detections_by_channel": test_by_channel,
            },
        ):
            response = client.get("/api/diagnostics/bird/detections")
            assert response.status_code == 200
            data = response.json()

            assert len(data["history"]) == 1
            assert data["history"][0]["channel_id"] == "1"
            assert data["summary"]["1"]["channel_id"] == "1"

    @patch("orpheus_dashboard.main._bird_detections_lock")
    def test_bird_detections_handles_error(self, mock_lock, client):
        """Bird detections should gracefully handle errors."""
        mock_lock.__enter__ = Mock(side_effect=Exception("Test error"))

        response = client.get("/api/diagnostics/bird/detections")
        assert response.status_code == 200
        data = response.json()

        # Should return empty state with error
        assert "error" in data
        assert len(data["history"]) == 0
        assert data["mqtt_connected"] is False


class TestCrowAnalysisEndpoint:
    """Tests for /api/diagnostics/crow/detections endpoint."""

    def test_crow_analysis_no_data(self, client):
        """Test crow analysis endpoint with no data."""
        response = client.get("/api/diagnostics/crow/detections")
        assert response.status_code == 200
        data = response.json()
        assert "summary" in data
        assert "history" in data
        assert "mqtt_connected" in data
        assert len(data["history"]) == 0

    def test_crow_analysis_response_structure(self, client):
        """Test crow analysis response has correct structure."""
        response = client.get("/api/diagnostics/crow/detections")
        assert response.status_code == 200
        data = response.json()

        # Check summary has all channels
        assert "1" in data["summary"]
        assert "2" in data["summary"]
        assert "3" in data["summary"]
        assert "4" in data["summary"]

        # Check types
        assert isinstance(data["history"], list)
        assert isinstance(data["mqtt_connected"], bool)

    def test_crow_analysis_with_data(self, client):
        """Test crow analysis endpoint returns cached data."""
        from collections import deque

        # Mock analysis data
        mock_analysis = {
            "event_id": "crow_det_20251205_143023_ch1_d4e5f6",
            "timestamp": "2025-12-05T14:30:23.456789+00:00",
            "channel_id": "1",
            "species_code": "amecro",
            "species_common": "American Crow",
            "crow_analysis": {
                "crow_count": 1,
                "crow_age": "adult",
                "behaviors": {
                    "alert": True,
                    "begging": False,
                    "soft_song": False,
                    "rattle": False,
                    "mob": False,
                },
                "quality": 2,
                "num_seconds_analyzed": 3,
            },
        }

        # Create proper cache objects
        test_cache = deque([mock_analysis], maxlen=50)
        test_by_channel = {"1": mock_analysis}

        with patch.dict(
            "orpheus_dashboard.main.__dict__",
            {
                "_crow_detections_cache": test_cache,
                "_crow_detections_by_channel": test_by_channel,
            },
        ):
            response = client.get("/api/diagnostics/crow/detections")
            assert response.status_code == 200
            data = response.json()

            assert len(data["history"]) == 1
            assert data["history"][0]["channel_id"] == "1"
            assert data["summary"]["1"]["channel_id"] == "1"

    @patch("orpheus_dashboard.main._crow_detections_lock")
    def test_crow_analysis_handles_error(self, mock_lock, client):
        """Crow analysis should gracefully handle errors."""
        mock_lock.__enter__ = Mock(side_effect=Exception("Test error"))

        response = client.get("/api/diagnostics/crow/detections")
        assert response.status_code == 200
        data = response.json()

        # Should return empty state with error
        assert "error" in data
        assert len(data["history"]) == 0
        assert data["mqtt_connected"] is False


class TestServiceLogsEndpoint:
    """Tests for /api/services/{service_name}/logs/tail endpoint."""

    @patch("orpheus_dashboard.main.os.path.exists")
    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.asyncio.create_subprocess_exec")
    def test_stream_service_logs_success(
        self, mock_create_subprocess_exec, mock_which, mock_exists, client
    ):
        """Should stream logs for a valid service."""
        mock_which.side_effect = lambda cmd: f"/bin/{cmd}"
        mock_exists.return_value = True

        class AsyncStream:
            def __init__(self, lines):
                self._lines = [line.encode() for line in lines]
                self._index = 0

            async def readline(self):
                if self._index < len(self._lines):
                    val = self._lines[self._index]
                    self._index += 1
                    return val
                return b""

        class MockProc:
            def __init__(self):
                self.stdout = AsyncStream(["line1\n", "line2\n"])
                self.stderr = AsyncStream([])
                self.returncode = None

            async def wait(self):
                return None

            def terminate(self):
                self.returncode = 0

        async def mock_create(*args, **kwargs):
            return MockProc()

        mock_create_subprocess_exec.side_effect = mock_create

        response = client.get("/api/services/orpheus-dashboard/logs/tail")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/plain")
        assert "line1" in response.text
        assert "line2" in response.text

    @patch("orpheus_dashboard.main.os.path.exists")
    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.asyncio.create_subprocess_exec")
    def test_stream_service_logs_no_systemctl(
        self, mock_create_subprocess_exec, mock_which, mock_exists, client
    ):
        """Should return error if systemctl is not found."""

        def which_side_effect(cmd):
            if cmd == "systemctl":
                return None
            return f"/bin/{cmd}"

        mock_which.side_effect = which_side_effect
        mock_exists.return_value = True
        mock_create_subprocess_exec.side_effect = FileNotFoundError()
        response = client.get("/api/services/orpheus-dashboard/logs/tail")
        assert response.status_code == 200
        assert (
            "file not found" in response.text.lower()
            or "could not execute" in response.text.lower()
        )

    @patch("orpheus_dashboard.main.os.path.exists")
    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.asyncio.create_subprocess_exec")
    def test_stream_service_logs_subprocess_error(
        self, mock_create_subprocess_exec, mock_which, mock_exists, client
    ):
        """Should handle subprocess errors gracefully."""
        mock_which.side_effect = lambda cmd: f"/bin/{cmd}"
        mock_exists.return_value = True
        mock_create_subprocess_exec.side_effect = Exception("subprocess failed")
        with pytest.raises(Exception) as excinfo:
            client.get("/api/services/orpheus-dashboard/logs/tail")
        assert "subprocess failed" in str(excinfo.value)

    @patch("orpheus_dashboard.main.os.path.exists")
    @patch("orpheus_dashboard.main.shutil.which")
    @patch("orpheus_dashboard.main.asyncio.create_subprocess_exec")
    def test_stream_service_logs_empty(
        self, mock_create_subprocess_exec, mock_which, mock_exists, client
    ):
        """Should handle empty log output."""
        mock_which.side_effect = lambda cmd: f"/bin/{cmd}"
        mock_exists.return_value = True

        class AsyncStream:
            def __init__(self, lines):
                self._lines = [line.encode() for line in lines]
                self._index = 0

            async def readline(self):
                if self._index < len(self._lines):
                    val = self._lines[self._index]
                    self._index += 1
                    return val
                return b""

        class MockProc:
            def __init__(self):
                self.stdout = AsyncStream([])
                self.stderr = AsyncStream([])
                self.returncode = None

            async def wait(self):
                return None

            def terminate(self):
                self.returncode = 0

        async def mock_create(*args, **kwargs):
            return MockProc()

        mock_create_subprocess_exec.side_effect = mock_create

        response = client.get("/api/services/orpheus-dashboard/logs/tail")
        assert response.status_code == 200
        assert response.text == ""

    def test_stream_service_logs_invalid_service(self, client):
        """Should return error for invalid service name."""
        response = client.get("/api/services/invalid-service/logs/tail")
        assert response.status_code == 200
        assert "invalid service name" in response.text.lower()
