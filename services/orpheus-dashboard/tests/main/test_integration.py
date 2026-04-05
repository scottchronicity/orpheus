"""Integration tests for main.py endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch


@pytest.fixture
def integration_client():
    """Create client with realistic mocks."""
    with patch("orpheus_dashboard.main.OrpheusConfig") as mock_config_class:
        config_instance = Mock()
        config_instance.dashboard_poll_interval.return_value = 5000
        config_instance.dashboard_services.return_value = [
            "orpheus-dashboard",
            "orpheus-mqtt",
            "orpheus-agent-audio-motion",
            "orpheus-bluetooth-autoconnect",
        ]

        # Mock camera
        mock_camera = Mock()
        mock_camera.name = "north-camera"
        mock_camera.get_health_status.return_value = {
            "name": "north-camera",
            "host": "192.168.1.100",
            "model": "IP5M-B1186EW",
            "type": "amcrest",
            "status": "healthy",
            "checks": {
                "network": {"ok": True, "latency_ms": 5.2},
                "http_api": {"ok": True, "response_time_ms": 120},
                "snapshot": {"ok": True},
                "rtsp_stream": {"ok": True},
            },
        }
        mock_camera.capture_snapshot.return_value = {
            "ok": True,
            "image_data": b"\xff\xd8\xff\xe0",  # JPEG header
            "cached_at": "2025-11-28T12:00:00Z",
        }

        config_instance.camera_registry.return_value = [mock_camera]
        config_instance.get_debug_safe_values.return_value = {
            "orpheus_config": {"dashboard.host": "0.0.0.0"},
            "effective_settings": {"dashboard.port": "8080"},
            "environment_overrides": {},
            "camera_environment": {},
            "camera_registry": {"source": "config:/etc/orpheus/dashboard/orpheus.yaml"},
        }

        mock_config_class.get_instance.return_value = config_instance

        with patch("orpheus_dashboard.main.config", config_instance):
            with patch("orpheus_dashboard.main.cameras", [mock_camera]):
                from orpheus_dashboard.main import app

                yield TestClient(app)


class TestFullDashboardWorkflow:
    """Tests that simulate full dashboard usage."""

    def test_complete_dashboard_data_fetch(self, integration_client):
        """Simulate fetching all dashboard data like frontend does."""
        # 1. Get config
        config_response = integration_client.get("/api/config")
        assert config_response.status_code == 200
        poll_interval = config_response.json()["poll_interval"]
        assert poll_interval == 5000

        # 2. Get health
        health_response = integration_client.get("/api/health")
        assert health_response.status_code == 200
        health = health_response.json()
        assert health["status"] == "ok"

        # 3. Get services
        with patch(
            "orpheus_dashboard.main.shutil.which", return_value="/bin/systemctl"
        ):
            with patch(
                "orpheus_dashboard.main.subprocess.run",
                return_value=Mock(returncode=0, stdout="active\n"),
            ):
                services_response = integration_client.get("/api/services/status")
                assert services_response.status_code == 200
                services = services_response.json()
                assert len(services["services"]) == 4

        # 4. Get cameras
        cameras_response = integration_client.get("/api/cameras")
        assert cameras_response.status_code == 200
        cameras = cameras_response.json()
        assert len(cameras) == 1
        assert cameras[0]["status"] == "healthy"

        # 5. Get camera snapshot
        snapshot_response = integration_client.get("/api/cameras/north-camera/snapshot")
        assert snapshot_response.status_code == 200
        assert snapshot_response.headers["content-type"] == "image/jpeg"

        # 6. Get debug info
        debug_response = integration_client.get("/api/debug/config")
        assert debug_response.status_code == 200

    @patch("orpheus_dashboard.main.get_data_storage_usage")
    @patch("orpheus_dashboard.main.get_storage_hardware_info")
    def test_storage_monitoring_workflow(
        self, mock_hardware, mock_usage, integration_client
    ):
        """Test complete storage monitoring workflow."""
        mock_usage.return_value = {
            "path": "/mnt/data",
            "total_gb": 1000,
            "used_gb": 250,
            "free_gb": 750,
            "percent_used": 25.0,
        }

        mock_hardware.return_value = {
            "devices": [
                {
                    "name": "/dev/sda1",
                    "mount": "/mnt/data",
                    "filesystem": "ext4",
                    "status": "healthy",
                }
            ]
        }

        # Get storage usage
        usage_response = integration_client.get("/api/system/storage/data")
        assert usage_response.status_code == 200
        usage = usage_response.json()
        assert usage["percent_used"] == 25.0

        # Get storage hardware
        hardware_response = integration_client.get("/api/hardware/storage")
        assert hardware_response.status_code == 200
        hardware = hardware_response.json()
        assert len(hardware["devices"]) == 1


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @patch("orpheus_dashboard.main.get_data_storage_usage")
    def test_storage_endpoint_handles_exceptions(
        self, mock_storage, integration_client
    ):
        """Storage endpoint should handle exceptions gracefully."""
        mock_storage.side_effect = Exception("Disk error")

        with pytest.raises(Exception):
            integration_client.get("/api/system/storage/data")

    def test_invalid_camera_name_returns_404(self, integration_client):
        """Invalid camera name should return 404."""
        response = integration_client.get("/api/cameras/invalid-camera/snapshot")
        assert response.status_code == 404

    @patch("orpheus_dashboard.main.cameras")
    def test_camera_snapshot_failure_returns_503(
        self, mock_cameras, integration_client
    ):
        """Camera snapshot failure should return 503."""
        mock_camera = Mock()
        mock_camera.name = "failing-camera"
        mock_camera.capture_snapshot.return_value = {
            "ok": False,
            "error": "Network timeout",
        }

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            response = integration_client.get("/api/cameras/failing-camera/snapshot")
            assert response.status_code == 503
            assert "timeout" in response.json()["detail"].lower()


class TestConcurrentRequests:
    """Tests for handling concurrent requests."""

    @patch("orpheus_dashboard.main.shutil.which", return_value="/bin/systemctl")
    @patch("orpheus_dashboard.main.subprocess.run")
    def test_multiple_service_checks_concurrent(
        self, mock_run, mock_which, integration_client
    ):
        """Multiple service status checks should work concurrently."""
        mock_run.return_value = Mock(returncode=0, stdout="active\n")

        # Make multiple concurrent requests
        responses = [integration_client.get("/api/services/status") for _ in range(5)]

        assert all(r.status_code == 200 for r in responses)
        assert all(
            len(r.json()["services"]) == 4 for r in responses
        )  # 4 services in integration mock

    def test_multiple_health_checks_concurrent(self, integration_client):
        """Multiple health checks should work concurrently."""
        responses = [integration_client.get("/api/health") for _ in range(5)]

        assert all(r.status_code == 200 for r in responses)
        assert all(r.json()["status"] == "ok" for r in responses)


class TestResponseFormats:
    """Tests for response format consistency."""

    def test_all_json_endpoints_return_valid_json(self, integration_client):
        """All JSON endpoints should return valid JSON."""
        endpoints = [
            "/api/config",
            "/api/health",
            "/api/cameras",
            "/api/debug/config",
        ]

        for endpoint in endpoints:
            response = integration_client.get(endpoint)
            assert response.status_code == 200
            # Should not raise JSONDecodeError
            data = response.json()
            assert data is not None

    def test_content_type_headers(self, integration_client):
        """Endpoints should have correct Content-Type headers."""
        # JSON endpoints
        response = integration_client.get("/api/health")
        assert "application/json" in response.headers["content-type"]

        # Image endpoint
        response = integration_client.get("/api/cameras/north-camera/snapshot")
        assert response.headers["content-type"] == "image/jpeg"


class TestCameraHealthCaching:
    """Tests for camera health check caching behavior."""

    @patch("orpheus_dashboard.main.cameras")
    @patch("orpheus_dashboard.main.config")
    def test_camera_health_ttl_passed_correctly(
        self, mock_config, mock_cameras_list, integration_client
    ):
        """Camera health checks should receive correct TTL from config."""
        mock_config.dashboard_poll_interval.return_value = 8000

        mock_camera = Mock()
        mock_camera.get_health_status.return_value = {
            "name": "test-cam",
            "status": "healthy",
        }

        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            integration_client.get("/api/cameras")

            # Should convert milliseconds to seconds: 8000ms = 8.0s
            mock_camera.get_health_status.assert_called_once_with(ttl_seconds=8.0)

    @patch("orpheus_dashboard.main.cameras")
    @patch("orpheus_dashboard.main.config")
    def test_multiple_camera_parallel_execution(
        self, mock_config, mock_cameras_list, integration_client
    ):
        """Multiple cameras should be checked in parallel."""
        mock_config.dashboard_poll_interval.return_value = 5000

        cameras = []
        for i in range(3):
            cam = Mock()
            cam.name = f"camera-{i}"
            cam.get_health_status.return_value = {
                "name": f"camera-{i}",
                "status": "healthy",
            }
            cameras.append(cam)

        with patch("orpheus_dashboard.main.cameras", cameras):
            response = integration_client.get("/api/cameras")
            data = response.json()

            assert len(data) == 3
            # All cameras should have been checked
            for cam in cameras:
                cam.get_health_status.assert_called_once()


class TestMQTTMessageHandlers:
    """Tests for MQTT message handler functions."""

    def test_on_crow_detection_message_new_format(self, integration_client):
        """Test _on_crow_detection_message with new detection format."""
        from orpheus_dashboard.main import _on_crow_detection_message
        from collections import deque

        # Test payload with new format (detection object)
        test_payload = {
            "event_id": "crow_det_20251205_143023_ch1",
            "timestamp": "2025-12-05T14:30:23.456789+00:00",
            "channel_id": "1",
            "detection": {
                "species": "american_crow",
                "call_type": "caw",
                "quality_score": 0.87,
            },
            "audio_clip_path": "/data/orpheus/audio/crow_detection/1/test.flac",
            "inference_time_ms": 145,
        }

        # Mock the caches
        test_cache = deque(maxlen=50)
        test_by_channel = {}

        with patch.dict(
            "orpheus_dashboard.main.__dict__",
            {
                "_crow_detections_cache": test_cache,
                "_crow_detections_by_channel": test_by_channel,
            },
        ):
            # Call the handler
            _on_crow_detection_message("orpheus/detection/crow/events", test_payload)

            # Verify the payload was added to cache
            assert len(test_cache) == 1
            assert test_cache[0] == test_payload

            # Verify per-channel cache was updated
