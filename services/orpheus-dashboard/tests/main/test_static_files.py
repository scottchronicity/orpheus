"""Tests for static file serving."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch


@pytest.fixture
def mock_config():
    """Mock OrpheusConfig for testing."""
    with patch("orpheus_dashboard.main.OrpheusConfig") as mock:
        config_instance = Mock()
        config_instance.dashboard_poll_interval.return_value = 5000
        config_instance.dashboard_services.return_value = ["orpheus-dashboard"]
        config_instance.camera_registry.return_value = []
        config_instance.mqtt.broker_host = "localhost"
        config_instance.mqtt.broker_port = 1883
        config_instance.mqtt.keepalive = 60
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


class TestStaticFiles:
    """Tests for static file serving."""

    def test_static_index_html_accessible(self, client):
        """Static index.html should be accessible via /static/index.html."""
        response = client.get("/static/index.html")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Verify it's actual HTML content
        assert b"<!DOCTYPE html>" in response.content or b"<html" in response.content

    def test_static_css_accessible(self, client):
        """Static CSS files should be accessible via /static/."""
        response = client.get("/static/style.css")
        assert response.status_code == 200
        assert "text/css" in response.headers["content-type"]

    def test_static_js_accessible(self, client):
        """Static JavaScript files should be accessible via /static/."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
        # JavaScript can be served as application/javascript or text/javascript
        assert (
            "javascript" in response.headers["content-type"]
            or "text/plain" in response.headers["content-type"]
        )

    def test_root_serves_index_html(self, client):
        """Root path should serve the index.html file."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        # Verify it's actual HTML content
        assert b"<!DOCTYPE html>" in response.content or b"<html" in response.content

    def test_nonexistent_static_file_404(self, client):
        """Requesting a non-existent static file should return 404."""
        response = client.get("/static/nonexistent.txt")
        assert response.status_code == 404
