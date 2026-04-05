from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Optional

from orpheus_common.config import Config, OrpheusConfig, TimelapseConfig


@contextmanager
def _preserve_singleton() -> Generator[None, None, None]:
    original_instance = OrpheusConfig._instance
    original_dotenv = OrpheusConfig._DOTENV_LOADED
    try:
        OrpheusConfig._instance = None
        OrpheusConfig._DOTENV_LOADED = False
        yield
    finally:
        OrpheusConfig._instance = original_instance
        OrpheusConfig._DOTENV_LOADED = original_dotenv


def _build_config(data: Optional[dict[str, Any]] = None, source: str = "<test>") -> Config:
    return Config(data or {}, source=source)


def test_camera_registry_falls_back_to_environment(monkeypatch: Any) -> None:
    env_vars = {
        "CAMERA_USER": "admin",
        "CAMERA_PASS": "password123",
        "CAMERA_1_TYPE": "amcrest",
        "CAMERA_1_NAME": "north",
        "CAMERA_1_HOST": "192.168.1.100",
    }

    with _preserve_singleton():
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)

        cfg = OrpheusConfig(config=_build_config())
        OrpheusConfig._instance = cfg

        registry = cfg.camera_registry(reload=True)

        assert cfg.camera_registry_source() == "environment"
        assert len(registry) == 1
        assert registry.get("north") is not None

        debug_snapshot = cfg.get_debug_safe_values()
        assert debug_snapshot["camera_registry"]["source"] == "environment"
        assert debug_snapshot["camera_registry"]["count"] == "1"
        assert debug_snapshot["camera_environment"]["CAMERA_USER"] == "admin"


def test_camera_registry_uses_yaml_config_when_available() -> None:
    config_data = {
        "cameras": {
            "auth": {"username": "admin", "password": "secret"},
            "north": {
                "type": "amcrest",
                "host": "192.168.1.100",
                "model": "IP5M-B1186EW-AI-V3",
                "enabled": True,
            },
        }
    }

    with _preserve_singleton():
        cfg = OrpheusConfig(
            config=_build_config(config_data, source="/etc/orpheus/dashboard/orpheus.yaml")
        )
        OrpheusConfig._instance = cfg

        registry = cfg.camera_registry(reload=True)

        assert cfg.camera_registry_source().startswith("config:")
        assert len(registry) == 1
        assert registry.get("north") is not None

    debug_snapshot = cfg.get_debug_safe_values()
    assert debug_snapshot["camera_registry"]["source"].startswith("config:")
    assert debug_snapshot["camera_registry"]["count"] == "1"
    assert debug_snapshot["orpheus_config"]["video.auth.username"] == "admin"


def test_debug_safe_values_include_camera_environment(monkeypatch: Any) -> None:
    with _preserve_singleton():
        monkeypatch.setenv("CAMERA_USER", "viewer")
        monkeypatch.setenv("CAMERA_PASS", "topsecret")

        cfg = OrpheusConfig(config=_build_config())
        OrpheusConfig._instance = cfg

        safe_values = cfg.get_debug_safe_values()

        assert safe_values["camera_environment"]["CAMERA_USER"] == "viewer"
        assert safe_values["camera_environment"]["CAMERA_PASS"].startswith("***")
        assert safe_values["camera_registry"]["source"] == "environment"
        assert safe_values["camera_registry"]["count"] == "0"


def test_audio_channels_parsed() -> None:
    config_data = {
        "audio": {
            "sample_rate": 32000,
            "chunk_size": 2048,
            "format": "pcm_s16le",
            "channels": [
                {"id": 1, "name": "mic-1", "enabled": True, "device": "hw:0"},
                {"id": 2, "name": "mic-2", "enabled": False, "device": "hw:1"},
            ],
        }
    }

    with _preserve_singleton():
        cfg = OrpheusConfig(config=_build_config(config_data))
        assert cfg.audio.sample_rate == 32000
        assert len(cfg.audio.channels) == 2
        enabled = cfg.get_enabled_audio_channels()
        assert len(enabled) == 1
        assert enabled[0].name == "mic-1"


