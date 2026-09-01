"""Tests for uncovered config.py code paths to increase coverage."""

import json
from pathlib import Path

import pytest

from orpheus_common.config import Config, ConfigError, DashboardConfig, OrpheusConfig


class TestConfigCoerceType:
    """Tests for Config._coerce_type method."""

    def test_coerce_type_none_reference(self):
        """_coerce_type should return value as-is when reference is None."""
        config = Config({}, source="<test>")
        result = config._coerce_type("test_value", None)
        assert result == "test_value"

    def test_coerce_type_bool_true(self):
        """_coerce_type should convert string to bool (true cases)."""
        config = Config({}, source="<test>")
        assert config._coerce_type("true", True) is True
        assert config._coerce_type("1", False) is True
        assert config._coerce_type("yes", False) is True
        assert config._coerce_type("on", False) is True

    def test_coerce_type_bool_false(self):
        """_coerce_type should convert string to bool (false cases)."""
        config = Config({}, source="<test>")
        assert config._coerce_type("false", True) is False
        assert config._coerce_type("0", True) is False
        assert config._coerce_type("no", True) is False
        assert config._coerce_type("anything", True) is False

    def test_coerce_type_int(self):
        """_coerce_type should convert string to int."""
        config = Config({}, source="<test>")
        result = config._coerce_type("42", 0)
        assert result == 42
        assert isinstance(result, int)

    def test_coerce_type_float(self):
        """_coerce_type should convert string to float."""
        config = Config({}, source="<test>")
        result = config._coerce_type("3.14", 0.0)
        assert result == 3.14
        assert isinstance(result, float)

    def test_coerce_type_list_valid_yaml(self):
        """_coerce_type should parse valid YAML list."""
        config = Config({}, source="<test>")
        result = config._coerce_type("[1, 2, 3]", [])
        assert result == [1, 2, 3]

    def test_coerce_type_list_invalid_yaml(self):
        """_coerce_type should return reference for invalid YAML list."""
        config = Config({}, source="<test>")
        result = config._coerce_type("[invalid yaml", [])
        assert result == []

    def test_coerce_type_dict_valid_yaml(self):
        """_coerce_type should parse valid YAML dict."""
        config = Config({}, source="<test>")
        result = config._coerce_type("{key: value}", {})
        assert result == {"key": "value"}

    def test_coerce_type_dict_invalid_yaml(self):
        """_coerce_type should return reference for invalid YAML dict."""
        config = Config({}, source="<test>")
        result = config._coerce_type("{invalid: yaml:", {})
        assert result == {}

    def test_coerce_type_list_parsed_as_wrong_type(self):
        """_coerce_type should return reference when parsed type doesn't match."""
        config = Config({}, source="<test>")
        # Parse yields a dict but we expect a list
        result = config._coerce_type("{key: value}", [])
        assert result == []


class TestConfigAsFlatDict:
    """Tests for Config.as_flat_dict method."""

    def test_as_flat_dict_simple(self):
        """as_flat_dict should flatten simple nested dict."""
        config = Config({"a": {"b": {"c": "value"}}}, source="<test>")
        result = config.as_flat_dict()
        assert result == {"a.b.c": "value"}

    def test_as_flat_dict_without_lists(self):
        """as_flat_dict should not include lists by default."""
        config = Config({"items": [1, 2, 3], "name": "test"}, source="<test>")
        result = config.as_flat_dict(include_lists=False)
        assert result == {"items": [1, 2, 3], "name": "test"}

    def test_as_flat_dict_with_lists(self):
        """as_flat_dict should flatten lists when include_lists=True."""
        config = Config({"items": [{"name": "a"}, {"name": "b"}]}, source="<test>")
        result = config.as_flat_dict(include_lists=True)
        assert "items[0].name" in result
        assert result["items[0].name"] == "a"
        assert "items[1].name" in result
        assert result["items[1].name"] == "b"


