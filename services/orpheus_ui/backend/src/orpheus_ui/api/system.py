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
from orpheus_ui.gpu import average_utilization, gpu_info
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


class GpuMemory(BaseModel):
    """GPU memory on a shared-memory SoC: the system RAM pool the GPU uses,
    and what the PANNs worker's CUDA allocator holds of it."""

    shared: bool = True
    total_bytes: int
    available_bytes: int
    inference_reserved_bytes: Optional[int] = None
    inference_allocated_bytes: Optional[int] = None
    inference_floor_bytes: Optional[int] = None


class GpuInfo(BaseModel):
    """GPU telemetry; ``available`` is false on a host without a readable GPU."""

    available: bool
    utilization_percent: Optional[float] = None  # mean over the window below
    utilization_window_seconds: Optional[int] = None
    temperature_c: Optional[float] = None
    memory: Optional[GpuMemory] = None


class HealthResponse(BaseModel):
    """System health metrics."""

    status: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int
    disk_system: Optional[DiskInfo] = None
    disk_data: Optional[DiskInfo] = None
    gpu: Optional[GpuInfo] = None


def _gpu_worker_floor_mib() -> Optional[int]:
    """The PANNs worker's memory floor from orpheus.yaml, when it runs on the GPU."""
    from orpheus_common import OrpheusConfig

    raw = getattr(OrpheusConfig.get_instance(), "_raw", None) or {}
    section = raw.get("audio_events") or {}
    if section.get("backend") != "gpu_worker":
        return None
    floor = (section.get("gpu_worker") or {}).get("floor_memory_mib")
    return int(floor) if isinstance(floor, (int, float)) else None


class ServiceStatus(BaseModel):
    """Individual service status."""

    name: str
    status: str  # "running", "stopped", "unknown"
    reason: str  # why, when not plainly running; names a stale dashboard.services entry


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

    memory = psutil.virtual_memory()
    try:
        from orpheus_ui.api.entities import get_audio_events_health

        gpu = gpu_info(
            memory.total,
            memory.available,
            get_audio_events_health(user=user),
            _gpu_worker_floor_mib(),
            average_utilization(),
        )
    except Exception as e:  # noqa: BLE001 - telemetry must never fail the health check
        logger.warning("GPU telemetry unavailable", error=str(e))
        gpu = {"available": False}

    return HealthResponse(
        status="ok",
        cpu_percent=round(psutil.cpu_percent(interval=1), 1),
        memory_percent=round(memory.percent, 1),
        disk_percent=round(root_usage.percent, 1),
        uptime_seconds=uptime,
        disk_system=disk_system,
        disk_data=disk_data,
        gpu=GpuInfo(**gpu),
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


# dashboard.services entries already reported as stale, so a dashboard polling
# every few seconds logs each one once rather than on every request.
_reported_stale_services: set = set()


def _unit_status(systemctl_path: str, name: str) -> tuple:
    """Status and reason for one dashboard.services entry, from systemd.

    Reads the unit's load state and canonical name as well as whether it is
    active, so a stale entry is reported as stale: a retired unit that is no
    longer installed would otherwise read as merely "stopped", and an
    ``Alias=`` left over from a rename (orpheus-mqtt for orpheus-backplane)
    would read as "running" under its old name.
    """
    unit = f"{name}.service"
    result = subprocess.run(
        [systemctl_path, "show", unit, "--property=Id,LoadState,ActiveState,SubState"],
        capture_output=True,
        text=True,
        timeout=2,
    )
    props = dict(
        line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line
    )
    load_state = props.get("LoadState", "")
    if result.returncode != 0 or not load_state:
        detail = (result.stderr or "").strip() or "no unit state returned"
        return "unknown", f"Could not read {unit} from systemd: {detail}"

    stale = None
    if load_state == "not-found":
        stale = (
            f"{unit} is not installed on this host. If it was retired or renamed, "
            f"remove '{name}' from dashboard.services in orpheus.yaml; if this host "
            "has no dashboard.services, set it to the units this host runs."
        )
    else:
        canonical = props.get("Id", unit)
        if canonical != unit:
            stale = (
                f"'{name}' is an alias of {canonical}. List "
                f"'{canonical[: -len('.service')]}' in dashboard.services instead."
            )
    if stale is not None and name not in _reported_stale_services:
        _reported_stale_services.add(name)
        logger.warning("Stale dashboard.services entry", service_name=name, detail=stale)

    if load_state == "not-found":
        return "unknown", stale
    active_state = props.get("ActiveState", "")
    if active_state == "active":
        return "running", stale or ""
    sub_state = props.get("SubState", "")
    state = f"{active_state} ({sub_state})" if sub_state else active_state or "unknown"
    return "stopped", stale or f"Service is not running: {state}"


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
            status, reason = _unit_status(systemctl_path, name)

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
