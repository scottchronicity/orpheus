"""Diagnostics and detection API endpoints.

Provides endpoints for audio/video diagnostics and detection history.
"""

import os
import re
import shutil
import subprocess
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from orpheus_common.detection import DetectionDB
from orpheus_common.logging import get_logger
from orpheus_common.storage import (
    get_audio_clip_path,
    get_data_root,
    get_video_path,
    normalize_sensor_id,
)
from orpheus_common.utils.time import is_full_day, parse_hhmm, timestamp_in_window
from pydantic import BaseModel, Field

from orpheus_ui.auth.backend import current_active_user, current_user_or_token_param
from orpheus_ui.auth.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["diagnostics"])

# Cache for audio health status from MQTT
_audio_health_cache: Optional[Dict[str, Any]] = None
_audio_health_lock = threading.Lock()

# Cache for video health status from MQTT
_video_health_cache: Optional[Dict[str, Any]] = None
_video_health_lock = threading.Lock()

# Cache for audio motion detections
_audio_detections_cache: deque = deque(maxlen=200)
_audio_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_audio_detections_lock = threading.Lock()

# Cache for video motion detections
_video_detections_cache: deque = deque(maxlen=20)
_video_detections_by_camera: Dict[str, Dict[str, Any]] = {}
_video_detections_lock = threading.Lock()

# Cache for bird detections
_bird_detections_cache: deque = deque(maxlen=50)
_bird_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_bird_detections_lock = threading.Lock()

# Cache for crow detections
_crow_detections_cache: deque = deque(maxlen=50)
_crow_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_crow_detections_lock = threading.Lock()

# Reference to MQTT client (set by main.py)
_mqtt_client = None


def set_mqtt_client(client):
    """Set the MQTT client reference for connection status checks."""
    global _mqtt_client
    _mqtt_client = client


# MQTT message handlers
def on_audio_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle audio health status messages from MQTT."""
    global _audio_health_cache
    with _audio_health_lock:
        _audio_health_cache = payload
        logger.debug(
            "Updated audio health cache",
            running=payload.get("running"),
            channel_count=len(payload.get("channels", [])),
        )


def on_video_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle video health status messages from MQTT."""
    global _video_health_cache
    with _video_health_lock:
        _video_health_cache = payload
        logger.debug(
            "Updated video health cache",
            running=payload.get("running"),
            cameras=len(payload.get("cameras", [])),
        )


def on_audio_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle audio motion detection messages from MQTT.

    Flattens nested Detection payload so that channel_id, duration_seconds,
    and peak_energy_db are available as top-level keys for the frontend.
    """
    with _audio_detections_lock:
        metadata = payload.get("metadata") or {}

        # Extract channel_id: metadata.channel_id → channel field → "unknown"
        channel_id = payload.get("channel_id") or metadata.get("channel_id")
        if not channel_id:
            raw_channel = payload.get("channel")
            channel_id = str(raw_channel) if raw_channel is not None else "unknown"
        payload["channel_id"] = channel_id

        # Promote duration_seconds and peak_energy_db from metadata
        if "duration_seconds" not in payload and "duration_seconds" in metadata:
            payload["duration_seconds"] = metadata["duration_seconds"]
        if "peak_energy_db" not in payload and "peak_energy_db" in metadata:
            payload["peak_energy_db"] = metadata["peak_energy_db"]

        _audio_detections_cache.append(payload)
        _audio_detections_by_channel[channel_id] = payload

    # Persist to DetectionDB for historical queries
    try:
        from datetime import datetime as _datetime
        from datetime import timezone as _timezone

        from orpheus_common.detection import Detection as _Detection
        from orpheus_common.detection import DetectionDB as _DetectionDB

        _db = _DetectionDB()
        _ts = payload.get("timestamp")
        if _ts:
            if isinstance(_ts, str):
                _dt = _datetime.fromisoformat(_ts.replace("Z", "+00:00"))
            else:
                _dt = _datetime.fromtimestamp(float(_ts), tz=_timezone.utc)
        else:
            _dt = _datetime.now(_timezone.utc)
        if _dt.tzinfo is None:
            _dt = _dt.replace(tzinfo=_timezone.utc)
        _det = _Detection(
            timestamp=_dt,
            detection_type="audio.motion",
            channel=payload.get("channel"),
            audio_clip_path=payload.get("audio_clip_path"),
            metadata={
                "channel_id": payload.get("channel_id"),
                "duration_seconds": payload.get("duration_seconds"),
                "peak_energy_db": payload.get("peak_energy_db"),
            },
        )
        _db.save(_det)
    except Exception as _e:
        logger.warning("Failed to persist audio detection to DB", error=str(_e))


def on_video_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle video motion detection messages from MQTT."""
    with _video_detections_lock:
        # Normalize clip_path → video_clip_path (video agent publishes "clip_path")
        if "clip_path" in payload and "video_clip_path" not in payload:
            payload["video_clip_path"] = payload["clip_path"]
        _video_detections_cache.append(payload)
        camera_id = payload.get("camera_id", "unknown")
        _video_detections_by_camera[camera_id] = payload


