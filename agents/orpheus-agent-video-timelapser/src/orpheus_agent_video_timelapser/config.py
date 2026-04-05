"""Configuration loader for the Video Timelapser agent."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orpheus_common.config import OrpheusConfig, TimelapseConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CameraTimelapseConfig:
    """Configuration for a single camera's timelapse settings."""

    name: str
    timelapses: list[TimelapseConfig]
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Aggregated agent configuration."""

    cameras: list[CameraTimelapseConfig]
    storage_base_path: Path
    log_level: str
    use_json_logging: bool


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load agent configuration from unified OrpheusConfig."""

    # Use the unified config system
    if config_path:
        orpheus_config = OrpheusConfig.load(config_path=config_path, allow_missing=False)
    else:
        orpheus_config = OrpheusConfig.get_instance()

    # Get camera registry
    camera_registry = orpheus_config.camera_registry()

    # Build list of cameras with timelapse settings
    cameras: list[CameraTimelapseConfig] = []
    for camera in camera_registry.list_cameras():
        # Check if timelapses are configured
        if not camera.timelapses or len(camera.timelapses) == 0:
            logger.debug(
                "Camera has no timelapse configuration, skipping",
                camera_name=camera.name,
            )
            continue

        cameras.append(
            CameraTimelapseConfig(
                name=camera.name,
                timelapses=camera.timelapses,
                enabled=camera.enabled,
            )
        )

    logger.info("Loaded timelapse configuration", camera_count=len(cameras))

    return AppConfig(
        cameras=cameras,
        storage_base_path=Path(orpheus_config.storage.base_path),
        log_level=orpheus_config.logging.level,
        use_json_logging=orpheus_config.logging.format == "json",
    )
