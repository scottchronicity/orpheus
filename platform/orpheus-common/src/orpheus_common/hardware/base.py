"""
Hardware abstraction base classes for Orpheus.

Provides abstract base classes for hardware components (cameras, audio interfaces, etc.)
with standardized health checking and status reporting.
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class Camera(ABC):
    """
    Abstract base class for all camera implementations.

    Provides standardized interface for camera health checking, snapshot capture,
    and RTSP stream access across different camera models.
    """

    def __init__(
        self,
        name: str,
        host: str,
        model: str,
        username: str,
        password: str,
        snapshots: Optional[Any] = None,
        timelapses: Optional[Any] = None,
        enabled: bool = True,
    ):
        """
        Initialize camera instance.

        Args:
            name: Camera identifier (e.g., "north", "south")
            host: Hostname or IP address
            model: Camera model number
            username: Authentication username
            password: Authentication password
            snapshots: Optional SnapshotConfig for periodic snapshot capture
            timelapses: Optional list of TimelapseConfig for timelapse generation
            enabled: Whether the camera is enabled (default True)
        """
        self.name = name
        self.host = host
        self.model = model
        self.username = username
        self.password = password
        self.snapshots = snapshots
        self.timelapses = timelapses
        self.enabled = enabled
        self.camera_type = self.__class__.__name__.replace("Camera", "").lower()
        self._last_health_check = 0
        self._last_health_status = None

    @abstractmethod
    def check_network(self) -> dict[str, Any]:
        """
        Ping camera to check network connectivity.

        Returns:
            Dictionary with keys:
            - ok (bool): Network check succeeded
            - latency_ms (float): Network latency in milliseconds
            - error (str|None): Error message if check failed
        """
        pass

    @abstractmethod
    def check_http_api(self) -> dict[str, Any]:
        """
        Check if HTTP API is accessible.

        Returns:
            Dictionary with keys:
            - ok (bool): API check succeeded
            - response_time_ms (float): Response time in milliseconds
            - error (str|None): Error message if check failed
        """
        pass

    @abstractmethod
    def capture_snapshot(self) -> dict[str, Any]:
        """
        Capture and cache a snapshot image.

        Returns:
            Dictionary with keys:
            - ok (bool): Snapshot captured successfully
            - size_bytes (int): Image size in bytes
            - cached_at (str): ISO timestamp when cached
            - image_data (bytes|None): JPEG image data
            - error (str|None): Error message if capture failed
        """
        pass

    @abstractmethod
    def check_rtsp_stream(self) -> dict[str, Any]:
        """
        Verify RTSP stream is accessible.

        Returns:
            Dictionary with keys:
            - ok (bool): Stream check succeeded
            - connection_time_ms (float): Connection time in milliseconds
            - error (str|None): Error message if check failed
        """
        pass

    @abstractmethod
    def get_system_info(self) -> dict[str, Any]:
        """
        Get camera system information.

        Returns:
            Dictionary with keys:
            - ok (bool): System info retrieved successfully
            - firmware_version (str): Camera firmware version
            - serial_number (str): Camera serial number
            - uptime_seconds (int): Camera uptime in seconds
            - error (str|None): Error message if retrieval failed
        """
        pass

    def get_health_status(self, ttl_seconds: float = 5.0) -> dict[str, Any]:
        """
        Run all health checks and return comprehensive status.

        Caches result for TTL seconds to avoid overwhelming camera with requests.

        Args:
            ttl_seconds: Cache TTL in seconds

        Returns:
            Dictionary with keys:
            - name (str): Camera name
            - host (str): Camera host/IP
            - model (str): Camera model
            - type (str): Camera type (e.g., "amcrest")
            - status (str): Overall status ("healthy", "degraded", "offline")
            - checks (dict): Individual check results
            - system_info (dict): System information
            - last_check (str): ISO timestamp of check

        Status Determination:
        - "offline": Network or HTTP API unreachable
        - "degraded": Network OK but snapshot or RTSP failing
        - "healthy": All checks passing
        """
        # Return cached status if less than TTL seconds old
        if self._last_health_status and (time.time() - self._last_health_check) < ttl_seconds:
            return self._last_health_status

        # Run all checks
        network = self.check_network()
        http_api = self.check_http_api()
        snapshot = self.capture_snapshot()
        rtsp = self.check_rtsp_stream()
        system_info = self.get_system_info()

        # Determine overall status
        if not network["ok"] or not http_api["ok"]:
            status = "offline"
        elif not snapshot["ok"] or not rtsp["ok"]:
            status = "degraded"
        else:
            status = "healthy"

        # Create a copy of snapshot status without the image data
        # This prevents JSON serialization errors with raw bytes
        snapshot_status = snapshot.copy()
        snapshot_status.pop("image_data", None)

        result = {
            "name": self.name,
            "host": self.host,
            "model": self.model,
            "type": self.camera_type,
            "status": status,
            "checks": {
                "network": network,
                "http_api": http_api,
                "snapshot": snapshot_status,
                "rtsp_stream": rtsp,
            },
            "system_info": system_info,
            "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

        # Cache result
        self._last_health_status = result
        self._last_health_check = time.time()

        return result
