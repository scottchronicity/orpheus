"""Tests for data visualization API endpoints."""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_dashboard.main.OrpheusConfig") as mock:
        config_instance = Mock()
        config_instance.dashboard_poll_interval.return_value = 5000
        config_instance.dashboard_services.return_value = []
        config_instance.camera_registry.return_value = []
        config_instance.mqtt.broker_host = "localhost"
        config_instance.mqtt.broker_port = 1883
        config_instance.mqtt.keepalive = 60
        mock.get_instance.return_value = config_instance
        yield config_instance


@pytest.fixture
def client(mock_config):
    """Create a test client with mocked dependencies."""
    with patch("orpheus_dashboard.main.config", mock_config):
        with patch("orpheus_dashboard.main.cameras", []):
            from orpheus_dashboard.main import app

            with TestClient(app) as test_client:
                yield test_client


@pytest.fixture
def mock_detection():
    """Create a mock detection object."""
    detection = Mock()
    detection.timestamp = datetime(2026, 1, 8, 12, 30, 0, tzinfo=timezone.utc)
    detection.species_code = "amecro"
    detection.species_common = "American Crow"
    detection.confidence = 0.95
    detection.channel = 1
    detection.metadata = {"call_type": "caw", "attributes": {"age": "adult"}}
    return detection


class TestBirdHistoryEndpoint:
    """Tests for /api/data/birds/history endpoint."""

    def test_bird_history_returns_200(self, client):
        """Endpoint should return 200 status."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/history")
            assert response.status_code == 200

    def test_bird_history_returns_correct_structure(self, client):
        """Endpoint should return correct data structure."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/history")
            data = response.json()

            assert "detections" in data
            assert "count" in data
            assert "start_date" in data
            assert "end_date" in data
            assert "filtered_count" in data
            assert isinstance(data["detections"], list)

    def test_bird_history_accepts_date_range_parameters(self, client):
        """Endpoint should accept start_date and end_date parameters."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get(
                "/api/data/birds/history?start_date=2026-01-01&end_date=2026-01-08"
            )
            data = response.json()

            assert data["start_date"] == "2026-01-01"
            assert data["end_date"] == "2026-01-08"

    def test_bird_history_formats_detections_correctly(self, client, mock_detection):
        """Endpoint should format detections with correct fields."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [mock_detection]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/history")
            data = response.json()

            assert len(data["detections"]) == 1
            detection = data["detections"][0]
            assert "timestamp" in detection
            assert "species_code" in detection
            assert "species_common" in detection
            assert "confidence" in detection
            assert "channel" in detection

    def test_bird_history_queries_with_correct_parameters(self, client):
        """Endpoint should query DetectionDB with correct parameters."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            client.get("/api/data/birds/history?days=7")

            # Verify query was called with correct parameters
            mock_db_instance.query.assert_called_once()
            call_kwargs = mock_db_instance.query.call_args.kwargs
            assert call_kwargs["detection_type"] == "species.detected"
            assert call_kwargs["limit"] == 100000  # Increased to handle large datasets
            assert "start_time" in call_kwargs

    def test_bird_history_filters_non_bird_sounds(self, client):
        """Endpoint should filter out non-bird sounds like sirens and human voices."""
        # Create mock detections with non-bird sounds
        bird_det = Mock()
        bird_det.timestamp = datetime(2026, 1, 8, 10, 0, 0, tzinfo=timezone.utc)
        bird_det.species_common = "American Crow"
        bird_det.species_code = "amecro"
        bird_det.confidence = 0.95
        bird_det.channel = 1

        siren_det = Mock()
        siren_det.timestamp = datetime(2026, 1, 8, 11, 0, 0, tzinfo=timezone.utc)
        siren_det.species_common = "Siren"
        siren_det.species_code = "siren"
        siren_det.confidence = 0.85
        siren_det.channel = 1

        human_det = Mock()
        human_det.timestamp = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
        human_det.species_common = "Human vocal"
        human_det.species_code = "human"
        human_det.confidence = 0.90
        human_det.channel = 2

        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [bird_det, siren_det, human_det]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/history")
            data = response.json()

            # Should only return the bird, not the siren or human vocal
            assert len(data["detections"]) == 1
            assert data["detections"][0]["species_common"] == "American Crow"
            assert data["filtered_count"] == 2


class TestBirdDailyCountsEndpoint:
    """Tests for /api/data/birds/daily endpoint."""

    def test_bird_daily_returns_200(self, client):
        """Endpoint should return 200 status."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/daily")
            assert response.status_code == 200

    def test_bird_daily_returns_correct_structure(self, client):
        """Endpoint should return correct data structure."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/daily")
            data = response.json()

            assert "daily_counts" in data
            assert "species" in data
            assert "start_date" in data
            assert "end_date" in data
            assert "filtered_count" in data
            assert isinstance(data["daily_counts"], list)
            assert isinstance(data["species"], list)

    def test_bird_daily_groups_by_date_and_species(self, client):
        """Endpoint should group detections by date and species."""
        # Create mock detections with same date but different species
        det1 = Mock()
        det1.timestamp = datetime(2026, 1, 8, 10, 0, 0, tzinfo=timezone.utc)
        det1.species_common = "American Crow"
        det1.species_code = "amecro"

        det2 = Mock()
        det2.timestamp = datetime(2026, 1, 8, 14, 0, 0, tzinfo=timezone.utc)
        det2.species_common = "Blue Jay"
        det2.species_code = "blujay"

        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [det1, det2]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/birds/daily")
            data = response.json()

            assert len(data["daily_counts"]) == 1  # Same day
            assert "American Crow" in data["species"]
            assert "Blue Jay" in data["species"]


class TestCrowStatsEndpoint:
    """Tests for /api/data/crows/stats endpoint."""

    def test_crow_stats_returns_200(self, client):
        """Endpoint should return 200 status."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/crows/stats")
            assert response.status_code == 200

    def test_crow_stats_returns_correct_structure(self, client):
        """Endpoint should return correct data structure."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/crows/stats")
            data = response.json()

            assert "total_detections" in data
            assert "age_distribution" in data
            assert "hourly_activity" in data
            assert "call_types" in data
            assert "intents" in data
            assert "start_date" in data
            assert "end_date" in data

    def test_crow_stats_queries_crow_detection_type(self, client):
        """Endpoint should query for detection_type='crow'."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            client.get("/api/data/crows/stats")

            # Verify query was called with correct parameters
            mock_db_instance.query.assert_called_once()
            call_kwargs = mock_db_instance.query.call_args.kwargs
            assert call_kwargs["detection_type"] == "crow"
            assert "start_time" in call_kwargs

    def test_crow_stats_parses_metadata_correctly(self, client, mock_detection):
        """Endpoint should correctly parse age and call_type from metadata."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [mock_detection]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/crows/stats")
            data = response.json()

            assert data["total_detections"] == 1
            assert "adult" in data["age_distribution"]
            assert data["age_distribution"]["adult"] == 1
            assert "caw" in data["call_types"]
            assert data["call_types"]["caw"] == 1

    def test_crow_stats_hourly_activity_has_24_hours(self, client):
        """Endpoint should return hourly activity for all 24 hours."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/crows/stats")
            data = response.json()

            assert len(data["hourly_activity"]) == 24
            # Check that all hours 0-23 are present
            hours = [entry["hour"] for entry in data["hourly_activity"]]
            assert hours == list(range(24))

    def test_crow_stats_handles_missing_metadata(self, client):
        """Endpoint should handle detections with missing metadata gracefully."""
        det = Mock()
        det.timestamp = datetime(2026, 1, 8, 12, 0, 0, tzinfo=timezone.utc)
        det.metadata = None

        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [det]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/crows/stats")
            data = response.json()

            assert response.status_code == 200
            assert data["total_detections"] == 1
            # Should have "unknown" for missing attributes
            assert "unknown" in data["age_distribution"]
            assert "unknown" in data["call_types"]


