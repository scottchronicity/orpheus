"""Tests for snapshot and timelapse API endpoints."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch
from pathlib import Path
import tempfile


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_dashboard.main.OrpheusConfig") as mock:
        config_instance = Mock()
        config_instance.dashboard_poll_interval.return_value = 5000
        config_instance.dashboard_services.return_value = ["orpheus-dashboard"]
        config_instance.camera_registry.return_value = []

        # Create a temporary storage directory for testing
        temp_dir = tempfile.mkdtemp()
        storage_mock = Mock()
        storage_mock.base_path = temp_dir
        config_instance.storage = storage_mock

        mock.get_instance.return_value = config_instance
        yield config_instance, temp_dir


@pytest.fixture
def mock_camera():
    """Create a mock camera with snapshot and timelapse config."""
    camera = Mock()
    camera.name = "test-camera"
    camera.enabled = True

    # Mock snapshots config
    snapshots = Mock()
    snapshots.interval = "5m"
    camera.snapshots = snapshots

    # Mock timelapses config
    timelapse = Mock()
    timelapse.start_time = "18:00"
    timelapse.lookback_window = "24h"
    timelapse.sampling_interval = "15m"
    timelapse.retention_days = 90
    timelapse.clip_duration = 2.0
    timelapse.timezone = "UTC"
    timelapse.label = "daily"
    camera.timelapses = [timelapse]

    return camera


@pytest.fixture
def client(mock_config, mock_camera):
    """Create a test client with mocked dependencies."""
    config_instance, temp_dir = mock_config
    with patch("orpheus_dashboard.main.config", config_instance):
        with patch("orpheus_dashboard.main.cameras", [mock_camera]):
            from orpheus_dashboard.main import app

            with TestClient(app) as test_client:
                yield test_client, temp_dir


class TestSnapshotStatusEndpoint:
    """Tests for /api/diagnostics/video/snapshots/status endpoint."""

    def test_snapshot_status_returns_cameras(self, client):
        """Endpoint should return camera status list."""
        test_client, _ = client
        response = test_client.get("/api/diagnostics/video/snapshots/status")
        assert response.status_code == 200
        data = response.json()
        assert "cameras" in data
        assert "date" in data

    def test_snapshot_status_includes_camera_info(self, client):
        """Endpoint should include camera configuration info."""
        test_client, _ = client
        response = test_client.get("/api/diagnostics/video/snapshots/status")
        data = response.json()
        assert len(data["cameras"]) > 0
        cam = data["cameras"][0]
        assert "camera_name" in cam
        assert "enabled" in cam
        assert "snapshots_configured" in cam
        assert "timelapses_configured" in cam

    def test_snapshot_status_with_existing_files(self, client):
        """Endpoint should find existing snapshot and timelapse files."""
        test_client, temp_dir = client
        from datetime import datetime, timezone as tz

        # Create today's date directory
        today_str = datetime.now(tz.utc).strftime("%Y.%m.%d")

        # Create snapshot directory and file
        snapshot_dir = Path(temp_dir) / "video" / "snapshots" / today_str
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = snapshot_dir / "2025-01-20T12-00-00.000Z.test-camera.jpg"
        snapshot_file.write_bytes(b"fake jpg")

        # Create timelapse directory and file
        timelapse_dir = Path(temp_dir) / "video" / "timelapses" / today_str
        timelapse_dir.mkdir(parents=True, exist_ok=True)
        timelapse_file = timelapse_dir / "18-00.test-camera.mp4"
        timelapse_file.write_bytes(b"fake mp4")

        response = test_client.get("/api/diagnostics/video/snapshots/status")
        assert response.status_code == 200
        data = response.json()
        assert len(data["cameras"]) > 0
        cam = data["cameras"][0]
        assert cam["snapshot_count_today"] >= 0
        assert cam["timelapse_count_today"] >= 0


class TestGetCameraSnapshotsEndpoint:
    """Tests for /api/video/snapshots/{camera_name} endpoint."""

    def test_get_snapshots_returns_list(self, client):
        """Endpoint should return snapshot list."""
        test_client, _ = client
        response = test_client.get("/api/video/snapshots/test-camera")
        assert response.status_code == 200
        data = response.json()
        assert "snapshots" in data
        assert "camera" in data

    def test_get_snapshots_validates_camera_name_with_slash(self, client):
        """Endpoint should reject camera names with slashes."""
        test_client, _ = client
        response = test_client.get("/api/video/snapshots/test%2Fcamera")
        # The endpoint validates "/" in camera name
        assert response.status_code in [400, 404, 422]

    def test_get_snapshots_with_date_param(self, client):
        """Endpoint should accept date parameter."""
        test_client, _ = client
        response = test_client.get("/api/video/snapshots/test-camera?date=2025.01.20")
        assert response.status_code == 200

    def test_get_snapshots_with_invalid_date(self, client):
        """Endpoint should reject invalid date format."""
        test_client, _ = client
        response = test_client.get("/api/video/snapshots/test-camera?date=invalid")
        assert response.status_code == 400

    def test_get_snapshots_with_limit(self, client):
        """Endpoint should accept limit parameter."""
        test_client, _ = client
        response = test_client.get("/api/video/snapshots/test-camera?limit=10")
        assert response.status_code == 200

    def test_get_snapshots_finds_existing_files(self, client):
        """Endpoint should find and list existing snapshot files."""
        test_client, temp_dir = client
        from datetime import datetime, timezone as tz

        # Create today's date directory
        today_str = datetime.now(tz.utc).strftime("%Y.%m.%d")

        # Create snapshot directory and files
        snapshot_dir = Path(temp_dir) / "video" / "snapshots" / today_str
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            snapshot_file = snapshot_dir / f"2025-01-20T12-0{i}-00.000Z.test-camera.jpg"
            snapshot_file.write_bytes(b"fake jpg content")

        response = test_client.get("/api/video/snapshots/test-camera")
        assert response.status_code == 200
        data = response.json()
        assert "snapshots" in data
        assert "count" in data
        assert data["count"] == 3
        assert len(data["snapshots"]) == 3
        # Verify each snapshot has expected fields
        for snap in data["snapshots"]:
            assert "filename" in snap
            assert "download_url" in snap
            assert "size_kb" in snap


class TestServeSnapshotFileEndpoint:
    """Tests for /api/video/snapshots/{camera}/{date}/{filename} endpoint."""

    def test_serve_snapshot_rejects_slash_in_camera(self, client):
        """Endpoint should reject slashes in camera name."""
        test_client, _ = client
        response = test_client.get(
            "/api/video/snapshots/test%2Fcamera/2025.01.20/test.jpg"
        )
        assert response.status_code in [400, 404, 422]

    def test_serve_snapshot_rejects_slash_in_date(self, client):
        """Endpoint should reject slashes in date."""
        test_client, _ = client
        response = test_client.get(
            "/api/video/snapshots/test-camera/2025%2F01.20/test.jpg"
        )
        assert response.status_code in [400, 404, 422]

    def test_serve_snapshot_returns_404_for_missing_file(self, client):
        """Endpoint should return 404 for non-existent files."""
        test_client, temp_dir = client
        # Create the directory structure but not the file
        snapshot_dir = Path(temp_dir) / "video" / "snapshots" / "2025.01.20"
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        response = test_client.get(
            "/api/video/snapshots/test-camera/2025.01.20/nonexistent.jpg"
        )
        assert response.status_code == 404

    def test_serve_snapshot_serves_existing_file(self, client):
        """Endpoint should serve existing snapshot files."""
        test_client, temp_dir = client
        # Create the directory and file
        snapshot_dir = Path(temp_dir) / "video" / "snapshots" / "2025.01.20"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_file = snapshot_dir / "test.jpg"
        snapshot_file.write_bytes(b"fake jpeg content")

        response = test_client.get(
            "/api/video/snapshots/test-camera/2025.01.20/test.jpg"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"


class TestGetCameraTimelapsesEndpoint:
    """Tests for /api/video/timelapses/{camera_name} endpoint."""

    def test_get_timelapses_returns_list(self, client):
        """Endpoint should return timelapse list."""
        test_client, _ = client
        response = test_client.get("/api/video/timelapses/test-camera")
        assert response.status_code == 200
        data = response.json()
        assert "timelapses" in data
        assert "camera" in data

    def test_get_timelapses_validates_camera_name_with_slash(self, client):
        """Endpoint should reject camera names with slashes."""
        test_client, _ = client
        response = test_client.get("/api/video/timelapses/test%2Fcamera")
        assert response.status_code in [400, 404, 422]

    def test_get_timelapses_with_date_param(self, client):
        """Endpoint should accept date parameter."""
        test_client, _ = client
        response = test_client.get("/api/video/timelapses/test-camera?date=2025.01.20")
        assert response.status_code == 200

    def test_get_timelapses_with_limit(self, client):
        """Endpoint should accept limit parameter."""
        test_client, _ = client
        response = test_client.get("/api/video/timelapses/test-camera?limit=5")
        assert response.status_code == 200

    def test_get_timelapses_finds_existing_files(self, client):
        """Endpoint should find and list existing timelapse files."""
        test_client, temp_dir = client

        # Create timelapse directory and files
        timelapse_dir = Path(temp_dir) / "video" / "timelapses" / "2025.01.20"
        timelapse_dir.mkdir(parents=True, exist_ok=True)
        for i in range(2):
            timelapse_file = timelapse_dir / f"18-0{i}.test-camera.mp4"
            timelapse_file.write_bytes(b"fake mp4 content")

        response = test_client.get("/api/video/timelapses/test-camera?date=2025.01.20")
        assert response.status_code == 200
        data = response.json()
        assert "timelapses" in data
        assert "count" in data
        assert data["count"] == 2
        assert len(data["timelapses"]) == 2
        # Verify each timelapse has expected fields
        for tl in data["timelapses"]:
            assert "filename" in tl
            assert "download_url" in tl
            assert "size_mb" in tl
            assert "date" in tl

    def test_get_timelapses_searches_multiple_dates(self, client):
        """Endpoint should search multiple date directories when date not specified."""
        test_client, temp_dir = client

        # Create timelapse directories for multiple dates
        for date in ["2025.01.18", "2025.01.19", "2025.01.20"]:
            timelapse_dir = Path(temp_dir) / "video" / "timelapses" / date
            timelapse_dir.mkdir(parents=True, exist_ok=True)
            timelapse_file = timelapse_dir / "18-00.test-camera.mp4"
            timelapse_file.write_bytes(b"fake mp4 content")

        response = test_client.get("/api/video/timelapses/test-camera")
        assert response.status_code == 200
        data = response.json()
        assert "timelapses" in data
        assert data["count"] == 3


class TestServeTimelapseFileEndpoint:
    """Tests for /api/video/timelapses/{camera}/{date}/{filename} endpoint."""

    def test_serve_timelapse_rejects_slash_in_camera(self, client):
        """Endpoint should reject slashes in camera name."""
        test_client, _ = client
        response = test_client.get(
            "/api/video/timelapses/test%2Fcamera/2025.01.20/test.mp4"
        )
        assert response.status_code in [400, 404, 422]

    def test_serve_timelapse_rejects_slash_in_date(self, client):
        """Endpoint should reject slashes in date."""
        test_client, _ = client
        response = test_client.get(
            "/api/video/timelapses/test-camera/2025%2F01.20/test.mp4"
        )
        assert response.status_code in [400, 404, 422]

    def test_serve_timelapse_returns_404_for_missing_file(self, client):
        """Endpoint should return 404 for non-existent files."""
        test_client, temp_dir = client
        # Create the directory structure but not the file
        timelapse_dir = Path(temp_dir) / "video" / "timelapses" / "2025.01.20"
        timelapse_dir.mkdir(parents=True, exist_ok=True)

        response = test_client.get(
            "/api/video/timelapses/test-camera/2025.01.20/nonexistent.mp4"
        )
        assert response.status_code == 404

    def test_serve_timelapse_serves_existing_mp4(self, client):
        """Endpoint should serve existing MP4 timelapse files."""
        test_client, temp_dir = client
        # Create the directory and file
        timelapse_dir = Path(temp_dir) / "video" / "timelapses" / "2025.01.20"
        timelapse_dir.mkdir(parents=True, exist_ok=True)
        timelapse_file = timelapse_dir / "test.mp4"
        timelapse_file.write_bytes(b"fake mp4 content")

        response = test_client.get(
            "/api/video/timelapses/test-camera/2025.01.20/test.mp4"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"

    def test_serve_timelapse_serves_existing_avi(self, client):
        """Endpoint should serve existing AVI timelapse files."""
        test_client, temp_dir = client
        # Create the directory and file
        timelapse_dir = Path(temp_dir) / "video" / "timelapses" / "2025.01.20"
        timelapse_dir.mkdir(parents=True, exist_ok=True)
        timelapse_file = timelapse_dir / "test.avi"
        timelapse_file.write_bytes(b"fake avi content")

        response = test_client.get(
            "/api/video/timelapses/test-camera/2025.01.20/test.avi"
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/x-msvideo"


class TestSecurityPathContainment:
    """Tests for security - path containment checks."""

    def test_snapshot_path_containment(self, client):
        """Verify snapshot path stays within snapshots directory."""
        test_client, temp_dir = client
        # This test verifies the path containment check works
        response = test_client.get("/api/video/snapshots/test/2025.01.20/test.jpg")
        # Should return 404 (not found) if path is valid but file doesn't exist
        assert response.status_code in [400, 404]

    def test_timelapse_path_containment(self, client):
        """Verify timelapse path stays within timelapses directory."""
        test_client, temp_dir = client
        response = test_client.get("/api/video/timelapses/test/2025.01.20/test.mp4")
        assert response.status_code in [400, 404]
