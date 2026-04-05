"""Camera API endpoints.

Provides endpoints for camera status and snapshot retrieval.
"""

import concurrent.futures

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from orpheus_common import OrpheusConfig
from orpheus_common.logging import get_logger

from orpheus_ui.auth.backend import current_active_user
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["cameras"])


@router.get("/cameras")
def get_cameras(user: User = Depends(current_active_user)):
    """Get status of all configured cameras.

    Returns health status for each camera in the registry.
    Requires authentication.
    """
    config = OrpheusConfig.get_instance()
    cameras = config.camera_registry()
    ttl = config.dashboard_poll_interval() / 1000.0

    # Run checks in parallel to reduce total latency
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = list(executor.map(lambda c: c.get_health_status(ttl_seconds=ttl), cameras))

    return results


@router.get("/cameras/{camera_name}/snapshot")
def get_camera_snapshot(camera_name: str, user: User = Depends(current_active_user)):
    """Get cached snapshot from specific camera.

    Args:
        camera_name: Name of the camera to get snapshot from.

    Returns:
        JPEG image data.
    """
    config = OrpheusConfig.get_instance()
    cameras = config.camera_registry()

    camera = next((c for c in cameras if c.name == camera_name), None)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    snapshot_result = camera.capture_snapshot()
    if not snapshot_result["ok"] or not snapshot_result.get("image_data"):
        raise HTTPException(
            status_code=503, detail=snapshot_result.get("error", "Snapshot unavailable")
        )

    return Response(
        content=snapshot_result["image_data"],
        media_type="image/jpeg",
        headers={
            "Cache-Control": "max-age=5",
            "X-Cached-At": snapshot_result.get("cached_at", ""),
        },
    )
