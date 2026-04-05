"""Tests for crow detection configuration."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from orpheus_agent_crow_detection.config import CrowDetectionConfig, load_config


class TestCrowDetectionConfig:
    """Tests for CrowDetectionConfig class."""

    def test_from_orpheus_config_defaults(self) -> None:
        """Test loading config with default values."""
        mock_config = MagicMock()
        mock_config._raw = {}

        config = CrowDetectionConfig.from_orpheus_config(mock_config)

        assert config.enabled is True
        assert config.quality_threshold == 0.5
        # Accept either /data/orpheus/... or $HOME/data/orpheus/... for dev/Jetson compatibility
        assert config.embedder_model_path.endswith("models/aves-base-bio.pt")
        assert config.classifier_model_path.endswith("models/mt_70.pt")
        assert config.embedder_sample_rate == 16000

    def test_from_orpheus_config_custom_values(self) -> None:
        """Test loading config with custom values."""
        mock_config = MagicMock()
        mock_config._raw = {
            "crow_detection": {
                "enabled": False,
                "quality_threshold": 0.7,
                "embedder_model_path": "/custom/path/embedder.pt",
                "classifier_model_path": "/custom/path/classifier.pt",
                "embedder_sample_rate": 24000,
            }
        }

        config = CrowDetectionConfig.from_orpheus_config(mock_config)

        assert config.enabled is False
        assert config.quality_threshold == 0.7
        assert config.embedder_model_path == "/custom/path/embedder.pt"
        assert config.classifier_model_path == "/custom/path/classifier.pt"
        assert config.embedder_sample_rate == 24000

    @patch("orpheus_agent_crow_detection.config.OrpheusConfig.get_instance")
    def test_load_config(self, mock_get_instance: MagicMock) -> None:
        """Test load_config function."""
        mock_orpheus_config = MagicMock()
        mock_orpheus_config._raw = {
            "crow_detection": {
                "enabled": True,
                "quality_threshold": 0.6,
            }
        }
        mock_get_instance.return_value = mock_orpheus_config

        config = load_config()

        assert config.enabled is True
        assert config.quality_threshold == 0.6
        mock_get_instance.assert_called_once_with(config_path=None)

    @patch("orpheus_agent_crow_detection.config.OrpheusConfig.get_instance")
    def test_load_config_with_path(self, mock_get_instance: MagicMock) -> None:
        """Test load_config with custom config path."""
        mock_orpheus_config = MagicMock()
        mock_orpheus_config._data = {}
        mock_get_instance.return_value = mock_orpheus_config

        config_path = Path("/custom/config.yaml")
        load_config(config_path)

        mock_get_instance.assert_called_once_with(config_path=config_path)
