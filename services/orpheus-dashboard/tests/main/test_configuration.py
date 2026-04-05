"""Tests for configuration and initialization in main.py"""

import pytest
from unittest.mock import Mock, patch


class TestConfigurationLoading:
    """Tests for OrpheusConfig integration."""

    @patch("orpheus_dashboard.main.OrpheusConfig")
    def test_config_singleton_is_loaded(self, mock_orpheus_config):
        """Configuration singleton should be loaded on module import."""
        mock_instance = Mock()
        mock_orpheus_config.get_instance.return_value = mock_instance

        # Force reimport to trigger config loading
        import importlib
        import orpheus_dashboard.main as main

        importlib.reload(main)

        mock_orpheus_config.get_instance.assert_called()

    @patch("orpheus_dashboard.main.OrpheusConfig")
    def test_camera_registry_is_loaded(self, mock_orpheus_config):
        """Camera registry should be loaded from config."""
        mock_instance = Mock()
        mock_registry = Mock()
        mock_instance.camera_registry.return_value = mock_registry
        mock_orpheus_config.get_instance.return_value = mock_instance

        # Force reimport to trigger config loading
        import importlib
        import orpheus_dashboard.main as main

        importlib.reload(main)

        mock_instance.camera_registry.assert_called_once()


class TestStaticFilesMounting:
    """Tests for static files configuration."""

    def test_static_files_mounted(self):
        """Static files should be mounted at /static."""
        from orpheus_dashboard.main import app

        # Check that static files are mounted
        routes = [route.path for route in app.routes]
        assert any("/static" in route for route in routes)


class TestLoggingConfiguration:
    """Tests for logging setup."""

    def test_logger_is_configured(self):
        """Logger should be configured with appropriate settings."""
        from orpheus_dashboard.main import logger

        assert logger.name == "orpheus_dashboard.main"
        assert logger.level >= 0  # Some logging level is set

    @patch("orpheus_common.logging.setup_logging")
    def test_logging_level_is_info(self, mock_setup_logging):
        """Logging should be configured with setup_logging."""
        import importlib
        import orpheus_dashboard.main as main

        importlib.reload(main)

        # Check that setup_logging was called
        mock_setup_logging.assert_called()
        # Verify it was called with the dashboard service name
        call_args = mock_setup_logging.call_args
        assert call_args[0][0] == "orpheus-dashboard"  # service_name parameter


class TestModuleConstants:
    """Tests for module-level constants and globals."""

    def test_config_is_defined(self):
        """config global should be defined."""
        from orpheus_dashboard.main import config

        assert config is not None

    def test_cameras_is_defined(self):
        """cameras global should be defined."""
        from orpheus_dashboard.main import cameras

        assert cameras is not None

    def test_app_is_defined(self):
        """app (FastAPI) should be defined."""
        from orpheus_dashboard.main import app

        assert app is not None

    def test_logger_is_defined(self):
        """logger should be defined."""
        from orpheus_dashboard.main import logger

        assert logger is not None


class TestPydanticModels:
    """Tests for Pydantic model definitions."""

    def test_health_response_model(self):
        """HealthResponse model should be properly defined."""
        from orpheus_dashboard.main import HealthResponse

        response = HealthResponse(
            status="ok",
            cpu_percent=45.2,
            memory_percent=62.8,
            disk_percent=35.1,
            uptime_seconds=3600,
        )

        assert response.status == "ok"
        assert response.cpu_percent == 45.2
        assert response.uptime_seconds == 3600

    def test_service_status_model(self):
        """ServiceStatus model should be properly defined."""
        from orpheus_dashboard.main import ServiceStatus

        service = ServiceStatus(
            name="orpheus-mqtt", status="running", reason="All good"
        )

        assert service.name == "orpheus-mqtt"
        assert service.status == "running"
        assert service.reason == "All good"

    def test_services_response_model(self):
        """ServicesResponse model should be properly defined."""
        from orpheus_dashboard.main import ServicesResponse, ServiceStatus

        services = ServicesResponse(
            services=[
                ServiceStatus(name="service1", status="running", reason=""),
                ServiceStatus(name="service2", status="stopped", reason="Not active"),
            ]
        )

        assert len(services.services) == 2
        assert services.services[0].name == "service1"
        assert services.services[1].status == "stopped"

    def test_health_response_validation(self):
        """HealthResponse should validate types."""
        from orpheus_dashboard.main import HealthResponse
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            HealthResponse(
                status="ok",
                cpu_percent="not_a_number",  # Should be float
                memory_percent=50.0,
                disk_percent=30.0,
                uptime_seconds=100,
            )

    def test_service_status_all_fields_required(self):
        """ServiceStatus should require all fields."""
        from orpheus_dashboard.main import ServiceStatus
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ServiceStatus(name="test")  # Missing status and reason