def test_env_overrides_support_double_underscores(monkeypatch: Any) -> None:
    with _preserve_singleton():
        monkeypatch.setenv("ORPHEUS_MQTT__BROKER_HOST", "mqtt.dev")
        monkeypatch.setenv("ORPHEUS_DASHBOARD__PORT", "9090")

        cfg = OrpheusConfig(config=_build_config())

        assert cfg.mqtt_broker_host() == "mqtt.dev"
        assert cfg.dashboard_port() == 9090


def test_dotenv_file_is_loaded(monkeypatch: Any, tmp_path: Any) -> None:
    dotenv_file = tmp_path / "orch.env"
    dotenv_file.write_text(
        "ORPHEUS_MQTT__BROKER_PORT=2883\nORPHEUS_STORAGE__BASE_PATH=./tmp-data\n"
    )

    monkeypatch.setenv("ORPHEUS_DOTENV_PATH", str(dotenv_file))

    with _preserve_singleton():
        # Clean up any env vars from the dotenv file after this test
        monkeypatch.delenv("ORPHEUS_MQTT__BROKER_PORT", raising=False)
        monkeypatch.delenv("ORPHEUS_STORAGE__BASE_PATH", raising=False)

        cfg = OrpheusConfig(config=_build_config())
        assert cfg.mqtt_broker_port() == 2883
        assert cfg.storage_data_path() == "./tmp-data"


def test_to_dict_returns_runtime_config_with_defaults(monkeypatch: Any) -> None:
    """Test that to_dict() returns runtime config including all defaults."""
    # Clean up any environment pollution from other tests
    monkeypatch.delenv("ORPHEUS_MQTT__BROKER_PORT", raising=False)
    monkeypatch.delenv("ORPHEUS_STORAGE__BASE_PATH", raising=False)

    config_data = {
        "mqtt": {
            "broker_host": "mqtt.test.local",
            "broker_port": 1883,
        },
        "storage": {
            "base_path": "/data/test",
            "retention": {
                "raw_audio_days": 45,
                # max_size_gb intentionally omitted to test defaults
            },
        },
    }

    with _preserve_singleton():
        # Prevent dotenv from being reloaded (which would override test values)
        OrpheusConfig._DOTENV_LOADED = True
        cfg = OrpheusConfig(config=_build_config(config_data))
        runtime_dict = cfg.to_dict()

        # Verify structure
        assert "mqtt" in runtime_dict
        assert "storage" in runtime_dict
        assert "audio" in runtime_dict
        assert "video" in runtime_dict
        assert "detection" in runtime_dict
        assert "dashboard" in runtime_dict
        assert "logging" in runtime_dict
        assert "hardware" in runtime_dict

        # Verify explicit config values are preserved
        assert runtime_dict["mqtt"]["broker_host"] == "mqtt.test.local"
        assert runtime_dict["mqtt"]["broker_port"] == 1883
        assert runtime_dict["storage"]["base_path"] == "/data/test"
        assert runtime_dict["storage"]["retention"]["raw_audio_days"] == 45

        # Verify defaults are included
        assert runtime_dict["storage"]["retention"]["max_size_gb"] == 50.0
        assert runtime_dict["storage"]["retention"]["cleanup_strategy"] == "oldest"
        assert runtime_dict["storage"]["retention"]["cleanup_trigger_percent"] == 90.0
        assert runtime_dict["storage"]["retention"]["cleanup_amount_percent"] == 25.0
        assert runtime_dict["storage"]["retention"]["check_interval_hours"] == 6.0
        assert runtime_dict["storage"]["retention"]["min_file_age_hours"] == 1.0

        # Verify it's JSON-serializable (no circular refs)
        import json

        json_str = json.dumps(runtime_dict)
        assert len(json_str) > 0


def test_get_debug_safe_values_uses_runtime_config() -> None:
    """Test that get_debug_safe_values() shows runtime config with defaults."""
    config_data = {
        "mqtt": {
            "broker_host": "mqtt.test.local",
        },
        "storage": {
            "retention": {
                "raw_audio_days": 45,
            },
        },
    }

    with _preserve_singleton():
        cfg = OrpheusConfig(config=_build_config(config_data))
        debug_values = cfg.get_debug_safe_values()

        # Should include defaults that weren't in YAML
        orpheus_config = debug_values["orpheus_config"]
        assert "storage.retention.max_size_gb" in orpheus_config
        assert orpheus_config["storage.retention.max_size_gb"] == "50.0"
        assert "storage.retention.cleanup_strategy" in orpheus_config
        assert orpheus_config["storage.retention.cleanup_strategy"] == "oldest"
        assert "storage.retention.raw_audio_days" in orpheus_config
        assert orpheus_config["storage.retention.raw_audio_days"] == "45"


