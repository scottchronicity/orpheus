"""
Camera registry and discovery for Orpheus.

Provides centralized camera management, loading cameras from configuration
and providing easy access across services and agents.
"""

import os
from typing import Optional

from orpheus_common.hardware.base import Camera
from orpheus_common.hardware.cameras import CAMERA_TYPE_MAP
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class CameraRegistry:
    """
    Centralized camera registry for loading and managing camera instances.

    Supports loading cameras from:
    - Environment variables (legacy dashboard pattern)
    - YAML configuration (new recommended pattern)
    """

    def __init__(self, cameras: list[Camera]):
        """
        Initialize registry with camera instances.

        Args:
            cameras: List of Camera instances
        """
        self._cameras = cameras
        self._camera_map = {cam.name: cam for cam in cameras}

    @classmethod
    def from_env(cls) -> "CameraRegistry":
        """
        Load camera configurations from environment variables (legacy).

        DEPRECATED: Use from_config() instead to load from OrpheusConfig.
        This method exists for backward compatibility and loads ONLY from
        environment variables, ignoring any YAML configuration.

        Environment Variables:
        - CAMERA_USER: Username for all cameras
        - CAMERA_PASS: Password for all cameras
        - CAMERA_N_TYPE: Camera type (e.g., "amcrest")
        - CAMERA_N_NAME: Camera name (e.g., "north")
        - CAMERA_N_HOST: Camera hostname or IP
        - CAMERA_N_MODEL: Camera model number

        Where N is 1-10.

        Returns:
            CameraRegistry instance

        Example:
            >>> # Set environment variables:
            >>> # CAMERA_USER=admin
            >>> # CAMERA_PASS=password
            >>> # CAMERA_1_TYPE=amcrest
            >>> # CAMERA_1_NAME=north
            >>> # CAMERA_1_HOST=192.168.1.100
            >>> registry = CameraRegistry.from_env()
            >>> camera = registry.get("north")
        """
        cameras = []

        # Load credentials directly from environment (not from config)
        username = os.getenv("CAMERA_USER")
        password = os.getenv("CAMERA_PASS")

        if not username or not password:
            logger.error("CAMERA_USER and CAMERA_PASS must be set in environment")
            return cls(cameras)

        for i in range(1, 11):  # Support up to 10 cameras
            cam_type = os.getenv(f"CAMERA_{i}_TYPE")
            if not cam_type:
                continue  # No more cameras configured

            name = os.getenv(f"CAMERA_{i}_NAME")
            host = os.getenv(f"CAMERA_{i}_HOST")
            model = os.getenv(f"CAMERA_{i}_MODEL", "Unknown")

            if not name or not host:
                logger.warning("Camera missing NAME or HOST, skipping", camera_index=i)
                continue

            camera_class = CAMERA_TYPE_MAP.get(cam_type.lower())
            if not camera_class:
                logger.warning(
                    "Unknown camera type, skipping", camera_type=cam_type, camera_index=i
                )
                continue

            try:
                camera = camera_class(
                    name=name,
                    host=host,
                    model=model,
                    username=username,
                    password=password,
                    snapshots=None,
                    timelapses=None,
                    enabled=True,
                )
                cameras.append(camera)
                logger.info("Loaded camera", camera_name=name, camera_type=cam_type)
            except Exception as e:
                logger.error("Failed to initialize camera", camera_index=i, error=str(e))

        logger.info("Loaded cameras from environment", camera_count=len(cameras))
        return cls(cameras)

    @classmethod
    def from_config(cls, config_file: str = "cameras.yaml") -> "CameraRegistry":
        """
        Load camera configurations from YAML file or OrpheusConfig.

        If config_file is "orpheus.yaml" or not specified, uses OrpheusConfig singleton.
        Otherwise loads from the specified YAML file.

        YAML Format (in orpheus.yaml):
            cameras:
              auth:
                username: admin
                password: mypassword
              north:
                type: amcrest
                host: 192.168.1.100
                model: IP5M-B1186EW-AI-V3
                enabled: true
              south:
                type: amcrest
                host: 192.168.1.101
                model: IP5M-B1186EW-AI-V3
                enabled: false

        Args:
            config_file: Path to YAML configuration file (default: "cameras.yaml")

        Returns:
            CameraRegistry instance

        Example:
            >>> registry = CameraRegistry.from_config()  # Uses OrpheusConfig
            >>> camera = registry.get("north")
        """
        from orpheus_common import OrpheusConfig

        # Use OrpheusConfig for the main config
        if config_file in ("orpheus.yaml", "cameras.yaml"):
            orpheus_config = OrpheusConfig.get_instance()
            username, password = orpheus_config.camera_credentials()
            cameras_config = orpheus_config.camera_configs()
        else:
            # Load from custom file (legacy support)
            try:
                from orpheus_common.config import Config

                config = Config.load(config_file, required=False)
                cameras_data = config.get("cameras", default={})

                if not cameras_data:
                    logger.warning("No cameras configuration found", config_file=config_file)
                    return cls([])

                # Get authentication
                auth = cameras_data.get("auth", {})
                username = auth.get("username")
                password = auth.get("password")
                cameras_config = {
                    k: v for k, v in cameras_data.items() if k != "auth" and isinstance(v, dict)
                }
            except Exception as e:
                logger.error(
                    "Failed to load camera configuration", config_file=config_file, error=str(e)
                )
                return cls([])

        if not username or not password:
            logger.error("cameras.auth.username and cameras.auth.password required")
            return cls([])

        cameras = []

        for name, cam_config in cameras_config.items():
            if not isinstance(cam_config, dict):
                logger.warning("Invalid camera config, skipping", camera_name=name)
                continue

            if not cam_config.get("enabled", True):
                logger.info("Camera is disabled, skipping", camera_name=name)
                continue

            cam_type = cam_config.get("type")
            host = cam_config.get("host")
            model = cam_config.get("model", "Unknown")

            if not cam_type or not host:
                logger.warning("Camera missing type or host, skipping", camera_name=name)
                continue

            camera_class = CAMERA_TYPE_MAP.get(cam_type.lower())
            if not camera_class:
                logger.warning("Unknown camera type", camera_type=cam_type, camera_name=name)
                continue

            try:
                # Extract snapshots and timelapses config if present
                snapshots = None
                timelapses = None

                if "snapshots" in cam_config:
                    from orpheus_common.config import SnapshotConfig

                    snapshots_data = cam_config["snapshots"]
                    if isinstance(snapshots_data, dict):
                        snapshots = SnapshotConfig.from_dict(snapshots_data)

                if "timelapses" in cam_config:
                    from orpheus_common.config import TimelapseConfig

                    timelapses_data = cam_config["timelapses"]
                    if isinstance(timelapses_data, list):
                        timelapses = [TimelapseConfig.from_dict(tl) for tl in timelapses_data]

                camera = camera_class(
                    name=name,
                    host=host,
                    model=model,
                    username=username,
                    password=password,
                    snapshots=snapshots,
                    timelapses=timelapses,
                    enabled=cam_config.get("enabled", True),
                )
                cameras.append(camera)
                logger.info("Loaded camera", camera_name=name, camera_type=cam_type)
            except Exception as e:
                logger.error("Failed to initialize camera", camera_name=name, error=str(e))

        logger.info("Loaded cameras from config", camera_count=len(cameras))
        return cls(cameras)

    # Legacy alias for backward compatibility
    @classmethod
    def load_from_env(cls) -> list[Camera]:
        """Legacy method - returns list instead of registry. Use from_env() instead."""
        return cls.from_env()._cameras

    def get(self, name: str) -> Optional[Camera]:
        """
        Get camera by name.

        Args:
            name: Camera name

        Returns:
            Camera instance or None if not found
        """
        return self._camera_map.get(name)

    def list_cameras(self) -> list[Camera]:
        """
        Get list of all cameras.

        Returns:
            List of Camera instances
        """
        return self._cameras.copy()

    def get_camera_names(self) -> list[str]:
        """
        Get list of camera names.

        Returns:
            List of camera names
        """
        return list(self._camera_map.keys())

    def __len__(self) -> int:
        """Get number of cameras in registry."""
        return len(self._cameras)

    def __iter__(self):
        """Iterate over cameras."""
        return iter(self._cameras)