class TestAudioConfigChannelsJSON:
    """Tests for audio channels JSON parsing."""

    def test_audio_config_channels_invalid_json(self):
        """AudioConfig.from_dict should raise ConfigError for invalid JSON string."""
        from orpheus_common.config import AudioConfig

        data = {
            "sample_rate": 48000,
            "chunk_size": 1024,
            "channels": "{invalid json",
        }
        with pytest.raises(ConfigError, match="audio.channels string is not valid JSON"):
            AudioConfig.from_dict(data)

    def test_audio_config_channels_valid_json_string(self):
        """AudioConfig.from_dict should parse valid JSON string for channels."""
        from orpheus_common.config import AudioConfig

        channels_json = json.dumps([{"id": 1, "name": "Channel 1", "enabled": True}])
        data = {"sample_rate": 48000, "chunk_size": 1024, "channels": channels_json}
        config = AudioConfig.from_dict(data)
        assert len(config.channels) == 1
        assert config.channels[0].name == "Channel 1"


class TestDashboardConfigServices:
    """Tests for dashboard.services parsing."""

    def test_dashboard_services_as_list(self):
        """DashboardConfig should accept services as a list."""
        data = {"services": ["service1", "service2"]}
        config = DashboardConfig.from_dict(data)
        assert config.services == ["service1", "service2"]

    def test_dashboard_services_as_string(self):
        """DashboardConfig should parse comma-separated services string."""
        data = {"services": "service1, service2, service3"}
        config = DashboardConfig.from_dict(data)
        assert config.services == ["service1", "service2", "service3"]

    def test_dashboard_services_invalid_type(self):
        """DashboardConfig should raise ConfigError for invalid services type."""
        data = {"services": 123}
        with pytest.raises(
            ConfigError, match="dashboard.services must be a list or comma-separated string"
        ):
            DashboardConfig.from_dict(data)