def on_bird_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle bird detection messages from MQTT."""
    try:
        with _bird_detections_lock:
            _bird_detections_cache.append(payload)
            channel_id = payload.get("channel_id", "unknown")
            _bird_detections_by_channel[channel_id] = payload
    except Exception as e:
        logger.error("Failed to process bird detection message", error=str(e))


def on_crow_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle crow detection messages from MQTT."""
    try:
        with _crow_detections_lock:
            # Crow agent stores channel_id inside metadata, not at top level
            channel_id = payload.get("channel_id") or payload.get("metadata", {}).get(
                "channel_id", "unknown"
            )
            payload["channel_id"] = channel_id  # normalise to top-level for consumers
            _crow_detections_cache.append(payload)
            _crow_detections_by_channel[channel_id] = payload
    except Exception as e:
        logger.error("Failed to process crow detection message", error=str(e))


# Non-bird sounds to filter out (BirdNET noise classifications)
# Stored in lowercase for case-insensitive matching
NON_BIRD_SOUNDS = {
    "human whistle",
    "human vocal",
    "human non-vocal",
    "siren",
    "fireworks",
    "engine",
    "dog",
    "power tools",
    "car horn",
    "alarm",
}


def is_bird_sound(common_name: str) -> bool:
    """Check if a sound is a bird (not noise/human/etc)."""
    return common_name.lower() not in NON_BIRD_SOUNDS


@router.get("/diagnostics/audio")
def get_audio_diagnostics(user: User = Depends(current_active_user)):
    """Get audio system health diagnostics.

    Returns real-time status of audio hardware from the audio agent via MQTT.
    Channel data includes level_db, peak_db, level_color, and has_signal for
    use by the AudioHealthPanel component.
    """
    from orpheus_common.diagnostics.audio_health import get_audio_health_monitor

    global _audio_health_cache

    try:
        with _audio_health_lock:
            if _audio_health_cache:
                result = dict(_audio_health_cache)
                # Normalize channels: preserve full diagnostic fields while
                # ensuring id/active are present for backwards-compatible consumers.
                raw_channels = result.get("channels", [])
                result["channels"] = [
                    {
                        "id": ch.get("id") or ch.get("channel_id", ""),
                        "active": ch.get("active", ch.get("has_signal", False)),
                        "level_db": ch.get("level_db", -100.0),
                        "peak_db": ch.get("peak_db", -100.0),
                        "level_color": ch.get("level_color", "none"),
                        "has_signal": ch.get("has_signal", ch.get("active", False)),
                    }
                    for ch in raw_channels
                ]
                return result

            # Fallback: read from the local AudioHealthMonitor singleton.
            # This provides data when the audio agent is running in-process
            # or the MQTT cache has not yet been populated.
            monitor = get_audio_health_monitor()
            status = monitor.get_status()
            raw_channels = status.get("channels", [])
            status["channels"] = [
                {
                    "id": ch.get("channel_id", ""),
                    "active": ch.get("has_signal", False),
                    "level_db": ch.get("level_db", -100.0),
                    "peak_db": ch.get("peak_db", -100.0),
                    "level_color": ch.get("level_color", "none"),
                    "has_signal": ch.get("has_signal", False),
                }
                for ch in raw_channels
            ]
            if not status.get("running") and not raw_channels:
                status["message"] = "Waiting for audio health data from agent (via MQTT)"
            return status
    except Exception as e:
        logger.warning("Failed to get audio diagnostics", error=str(e))
        return {
            "running": False,
            "error": str(e),
            "message": "Audio diagnostics unavailable",
            "xrun": {"total": 0},
            "channels": [],
            "hardware": {},
            "timing": {},
            "system": {},
        }


