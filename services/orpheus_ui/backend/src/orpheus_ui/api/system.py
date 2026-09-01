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
from fastapi import APIRouter, Depends, Response
from orpheus_common.hardware.storage import get_storage_hardware_info
from orpheus_common.logging import get_logger
from orpheus_common.system import list_storage_volumes
from orpheus_common.system.health import get_data_storage_usage
from pydantic import BaseModel

from orpheus_ui.api._responses import set_cache_control
from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User
from orpheus_ui.storage_categories import build_headroom_payload
from orpheus_ui.storage_history import compute_rate_and_projection, get_storage_history_db

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


class StorageHistoryPoint(BaseModel):
    """One daily storage sample."""

    day: str
    total_bytes: Optional[int] = None
    used_bytes: Optional[int] = None
    free_bytes: Optional[int] = None


class StorageVolumeTrend(BaseModel):
    """Current usage + daily history + fill-rate projection for one volume."""

    key: str
    label: str
    path: str
    total: Optional[int] = None
    used: Optional[int] = None
    free: Optional[int] = None
    percent: float = 0.0
    ok: bool = True
    error: Optional[str] = None
    series: List[StorageHistoryPoint] = []
    # Signed slope of free space: negative = filling up. None until there
    # are at least two days of history.
    free_bytes_per_day: Optional[float] = None
    # Days until free space hits zero at the current rate. None when free
    # space is flat/growing, or before there's enough history.
    projected_days_until_full: Optional[float] = None


class StorageHistoryResponse(BaseModel):
    """Per-volume storage trends over the requested window."""

    days: int
    volumes: List[StorageVolumeTrend]


@router.get("/system/storage/history", response_model=StorageHistoryResponse)
def get_storage_history(
    days: int = 30,
    response: Response = None,  # type: ignore[assignment]
    user: User = Depends(current_active_user),
):
    """Daily storage history + fill-rate projection for every tracked volume.

    For each storage space (system, orpheus data, …) returns its current
    usage, the daily free-space series over the last ``days`` days, and —
    once there are at least two days of history — the rate free space is
    changing and the projected days until full. History is forward-looking:
    it starts accumulating the day the sampler first runs.
    """
    days = max(1, min(days, 365))
    # Storage data updates ~daily so a 30s browser cache absorbs the
    # 60s react-query poll on Diagnostics without staleness mattering.
    # Matches the Cache-Control pattern used on the data history
    # endpoints in api/diagnostics.py.
    if response is not None:
        # Storage history polls slower than the data-history endpoints, so it
        # keeps its own max-age=30 / swr=60 rather than the shared 3x default —
        # see api/_responses.set_cache_control.
        set_cache_control(response, max_age=30, stale_while_revalidate=60)
    db = get_storage_history_db()
    volumes = []
    for vol in list_storage_volumes():
        series = db.history(vol["key"], days=days)
        projection = compute_rate_and_projection(series, vol.get("free"))
        volumes.append(
            StorageVolumeTrend(
                key=vol["key"],
                label=vol["label"],
                path=vol["path"],
                total=vol.get("total"),
                used=vol.get("used"),
                free=vol.get("free"),
                percent=vol.get("percent", 0.0),
                ok=vol.get("ok", False),
                error=vol.get("error"),
                series=[StorageHistoryPoint(**p) for p in series],
                free_bytes_per_day=projection["free_bytes_per_day"],
                projected_days_until_full=projection["projected_days_until_full"],
            )
        )
    return StorageHistoryResponse(days=days, volumes=volumes)


@router.get("/system/storage/headroom")
def get_storage_headroom(
    response: Response = None,  # type: ignore[assignment]
    user: User = Depends(current_active_user),
):
    """What each recording category is using, and which of them get trimmed.

    Serves the report orpheus-storage-sweep published on its last run —
    nothing here walks the filesystem, because the sweep already surveys the
    data root every few minutes and already holds the retention policy. Every
    category has a size; only some have a ceiling, and the payload keeps those
    two facts apart. Values carry the timestamp of the run that measured them.
    """
    if response is not None:
        # The report refreshes on the sweep cadence (minutes), so a short
        # browser cache costs nothing and absorbs the Diagnostics poll.
        set_cache_control(response, max_age=30, stale_while_revalidate=60)
    return build_headroom_payload()


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