class TestConfigErrorHandling:
    """Tests for ConfigError raising in various scenarios."""

    def test_mqtt_broker_host_required(self):
        """MQTTConfig should raise ConfigError if broker_host is missing."""
        from orpheus_common.config import MQTTConfig

        with pytest.raises(ConfigError, match="mqtt.broker_host is required"):
            MQTTConfig.from_dict({})

    def test_audio_sample_rate_must_be_int(self):
        """AudioConfig should raise ConfigError for non-integer sample_rate."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": "not an int", "chunk_size": 1024}
        with pytest.raises(ConfigError, match="audio.sample_rate must be an integer"):
            AudioConfig.from_dict(data)

    def test_audio_chunk_size_must_be_int(self):
        """AudioConfig should raise ConfigError for non-integer chunk_size."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": 48000, "chunk_size": "not an int"}
        with pytest.raises(ConfigError, match="audio.chunk_size must be an integer"):
            AudioConfig.from_dict(data)

    def test_audio_channels_must_be_list(self):
        """AudioConfig should raise ConfigError if channels is not a list."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": 48000, "chunk_size": 1024, "channels": "not a list"}
        with pytest.raises(ConfigError, match="audio.channels string is not valid JSON"):
            AudioConfig.from_dict(data)

    def test_audio_buffer_duration_ms_must_be_int(self):
        """AudioConfig should raise ConfigError for non-integer buffer_duration_ms."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": 48000, "chunk_size": 1024, "buffer_duration_ms": "not an int"}
        with pytest.raises(ConfigError, match="audio.buffer_duration_ms must be an integer"):
            AudioConfig.from_dict(data)

    def test_audio_buffer_duration_ms_parsed_from_dict(self):
        """AudioConfig.from_dict should parse buffer_duration_ms from data."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": 48000, "chunk_size": 1024, "buffer_duration_ms": 21, "channels": []}
        config = AudioConfig.from_dict(data)
        assert config.buffer_duration_ms == 21

    def test_audio_buffer_duration_ms_default(self):
        """AudioConfig.from_dict should use default buffer_duration_ms when not provided."""
        from orpheus_common.config import AudioConfig

        data = {"sample_rate": 48000, "chunk_size": 1024, "channels": []}
        config = AudioConfig.from_dict(data)
        assert config.buffer_duration_ms == 200

    def test_audio_to_dict_includes_buffer_duration_ms(self):
        """AudioConfig.to_dict should include buffer_duration_ms."""
        from orpheus_common.config import AudioConfig

        config = AudioConfig(sample_rate=48000, chunk_size=1024, buffer_duration_ms=21, channels=[])
        result = config.to_dict()
        assert result["buffer_duration_ms"] == 21

    def test_dashboard_port_must_be_int(self):
        """DashboardConfig should raise ConfigError for non-integer port."""
        data = {"port": "not an int"}
        with pytest.raises(ConfigError, match="dashboard.port must be an integer"):
            DashboardConfig.from_dict(data)

    def test_dashboard_poll_interval_must_be_int(self):
        """DashboardConfig should raise ConfigError for non-integer poll_interval."""
        data = {"poll_interval": "not an int"}
        with pytest.raises(ConfigError, match="dashboard.poll_interval must be an integer"):
            DashboardConfig.from_dict(data)


class TestYAMLParsing:
    """Tests for YAML parsing in _smart_cast."""

    def test_smart_cast_yaml_error(self):
        """_smart_cast should return original value on YAML error."""
        from orpheus_common.config import _smart_cast

        # Malformed YAML should return the original string
        result = _smart_cast("{ invalid: yaml:")
        assert result == "{ invalid: yaml:"

    def test_smart_cast_yaml_none_for_nonempty_string(self):
        """_smart_cast should return value if YAML parses to None but string is non-empty."""
        from orpheus_common.config import _smart_cast

        # Empty YAML document parses to None
        result = _smart_cast("---")
        # Should return original value since it's non-empty but parsed to None
        assert result == "---"


class TestOrpheusConfigMissingFile:
    """Tests for OrpheusConfig with missing config file."""

    def test_load_with_allow_missing_true(self, monkeypatch):
        """OrpheusConfig should return empty dict when file is missing and allow_missing=True."""
        # Use a non-existent path
        nonexistent = Path("/definitely/does/not/exist/orpheus.yaml")

        # Temporarily reset the singleton
        original_instance = OrpheusConfig._instance
        try:
            OrpheusConfig._instance = None
            config = OrpheusConfig.load(config_path=nonexistent, allow_missing=True)
            # Should succeed with empty config
            assert config is not None
        finally:
            OrpheusConfig._instance = original_instance

    def test_load_with_allow_missing_false(self, monkeypatch):
        """OrpheusConfig should raise ConfigError when file is missing and allow_missing=False."""
        nonexistent = Path("/definitely/does/not/exist/orpheus.yaml")

        # Clear environment variables that could provide alternate paths
        monkeypatch.delenv("ORPHEUS_CONFIG_PATH", raising=False)
        monkeypatch.delenv("ORPHEUS_CONFIG_DIR", raising=False)

        # Change to a temporary directory where no config files exist
        import tempfile
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.chdir(tmpdir)

            original_instance = OrpheusConfig._instance
            original_dotenv = OrpheusConfig._DOTENV_LOADED
            try:
                OrpheusConfig._instance = None
                OrpheusConfig._DOTENV_LOADED = False

                # Mock Path.is_file() to always return False so no config files are found
                with patch("pathlib.Path.is_file", return_value=False):
                    with pytest.raises(ConfigError, match="Could not find orpheus.yaml"):
                        OrpheusConfig.load(config_path=nonexistent, allow_missing=False)
            finally:
                OrpheusConfig._instance = original_instance
                OrpheusConfig._DOTENV_LOADED = original_dotenv


class TestAudioConfigPlaybackCommand:
    """Tests for AudioConfig.playback_command field."""

    def test_from_dict_with_playback_command(self):
        """AudioConfig.from_dict should parse playback_command field."""
        from orpheus_common.config import AudioConfig

        data = {
            "sample_rate": 48000,
            "chunk_size": 2048,
            "format": "pcm_s32le",
            "playback_command": "ffplay",
            "channels": [],
        }
        config = AudioConfig.from_dict(data)
        assert config.playback_command == "ffplay"

    def test_from_dict_without_playback_command_uses_default(self):
        """AudioConfig.from_dict should use default playback_command if not provided."""
        from orpheus_common.config import AudioConfig

        data = {
            "sample_rate": 48000,
            "chunk_size": 2048,
            "format": "float32",
            "channels": [],
        }
        config = AudioConfig.from_dict(data)
        assert config.playback_command == "aplay"

    def test_to_dict_includes_playback_command(self):
        """AudioConfig.to_dict should include playback_command field."""
        from orpheus_common.config import AudioConfig

        config = AudioConfig(
            sample_rate=48000,
            chunk_size=2048,
            format="pcm_s32le",
            playback_command="paplay",
            channels=[],
        )
        result = config.to_dict()
        assert result["playback_command"] == "paplay"
        assert result["sample_rate"] == 48000
        assert result["chunk_size"] == 2048
        assert result["format"] == "pcm_s32le"
        assert result["channels"] == []

    def test_env_override_playback_command(self, monkeypatch, tmp_path):
        """Environment variable ORPHEUS_AUDIO__PLAYBACK_COMMAND should override config."""
        import yaml

        # Create a temporary config file
        config_data = {
            "mqtt": {"broker_host": "localhost", "broker_port": 1883},
            "audio": {
                "sample_rate": 48000,
                "chunk_size": 2048,
                "format": "float32",
                "playback_command": "aplay",
                "channels": [],
            },
            "storage": {"base_path": "/tmp/orpheus"},
            "detection": {"database_path": "/tmp/detections.db"},
        }
        config_file = tmp_path / "orpheus.yaml"
        with open(config_file, "w") as f:
            yaml.dump(config_data, f)

        # Set environment variable to override playback_command
        monkeypatch.setenv("ORPHEUS_AUDIO__PLAYBACK_COMMAND", "ffplay")

        # Reset singleton
        original_instance = OrpheusConfig._instance
        try:
            OrpheusConfig._instance = None
            config = OrpheusConfig.load(config_path=config_file)
            assert config.audio.playback_command == "ffplay"
        finally:
            OrpheusConfig._instance = original_instance

    def test_to_dict_with_channels(self):
        """AudioConfig.to_dict should serialize channels correctly."""
        from orpheus_common.config import AudioChannel, AudioConfig, AudioDetectionConfig

        detection = AudioDetectionConfig(
            algorithm="adaptive_threshold",
            threshold_db=-40.0,
            margin_db=10.0,
        )
        channel = AudioChannel(
            id=1,
            name="Test Channel",
            enabled=True,
            device="alsa://test",
            detection=detection,
        )
        config = AudioConfig(
            sample_rate=48000,
            chunk_size=2048,
            format="pcm_s32le",
            playback_command="aplay",
            channels=[channel],
        )
        result = config.to_dict()
        assert len(result["channels"]) == 1
        assert result["channels"][0]["id"] == 1
        assert result["channels"][0]["name"] == "Test Channel"
        assert result["channels"][0]["detection"]["algorithm"] == "adaptive_threshold"


class TestSiteConfig:
    """Tests for SiteConfig dataclass."""

    def test_defaults(self):
        """SiteConfig should have sensible defaults."""
        from orpheus_common.config import SiteConfig

        site = SiteConfig.from_dict({})
        assert site.lat is None
        assert site.lon is None
        assert site.elevation is None
        assert site.name == ""

    def test_from_dict(self):
        """SiteConfig should parse from dict."""
        from orpheus_common.config import SiteConfig

        site = SiteConfig.from_dict(
            {"lat": 47.6, "lon": -122.3, "elevation": 56.0, "name": "Seattle"}
        )
        assert site.lat == 47.6
        assert site.lon == -122.3
        assert site.elevation == 56.0
        assert site.name == "Seattle"

    def test_partial_dict(self):
        """SiteConfig should handle partial data."""
        from orpheus_common.config import SiteConfig

        site = SiteConfig.from_dict({"lat": 47.6, "lon": -122.3})
        assert site.lat == 47.6
        assert site.lon == -122.3
        assert site.elevation is None
        assert site.name == ""

    def test_orpheus_config_has_site(self):
        """OrpheusConfig should expose a site attribute."""
        config = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}},
            source="<test>",
        )
        assert hasattr(config, "site")
        assert config.site.lat is None

    def test_orpheus_config_site_from_yaml(self):
        """OrpheusConfig should parse the site section from data."""
        config = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "site": {"lat": 47.6, "lon": -122.3, "elevation": 56.0, "name": "HQ"},
            },
            source="<test>",
        )
        assert config.site.lat == 47.6
        assert config.site.lon == -122.3
        assert config.site.elevation == 56.0
        assert config.site.name == "HQ"


class TestEventCorrelationConfig:
    """Tests for EventCorrelationConfig dataclass."""

    def test_defaults(self):
        """EventCorrelationConfig should have sensible defaults."""
        from orpheus_common.config import EventCorrelationConfig

        ec = EventCorrelationConfig.from_dict({})
        # Layer 2 (cross-classifier-identity): audio.classified is now a
        # first-class clustering input.
        assert ec.input_topics == [
            "orpheus/detection/bird/events",
            "orpheus/detection/crow/events",
            "orpheus/detection/audio/events",
        ]

    def test_custom_topics(self):
        """EventCorrelationConfig should accept custom topics."""
        from orpheus_common.config import EventCorrelationConfig

        ec = EventCorrelationConfig.from_dict({"input_topics": ["orpheus/detection/custom/events"]})
        assert ec.input_topics == ["orpheus/detection/custom/events"]

    def test_invalid_topics_type(self):
        """EventCorrelationConfig should reject non-list input_topics."""
        from orpheus_common.config import EventCorrelationConfig

        with pytest.raises(ConfigError):
            EventCorrelationConfig.from_dict({"input_topics": "not-a-list"})

    def test_orpheus_config_has_correlation(self):
        """OrpheusConfig should expose a correlation attribute."""
        config = OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}},
            source="<test>",
        )
        assert hasattr(config, "correlation")
        # Layer 2: 3 default topics (bird + crow + audio.classified).
        assert len(config.correlation.input_topics) == 3

    def test_orpheus_config_correlation_from_yaml(self):
        """OrpheusConfig should parse the correlation section from data."""
        config = OrpheusConfig.from_dict(
            {
                "mqtt": {"broker_host": "localhost"},
                "correlation": {"input_topics": ["a/b"]},
            },
            source="<test>",
        )
        assert config.correlation.input_topics == ["a/b"]


class TestAgentsSectionGuards:
    """agents.<name> must be a mapping (or empty). A scalar there previously
    crashed config load with a raw AttributeError deep in from_dict."""

    def _load(self, agents):
        return OrpheusConfig.from_dict(
            {"mqtt": {"broker_host": "localhost"}, "agents": agents}, source="<test>"
        )

    def test_empty_agent_entry_yields_defaults(self):
        cfg = self._load({"audio-motion": None})  # bare `audio-motion:` key
        assert cfg.agents["audio-motion"].heartbeat_seconds == 30.0

    def test_empty_agents_section_yields_no_overrides(self):
        assert self._load(None).agents == {}

    def test_scalar_agent_entry_raises_config_error(self):
        with pytest.raises(ConfigError, match="agents.audio-motion must be a mapping"):
            self._load({"audio-motion": "fast"})

    def test_scalar_agents_section_raises_config_error(self):
        with pytest.raises(ConfigError, match="agents must be a mapping"):
            self._load("fast")
