"""
Storage hardware monitoring for Orpheus data storage paths.

Provides health checking for the configured data root (via
``ORPHEUS_DATA_ROOT``) alongside the root filesystem, including
mount status, filesystem info, and writability checks.
"""

import os
import shutil
from typing import Any

import psutil

from orpheus_common.logging import get_logger

logger = get_logger(__name__)


def _get_single_storage_info(
    name: str, path: str, required_mount: bool = False, check_writable: bool = True
) -> dict[str, Any]:
    """
    Helper to get info for a single storage path.

    Args:
        name: Display name for the storage device
        path: Path to check
        required_mount: Whether this path should be a mount point
        check_writable: Whether to test write permissions

    Returns:
        Dictionary with storage device information
    """
    info = {
        "name": name,
        "path": path,
        "exists": os.path.exists(path),
        "is_mount": False,
        "filesystem": "unknown",
        "device": "unknown",
        "status": "unknown",
        "usage": None,
        "checks": {"path_exists": False, "is_mount": False},
    }

    if os.path.exists(path):
        info["checks"]["path_exists"] = True
        info["is_mount"] = os.path.ismount(path)
        info["checks"]["is_mount"] = info["is_mount"]

        # Check writability
        if check_writable:
            try:
                test_file = os.path.join(path, ".write_test")
                with open(test_file, "w") as f:
                    f.write("test")
                os.remove(test_file)
                info["checks"]["writable"] = True
            except Exception as e:
                logger.warning("Storage not writable", path=path, error=str(e))
                info["checks"]["writable"] = False

        # Get usage stats
        try:
            usage = shutil.disk_usage(path)
            total = usage.total
            used = usage.used
            free = usage.free
            percent = round((used / total) * 100, 1) if total > 0 else 0
            info["usage"] = {
                "total": total,
                "used": used,
                "free": free,
                "percent": percent,
            }
        except Exception:
            pass

        # Try to find partition info
        try:
            partitions = psutil.disk_partitions(all=True)
            for p in partitions:
                if p.mountpoint == path:
                    info["filesystem"] = p.fstype
                    info["device"] = p.device
                    info["opts"] = p.opts
                    break
        except Exception as e:
            logger.warning("Failed to get partition info", error=str(e))

        # Determine status
        if check_writable and not info["checks"].get("writable", True):
            info["status"] = "critical"
            info["message"] = "Read-only or inaccessible"
        elif required_mount and not info["is_mount"]:
            info["status"] = "degraded"
            info["message"] = "Not mounted (using rootfs)"
        else:
            info["status"] = "healthy"

        # Check usage thresholds for status
        if info["usage"]:
            if info["usage"]["percent"] > 90:
                info["status"] = "critical" if info["status"] == "healthy" else info["status"]
                info["message"] = "Storage full (>90%)"
            elif info["usage"]["percent"] > 85:
                info["status"] = "degraded" if info["status"] == "healthy" else info["status"]
                info["message"] = "Storage filling up (>85%)"

    else:
        info["status"] = "critical"
        info["message"] = "Path not found"

    return info


def get_storage_hardware_info() -> list[dict[str, Any]]:
    """
    Get hardware-level information about storage devices.

    Returns a list of storage device information including the root filesystem
    and the configured Orpheus data root. Uses ORPHEUS_DATA_ROOT environment
    variable to locate external storage.

    Returns:
        List of dictionaries with storage hardware information.
        Each dictionary contains:
        - name (str): Storage device name
        - path (str): Mount path
        - exists (bool): Path exists
        - is_mount (bool): Path is a mount point
        - filesystem (str): Filesystem type (ext4, etc.)
        - device (str): Device node (/dev/sdX)
        - status (str): Overall status (healthy, degraded, critical)
        - usage (dict): Disk usage statistics
        - checks (dict): Individual check results
        - message (str): Status message if not healthy

    Example:
        >>> from orpheus_common.hardware.storage import get_storage_hardware_info
        >>> devices = get_storage_hardware_info()
        >>> for device in devices:
        ...     print(f"{device['name']}: {device['status']}")
        ...     if device['status'] != 'healthy':
        ...         print(f"  Issue: {device.get('message', 'Unknown')}")
    """
    devices = []

    # Root Filesystem
    # Don't check writability for root as it's often read-only (macOS SIP, etc)
    # and we typically don't write to root directly.
    devices.append(
        _get_single_storage_info("Root Filesystem", "/", required_mount=True, check_writable=False)
    )

    # Configured data root (e.g., external drive)
    from orpheus_common.storage.paths import get_data_root

    data_path = str(get_data_root())
    devices.append(
        _get_single_storage_info(
            "External Storage (ORPHEUS_DATA_ROOT)",
            data_path,
            required_mount=True,
            check_writable=True,
        )
    )

    return devices
