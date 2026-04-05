"""
System health monitoring for Orpheus platform.

Provides system-level health metrics including CPU, memory, disk usage,
uptime, and service status via systemd.
"""

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Optional

import psutil

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SystemMetrics:
    """System health metrics."""

    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "cpu_percent": self.cpu_percent,
            "memory_percent": self.memory_percent,
            "disk_percent": self.disk_percent,
            "uptime_seconds": self.uptime_seconds,
        }


@dataclass
class StorageMetrics:
    """Storage usage metrics for configured data root."""

    ok: bool
    path: str
    total: int
    used: int
    free: int
    percent: float
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "ok": self.ok,
            "path": self.path,
        }
        if self.ok:
            result.update(
                {
                    "total": self.total,
                    "used": self.used,
                    "free": self.free,
                    "percent": self.percent,
                }
            )
        else:
            result["error"] = self.error
        return result


class SystemHealth:
    """
    System health monitoring for Orpheus platform.

    Provides metrics for CPU, memory, disk, uptime, and systemd services.
    """

    def get_metrics(self) -> SystemMetrics:
        """
        Get current system health metrics.

        Returns:
            SystemMetrics with CPU, memory, disk, and uptime

        Example:
            >>> from orpheus_common.system.health import SystemHealth
            >>> health = SystemHealth()
            >>> metrics = health.get_metrics()
            >>> print(f"CPU: {metrics.cpu_percent}%")
        """
        boot_time = psutil.boot_time()
        uptime = int(time.time() - boot_time)

        return SystemMetrics(
            cpu_percent=round(psutil.cpu_percent(interval=1), 1),
            memory_percent=round(psutil.virtual_memory().percent, 1),
            disk_percent=round(psutil.disk_usage("/").percent, 1),
            uptime_seconds=uptime,
        )

    def get_data_storage(self) -> StorageMetrics:
        """
        Get storage usage for the external data root.

        Uses ORPHEUS_DATA_ROOT environment variable to locate storage.
        Defaults to /data/orpheus.

        Returns:
            StorageMetrics with usage statistics or error

        Example:
            >>> health = SystemHealth()
            >>> storage = health.get_data_storage()
            >>> if storage.ok:
            ...     print(f"Storage {storage.percent}% full")
        """
        from orpheus_common.storage.paths import get_data_root

        path = str(get_data_root())

        if not os.path.exists(path):
            return StorageMetrics(
                ok=False,
                path=path,
                total=0,
                used=0,
                free=0,
                percent=0.0,
                error=f"Path not found: {path}",
            )

        try:
            usage = shutil.disk_usage(path)

            total = usage.total
            used = usage.used
            free = usage.free
            percent = round((used / total) * 100, 1) if total > 0 else 0.0

            return StorageMetrics(
                ok=True,
                path=path,
                total=total,
                used=used,
                free=free,
                percent=percent,
            )
        except Exception as e:
            return StorageMetrics(
                ok=False, path=path, total=0, used=0, free=0, percent=0.0, error=str(e)
            )

    def check_service(self, service_name: str) -> dict[str, str]:
        """
        Check status of a systemd service.

        Args:
            service_name: Service name (without .service suffix)

        Returns:
            Dictionary with:
            - name (str): Service name
            - status (str): "running", "stopped", or "unknown"
            - reason (str): Error message if not running

        Example:
            >>> health = SystemHealth()
            >>> status = health.check_service("orpheus-dashboard")
            >>> print(f"Dashboard: {status['status']}")
        """
        # Find systemctl executable
        systemctl_path = shutil.which("systemctl")
        if not systemctl_path:
            for path in ["/bin/systemctl", "/usr/bin/systemctl"]:
                if os.path.exists(path):
                    systemctl_path = path
                    break

        if not systemctl_path:
            logger.warning("systemctl executable not found")
            return {"name": service_name, "status": "unknown", "reason": "systemctl not available"}

        try:
            result = subprocess.run(
                [systemctl_path, "is-active", f"{service_name}.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )

            if result.returncode == 0:
                status = "running"
                reason = ""
            else:
                status = "stopped"
                reason = "Service is not running"

            return {"name": service_name, "status": status, "reason": reason}

        except subprocess.TimeoutExpired:
            logger.error("Timeout querying service", service_name=service_name)
            return {
                "name": service_name,
                "status": "unknown",
                "reason": "Timeout querying service status",
            }
        except Exception as e:
            logger.error("Error querying service", service_name=service_name, error=str(e))
            return {"name": service_name, "status": "unknown", "reason": str(e)}

    def check_services(self, service_names: list[str]) -> list[dict[str, str]]:
        """
        Check status of multiple systemd services.

        Args:
            service_names: List of service names (without .service suffix)

        Returns:
            List of service status dictionaries

        Example:
            >>> health = SystemHealth()
            >>> services = health.check_services([
            ...     "orpheus-dashboard",
            ...     "orpheus-mqtt",
            ...     "orpheus-agent-audio-motion"
            ... ])
            >>> for svc in services:
            ...     print(f"{svc['name']}: {svc['status']}")
        """
        return [self.check_service(name) for name in service_names]


# Convenience functions for backward compatibility


def get_system_metrics() -> dict[str, Any]:
    """Get system health metrics as dictionary."""
    health = SystemHealth()
    return health.get_metrics().to_dict()


def get_data_storage_usage() -> dict[str, Any]:
    """Get data storage usage as dictionary."""
    health = SystemHealth()
    return health.get_data_storage().to_dict()


def check_service_status(service_name: str) -> dict[str, str]:
    """Check single service status."""
    health = SystemHealth()
    return health.check_service(service_name)
