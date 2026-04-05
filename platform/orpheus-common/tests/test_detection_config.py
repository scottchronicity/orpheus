"""Tests for AudioDetectionConfig and AudioChannel detection integration."""

import tempfile
from pathlib import Path

from orpheus_common.config import AudioChannel, AudioConfig, AudioDetectionConfig, OrpheusConfig


class TestAudioDetectionConfig:
    """Tests for AudioDetectionConfig dataclass."""

    def test_detection_config_defaults(self) -> None:
        """AudioDetectionConfig should have sensible defaults."""
        detection = AudioDetectionConfig()
        assert detection.algorithm == "adaptive_threshold"
        assert detection.threshold_db == -30.0
        assert detection.margin_db == 10.0
        assert detection.release_threshold_db == -35.0
        assert detection.holdoff_seconds == 2.0
        assert detection.min_duration_seconds == 0.3
        assert detection.max_duration_seconds == 30.0
        assert detection.prebuffer_seconds == 0.5
        assert detection.window_seconds == 30.0
        assert detection.update_interval_seconds == 5.0

    def test_detection_config_from_dict(self) -> None:
        """AudioDetectionConfig.from_dict should parse all fields."""
        data = {
            "algorithm": "fixed_threshold",
            "threshold_db": -25.0,
            "margin_db": 5.0,
            "release_threshold_db": -30.0,
            "holdoff_seconds": 1.5,
            "min_duration_seconds": 0.2,
            "max_duration_seconds": 20.0,
            "prebuffer_seconds": 0.3,
            "window_seconds": 60.0,
            "update_interval_seconds": 10.0,
        }
        detection = AudioDetectionConfig.from_dict(data)
        assert detection.algorithm == "fixed_threshold"
        assert detection.threshold_db == -25.0
        assert detection.margin_db == 5.0
        assert detection.release_threshold_db == -30.0
        assert detection.holdoff_seconds == 1.5
        assert detection.min_duration_seconds == 0.2
        assert detection.max_duration_seconds == 20.0
        assert detection.prebuffer_seconds == 0.3
        assert detection.window_seconds == 60.0
        assert detection.update_interval_seconds == 10.0

    def test_detection_config_from_dict_partial(self) -> None:
        """AudioDetectionConfig.from_dict should use defaults for missing fields."""
        data = {
            "algorithm": "adaptive_threshold",
            "threshold_db": -35.0,
        }
        detection = AudioDetectionConfig.from_dict(data)
        assert detection.algorithm == "adaptive_threshold"
        assert detection.threshold_db == -35.0
        # Verify defaults are used for unspecified fields
        assert detection.margin_db == 10.0
        assert detection.holdoff_seconds == 2.0


class TestAudioChannelWithDetection:
    """Tests for AudioChannel with detection config."""

    def test_audio_channel_without_detection(self) -> None:
        """AudioChannel should work without detection config."""
        channel = AudioChannel(id=1, name="Test Channel")
        assert channel.id == 1
        assert channel.name == "Test Channel"
        assert channel.detection is None

    def test_audio_channel_from_dict_without_detection(self) -> None:
        """AudioChannel.from_dict should work without detection field."""
        data = {"id": 1, "name": "Test Channel", "enabled": True}
        channel = AudioChannel.from_dict(data)
        assert channel.id == 1
        assert channel.name == "Test Channel"
        assert channel.detection is None

    def test_audio_channel_from_dict_with_detection(self) -> None:
        """AudioChannel.from_dict should parse detection config."""
        data = {
            "id": 1,
            "name": "Test Channel",
            "enabled": True,
            "detection": {
                "algorithm": "adaptive_threshold",
                "threshold_db": -35.0,
                "margin_db": 8.0,
                "release_threshold_db": -40.0,
                "holdoff_seconds": 1.5,
                "min_duration_seconds": 0.2,
                "max_duration_seconds": 20.0,
                "prebuffer_seconds": 0.5,
            },
        }
        channel = AudioChannel.from_dict(data)
        assert channel.id == 1
        assert channel.name == "Test Channel"
        assert channel.detection is not None
        assert channel.detection.algorithm == "adaptive_threshold"
        assert channel.detection.threshold_db == -35.0
        assert channel.detection.margin_db == 8.0
        assert channel.detection.release_threshold_db == -40.0
        assert channel.detection.holdoff_seconds == 1.5
        assert channel.detection.min_duration_seconds == 0.2
        assert channel.detection.max_duration_seconds == 20.0
        assert channel.detection.prebuffer_seconds == 0.5


