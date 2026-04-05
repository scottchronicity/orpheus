"""Configuration loader for the Video Motion Detector agent."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)

# RTSP stream type constants for Amcrest cameras
RTSP_MAIN_STREAM = 0  # High quality main stream
RTSP_SUB_STREAM = 1  # Lower quality sub-stream


@dataclass(frozen=True)
class CameraConfig:
    """Runtime configuration for an individual camera."""

    id: str
    label: str
    enabled: bool = True
    rtsp_url: Optional[str] = None


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
class RuntimeSettings:
    """Video capture runtime configuration."""

    fps: int
    width: int
    height: int
    max_pending_frames: int
    working_directory: Path


@dataclass(frozen=True)
class StorageSettings:
    """Clip persistence configuration."""

    category: str
    retain_days: int
    write_format: str


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
    cameras: list[CameraConfig]
    storage: StorageSettings
    logging: LoggingSettings


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load agent configuration from unified OrpheusConfig."""

    # Use the unified config system
    if config_path:
        orpheus_config = OrpheusConfig.load(config_path=config_path, allow_missing=False)
    else:
        orpheus_config = OrpheusConfig.get_instance()

    # Get camera registry
    camera_registry = orpheus_config.camera_registry()

    # Get video motion settings from config with defaults
    motion_cfg = orpheus_config.video.motion_detection
    if motion_cfg:
        fps = motion_cfg.fps
        width = motion_cfg.width
        height = motion_cfg.height
    else:
        # Fallback defaults if motion_detection not configured
        fps = 10
        width = 640
        height = 480

    runtime = RuntimeSettings(
        fps=fps,
        width=width,
        height=height,
        max_pending_frames=50,
        working_directory=Path(orpheus_config.storage.base_path) / "video" / "motion",
    )

    mqtt = MQTTSettings(
        broker_host=orpheus_config.mqtt.broker_host,
        broker_port=orpheus_config.mqtt.broker_port,
        keepalive=orpheus_config.mqtt.keepalive,
        topic_events=orpheus_config.mqtt.topics.get(
            "video_motion_events", "orpheus/video/motion/events"
        ),
        topic_status=orpheus_config.mqtt.topics.get(
            "video_motion_status", "orpheus/video/motion/status"
        ),
        qos=1,
    )

    # Get cameras from registry
    cameras: list[CameraConfig] = []
    for camera in camera_registry.list_cameras():
        rtsp_url = camera.get_rtsp_url(channel=1, subtype=RTSP_SUB_STREAM)
        if not rtsp_url:
            logger.warning("Camera has no RTSP URL, skipping", camera_name=camera.name)
            continue
        cameras.append(
            CameraConfig(
                id=camera.name,
                label=f"{camera.name} ({camera.model})",
                enabled=True,
                rtsp_url=rtsp_url,
            )
        )

    storage = StorageSettings(
        category="video_motion",
        retain_days=orpheus_config.storage.retention.raw_video_days,
        write_format=orpheus_config.storage.format.video,
    )

    logging_settings = LoggingSettings(
        level=orpheus_config.logging.level,
        use_json=orpheus_config.logging.format == "json",
    )

    return AppConfig(
        runtime=runtime,
        mqtt=mqtt,
        cameras=cameras,
        storage=storage,
        logging=logging_settings,
    )
