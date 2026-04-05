"""Configuration loader for the Video Snapshotter agent."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from orpheus_common.config import OrpheusConfig
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CameraSnapshotConfig:
    """Configuration for a single camera's snapshot settings."""

    name: str
    rtsp_url: str
    interval: str
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    """Aggregated agent configuration."""

    cameras: list[CameraSnapshotConfig]
    storage_base_path: Path
    log_level: str
    use_json_logging: bool
    retention_days: int = 547


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    """Load agent configuration from unified OrpheusConfig."""

    # Use the unified config system
    if config_path:
        orpheus_config = OrpheusConfig.load(config_path=config_path, allow_missing=False)
    else:
        orpheus_config = OrpheusConfig.get_instance()

    # Get camera registry
    camera_registry = orpheus_config.camera_registry()

    # Build list of cameras with snapshot settings
    cameras: list[CameraSnapshotConfig] = []
    for camera in camera_registry.list_cameras():
        # Check if snapshots are configured and enabled
        if not camera.snapshots or not camera.snapshots.interval:
            logger.debug(
                "Camera has no snapshot configuration, skipping",
                camera_name=camera.name,
            )
            continue

        # Skip if interval is "0" (disabled)
        if camera.snapshots.interval == "0":
            logger.debug(
                "Camera snapshot interval is '0' (disabled), skipping",
                camera_name=camera.name,
            )
            continue

        # Get RTSP URL for main stream (channel 1, main stream 0)
        rtsp_url = camera.get_rtsp_url(channel=1, subtype=0)
        if not rtsp_url:
            logger.warning("Camera has no RTSP URL, skipping", camera_name=camera.name)
            continue

        cameras.append(
            CameraSnapshotConfig(
                name=camera.name,
                rtsp_url=rtsp_url,
                interval=camera.snapshots.interval,
                enabled=camera.enabled,
            )
        )

    logger.info("Loaded snapshot configuration", camera_count=len(cameras))

    video_snapshotter_cfg = orpheus_config._raw.get("video_snapshotter", {}) or {}
    retention_days = int(video_snapshotter_cfg.get("retention_days", 547))

    return AppConfig(
        cameras=cameras,
        storage_base_path=Path(orpheus_config.storage.base_path),
        log_level=orpheus_config.logging.level,
        use_json_logging=orpheus_config.logging.format == "json",
        retention_days=retention_days,
    )
