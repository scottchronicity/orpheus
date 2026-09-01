"""Tests for ``AudioEventsConfig``."""

from __future__ import annotations

from unittest.mock import MagicMock

from orpheus_agent_audio_events.config import AudioEventsConfig


def _orpheus_config_with(raw: dict) -> MagicMock:
    """Helper: build a mock OrpheusConfig whose ``_raw`` attr is the given dict."""
    mock = MagicMock()
    mock._raw = raw
    return mock


class TestAudioEventsConfigDefaults:
    """When ``audio_events`` is missing from orpheus.yaml the agent must
    still construct a sane config from defaults."""

    def test_no_audio_events_section_yields_defaults(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(_orpheus_config_with({}))
        assert config.enabled is True
        assert config.model_variant == "cnn14_sed"
        assert config.sample_rate == 32000
        assert config.clip_threshold == 0.3
        assert config.frame_threshold == 0.2
        assert config.bridge_ms == 100
        assert config.min_interval_ms == 150
        assert config.max_labels_per_clip is None
        assert config.device == "auto"
        assert config.max_concurrent_clips == 2

    def test_default_input_topic_is_audio_motion(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(_orpheus_config_with({}))
        assert config.input_topic == "orpheus/audio/motion/events"

    def test_default_output_topic_is_detection_audio(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(_orpheus_config_with({}))
        assert config.output_topic == "orpheus/detection/audio/events"


class TestAudioEventsConfigOverrides:
    """Verify per-field overrides from orpheus.yaml's ``audio_events`` section."""

    def test_disabled(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with({"audio_events": {"enabled": False}})
        )
        assert config.enabled is False

    def test_thresholds_override(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with(
                {
                    "audio_events": {
                        "clip_threshold": 0.5,
                        "frame_threshold": 0.4,
                        "bridge_ms": 200,
                        "min_interval_ms": 300,
                    }
                }
            )
        )
        assert config.clip_threshold == 0.5
        assert config.frame_threshold == 0.4
        assert config.bridge_ms == 200
        assert config.min_interval_ms == 300

    def test_max_labels_per_clip_override(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with({"audio_events": {"max_labels_per_clip": 5}})
        )
        assert config.max_labels_per_clip == 5

    def test_max_concurrent_clips_override(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with({"audio_events": {"max_concurrent_clips": 4}})
        )
        assert config.max_concurrent_clips == 4

    def test_model_variant_and_path(self) -> None:
        custom_path = "/var/lib/orpheus/models/custom.pth"
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with(
                {
                    "audio_events": {
                        "model_variant": "cnn10_sed",
                        "model_path": custom_path,
                    }
                }
            )
        )
        assert config.model_variant == "cnn10_sed"
        assert config.model_path == custom_path

    def test_topics_pick_up_mqtt_section(self) -> None:
        """Default topics fall back to ``mqtt.topics`` if specified."""
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with(
                {
                    "mqtt": {
                        "topics": {
                            "audio_motion_events": "custom/in",
                            "audio_events_detections": "custom/out",
                        }
                    }
                }
            )
        )
        assert config.input_topic == "custom/in"
        assert config.output_topic == "custom/out"

    def test_explicit_topics_take_precedence(self) -> None:
        config = AudioEventsConfig.from_orpheus_config(
            _orpheus_config_with(
                {
                    "audio_events": {
                        "input_topic": "explicit/in",
                        "output_topic": "explicit/out",
                    }
                }
            )
        )
        assert config.input_topic == "explicit/in"
        assert config.output_topic == "explicit/out"
