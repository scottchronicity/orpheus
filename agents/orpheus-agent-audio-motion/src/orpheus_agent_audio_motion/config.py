"""Configuration loader for the Audio Motion Detector agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ChannelConfig:
    """Runtime configuration for an individual audio channel."""

    id: str
    label: str
    enabled: bool = True


@dataclass(frozen=True)
class MQTTSettings:
    """MQTT broker connection and topic settings."""

    broker_host: str
    broker_port: int
    keepalive: int
    topic_events: str
    topic_status: str
    qos: int


@dataclass(frozen=True)
class DetectorSettings:
    """Parameters governing the motion detection heuristics."""

    aggressiveness: str
    trigger_threshold_dbfs: float
    release_threshold_dbfs: float
    cooldown_seconds: float
    min_event_duration_ms: int
    max_event_duration_ms: int


@dataclass(frozen=True)
class RuntimeSettings:
    """Audio capture runtime configuration."""

    sample_rate: int
    frame_duration_ms: int
    max_pending_frames: int
    working_directory: Path


@dataclass(frozen=True)
class StorageSettings:
    """Clip persistence configuration."""

    category: str
    retain_days: int
    write_format: str
    # Cleanup-sweep cadence. The audio agent's historical behavior is HOURLY
    # (the shared StorageRetention default is 6h) — see load_app_config for the
    # resolution rules. Kept here so main._periodic_cleanup has one seam to read.
    check_interval_hours: float = 1.0


@dataclass(frozen=True)
class LoggingSettings:
    """Logging preferences."""

    level: str
    use_json: bool


@dataclass(frozen=True)
class AppConfig:
    """Aggregated agent configuration."""

    runtime: RuntimeSettings
    mqtt: MQTTSettings
    channels: list[ChannelConfig]
    storage: StorageSettings
    logging: LoggingSettings


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load agent configuration from unified OrpheusConfig."""

    logger.debug("load_app_config called", config_path=str(config_path))

    # Use the unified config system
    # If a config_path is provided, load it explicitly; otherwise use the singleton
    if config_path:
        logger.debug("Loading explicit config", config_path=str(config_path))
        orpheus_config = OrpheusConfig.load(config_path=config_path, allow_missing=False)
    else:
        logger.debug("Getting OrpheusConfig singleton")
        orpheus_config = OrpheusConfig.get_instance()

    logger.debug("OrpheusConfig loaded", source=orpheus_config.config_source())

    # Get buffer duration from config, default to 200ms for stability
    buffer_duration_ms = getattr(orpheus_config.audio, "buffer_duration_ms", 200)

    runtime = RuntimeSettings(
        sample_rate=orpheus_config.audio.sample_rate,
        frame_duration_ms=buffer_duration_ms,
        max_pending_frames=50,  # Fixed for now
        working_directory=Path(orpheus_config.storage.base_path) / "audio" / "motion",
    )
    logger.debug(
        "Runtime settings created",
        sample_rate=runtime.sample_rate,
        buffer_duration_ms=buffer_duration_ms,
    )

    mqtt = MQTTSettings(
        broker_host=orpheus_config.mqtt.broker_host,
        broker_port=orpheus_config.mqtt.broker_port,
        keepalive=orpheus_config.mqtt.keepalive,
        topic_events=orpheus_config.mqtt.topics.get(
            "audio_motion_events", "orpheus/audio/motion/events"
        ),
        topic_status=orpheus_config.mqtt.topics.get(
            "audio_motion_status", "orpheus/audio/motion/status"
        ),
        qos=1,
    )

    # Get channels from unified config
    channels: list[ChannelConfig] = []
    for audio_channel in orpheus_config.audio.channels:
        if audio_channel.enabled:
            channels.append(
                ChannelConfig(
                    id=str(audio_channel.id),
                    label=audio_channel.name,
                    enabled=True,
                )
            )

    # Cleanup cadence: HOURLY by default — the audio agent's historical behavior.
    # The shared StorageRetention default is 6h, and the parsed dataclass can't
    # distinguish "operator set 6" from "unset", so falling through to it would
    # silently 6x the gap between cleanup passes on an unchanged yaml
    # (reversibility: defaults preserve today's behavior). An explicit
    # storage.retention.check_interval_hours still wins — presence is checked
    # against the raw parsed yaml (OrpheusConfig has no public "was it set"
    # accessor yet; the getattr fallback keeps a config without _raw on hourly).
    raw_storage = (getattr(orpheus_config, "_raw", None) or {}).get("storage") or {}
    raw_cadence = (raw_storage.get("retention") or {}).get("check_interval_hours")
    check_interval_hours = float(raw_cadence) if raw_cadence is not None else 1.0

    storage = StorageSettings(
        category="audio_motion",
        retain_days=orpheus_config.storage.retention.raw_audio_days,
        write_format=orpheus_config.storage.format.audio,
        check_interval_hours=check_interval_hours,
    )

    logging_settings = LoggingSettings(
        level=orpheus_config.logging.level,
        use_json=orpheus_config.logging.format == "json",
    )

    return AppConfig(
        runtime=runtime,
        mqtt=mqtt,
        channels=channels,
        storage=storage,
        logging=logging_settings,
    )