def test_camera_configs_includes_snapshots_and_timelapses() -> None:
    """Test that camera_configs() includes snapshots and timelapses settings."""
    config_data = {
        "cameras": {
            "auth": {"username": "admin", "password": "secret"},
            "north": {
                "type": "amcrest",
                "host": "192.168.1.100",
                "model": "IP5M-B1186EW-AI-V3",
                "enabled": True,
                "snapshots": {"interval": "5m"},
                "timelapses": [
                    {
                        "label": "daily",
                        "start_time": "18:00",
                        "lookback_window": "24h",
                        "sampling_interval": "15m",
                        "retention_days": 90,
                        "clip_duration": 2.0,
                    },
                    {
                        "label": "two-day",
                        "start_time": "23:00",
                        "lookback_window": "48h",
                        "sampling_interval": "30m",
                        "retention_days": 90,
                        "clip_duration": 1.0,
                    },
                ],
            },
            "south": {
                "type": "amcrest",
                "host": "192.168.1.101",
                "model": "IP5M-B1186EW-AI-V3",
                "enabled": True,
            },
        }
    }

    with _preserve_singleton():
        cfg = OrpheusConfig(config=_build_config(config_data))
        OrpheusConfig._instance = cfg

        camera_configs = cfg.camera_configs()

        # Check north camera has snapshots and timelapses
        assert "north" in camera_configs
        north = camera_configs["north"]
        assert "snapshots" in north
        assert north["snapshots"]["interval"] == "5m"
        assert "timelapses" in north
        assert len(north["timelapses"]) == 2
        assert north["timelapses"][0]["label"] == "daily"
        assert north["timelapses"][0]["start_time"] == "18:00"
        assert north["timelapses"][0]["lookback_window"] == "24h"
        assert north["timelapses"][0]["sampling_interval"] == "15m"
        assert north["timelapses"][0]["retention_days"] == 90
        assert north["timelapses"][0]["clip_duration"] == 2.0
        assert north["timelapses"][1]["label"] == "two-day"
        assert north["timelapses"][1]["start_time"] == "23:00"
        assert north["timelapses"][1]["lookback_window"] == "48h"
        assert north["timelapses"][1]["sampling_interval"] == "30m"

        # Check south camera has no snapshots/timelapses
        assert "south" in camera_configs
        south = camera_configs["south"]
        assert "snapshots" not in south
        assert "timelapses" not in south


def test_camera_configs_timelapse_dicts_roundtrip_through_from_dict() -> None:
    """Verify camera_configs() timelapse dicts can be re-parsed by TimelapseConfig.from_dict().

    This is the code path used by CameraRegistry.from_config(): it calls
    camera_configs() to serialise cameras, then re-parses timelapse dicts
    with TimelapseConfig.from_dict().  If any required field (like 'label')
    is missing from the serialised dict the registry blows up.
    """
    config_data = {
        "cameras": {
            "auth": {"username": "admin", "password": "secret"},
            "cam1": {
                "type": "amcrest",
                "host": "192.168.1.50",
                "enabled": True,
                "timelapses": [
                    {
                        "label": "daily",
                        "start_time": "23:00",
                        "lookback_window": "24h",
                        "sampling_interval": "30m",
                        "retention_days": 90,
                        "clip_duration": 1.25,
                        "timezone": "America/Detroit",
                    },
                    {
                        "label": "hourly",
                        "start_time": "00:00",
                        "lookback_window": "1h",
                        "sampling_interval": "5m",
                        "retention_days": 30,
                        "clip_duration": 1.25,
                        "timezone": "America/Detroit",
                    },
                ],
            },
        },
    }

    with _preserve_singleton():
        cfg = OrpheusConfig(config=_build_config(config_data))
        cam_cfgs = cfg.camera_configs()

        for tl_dict in cam_cfgs["cam1"]["timelapses"]:
            # Must not raise — this is the exact call CameraRegistry makes
            tl = TimelapseConfig.from_dict(tl_dict)
            assert tl.label in ("daily", "hourly")
            assert tl.start_time in ("23:00", "00:00")