@router.get("/diagnostics/logs/{service_name}")
def get_service_logs(
    service_name: str, user: User = Depends(current_active_user)
) -> Dict[str, Any]:
    """Get recent systemd service logs via journalctl.

    Returns the last 100 lines of journal output for the given service as an
    array of strings.  Only alphanumeric service names (plus hyphens and
    underscores) are accepted to prevent command injection.

    Args:
        service_name: The systemd unit name (e.g. orpheus-agent-audio-motion).

    Returns:
        Dict with ``service_name`` and ``lines`` (list of log line strings).
    """
    if not re.match(r"^[a-zA-Z0-9_\-]+$", service_name):
        raise HTTPException(status_code=400, detail="Invalid service name")

    try:
        sudo_path = shutil.which("sudo") or "/usr/bin/sudo"
        journalctl_path = shutil.which("journalctl") or "/usr/bin/journalctl"
        result = subprocess.run(
            [sudo_path, "-n", journalctl_path, "-u", service_name, "-n", "100", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines: List[str] = result.stdout.splitlines()
        return {"service_name": service_name, "lines": lines}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="journalctl timed out")
    except FileNotFoundError:
        # sudo/journalctl not available (e.g. dev/macOS environment)
        return {
            "service_name": service_name,
            "lines": ["journalctl not available in this environment"],
        }
    except Exception as e:
        logger.error("Failed to get service logs", service_name=service_name, error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get logs: {e}")


@router.get("/diagnostics/video")
def get_video_diagnostics(user: User = Depends(current_active_user)):
    """Get video system health diagnostics.

    Returns real-time status of video hardware from the video agent via MQTT.
    """
    global _video_health_cache

    try:
        with _video_health_lock:
            if _video_health_cache:
                result = dict(_video_health_cache)
                # Ensure camera_count is present (may be missing from some agent versions)
                if "camera_count" not in result:
                    cameras_list = result.get("cameras", [])
                    result["camera_count"] = len(cameras_list)
                return result
            else:
                with _video_detections_lock:
                    active_cameras = list(_video_detections_by_camera.keys())
                    cameras_status = []
                    last_detection_time = None

                    for camera_id in active_cameras:
                        detection = _video_detections_by_camera[camera_id]
                        timestamp = detection.get("timestamp", "")
                        cameras_status.append(
                            {
                                "camera_id": camera_id,
                                "last_detection": timestamp,
                                "running": True,
                            }
                        )
                        if timestamp and (
                            not last_detection_time or timestamp > last_detection_time
                        ):
                            last_detection_time = timestamp

                    mqtt_connected = _mqtt_client is not None and _mqtt_client.is_connected

                    return {
                        "running": len(active_cameras) > 0,
                        "cameras": cameras_status,
                        "camera_count": len(active_cameras),
                        "last_detection": last_detection_time,
                        "mqtt_connected": mqtt_connected,
                        "message": "Waiting for video health data from agent (via MQTT)"
                        if len(active_cameras) > 0
                        else "No cameras detected",
                        "hardware": {},
                        "timing": {},
                        "system": {},
                        "mqtt": {},
                    }
    except Exception as e:
        logger.warning("Failed to get video diagnostics", error=str(e))
        return {
            "running": False,
            "cameras": [],
            "camera_count": 0,
            "last_detection": None,
            "mqtt_connected": False,
            "error": str(e),
            "message": "Video diagnostics unavailable",
            "hardware": {},
            "timing": {},
            "system": {},
            "mqtt": {},
        }


@router.get("/diagnostics/audio/detections")
def get_audio_detections(user: User = Depends(current_active_user)):
    """Get recent audio motion detections from all channels."""
    try:
        with _audio_detections_lock:
            summary = {}
            for channel_id in ["1", "2", "3", "4"]:
                if channel_id in _audio_detections_by_channel:
                    summary[channel_id] = _audio_detections_by_channel[channel_id]
                else:
                    summary[channel_id] = None

            history = list(reversed(_audio_detections_cache))
            mqtt_connected = _mqtt_client is not None and _mqtt_client.is_connected

            return {
                "summary": summary,
                "history": history,
                "mqtt_connected": mqtt_connected,
            }
    except Exception as e:
        logger.warning("Failed to get audio detections", error=str(e))
        return {
            "summary": {"1": None, "2": None, "3": None, "4": None},
            "history": [],
            "mqtt_connected": False,
            "error": str(e),
        }


@router.get("/diagnostics/video/detections")
def get_video_detections(user: User = Depends(current_active_user)):
    """Get recent video motion detections from all cameras."""
    try:
        with _video_detections_lock:
            summary = {}
            for camera_id in ["orpheus-eye-1", "orpheus-eye-2", "orpheus-eye-3", "orpheus-eye-4"]:
                if camera_id in _video_detections_by_camera:
                    summary[camera_id] = _video_detections_by_camera[camera_id]
                else:
                    summary[camera_id] = None

            history = list(reversed(_video_detections_cache))
            mqtt_connected = _mqtt_client is not None and _mqtt_client.is_connected

            return {
                "summary": summary,
                "history": history,
                "mqtt_connected": mqtt_connected,
            }
    except Exception as e:
        logger.warning("Failed to get video detections", error=str(e))
        return {
            "summary": {
                "orpheus-eye-1": None,
                "orpheus-eye-2": None,
                "orpheus-eye-3": None,
                "orpheus-eye-4": None,
            },
            "history": [],
            "mqtt_connected": False,
            "error": str(e),
        }


@router.get("/diagnostics/video/clips/{camera_id}")
def get_video_clips(camera_id: str, user: User = Depends(current_active_user)):
    """Get list of available video clips for a specific camera."""
    try:
        video_path = get_video_path(category="video_motion")
        camera_path = video_path / camera_id

        if not camera_path.exists():
            return {"clips": [], "error": None}

        clips = []
        for clip_file in sorted(camera_path.glob("*.mp4"), reverse=True)[:50]:
            try:
                stat = clip_file.stat()
                clips.append(
                    {
                        "filename": clip_file.name,
                        "path": str(clip_file),
                        "size_bytes": stat.st_size,
                        "modified_time": stat.st_mtime,
                    }
                )
            except Exception as e:
                logger.warning("Failed to stat clip", clip_file=str(clip_file), error=str(e))

        return {"clips": clips, "error": None}
    except Exception as e:
        logger.error("Failed to get video clips", camera_id=camera_id, error=str(e))
        return {"clips": [], "error": str(e)}


@router.get("/diagnostics/bird/detections")
def get_bird_detections(user: User = Depends(current_active_user)):
    """Get recent bird detections from all channels."""
    try:
        with _bird_detections_lock:
            summary = {}
            for channel_id in ["1", "2", "3", "4"]:
                det = _bird_detections_by_channel.get(channel_id)
                if det:
                    det = dict(det)
                    if "audio_clip_path" in det:
                        det["clip_path"] = det["audio_clip_path"]
                    summary[channel_id] = det
                else:
                    summary[channel_id] = None

            history = []
            for det in reversed(_bird_detections_cache):
                det = dict(det)
                if "audio_clip_path" in det:
                    det["clip_path"] = det["audio_clip_path"]
                history.append(det)

            mqtt_connected = _mqtt_client is not None and _mqtt_client.is_connected

            return {
                "summary": summary,
                "history": history,
                "mqtt_connected": mqtt_connected,
            }
    except Exception as e:
        logger.warning("Failed to get bird detections", error=str(e))
        return {
            "summary": {"1": None, "2": None, "3": None, "4": None},
            "history": [],
            "mqtt_connected": False,
            "error": str(e),
        }


@router.get("/diagnostics/crow/detections")
def get_crow_detections(user: User = Depends(current_active_user)):
    """Get recent crow analysis results from all channels."""
    try:
        with _crow_detections_lock:
            summary = {}
            for channel_id in ["1", "2", "3", "4"]:
                if channel_id in _crow_detections_by_channel:
                    summary[channel_id] = _crow_detections_by_channel[channel_id]
                else:
                    summary[channel_id] = None

            history = list(reversed(_crow_detections_cache))
            mqtt_connected = _mqtt_client is not None and _mqtt_client.is_connected

            return {
                "summary": summary,
                "history": history,
                "mqtt_connected": mqtt_connected,
            }
    except Exception as e:
        logger.warning("Failed to get crow detections", error=str(e))
        return {
            "summary": {"1": None, "2": None, "3": None, "4": None},
            "history": [],
            "mqtt_connected": False,
            "error": str(e),
        }


@router.get("/audio/clips/{channel_id}/{filename:path}")
def get_audio_clip(
    channel_id: str,
    filename: str,
    user: User = Depends(current_user_or_token_param),
):
    """Serve an audio clip file from the audio_motion storage directory.

    Handles both absolute paths (from database) and relative filenames.
    Supports both legacy numeric IDs (1-4) and new string-based IDs (mic-1 to mic-4).
    """
    # Normalize and validate channel ID using orpheus-common utility
    normalized_channel_id = normalize_sensor_id(channel_id)

    if normalized_channel_id not in ["1", "2", "3", "4"]:
        raise HTTPException(status_code=400, detail="Invalid channel ID")

    # Check if filename is an absolute path (cross-platform)
    if Path(filename).is_absolute():
        # Absolute path from database - use it directly with security check
        clip_path = Path(filename).resolve()

        # Security: Verify path is within ORPHEUS_DATA_ROOT
        data_root = get_data_root()
        if not str(clip_path).startswith(str(data_root.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path: outside data root")
    else:
        # Relative filename - use orpheus-common utility for consistent path construction
        clip_path = get_audio_clip_path(
            category="audio_motion", sensor_id=normalized_channel_id, filename=filename
        ).resolve()

        # Verify the file exists within expected directory structure
        base_path = clip_path.parent
        if not str(clip_path).startswith(str(base_path.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")

    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    if filename.endswith(".flac"):
        media_type = "audio/flac"
    elif filename.endswith(".wav"):
        media_type = "audio/wav"
    else:
        media_type = "application/octet-stream"

    return FileResponse(str(clip_path), media_type=media_type)


@router.get("/video/clips/{camera_id}/{filename:path}")
def get_video_clip(
    camera_id: str,
    filename: str,
    user: User = Depends(current_user_or_token_param),
):
    """Serve a video clip file from the video_motion storage directory.

    Handles both absolute paths (from database) and relative filenames.
    """
    valid_cameras = ["orpheus-eye-1", "orpheus-eye-2", "orpheus-eye-3", "orpheus-eye-4"]
    if camera_id not in valid_cameras:
        raise HTTPException(status_code=400, detail="Invalid camera ID")

    data_root = Path(os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus"))

    # Check if filename is an absolute path (cross-platform)
    if Path(filename).is_absolute():
        # Absolute path from database - use it directly with security check
        clip_path = Path(filename).resolve()

        # Security: Verify path is within ORPHEUS_DATA_ROOT
        if not str(clip_path).startswith(str(data_root.resolve())):
            raise HTTPException(status_code=400, detail="Invalid path: outside data root")
    else:
        # Relative filename - construct path as before
        video_path = get_video_path(category="video_motion")
        base_path = video_path / camera_id
        clip_path = (base_path / filename).resolve()

        # Verify resolved path is within the expected directory (prevent path traversal)
        if not str(clip_path).startswith(str(base_path.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")

    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    if filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".avi"):
        media_type = "video/x-msvideo"
    else:
        media_type = "application/octet-stream"

    return FileResponse(str(clip_path), media_type=media_type)


@router.get("/data/birds/history")
def get_bird_history(
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    species: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    user: User = Depends(current_active_user),
):
    """Get bird detection history with server-side aggregated stats.

    Query params:
      species: comma-separated species codes/common names to keep (case-insensitive).
      start_time, end_time: HH:MM time-of-day window (interpreted in `tz`).
        When start > end the window wraps midnight.
      tz: IANA timezone name (e.g. "America/Los_Angeles") for interpreting start_time/end_time.
      page, page_size: when both provided, return the given 1-indexed slice instead of
        the legacy 2000-row cap; response adds page/page_size/total_pages.

    Omitting page/page_size preserves the legacy response shape (first 2000 rows).
    Omitting start_time/end_time or leaving them at 00:00/23:59 disables the time filter.
    """
    try:
        db = DetectionDB()

        if start_date:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_dt = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_dt = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_dt = datetime.now(timezone.utc) - timedelta(days=days)
            end_dt = datetime.now(timezone.utc)

        species_allow: Optional[set] = None
        if species:
            species_allow = {
                s.strip().lower() for s in species.split(",") if s.strip()
            }
            if not species_allow:
                species_allow = None

        # Time-of-day window (HH:MM in user's timezone). Applied AFTER the date range.
        start_hhmm = parse_hhmm(start_time)
        end_hhmm = parse_hhmm(end_time)
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )

        detections = db.query(
            detection_type="species.detected",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )

        from collections import defaultdict

        # Compute stats from the full (possibly species-filtered) dataset
        hourly_counts: Dict[int, int] = defaultdict(int)
        species_counts: Dict[str, int] = defaultdict(int)
        all_species_counts: Dict[str, int] = defaultdict(int)
        all_results = []
        filtered_count = 0

        for det in detections:
            species_common = det.species_common or det.species_code or ""
            species_code = det.species_code or ""

            # Filter out non-bird sounds (human, noise, etc)
            if not is_bird_sound(species_common) or not is_bird_sound(species_code):
                filtered_count += 1
                continue

            # Time-of-day filter (interpreted in user's tz) — applied before
            # species accumulation so stats reflect the final filtered set.
            if apply_time_window and not timestamp_in_window(
                det.timestamp, start_hhmm, end_hhmm, tz
            ):
                continue

            display_name = det.species_common or det.species_code or species_code
            # Always track the full (unfiltered-by-species) distribution so the
            # frontend species-filter dropdown can list every species in range.
            all_species_counts[display_name] += 1

            # Species filter: apply AFTER is_bird_sound so non-bird rows stay filtered out.
            if species_allow is not None:
                if (
                    species_common.lower() not in species_allow
                    and species_code.lower() not in species_allow
                    and display_name.lower() not in species_allow
                ):
                    continue

            hourly_counts[det.timestamp.hour] += 1
            species_counts[display_name] += 1

            context = None
            if det.context is not None:
                ctx = det.context
                context = ctx.model_dump(mode="json") if hasattr(ctx, "model_dump") else dict(ctx)

            all_results.append(
                {
                    "timestamp": det.timestamp.isoformat(),
                    "species_code": det.species_code,
                    "species_common": det.species_common or det.species_code,
                    "confidence": det.confidence,
                    "channel": det.channel,
                    "audio_clip_path": det.audio_clip_path,
                    "context": context,
                    "source_event_id": det.source_event_id,
                }
            )

        total_count = len(all_results)
        hourly_activity = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]

        # Daily activity: count per calendar date (for trend-over-time chart)
        daily_counts: Dict[str, int] = defaultdict(int)
        for r in all_results:
            daily_counts[r["timestamp"][:10]] += 1
        daily_activity = [
            {"date": d, "count": daily_counts[d]} for d in sorted(daily_counts.keys())
        ]

        # Sort descending so the table shows most-recent first
        all_results.sort(key=lambda x: x["timestamp"], reverse=True)

        # Pagination: opt-in via page+page_size. Otherwise preserve legacy 2000-row cap.
        paged_response: Dict[str, Any] = {}
        if page is not None and page_size is not None:
            p = max(1, page)
            ps = max(1, min(page_size, 1000))
            total_pages = max(1, (total_count + ps - 1) // ps)
            start_idx = (p - 1) * ps
            results = all_results[start_idx : start_idx + ps]
            paged_response = {
                "page": p,
                "page_size": ps,
                "total_pages": total_pages,
            }
        else:
            results = all_results[:2000]

        # Evenly-distributed scatter sample (max 500 points spanning full range)
        sorted_asc = sorted(all_results, key=lambda x: x["timestamp"])
        n = len(sorted_asc)
        if n <= 500:
            scatter_sample = [
                {
                    "timestamp": r["timestamp"],
                    "species_code": r["species_code"],
                    "species_common": r["species_common"],
                    "confidence": r["confidence"],
                }
                for r in sorted_asc
            ]
        else:
            step = n / 500
            scatter_sample = [
                {
                    "timestamp": sorted_asc[int(i * step)]["timestamp"],
                    "species_code": sorted_asc[int(i * step)]["species_code"],
                    "species_common": sorted_asc[int(i * step)]["species_common"],
                    "confidence": sorted_asc[int(i * step)]["confidence"],
                }
                for i in range(500)
            ]

        response = {
            "detections": results,
            "count": total_count,
            "filtered_count": filtered_count,
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "scatter_sample": scatter_sample,
            "stats": {
                "total_count": total_count,
                "unique_species_count": len(species_counts),
                "hourly_activity": hourly_activity,
                "daily_activity": daily_activity,
                "species_distribution": dict(species_counts),
                "all_species": dict(all_species_counts),
            },
        }
        response.update(paged_response)
        return response
    except Exception as e:
        logger.error("Failed to fetch bird history", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch bird history: {e}")


@router.get("/data/crows/stats")
def get_crow_stats(
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    call_types: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
    user: User = Depends(current_active_user),
):
    """Get crow detection statistics for dashboard visualization.

    Query params:
      call_types: comma-separated call_type values to keep (case-insensitive).
      start_time, end_time: HH:MM time-of-day window (interpreted in `tz`).
        When start > end the window wraps midnight.
      tz: IANA timezone name for interpreting start_time/end_time.
      page, page_size: when both provided, return the given 1-indexed slice instead of
        the legacy 2000-row cap; response adds page/page_size/total_pages.

    Omitting page/page_size preserves the legacy response shape (first 2000 rows).
    """
    try:
        db = DetectionDB()

        if start_date:
            start_dt = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_dt = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_dt = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_dt = datetime.now(timezone.utc) - timedelta(days=days)
            end_dt = datetime.now(timezone.utc)

        call_types_allow: Optional[set] = None
        if call_types:
            call_types_allow = {
                s.strip().lower() for s in call_types.split(",") if s.strip()
            }
            if not call_types_allow:
                call_types_allow = None

        start_hhmm = parse_hhmm(start_time)
        end_hhmm = parse_hhmm(end_time)
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )

        detections = db.query(
            detection_type="crow.analyzed",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )

        from collections import defaultdict

        age_counts: Dict[str, int] = defaultdict(int)
        hourly_counts: Dict[int, int] = defaultdict(int)
        daily_counts: Dict[str, int] = defaultdict(int)
        call_type_counts: Dict[str, int] = defaultdict(int)
        all_call_type_counts: Dict[str, int] = defaultdict(int)
        intent_counts: Dict[str, int] = defaultdict(int)

        # Build detections list for table display
        detection_list = []

        for det in detections:
            metadata = det.metadata or {}
            attributes = metadata.get("attributes", {})
            call_type = metadata.get("call_type") or "unknown"

            # Always track the full distribution so the frontend dropdown can
            # list every call_type present in the date range.
            all_call_type_counts[call_type] += 1

            if call_types_allow is not None and call_type.lower() not in call_types_allow:
                continue

            if apply_time_window and not timestamp_in_window(
                det.timestamp, start_hhmm, end_hhmm, tz
            ):
                continue

            hour = det.timestamp.hour
            hourly_counts[hour] += 1
            daily_counts[det.timestamp.date().isoformat()] += 1

            age = attributes.get("age", "unknown") if attributes else "unknown"
            age_counts[age] += 1

            call_type_counts[call_type] += 1

            intent = attributes.get("intent", "unknown") if attributes else "unknown"
            if intent != "unknown":
                intent_counts[intent] += 1

            # Resolve channel from metadata if not in main field
            channel_val = det.channel
            if channel_val is None and metadata:
                channel_val = metadata.get("channel_id") or metadata.get("channel")

            age = attributes.get("age") if attributes else None
            context_val = None
            if det.context is not None:
                ctx = det.context
                context_val = (
                    ctx.model_dump(mode="json") if hasattr(ctx, "model_dump") else dict(ctx)
                )
            detection_list.append(
                {
                    "timestamp": det.timestamp.isoformat(),
                    "confidence": det.confidence,
                    "call_type": call_type,
                    "audio_clip_path": det.audio_clip_path,
                    "channel": channel_val,
                    "age": age,
                    "context": context_val,
                }
            )

        hourly_data = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]
        daily_activity = [
            {"date": d, "count": daily_counts[d]} for d in sorted(daily_counts.keys())
        ]

        # Evenly-distributed scatter sample (max 500 points spanning full date range).
        # Must be computed BEFORE paginating so the sample spans all dates, not
        # just the most-recent slice.  Only include entries with non-null confidence.
        sorted_asc = sorted(
            [d for d in detection_list if d["confidence"] is not None],
            key=lambda x: x["timestamp"],
        )
        n = len(sorted_asc)
        if n <= 500:
            scatter_sample = [
                {
                    "timestamp": r["timestamp"],
                    "call_type": r["call_type"],
                    "confidence": r["confidence"],
                }
                for r in sorted_asc
            ]
        else:
            step = n / 500
            scatter_sample = [
                {
                    "timestamp": sorted_asc[int(i * step)]["timestamp"],
                    "call_type": sorted_asc[int(i * step)]["call_type"],
                    "confidence": sorted_asc[int(i * step)]["confidence"],
                }
                for i in range(500)
            ]

        # Sort by timestamp descending (most-recent first) for the table
        detection_list.sort(key=lambda x: x["timestamp"], reverse=True)
        total_count = len(detection_list)

        # Pagination: opt-in via page+page_size. Otherwise preserve legacy 2000-row cap.
        paged_response: Dict[str, Any] = {}
        if page is not None and page_size is not None:
            p = max(1, page)
            ps = max(1, min(page_size, 1000))
            total_pages = max(1, (total_count + ps - 1) // ps)
            start_idx = (p - 1) * ps
            detection_list = detection_list[start_idx : start_idx + ps]
            paged_response = {
                "page": p,
                "page_size": ps,
                "total_pages": total_pages,
            }
        else:
            detection_list = detection_list[:2000]

        response = {
            "total_detections": total_count,
            "age_distribution": dict(age_counts),
            "hourly_activity": hourly_data,
            "daily_activity": daily_activity,
            "call_types": dict(call_type_counts),
            "all_call_types": dict(all_call_type_counts),
            "intents": dict(intent_counts),
            "detections": detection_list,
            "scatter_sample": scatter_sample,
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
        }
        response.update(paged_response)
        return response
    except Exception as e:
        logger.error("Failed to fetch crow stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch crow stats: {e}")


@router.get("/data/audio/history")
def get_audio_history(
    days: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: User = Depends(current_active_user),
):
    """Get audio motion detection history from the database."""
    try:
        db = DetectionDB()

        if start_date:
            start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_time = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_time = datetime.now(timezone.utc)
        else:
            days = days or 1
            start_time = datetime.now(timezone.utc) - timedelta(days=days)
            end_time = datetime.now(timezone.utc)

        detections = db.query(
            detection_type="audio.motion",
            start_time=start_time,
            end_time=end_time,
            limit=100000,
        )

        hourly_counts: Dict[int, int] = {}
        for h in range(24):
            hourly_counts[h] = 0
        channel_counts: Dict[str, int] = {}
        results = []
        for det in detections:
            hourly_counts[det.timestamp.hour] = hourly_counts.get(det.timestamp.hour, 0) + 1
            metadata = det.metadata or {}
            channel_id = metadata.get("channel_id") or str(det.channel or "unknown")
            channel_counts[channel_id] = channel_counts.get(channel_id, 0) + 1
            context_val = None
            if det.context is not None:
                ctx = det.context
                context_val = (
                    ctx.model_dump(mode="json") if hasattr(ctx, "model_dump") else dict(ctx)
                )
            results.append(
                {
                    "timestamp": det.timestamp.isoformat(),
                    "channel_id": channel_id,
                    "channel": det.channel,
                    "duration_seconds": metadata.get("duration_seconds"),
                    "peak_energy_db": metadata.get("peak_energy_db"),
                    "audio_clip_path": det.audio_clip_path,
                    "context": context_val,
                    "source_event_id": det.source_event_id,
                }
            )

        hourly_activity = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]

        return {
            "detections": results,
            "count": len(results),
            "hourly_activity": hourly_activity,
            "channel_activity": channel_counts,
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch audio history", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch audio history: {e}")


# ===== Audio Playback API =====


class PlaybackRequest(BaseModel):
    """Audio playback request model."""

    sound_name: str
    repeat_count: int = Field(default=1, ge=1, le=10)
    pause_between: float = Field(default=0.0, ge=0.0, le=60.0)


class PlaybackResponse(BaseModel):
    """Audio playback response model."""

    success: bool
    message: str


@router.get("/audio/playback/sounds")
def get_available_sounds(user: User = Depends(current_active_user)):
    """Get list of available sounds for playback."""
    try:
        from orpheus_common.audio import get_sound_registry

        registry = get_sound_registry()
        sounds = registry.list_sounds()

        return {
            "sounds": sounds,
            "count": len(sounds),
        }
    except Exception as e:
        logger.exception("Failed to get sound list", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to get sound list: {e}")


@router.post("/audio/playback/play", response_model=PlaybackResponse)
def play_sound(request: PlaybackRequest, user: User = Depends(current_active_user)):
    """Request playback of a sound via MQTT."""
    if not _mqtt_client:
        raise HTTPException(
            status_code=503,
            detail="MQTT client not connected. Cannot send playback request.",
        )

    try:
        # Publish playback request to MQTT
        playback_message = {
            "sound_name": request.sound_name,
            "repeat_count": request.repeat_count,
            "pause_between": request.pause_between,
        }

        _mqtt_client.publish(
            "orpheus/audio/playback/request",
            playback_message,
            qos=1,
        )

        logger.info(
            "Playback request sent",
            sound_name=request.sound_name,
            repeat_count=request.repeat_count,
            pause_between=request.pause_between,
        )

        return PlaybackResponse(
            success=True,
            message=f"Playback request sent for '{request.sound_name}'",
        )

    except Exception as e:
        logger.exception("Failed to send playback request", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to send playback request: {e}")
