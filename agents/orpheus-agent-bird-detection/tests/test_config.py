"""Tests for bird detection configuration."""

import os
from unittest.mock import Mock, patch

import pytest
from orpheus_common import OrpheusConfig

from orpheus_agent_bird_detection.config import BirdDetectionConfig, load_config


class TestBirdDetectionConfig:
    """Tests for BirdDetectionConfig."""

    class ConfigStub:
        def __init__(self, data):
            self._data = data
            self._raw = data

    def test_from_orpheus_config_with_defaults(self) -> None:
        """Should create config with defaults when no bird_detection section exists."""

        # Remove ORPHEUS_DATA_ROOT from environment if present
        with patch.dict(os.environ, {}, clear=False):
            if "ORPHEUS_DATA_ROOT" in os.environ:
                del os.environ["ORPHEUS_DATA_ROOT"]
            config_stub = self.ConfigStub({})
            config = BirdDetectionConfig.from_orpheus_config(config_stub)
            assert config.model_path == "/data/orpheus/models/birdnet.onnx"
            assert config.confidence_threshold == 0.50
            assert config.location_lat == 43.965542
            assert config.location_lon == -84.943588
            assert config.geo_filter_min_prob == 0.03
            assert config.geo_filter_weak_admit_prob == 0.0005
            assert config.geo_filter_weak_admit_conf == 0.85
            assert config.site_species_whitelist == []
            assert config.execution_provider == "auto"

    def test_explicit_model_path_override_wins_over_the_data_root(self) -> None:
        env = {
            "ORPHEUS_DATA_ROOT": "/data/orpheus",
            "ORPHEUS_BIRD_DETECTION__MODEL_PATH": "/srv/models/birdnet-v2.onnx",
        }
        with patch.dict(os.environ, env):
            config = BirdDetectionConfig.from_orpheus_config(OrpheusConfig.from_dict({}))
        assert config.model_path == "/srv/models/birdnet-v2.onnx"

    def test_data_root_still_places_the_default_model(self) -> None:
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": "/home/dev/data/orpheus"}):
            os.environ.pop("ORPHEUS_BIRD_DETECTION__MODEL_PATH", None)
            yaml_path = {"bird_detection": {"model_path": "/data/orpheus/models/birdnet.onnx"}}
            config = BirdDetectionConfig.from_orpheus_config(OrpheusConfig.from_dict(yaml_path))
        assert config.model_path == "/home/dev/data/orpheus/models/birdnet.onnx"

    def test_execution_provider_is_read_from_bird_config(self) -> None:
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}):
            config = BirdDetectionConfig.from_orpheus_config(
                self.ConfigStub({"bird_detection": {"execution_provider": "CUDA"}})
            )
        assert config.execution_provider == "cuda"

    def test_invalid_execution_provider_fails_validation(self) -> None:
        with (
            patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}),
            pytest.raises(ValueError, match="execution_provider must be one of"),
        ):
            BirdDetectionConfig.from_orpheus_config(
                self.ConfigStub({"bird_detection": {"execution_provider": "metal"}})
            )

    def test_from_orpheus_config_with_geo_overrides_and_whitelist(self) -> None:
        """Should read geo filter knobs and site whitelist from YAML."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}):
            config_stub = self.ConfigStub(
                {
                    "bird_detection": {
                        "geo_filter_min_prob": 0.05,
                        "geo_filter_weak_admit_prob": 0.001,
                        "geo_filter_weak_admit_conf": 0.9,
                        "site_species_whitelist": [
                            "Antrostomus vociferus",
                            "Scolopax minor",
                        ],
                    }
                }
            )
            config = BirdDetectionConfig.from_orpheus_config(config_stub)
            assert config.geo_filter_min_prob == 0.05
            assert config.geo_filter_weak_admit_prob == 0.001
            assert config.geo_filter_weak_admit_conf == 0.9
            assert config.site_species_whitelist == [
                "Antrostomus vociferus",
                "Scolopax minor",
            ]

    def test_from_orpheus_config_with_invalid_whitelist_type(self) -> None:
        """A non-list whitelist value should be ignored (logged warning, defaults to [])."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}):
            config_stub = self.ConfigStub(
                {"bird_detection": {"site_species_whitelist": "not a list"}}
            )
            config = BirdDetectionConfig.from_orpheus_config(config_stub)
            assert config.site_species_whitelist == []

    def test_from_orpheus_config_with_custom_values(self) -> None:
        """Should use custom values when provided."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}):
            config_stub = self.ConfigStub(
                {
                    "bird_detection": {
                        "model_path": "/custom/path/model.onnx",
                        "confidence_threshold": 0.7,
                        "location_lat": 45.0,
                        "location_lon": -90.0,
                    }
                }
            )
            config = BirdDetectionConfig.from_orpheus_config(config_stub)
            assert config.model_path == "/custom/path/model.onnx"
            assert config.confidence_threshold == 0.7
            assert config.location_lat == 45.0
            assert config.location_lon == -90.0

    @patch("orpheus_agent_bird_detection.config.OrpheusConfig")
    def test_load_config(self, mock_orpheus_config_class: Mock) -> None:
        """Should load configuration using OrpheusConfig."""
        with patch.dict(os.environ, {"ORPHEUS_DATA_ROOT": ""}):
            mock_instance = Mock()
            config_dict = {
                "bird_detection": {
                    "model_path": "/test/model.onnx",
                    "confidence_threshold": 0.6,
                    "location_lat": 40.0,
                    "location_lon": -100.0,
                }
            }
            mock_instance._data = config_dict
            mock_instance._raw = config_dict
            mock_orpheus_config_class.get_instance.return_value = mock_instance

            config = load_config(mock_instance)

            assert config.model_path == "/test/model.onnx"
            assert config.confidence_threshold == 0.6
