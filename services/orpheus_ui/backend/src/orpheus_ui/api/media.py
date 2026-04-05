"""Media API endpoints.

Provides endpoints for historical media retrieval (snapshots and timelapses).
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from orpheus_common import OrpheusConfig
from orpheus_common.logging import get_logger
from orpheus_common.storage import parse_timelapse_filename, tier_sort_key

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/snapshots/{camera_name}")
def get_camera_snapshots(
    camera_name: str,
    date: Optional[str] = None,
    hour: Optional[int] = None,
    limit: int = 50,
    user: User = Depends(current_active_user),
):
    """Get list of snapshots for a specific camera.

    Args:
        camera_name: The camera name
        date: Optional date in YYYY.MM.DD format (defaults to today)
        limit: Maximum number of snapshots to return (default 50)

    Returns:
        List of snapshot metadata including filename, timestamp, and size.
    """
    try:
        # Validate camera name to prevent path traversal
        if ".." in camera_name or "/" in camera_name:
            raise HTTPException(status_code=400, detail="Invalid camera name")

        config = OrpheusConfig.get_instance()
        storage_base = Path(config.storage.base_path)

        # Use today's date if not specified
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y.%m.%d")

        # Validate date format
        if not date or len(date) != 10 or date.count(".") != 2:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY.MM.DD")

        snapshot_dir = storage_base / "video" / "snapshots" / date

        if not snapshot_dir.exists():
            return {"snapshots": [], "date": date, "camera": camera_name}

        # Find snapshots for this camera
        snapshot_pattern = f"*.{camera_name}.jpg"
        snapshots = []

        all_snapshot_files = sorted(snapshot_dir.glob(snapshot_pattern), reverse=True)

        # Filter by hour if specified (using UTC hour from mtime)
        if hour is not None:
            all_snapshot_files = [
                f
                for f in all_snapshot_files
                if datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).hour == hour
            ]

        for snapshot_file in all_snapshot_files[:limit]:
            try:
                stat = snapshot_file.stat()
                snapshots.append(
                    {
                        "filename": snapshot_file.name,
                        "date": date,
                        "camera": camera_name,
                        "size_bytes": stat.st_size,
                        "size_kb": round(stat.st_size / 1024, 1),
                        "modified_time": stat.st_mtime,
                        "timestamp_iso": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "download_url": (
                            f"/api/media/snapshots/{camera_name}/{date}/{snapshot_file.name}"
                        ),
                    }
                )
            except Exception as e:
                logger.warning("Failed to stat snapshot", path=str(snapshot_file), error=str(e))

        return {
            "snapshots": snapshots,
            "date": date,
            "camera": camera_name,
            "hour": hour,
            "count": len(snapshots),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get snapshots", camera=camera_name, error=str(e))
        return {"snapshots": [], "error": str(e)}


@router.get("/snapshots/{camera_name}/{date}/{filename:path}")
def serve_snapshot_file(
    camera_name: str,
    date: str,
    filename: str,
    user: User = Depends(current_active_user),
):
    """Serve a snapshot image file.

    Args:
        camera_name: The camera name
        date: Date in YYYY.MM.DD format
        filename: The snapshot filename

    Returns:
        The JPEG image file
    """
    # Validate inputs to prevent path traversal
    if ".." in camera_name or "/" in camera_name:
        raise HTTPException(status_code=400, detail="Invalid camera name")
    if ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid date")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    config = OrpheusConfig.get_instance()
    storage_base = Path(config.storage.base_path).resolve()
    snapshots_base = (storage_base / "video" / "snapshots").resolve()
    snapshot_path = (snapshots_base / date / filename).resolve()

    # Security: Ensure resolved path is within the allowed directory
    try:
        snapshot_path.relative_to(snapshots_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not snapshot_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")

    return FileResponse(
        str(snapshot_path),
        media_type="image/jpeg",
        filename=filename,
    )


@router.get("/timelapses/{camera_name}")
def get_camera_timelapses(
    camera_name: str,
    date: Optional[str] = None,
    limit: int = 1000,
    user: User = Depends(current_active_user),
):
    """Get list of timelapse videos for a specific camera.

    Args:
        camera_name: The camera name
        date: Optional date in YYYY.MM.DD format (defaults to all recent)
        limit: Maximum number of timelapses to return (default 1000, 0 for unlimited)

    Returns:
        List of timelapse metadata including filename, timestamp, and size.
    """
    try:
        # Validate camera name to prevent path traversal
        if ".." in camera_name or "/" in camera_name:
            raise HTTPException(status_code=400, detail="Invalid camera name")

        config = OrpheusConfig.get_instance()
        storage_base = Path(config.storage.base_path)
        timelapse_base = storage_base / "video" / "timelapses"

        if not timelapse_base.exists():
            return {"timelapses": [], "camera": camera_name}

        timelapses = []

        # If date specified, only search that date
        if date:
            date_dirs = [timelapse_base / date] if (timelapse_base / date).exists() else []
        else:
            # Search all date directories, most recent first
            date_dirs = sorted(timelapse_base.iterdir(), reverse=True)[:30]

        for date_dir in date_dirs:
            if not date_dir.is_dir():
                continue

            date_str = date_dir.name
            # Match any .mp4 file containing the camera name (supports both old and new formats)
            # Old format: HH-MM.camera_name.mp4
            # New format: camera_name.label.tier.lookback.timestamp.mp4
            timelapse_pattern = f"*{camera_name}*.mp4"

            for timelapse_file in date_dir.glob(timelapse_pattern):
                try:
                    stat = timelapse_file.stat()

                    # Parse filename to extract metadata
                    parsed = parse_timelapse_filename(timelapse_file.name)

                    timelapses.append(
                        {
                            "filename": timelapse_file.name,
                            "date": date_str,
                            "camera": camera_name,
                            "size_bytes": stat.st_size,
                            "size_mb": round(stat.st_size / (1024 * 1024), 2),
                            "modified_time": stat.st_mtime,
                            "timestamp_iso": datetime.fromtimestamp(
                                stat.st_mtime, tz=timezone.utc
                            ).isoformat(),
                            "download_url": (
                                f"/api/media/timelapses/{camera_name}/{date_str}/"
                                f"{timelapse_file.name}"
                            ),
                            # Parsed metadata (may be None for legacy format)
                            "label": parsed.label if parsed else None,
                            "tier": parsed.tier if parsed else None,
                            "tier_display": parsed.tier_display if parsed else None,
                            "lookback": parsed.lookback if parsed else None,
                        }
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to stat timelapse", path=str(timelapse_file), error=str(e)
                    )

        # Sort by tier (24h first, then 1h, etc.) then by time within each tier
        timelapses.sort(key=lambda t: (tier_sort_key(t.get("tier")), -t.get("modified_time", 0)))

        # Apply limit after sorting (0 means unlimited)
        if limit > 0:
            timelapses = timelapses[:limit]

        return {
            "timelapses": timelapses,
            "camera": camera_name,
            "count": len(timelapses),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get timelapses", camera=camera_name, error=str(e))
        return {"timelapses": [], "error": str(e)}


@router.get("/timelapses/{camera_name}/{date}/{filename:path}")
def serve_timelapse_file(
    camera_name: str,
    date: str,
    filename: str,
    user: User = Depends(current_active_user),
):
    """Serve a timelapse video file.

    Args:
        camera_name: The camera name
        date: Date in YYYY.MM.DD format
        filename: The timelapse filename

    Returns:
        The MP4 video file
    """
    # Validate inputs to prevent path traversal
    if ".." in camera_name or "/" in camera_name:
        raise HTTPException(status_code=400, detail="Invalid camera name")
    if ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid date")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    config = OrpheusConfig.get_instance()
    storage_base = Path(config.storage.base_path).resolve()
    timelapses_base = (storage_base / "video" / "timelapses").resolve()
    timelapse_path = (timelapses_base / date / filename).resolve()

    # Security: Ensure resolved path is within the allowed directory
    try:
        timelapse_path.relative_to(timelapses_base)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not timelapse_path.exists():
        raise HTTPException(status_code=404, detail="Timelapse not found")

    # Determine content type
    if filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".avi"):
        media_type = "video/x-msvideo"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        str(timelapse_path),
        media_type=media_type,
        filename=filename,
    )


@router.get("/timelapse-config")
def get_timelapse_config(user: User = Depends(current_active_user)):
    """Get timelapse configuration for all cameras from orpheus config.

    Returns human-readable timelapse schedule information per camera.
    """
    try:
        config = OrpheusConfig.get_instance()
        cameras = config.video.cameras

        result = {}
        for camera_name, camera in cameras.items():
            if not camera.enabled:
                continue

            snapshot_interval = None
            if camera.snapshots:
                snapshot_interval = getattr(camera.snapshots, "interval", None)

            timelapse_configs = []
            if camera.timelapses:
                for tl in camera.timelapses:
                    timelapse_configs.append(
                        {
                            "label": tl.label,
                            "lookback_window": tl.lookback_window,
                            "sampling_interval": tl.sampling_interval,
                            "start_time": tl.start_time,
                            "retention_days": tl.retention_days,
                            "timezone": tl.timezone,
                        }
                    )

            result[camera_name] = {
                "snapshot_interval": snapshot_interval,
                "timelapses": timelapse_configs,
            }

        return {"cameras": result}
    except Exception as e:
        logger.error("Failed to get timelapse config", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get timelapse config: {e}")
