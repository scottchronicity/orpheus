"""System health and status API endpoints.

Provides endpoints for system health monitoring, service status,
and storage information.
"""

import os
import shutil
import subprocess
import time
from typing import List, Optional

import psutil
from fastapi import APIRouter, Depends
from orpheus_common.hardware.storage import get_storage_hardware_info
from orpheus_common.logging import get_logger
from orpheus_common.system.health import get_data_storage_usage
from pydantic import BaseModel

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


class DiskInfo(BaseModel):
    """Disk storage information."""

    path: str
    percent: float
    total: Optional[int] = None
    used: Optional[int] = None
    free: Optional[int] = None
    ok: bool = True
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """System health metrics."""

    status: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int
    disk_system: Optional[DiskInfo] = None
    disk_data: Optional[DiskInfo] = None


class ServiceStatus(BaseModel):
    """Individual service status."""

    name: str
    status: str  # "running", "stopped", "unknown"
    reason: str


class ServicesResponse(BaseModel):
    """All services status."""

    services: List[ServiceStatus]


@router.get("/health", response_model=HealthResponse)
def get_health(user: User = Depends(current_active_user)):
    """Get current system health metrics.

    Returns CPU, memory, disk usage and system uptime.
    Includes both system (/) and data (/data/orpheus) disk metrics.
    Requires authentication.
    """
    boot_time = psutil.boot_time()
    uptime = int(time.time() - boot_time)

    # Get system disk usage (root filesystem)
    root_usage = psutil.disk_usage("/")
    disk_system = DiskInfo(
        path="/",
        percent=round(root_usage.percent, 1),
        total=root_usage.total,
        used=root_usage.used,
        free=root_usage.free,
        ok=True,
    )

    # Get data storage usage
    data_storage = get_data_storage_usage()
    disk_data = DiskInfo(
        path=data_storage.get("path", "/data/orpheus"),
        percent=data_storage.get("percent", 0.0),
        total=data_storage.get("total"),
        used=data_storage.get("used"),
        free=data_storage.get("free"),
        ok=data_storage.get("ok", False),
        error=data_storage.get("error"),
    )

    return HealthResponse(
        status="ok",
        cpu_percent=round(psutil.cpu_percent(interval=1), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_percent=round(root_usage.percent, 1),
        uptime_seconds=uptime,
        disk_system=disk_system,
        disk_data=disk_data,
    )


@router.get("/system/storage/data")
def get_storage_data(user: User = Depends(current_active_user)):
    """Get storage usage for the external data drive."""
    return get_data_storage_usage()


@router.get("/hardware/storage")
def get_storage_hardware(user: User = Depends(current_active_user)):
    """Get hardware status of storage devices."""
    return get_storage_hardware_info()


@router.get("/services/status", response_model=ServicesResponse)
def get_services_status(user: User = Depends(current_active_user)):
    """Get status of all Orpheus services.

    Queries systemctl for actual status.
    Requires authentication.
    """
    # Import config here to avoid circular imports
    from orpheus_common import OrpheusConfig

    config = OrpheusConfig.get_instance()
    service_names = config.dashboard_services()

    services_status = []

    # Find systemctl executable
    systemctl_path = shutil.which("systemctl")
    logger.debug("Locating systemctl", systemctl_path=systemctl_path)

    if not systemctl_path:
        for path in ["/bin/systemctl", "/usr/bin/systemctl"]:
            if os.path.exists(path):
                systemctl_path = path
                logger.debug("Found systemctl at fallback path", systemctl_path=systemctl_path)
                break

    if not systemctl_path:
        logger.warning("systemctl executable not found in PATH or fallback locations")

    for name in service_names:
        if not systemctl_path:
            # Handle local dev environment where systemctl is missing
            if name == "orpheus-ui":
                status = "running"
                reason = "Running in local dev mode (systemctl not found)"
            else:
                status = "unknown"
                reason = "Systemctl not available (checked PATH, /bin, /usr/bin)"

            services_status.append(ServiceStatus(name=name, status=status, reason=reason))
            continue

        try:
            logger.debug("Checking service", service_name=name)
            result = subprocess.run(
                [systemctl_path, "is-active", f"{name}.service"],
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

        except subprocess.TimeoutExpired:
            logger.error("Timeout querying service", service_name=name)
            status = "unknown"
            reason = "Timeout querying service status"
        except Exception as e:
            logger.error("Error querying service", service_name=name, error=str(e))
            status = "unknown"
            reason = str(e)

        services_status.append(ServiceStatus(name=name, status=status, reason=reason))

    return ServicesResponse(services=services_status)
