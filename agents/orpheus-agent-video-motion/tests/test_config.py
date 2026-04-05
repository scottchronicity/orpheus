"""Tests for video motion agent configuration."""

from pathlib import Path

from orpheus_agent_video_motion.config import (
    AppConfig,
    CameraConfig,
    LoggingSettings,
    MQTTSettings,
    RuntimeSettings,
    StorageSettings,
    load_app_config,
)


def test_load_app_config_from_file(mock_config_path: Path):
    """Test loading configuration from a file."""
    config = load_app_config(mock_config_path)

    assert isinstance(config, AppConfig)
    assert isinstance(config.runtime, RuntimeSettings)
    assert isinstance(config.mqtt, MQTTSettings)
    assert isinstance(config.storage, StorageSettings)
    assert isinstance(config.logging, LoggingSettings)

    # Check runtime settings
    assert config.runtime.fps > 0
    assert config.runtime.width > 0
    assert config.runtime.height > 0

    # Check MQTT settings
    assert config.mqtt.broker_host == "localhost"
    assert config.mqtt.broker_port == 1883

    # Check storage settings
    assert config.storage.category == "video_motion"
    assert config.storage.write_format == "mp4"


def test_camera_config_dataclass():
    """Test CameraConfig dataclass."""
    camera = CameraConfig(
        id="test-camera",
        label="Test Camera",
        enabled=True,
        rtsp_url="rtsp://test:test@192.168.1.100:554/cam/realmonitor?channel=1&subtype=1",
    )

    assert camera.id == "test-camera"
    assert camera.label == "Test Camera"
    assert camera.enabled is True
    assert camera.rtsp_url is not None


def test_mqtt_settings_dataclass():
    """Test MQTTSettings dataclass."""
    mqtt = MQTTSettings(
        broker_host="localhost",
        broker_port=1883,
        keepalive=60,
        topic_events="test/events",
        topic_status="test/status",
        qos=1,
    )

    assert mqtt.broker_host == "localhost"
    assert mqtt.broker_port == 1883
    assert mqtt.qos == 1


def test_runtime_settings_dataclass():
    """Test RuntimeSettings dataclass."""
    runtime = RuntimeSettings(
        fps=10,
        width=640,
        height=480,
        max_pending_frames=50,
        working_directory=Path("/tmp/test"),
    )

    assert runtime.fps == 10
    assert runtime.width == 640
    assert runtime.height == 480


def test_storage_settings_dataclass():
    """Test StorageSettings dataclass."""
    storage = StorageSettings(
        category="video_motion",
        retain_days=30,
        write_format="mp4",
    )

    assert storage.category == "video_motion"
    assert storage.retain_days == 30
    assert storage.write_format == "mp4"


def test_logging_settings_dataclass():
    """Test LoggingSettings dataclass."""
    logging = LoggingSettings(
        level="INFO",
        use_json=False,
    )

    assert logging.level == "INFO"
    assert logging.use_json is False
