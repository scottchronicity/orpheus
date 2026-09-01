"""Configuration management for the audio-events detection agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from orpheus_common.config import OrpheusConfig


@dataclass
class AudioEventsConfig:
    """Configuration for the audio-events detection agent.

    See companion design doc ``docs/designs/audio-events-agent.md`` §4.1 for
    the rationale behind each knob's default value.
    """

    enabled: bool
    model_path: str
    model_variant: str
    sample_rate: int
    clip_threshold: float
    frame_threshold: float
    bridge_ms: int
    min_interval_ms: int
    max_labels_per_clip: int | None
    device: str
    input_topic: str
    output_topic: str
    # Max clips processed concurrently. A new audio.motion tick starts a new clip
    # without cancelling an in-flight one (older instances finish); bounded so SED
    # inference can't thrash the Jetson's unified RAM/GPU. Default small.
    max_concurrent_clips: int

    @classmethod
    def from_orpheus_config(cls, config: OrpheusConfig) -> AudioEventsConfig:
        """Build an ``AudioEventsConfig`` from the unified ``orpheus.yaml``."""
        agent_config = config._raw.get("audio_events", {})

        data_root = os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")
        default_model_path = f"{data_root}/models/panns_cnn14_decision_level_max.pth"

        topics = config._raw.get("mqtt", {}).get("topics", {})
        default_input_topic = topics.get("audio_motion_events", "orpheus/audio/motion/events")
        default_output_topic = topics.get(
            "audio_events_detections", "orpheus/detection/audio/events"
        )

        return cls(
            enabled=agent_config.get("enabled", True),
            model_path=agent_config.get("model_path", default_model_path),
            model_variant=agent_config.get("model_variant", "cnn14_sed"),
            sample_rate=int(agent_config.get("sample_rate", 32000)),
            clip_threshold=float(agent_config.get("clip_threshold", 0.3)),
            frame_threshold=float(agent_config.get("frame_threshold", 0.2)),
            bridge_ms=int(agent_config.get("bridge_ms", 100)),
            min_interval_ms=int(agent_config.get("min_interval_ms", 150)),
            max_labels_per_clip=agent_config.get("max_labels_per_clip"),
            device=str(agent_config.get("device", "auto")),
            input_topic=str(agent_config.get("input_topic", default_input_topic)),
            output_topic=str(agent_config.get("output_topic", default_output_topic)),
            max_concurrent_clips=int(agent_config.get("max_concurrent_clips", 2)),
        )


def load_config(config_path: Path | None = None) -> AudioEventsConfig:
    """Load audio-events configuration from the unified ``orpheus.yaml``."""
    orpheus_config = OrpheusConfig.get_instance(config_path=config_path)
    return AudioEventsConfig.from_orpheus_config(orpheus_config)