class TestNonBirdSoundsEndpoint:
    """Tests for /api/data/non-birds/daily endpoint."""

    def test_non_bird_daily_returns_200(self, client):
        """Endpoint should return 200 status."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/non-birds/daily")
            assert response.status_code == 200

    def test_non_bird_daily_returns_correct_structure(self, client):
        """Endpoint should return correct data structure."""
        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = []
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/non-birds/daily")
            data = response.json()

            assert "daily_counts" in data
            assert "sound_types" in data
            assert "start_date" in data
            assert "end_date" in data
            assert isinstance(data["daily_counts"], list)
            assert isinstance(data["sound_types"], list)

    def test_non_bird_daily_filters_correctly(self, client):
        """Endpoint should only return non-bird sounds."""
        # Create mock detections
        bird_det = Mock()
        bird_det.timestamp = datetime(2026, 1, 8, 10, 0, 0, tzinfo=timezone.utc)
        bird_det.species_common = "American Crow"
        bird_det.species_code = "amecro"

        siren_det = Mock()
        siren_det.timestamp = datetime(2026, 1, 8, 11, 0, 0, tzinfo=timezone.utc)
        siren_det.species_common = "Siren"
        siren_det.species_code = "siren"

        with patch("orpheus_dashboard.main.DetectionDB") as mock_db:
            mock_db_instance = Mock()
            mock_db_instance.query.return_value = [bird_det, siren_det]
            mock_db.return_value = mock_db_instance

            response = client.get("/api/data/non-birds/daily")
            data = response.json()

            # Should only include siren, not bird
            assert len(data["sound_types"]) == 1
            assert "Siren" in data["sound_types"]
            assert "American Crow" not in data["sound_types"]