class TestAudioConfigWithDetection:
    """Tests for AudioConfig with per-channel detection settings."""

    def test_audio_config_channels_with_detection(self) -> None:
        """AudioConfig should parse channels with detection configs."""
        data = {
            "sample_rate": 48000,
            "channels": [
                {
                    "id": 1,
                    "name": "Channel 1",
                    "enabled": True,
                    "detection": {
                        "algorithm": "adaptive_threshold",
                        "threshold_db": -35.0,
                        "margin_db": 8.0,
                    },
                },
                {
                    "id": 2,
                    "name": "Channel 2",
                    "enabled": True,
                    "detection": {
                        "algorithm": "fixed_threshold",
                        "threshold_db": -25.0,
                        "margin_db": 5.0,
                    },
                },
            ],
        }
        audio_config = AudioConfig.from_dict(data)
        assert len(audio_config.channels) == 2

        # Check first channel
        assert audio_config.channels[0].id == 1
        assert audio_config.channels[0].detection is not None
        assert audio_config.channels[0].detection.algorithm == "adaptive_threshold"
        assert audio_config.channels[0].detection.threshold_db == -35.0

        # Check second channel
        assert audio_config.channels[1].id == 2
        assert audio_config.channels[1].detection is not None
        assert audio_config.channels[1].detection.algorithm == "fixed_threshold"
        assert audio_config.channels[1].detection.threshold_db == -25.0


class TestOrpheusConfigWithDetection:
    """Integration tests for OrpheusConfig with per-channel detection."""

    def test_orpheus_config_loads_detection_from_yaml(self) -> None:
        """OrpheusConfig should load per-channel detection settings from YAML."""
        config_content = """
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Front Door
      enabled: true
      detection:
        algorithm: adaptive_threshold
        threshold_db: -35.0
        margin_db: 8.0
        release_threshold_db: -40.0
        holdoff_seconds: 1.5
        min_duration_seconds: 0.2
        max_duration_seconds: 20.0
        prebuffer_seconds: 0.5
        window_seconds: 30.0
        update_interval_seconds: 5.0
    - id: 2
      name: Back Door
      enabled: true
      detection:
        algorithm: fixed_threshold
        threshold_db: -25.0
        margin_db: 5.0

storage:
  base_path: /data/orpheus
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            # Clear singleton
            OrpheusConfig._instance = None
            config = OrpheusConfig.load(config_path=temp_path)

            # Verify channels loaded with detection config
            assert len(config.audio.channels) == 2

            # Check first channel (adaptive threshold)
            channel1 = config.audio.channels[0]
            assert channel1.id == 1
            assert channel1.name == "Front Door"
            assert channel1.detection is not None
            assert channel1.detection.algorithm == "adaptive_threshold"
            assert channel1.detection.threshold_db == -35.0
            assert channel1.detection.margin_db == 8.0
            assert channel1.detection.release_threshold_db == -40.0
            assert channel1.detection.holdoff_seconds == 1.5
            assert channel1.detection.min_duration_seconds == 0.2
            assert channel1.detection.max_duration_seconds == 20.0
            assert channel1.detection.prebuffer_seconds == 0.5
            assert channel1.detection.window_seconds == 30.0
            assert channel1.detection.update_interval_seconds == 5.0

            # Check second channel (fixed threshold)
            channel2 = config.audio.channels[1]
            assert channel2.id == 2
            assert channel2.name == "Back Door"
            assert channel2.detection is not None
            assert channel2.detection.algorithm == "fixed_threshold"
            assert channel2.detection.threshold_db == -25.0
            assert channel2.detection.margin_db == 5.0
            # Verify defaults are used for fields not in YAML
            assert channel2.detection.holdoff_seconds == 2.0

        finally:
            temp_path.unlink()
            OrpheusConfig._instance = None

    def test_orpheus_config_channel_without_detection(self) -> None:
        """OrpheusConfig should handle channels without detection config."""
        config_content = """
mqtt:
  broker_host: localhost
  broker_port: 1883

audio:
  sample_rate: 48000
  channels:
    - id: 1
      name: Test Channel
      enabled: true

storage:
  base_path: /data/orpheus
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(config_content)
            temp_path = Path(f.name)

        try:
            # Clear singleton
            OrpheusConfig._instance = None
            config = OrpheusConfig.load(config_path=temp_path)

            # Verify channel loaded without detection config
            assert len(config.audio.channels) == 1
            channel = config.audio.channels[0]
            assert channel.id == 1
            assert channel.name == "Test Channel"
            assert channel.detection is None

        finally:
            temp_path.unlink()
            OrpheusConfig._instance = None
