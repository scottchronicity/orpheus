"""Diagnostics and detection API endpoints.

Provides endpoints for audio/video diagnostics and detection history.
"""

import json
import re
import shutil
import subprocess
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from orpheus_common.detection import (
    BIRD_LIKE_AUDIOSET_MIDS,
    TaxonomyRef,
    TemporalInterval,
)
from orpheus_common.events import SpatiotemporalContext
from orpheus_common.logging import get_logger
from orpheus_common.storage import (
    get_audio_path,
    get_video_path,
    normalize_sensor_id,
)
from orpheus_common.utils.time import is_full_day, parse_hhmm, timestamp_in_window
from pydantic import BaseModel, Field

from orpheus_ui.api._date_range import resolve_date_range
from orpheus_ui.api._responses import even_sample, paginate, set_cache_control
from orpheus_ui.auth.backend import (
    current_active_user,
    current_user_or_token_param,
    require_role,
)
from orpheus_ui.auth.models import User
from orpheus_ui.db import get_detection_db

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["diagnostics"])

# Every camera id that may become a path component. Both the clip listing and the
# clip serving route check against this: the listing route once shipped without
# it, which let a traversal enumerate filenames outside the camera's directory.
VALID_CAMERAS = ("orpheus-eye-1", "orpheus-eye-2", "orpheus-eye-3", "orpheus-eye-4")
# Returned to the client in place of an exception message. The detail still goes
# to the service log; putting it in the response body hands a signed-in account
# filesystem paths and library internals it has no use for.
ERROR_OPAQUE = "unavailable - see the service log for detail"

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


@router.get("/diagnostics/bus")
def get_bus_diagnostics(user: User = Depends(current_active_user)) -> Dict[str, Any]:
    """Dispatch backpressure of the UI's own bus client: queue depth + total
    drop-oldest message drops, plus which subscriptions the broker has actually
    accepted. The drop counter is the only visibility an operator has into a
    slow subscriber silently shedding messages — the journald warning is
    rate-limited to every 1000th drop. ``subscriptions.pending`` non-empty while
    connected is the shape of a UI that looks live and is serving stale data.
    """
    bus = _mqtt_client
    stats_fn = getattr(bus, "dispatch_stats", None)
    if bus is None or not callable(stats_fn):
        return {"available": False}
    try:
        out: Dict[str, Any] = {"available": True, **stats_fn()}
    except Exception as e:
        logger.warning("bus dispatch stats unavailable", error=str(e))
        return {"available": False}
    sub_fn = getattr(bus, "subscription_status", None)
    if callable(sub_fn):
        try:
            out["subscriptions"] = sub_fn()
        except Exception as e:
            logger.warning("bus subscription status unavailable", error=str(e))
    return out


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

    # NOTE: audio.motion rows are NOT persisted here. The audio-motion AGENT
    # owns and persists its own stream (it's the chain root every downstream
    # classifier references) — see ADR 0012. This handler used to save the
    # row, but it minted a brand-new event_id on save, so the persisted
    # chain root never matched the event_id audio-motion published — which
    # every bird/audio/crow detection stored as its source_event_id /
    # root_event_id. That single ownership bug silently broke cross-classifier
    # correlation, entity clustering, lineage, and the root_event_id backfill.
    # The UI backend is presentation-only: it keeps the in-memory cache above
    # for the live levels display and does not write to DetectionDB.


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


# AudioSet machine_ids that count as "bird-like" for the audio-events vs
# bird-detection parity dashboard. The seed set is the single source of
# truth in orpheus-common (orpheus_common.detection.audioset_birds) so it
# can't drift from anything else that needs it; the cache + equivalence-
# graph expansion below layer on top of it. Intentionally permissive —
# this is COVERAGE scoring, distinct from the clade-precise identity bridge
# (orpheus_common.detection.taxonomy_bridge.same_source).


# Cross-classifier-identity §5 (step 15): the "bird-like AudioSet mids"
# set grows dynamically as auto-discovery learns equivalences. The
# hardcoded set above stays as the seed; we walk equivalent_taxa() from
# each seed to harvest any AudioSet refs the system has since learned
# are equivalent (or transitively reachable via IOC bridges).
#
# **TTL-based cache.** The UI backend runs in one process; the
# correlator's auto-discovery worker runs in a separate process and
# writes new equivalences to the shared SQLite file. The UI's in-process
# cache CANNOT be invalidated by the correlator. We use a short TTL so
# new equivalences become visible automatically within a few minutes
# without requiring a UI restart or a manual /equivalences/scan call.
#
# Explicit ``reset_bird_like_audioset_cache()`` is still respected for
# the same-process case (accept/reject via UI endpoints) — it just
# resets the timestamp so the next call recomputes immediately.
_BIRD_LIKE_CACHE_TTL_SECONDS = 300.0  # 5 minutes
_EXPANDED_BIRD_LIKE_CACHE: Optional[set[str]] = None
_EXPANDED_BIRD_LIKE_CACHE_AT: float = 0.0  # monotonic time of last compute
# Generation counter bumped by every reset(). Captured before a (lock-free) compute
# and re-checked at install time: if a reset() fired while we were computing, the
# snapshot is pre-reset/stale and must be DISCARDED rather than installed — otherwise
# the just-accepted equivalence that triggered the reset would be clobbered and the UI
# pinned to the old graph for the full TTL (the monotonic-time check alone can't catch
# this, since the compute's ``now`` predates the reset).
_EXPANDED_BIRD_LIKE_CACHE_GEN: int = 0
# Guards the compute / read / reset of the cache. Without it, the
# read path can observe ``_EXPANDED_BIRD_LIKE_CACHE = None`` mid-
# reset and call back into is_bird_like_audioset with ``in None``.
_EXPANDED_BIRD_LIKE_CACHE_LOCK = threading.Lock()


def _expanded_bird_like_audioset_mids() -> set[str]:
    """The hardcoded BIRD_LIKE_AUDIOSET_MIDS plus any AudioSet refs
    reachable from them through the equivalence graph."""
    global _EXPANDED_BIRD_LIKE_CACHE
    global _EXPANDED_BIRD_LIKE_CACHE_AT
    import time as _time  # noqa: PLC0415

    now = _time.monotonic()
    with _EXPANDED_BIRD_LIKE_CACHE_LOCK:
        if (
            _EXPANDED_BIRD_LIKE_CACHE is not None
            and (now - _EXPANDED_BIRD_LIKE_CACHE_AT) < _BIRD_LIKE_CACHE_TTL_SECONDS
        ):
            return _EXPANDED_BIRD_LIKE_CACHE
        gen_at_start = _EXPANDED_BIRD_LIKE_CACHE_GEN  # snapshot the generation

    # Recompute outside the lock — the equivalence DB walk can take
    # tens of milliseconds and we don't want to block readers on it.
    expanded = set(BIRD_LIKE_AUDIOSET_MIDS)
    try:
        # Lazy import to avoid importing orpheus_common.detection at module
        # load time (it touches the DB path).
        from orpheus_common.detection import (  # noqa: PLC0415
            TaxonomyEquivalenceDB,
            TaxonomyRef,
        )

        eq_db = TaxonomyEquivalenceDB()
        for mid in list(BIRD_LIKE_AUDIOSET_MIDS):
            seed = TaxonomyRef(namespace="audioset", id=mid)
            for eq in eq_db.equivalent_taxa(seed):
                if eq.namespace == "audioset":
                    expanded.add(eq.id)
    except Exception:
        # Equivalence DB unavailable / not yet initialised — fall back
        # to the seed set, which is fine.
        pass

    with _EXPANDED_BIRD_LIKE_CACHE_LOCK:
        # Re-take the lock for the install. Discard our snapshot if a reset() fired
        # during the compute (generation moved) — installing it would clobber the
        # just-accepted equivalence and pin the UI for the full TTL. Also keep any
        # fresher result another thread already installed (monotonic-time check).
        reset_during_compute = _EXPANDED_BIRD_LIKE_CACHE_GEN != gen_at_start
        if not reset_during_compute and (
            _EXPANDED_BIRD_LIKE_CACHE is None
            or (now - _EXPANDED_BIRD_LIKE_CACHE_AT) >= _BIRD_LIKE_CACHE_TTL_SECONDS
        ):
            _EXPANDED_BIRD_LIKE_CACHE = expanded
            _EXPANDED_BIRD_LIKE_CACHE_AT = now
            return expanded
        # A reset invalidated us (leave the cache cleared so the next call recomputes
        # post-reset) or a peer installed fresher — return the freshest available.
        return _EXPANDED_BIRD_LIKE_CACHE if _EXPANDED_BIRD_LIKE_CACHE is not None else expanded


def reset_bird_like_audioset_cache() -> None:
    """Bust the expanded-bird-like cache. Called when the equivalence
    graph has been updated (e.g. after an accept/reject) so the next
    bird-correlation query sees the new state. Bumps the generation so an
    in-flight compute can't reinstall a pre-reset snapshot."""
    global _EXPANDED_BIRD_LIKE_CACHE
    global _EXPANDED_BIRD_LIKE_CACHE_AT
    global _EXPANDED_BIRD_LIKE_CACHE_GEN
    with _EXPANDED_BIRD_LIKE_CACHE_LOCK:
        _EXPANDED_BIRD_LIKE_CACHE = None
        _EXPANDED_BIRD_LIKE_CACHE_AT = 0.0
        _EXPANDED_BIRD_LIKE_CACHE_GEN += 1


def is_bird_like_audioset(
    species_code: Optional[str], taxonomy_id: Optional[str]
) -> bool:
    """True if an audio.classified detection is bird-related.

    Used by /api/data/audio-events/bird-correlation to score parity with
    BirdNET. Accepts EITHER a Detection.species_code of the form
    ``audioset_<mid>`` OR a TaxonomyRef.id of the form ``<mid>``.

    Layer 3: the set is the hardcoded seed PLUS any AudioSet ref the
    equivalence graph has learned is in the same equivalence class
    (auto-discovery / human accept).
    """
    expanded = _expanded_bird_like_audioset_mids()
    if taxonomy_id and taxonomy_id in expanded:
        return True
    if species_code and species_code.startswith("audioset_"):
        return species_code[len("audioset_") :] in expanded
    return False


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
            "error": ERROR_OPAQUE,
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
            "error": ERROR_OPAQUE,
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
            "error": ERROR_OPAQUE,
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
            "error": ERROR_OPAQUE,
        }


@router.get("/diagnostics/video/clips/{camera_id}")
def get_video_clips(camera_id: str, user: User = Depends(current_active_user)):
    """Get list of available video clips for a specific camera."""
    if camera_id not in VALID_CAMERAS:
        raise HTTPException(status_code=400, detail="Invalid camera ID")

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
        return {"clips": [], "error": ERROR_OPAQUE}


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
            "error": ERROR_OPAQUE,
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
            "error": ERROR_OPAQUE,
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

    # Both the absolute (from-DB) and relative branches must contain to THIS
    # channel's clip directory — not merely to the data root. A stored absolute
    # path is still attacker-influenceable via the URL, and is_relative_to(
    # data_root) passes for any file under the root, users.db and the detections
    # DB included. Resolve, then require the narrow base for both.
    base_path = (get_audio_path(category="audio_motion") / normalized_channel_id).resolve()
    if Path(filename).is_absolute():
        clip_path = Path(filename).resolve()
    else:
        clip_path = (base_path / filename).resolve()

    # Use Path.is_relative_to (3.9+) — string-prefix matching is vulnerable to
    # /audio_motion/1 → /audio_motion/10 prefix confusion.
    if not clip_path.is_relative_to(base_path):
        raise HTTPException(status_code=400, detail="Invalid path: outside clip directory")

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
    if camera_id not in VALID_CAMERAS:
        raise HTTPException(status_code=400, detail="Invalid camera ID")

    # Contain to THIS camera's clip directory for both branches. A stored
    # absolute path is attacker-influenceable via the URL, and containing only
    # to the data root lets is_relative_to pass for any file under it (users.db,
    # the detections DB). Resolve, then require the narrow base.
    base_path = (get_video_path(category="video_motion") / camera_id).resolve()
    if Path(filename).is_absolute():
        clip_path = Path(filename).resolve()
    else:
        clip_path = (base_path / filename).resolve()

    # Use Path.is_relative_to (3.9+) — string-prefix matching is vulnerable to
    # prefix confusion.
    if not clip_path.is_relative_to(base_path):
        raise HTTPException(status_code=400, detail="Invalid path: outside clip directory")

    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    if filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".avi"):
        media_type = "video/x-msvideo"
    else:
        media_type = "application/octet-stream"

    return FileResponse(str(clip_path), media_type=media_type)


# ---------------------------------------------------------------------------
# Raw-row access for the history/stats aggregations
# ---------------------------------------------------------------------------
# The five history/stats endpoints below aggregate up to 100k rows per
# request. Building a Detection per row (Pydantic validation + JSON sidecar
# parsing for fields the endpoint never reads) dominates page-load cost at
# production row counts, so they consume DetectionDB.query_rows() (same
# filters/order/limit as query(), raw sqlite3.Rows) through these helpers,
# which replicate _row_to_detection's exact per-field transformations for
# JUST the fields the endpoints project — same classes, same round-trips, so
# legacy-row normalisation is identical. Defined ONCE here; the endpoints
# share them.


def _rval(row: Any, key: str) -> Any:
    """``row[key]`` tolerant of partial schemas (mirrors _row_to_detection)."""
    return row[key] if key in row.keys() else None


def _row_ts(row: Any) -> datetime:
    return datetime.fromisoformat(row["timestamp"])


def _row_metadata(row: Any) -> Dict[str, Any]:
    raw = _rval(row, "metadata")
    return json.loads(raw) if raw else {}


def _row_context_dump(row: Any) -> Optional[Dict[str, Any]]:
    raw = _rval(row, "event_metadata")
    if not raw:
        return None
    ctx = json.loads(raw).get("context")
    if isinstance(ctx, dict):
        # Same SpatiotemporalContext round-trip today's Detection path
        # applies, so legacy rows normalise identically.
        return SpatiotemporalContext(**ctx).model_dump(mode="json")
    return None


def _row_taxonomy_ref(row: Any) -> Optional[TaxonomyRef]:
    ns = _rval(row, "taxonomy_namespace")
    tid = _rval(row, "taxonomy_id")
    if ns and tid:
        return TaxonomyRef(namespace=ns, id=tid)
    return None


def _row_intervals_dump(row: Any) -> Optional[List[Dict[str, Any]]]:
    raw = _rval(row, "intervals_json")
    if not raw:
        return None
    return [
        TemporalInterval(**iv).model_dump(mode="json") for iv in json.loads(raw)
    ]


@router.get("/data/birds/history")
def get_bird_history(
    days: Optional[int] = Query(
        # No ge/le validation: the historical endpoints accepted any int (0/absent
        # -> the default window), so bounds here would 422 previously-valid calls.
        None,
        description="Rolling window size in days (0/absent = default window).",
    ),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    species: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: Optional[str] = None,
    # No ge/le validation on page/page_size: paginate() clamps server-side
    # (page floor 1, page_size to [1, 1000]) exactly as the historical inline
    # blocks did — request-level bounds would 422 previously-accepted values.
    page: Optional[int] = Query(None, description="1-indexed page number."),
    page_size: Optional[int] = Query(
        None, description="Rows per page. Required with page. Clamped to 1000."
    ),
    response: Response = None,  # type: ignore[assignment]
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
        db = get_detection_db()

        start_dt, end_dt = resolve_date_range(days, start_date, end_date, default_days=7)

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

        rows = db.query_rows(
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

        for row in rows:
            row_common = row["species_common"]
            row_code = row["species_code"]
            species_common = row_common or row_code or ""
            species_code = row_code or ""

            # Filter out non-bird sounds (human, noise, etc). Also drop
            # rows with NO usable label — ``is_bird_sound('')`` returns
            # True (empty string isn't in NON_BIRD_SOUNDS), so without
            # this empty-label guard a partial row would inflate the
            # bird stats.
            if not species_common and not species_code:
                filtered_count += 1
                continue
            if not is_bird_sound(species_common) or not is_bird_sound(species_code):
                filtered_count += 1
                continue

            ts = _row_ts(row)
            # Time-of-day filter (interpreted in user's tz) — applied before
            # species accumulation so stats reflect the final filtered set.
            if apply_time_window and not timestamp_in_window(
                ts, start_hhmm, end_hhmm, tz
            ):
                continue

            display_name = row_common or row_code or species_code
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

            hourly_counts[ts.hour] += 1
            species_counts[display_name] += 1

            context = _row_context_dump(row)

            # Cross-classifier-identity: surface the IOC scientific
            # name + taxonomy ref so the Birds UI can build external
            # species links (iNaturalist / Wikipedia / GBIF) without
            # hitting any third-party API.
            scientific_name = None
            taxonomy_payload = None
            taxonomy = _row_taxonomy_ref(row)
            if taxonomy is not None:
                taxonomy_payload = taxonomy.model_dump(mode="json")
                if taxonomy.namespace == "ioc":
                    scientific_name = taxonomy.id

            all_results.append(
                {
                    "timestamp": ts.isoformat(),
                    "species_code": row_code,
                    "species_common": row_common or row_code,
                    "species_scientific": scientific_name,
                    "taxonomy": taxonomy_payload,
                    "confidence": row["confidence"],
                    "channel": row["channel"],
                    "audio_clip_path": row["audio_clip_path"],
                    "context": context,
                    "source_event_id": row["source_event_id"],
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
        if isinstance(page, int) and isinstance(page_size, int):
            results, p, ps, total_pages = paginate(all_results, page, page_size)
            paged_response = {
                "page": p,
                "page_size": ps,
                "total_pages": total_pages,
            }
        else:
            results = all_results[:2000]

        # Evenly-distributed scatter sample (max 500 points spanning full range)
        sorted_asc = sorted(all_results, key=lambda x: x["timestamp"])
        scatter_sample = [
            {
                "timestamp": r["timestamp"],
                "species_code": r["species_code"],
                "species_common": r["species_common"],
                "confidence": r["confidence"],
            }
            for r in even_sample(sorted_asc)
        ]

        result = {
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
        result.update(paged_response)
        # 10s browser cache lets a fast tab-switch / quick refetch hit
        # the disk cache instead of re-running the per-row time-window
        # scan. With 30s react-query polling, every other poll is free.
        if response is not None:
            set_cache_control(response, max_age=10)
        return result
    except HTTPException:
        # A 400 from resolve_date_range (bad start_date/end_date) must escape
        # as-is; the bare ``except Exception`` below would re-wrap it as a 500.
        raise
    except Exception as e:
        logger.error("Failed to fetch bird history", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch bird history: {e}")


@router.get("/data/audio-events/history")
def get_audio_events_history(
    days: Optional[int] = Query(
        # No ge/le validation: the historical endpoints accepted any int (0/absent
        # -> the default window), so bounds here would 422 previously-valid calls.
        None,
        description="Rolling window size in days (0/absent = default window).",
    ),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    labels: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: Optional[str] = None,
    # No ge/le validation on page/page_size: paginate() clamps server-side
    # (page floor 1, page_size to [1, 1000]) exactly as the historical inline
    # blocks did — request-level bounds would 422 previously-accepted values.
    page: Optional[int] = Query(None, description="1-indexed page number."),
    page_size: Optional[int] = Query(
        None, description="Rows per page. Required with page. Clamped to 1000."
    ),
    response: Response = None,  # type: ignore[assignment]
    user: User = Depends(current_active_user),
):
    """Get audio-events detection history with server-side aggregated stats.

    Mirrors ``/data/birds/history`` but filters on
    ``detection_type="audio.classified"`` and accepts ALL labels (no
    is_bird_sound filter — that's the point of this stream).

    Query params:
      labels: pipe-separated label common names or AudioSet machine_ids
        to keep (case-insensitive). E.g. ``"Dog|Rain|/m/04rlf"``. Pipe
        instead of comma because AudioSet display names routinely
        contain literal commas (e.g. ``"Heart sounds, heartbeat"`` —
        AudioSet /m/03qc9zr); a comma-based parser would silently
        fragment such a single-label selection into the wrong filter.
        The frontend ``useUrlMultiSelect('label', {separator: '|'})``
        produces the same encoding. ``"Dog"`` alone (no separator)
        also works because ``"Dog".split("|") == ["Dog"]``.
      start_time, end_time: HH:MM time-of-day window (interpreted in `tz`).
      tz: IANA timezone name for interpreting start_time/end_time.
      page, page_size: when both provided, return the given 1-indexed slice
        instead of the legacy 2000-row cap; response adds page/page_size/
        total_pages.

    Per-detection fields include ``intervals`` (TemporalInterval list,
    seconds offset within the clip) and ``taxonomy`` (namespace+id) per
    ADR 0011.
    """
    try:
        db = get_detection_db()

        start_dt, end_dt = resolve_date_range(days, start_date, end_date, default_days=7)

        labels_allow: Optional[set] = None
        if labels:
            # ALWAYS split on pipe — never comma. A comma fallback would
            # silently break single-label selections of comma-bearing
            # AudioSet display names (the very case that motivated the
            # pipe separator in the first place). ``"Heart sounds,
            # heartbeat".split("|") == ["Heart sounds, heartbeat"]``,
            # which is correct. ``"Dog".split("|") == ["Dog"]`` also
            # works for the single-pipe-free case.
            tokens = labels.split("|")
            labels_allow = {
                lbl.strip().lower() for lbl in tokens if lbl.strip()
            }
            if not labels_allow:
                labels_allow = None

        start_hhmm = parse_hhmm(start_time)
        end_hhmm = parse_hhmm(end_time)
        apply_time_window = (
            start_hhmm is not None
            and end_hhmm is not None
            and not is_full_day(start_hhmm, end_hhmm)
        )

        rows = db.query_rows(
            detection_type="audio.classified",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )

        from collections import defaultdict

        hourly_counts: Dict[int, int] = defaultdict(int)
        label_counts: Dict[str, int] = defaultdict(int)
        all_label_counts: Dict[str, int] = defaultdict(int)
        all_results = []

        for row in rows:
            row_common = row["species_common"]
            row_code = row["species_code"]
            label_common = row_common or row_code or ""
            label_code = row_code or ""
            taxonomy = _row_taxonomy_ref(row)
            taxonomy_id = taxonomy.id if taxonomy else None

            ts = _row_ts(row)
            if apply_time_window and not timestamp_in_window(
                ts, start_hhmm, end_hhmm, tz
            ):
                continue

            display_name = label_common or label_code
            all_label_counts[display_name] += 1

            if labels_allow is not None:
                tax_match = taxonomy_id and taxonomy_id.lower() in labels_allow
                if (
                    label_common.lower() not in labels_allow
                    and label_code.lower() not in labels_allow
                    and display_name.lower() not in labels_allow
                    and not tax_match
                ):
                    continue

            hourly_counts[ts.hour] += 1
            label_counts[display_name] += 1

            context = _row_context_dump(row)
            intervals_payload = _row_intervals_dump(row)
            taxonomy_payload = (
                taxonomy.model_dump(mode="json") if taxonomy is not None else None
            )

            all_results.append(
                {
                    "timestamp": ts.isoformat(),
                    "species_code": row_code,
                    "species_common": row_common or row_code,
                    "confidence": row["confidence"],
                    "channel": row["channel"],
                    "audio_clip_path": row["audio_clip_path"],
                    "context": context,
                    "source_event_id": row["source_event_id"],
                    "intervals": intervals_payload,
                    "taxonomy": taxonomy_payload,
                }
            )

        total_count = len(all_results)
        hourly_activity = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]

        daily_counts: Dict[str, int] = defaultdict(int)
        for r in all_results:
            daily_counts[r["timestamp"][:10]] += 1
        daily_activity = [
            {"date": d, "count": daily_counts[d]} for d in sorted(daily_counts.keys())
        ]

        all_results.sort(key=lambda x: x["timestamp"], reverse=True)

        # Evenly-distributed scatter sample (max 500 points spanning the full
        # range). Mirrors /data/birds/history so the Audio Events page can
        # reuse the shared ConfidenceScatterChart. NOTE: this is an EVEN
        # sample across the whole window — the newest few detections often
        # aren't in it by design; it's a distribution view, not a live tail.
        sorted_asc = sorted(all_results, key=lambda x: x["timestamp"])
        scatter_sample = [
            {
                "timestamp": r["timestamp"],
                "species_code": r["species_code"],
                "species_common": r["species_common"],
                "confidence": r["confidence"],
            }
            for r in even_sample(sorted_asc)
        ]

        paged_response: Dict[str, Any] = {}
        if isinstance(page, int) and isinstance(page_size, int):
            results, p, ps, total_pages = paginate(all_results, page, page_size)
            paged_response = {
                "page": p,
                "page_size": ps,
                "total_pages": total_pages,
            }
        else:
            results = all_results[:2000]

        result = {
            "detections": results,
            "count": total_count,
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "scatter_sample": scatter_sample,
            "stats": {
                "total_count": total_count,
                "unique_label_count": len(label_counts),
                "hourly_activity": hourly_activity,
                "daily_activity": daily_activity,
                "label_distribution": dict(label_counts),
                "all_labels": dict(all_label_counts),
            },
        }
        result.update(paged_response)
        if response is not None:
            set_cache_control(response, max_age=10)
        return result
    except HTTPException:
        # Bad start_date/end_date -> resolve_date_range raised a 400; let it
        # through instead of the bare ``except`` re-wrapping it as a 500.
        raise
    except Exception as e:
        logger.error("Failed to fetch audio events history", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch audio events history: {e}"
        )


@router.get("/data/audio-events/bird-correlation")
def get_audio_events_bird_correlation(
    days: Optional[int] = Query(
        # No ge/le validation: the historical endpoints accepted any int (0/absent
        # -> the default window), so bounds here would 422 previously-valid calls.
        None,
        description="Rolling window size in days (0/absent = default window).",
    ),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: User = Depends(current_active_user),
):
    """Bird-detection parity dashboard for the audio-events agent.

    For each audio.motion event in the date range, asks two questions:
      Q1. Did the audio-events agent fire on a bird-like AudioSet label
          (see BIRD_LIKE_AUDIOSET_MIDS)?
      Q2. Did the bird-detection agent fire on any bird species?

    Returns per-day cohort counts and a parity ratio so the user can
    decide when audio-events is permissive enough to gate bird-detection
    behind. The gating threshold is ``parity_ratio >= 1.0`` over a few
    consecutive days — anything below 1.0 means audio-events is MISSING
    birds that BirdNET caught, which would be a regression if used as a
    gate.
    """
    try:
        db = get_detection_db()

        start_dt, end_dt = resolve_date_range(days, start_date, end_date, default_days=7)

        # Pull all three signal streams in the window (raw rows — this
        # endpoint reads plain columns only, no JSON sidecars at all).
        audio_motion = db.query_rows(
            detection_type="audio.motion",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )
        bird_detections = db.query_rows(
            detection_type="species.detected",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )
        audio_events = db.query_rows(
            detection_type="audio.classified",
            start_time=start_dt,
            end_time=end_dt,
            limit=100000,
        )

        # Group by root_event_id (the audio.motion event at the head of
        # the detection chain). Detection.root_event_id was added in
        # Layer 1.5 specifically so multi-hop chains
        # (audio-motion → audio-events → crow-detection, etc.)
        # correlate correctly. Using source_event_id only worked when
        # the bird/audio classifier was a DIRECT child of audio.motion;
        # for any intermediate hop the source_event_id points one level
        # up the chain instead of at the root, and the set-intersection
        # silently fails.
        # Fallback to source_event_id when root_event_id is NULL
        # (legacy rows pre-Layer-1.5 migration / before the backfill).
        from collections import defaultdict

        bird_caught: set = set()
        audio_caught: set = set()

        for row in bird_detections:
            src = _rval(row, "root_event_id") or row["source_event_id"]
            if not src:
                continue
            # Filter to actual birds (BirdNET sometimes labels non-birds).
            # Require AT LEAST one non-empty label that ``is_bird_sound``
            # accepts. ``is_bird_sound('')`` returns True (empty string
            # isn't in NON_BIRD_SOUNDS), so without this guard a row
            # with empty species_common AND empty species_code would
            # vacuously qualify and inflate the parity cohort.
            label_common = row["species_common"] or row["species_code"] or ""
            label_code = row["species_code"] or ""
            if not label_common and not label_code:
                continue
            if is_bird_sound(label_common) and is_bird_sound(label_code):
                bird_caught.add(src)

        for row in audio_events:
            src = _rval(row, "root_event_id") or row["source_event_id"]
            if not src:
                continue
            tax = _row_taxonomy_ref(row)
            taxonomy_id = tax.id if tax else None
            if is_bird_like_audioset(row["species_code"], taxonomy_id):
                audio_caught.add(src)

        # Per-day cohort counts.
        daily: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {
                "audio_motion_count": 0,
                "both": 0,
                "audio_events_only": 0,
                "birdnet_only": 0,
                "neither": 0,
            }
        )
        # Track missed clips (BirdNET caught a bird, audio-events did not)
        # — the actionable cohort for tuning the audio-events thresholds.
        birdnet_only_clips: List[Dict[str, Any]] = []

        for evt in audio_motion:
            src = evt["event_id"]
            evt_ts = _row_ts(evt)
            day = evt_ts.date().isoformat()
            bucket = daily[day]
            bucket["audio_motion_count"] += 1

            b = src in bird_caught
            a = src in audio_caught
            if a and b:
                bucket["both"] += 1
            elif a and not b:
                bucket["audio_events_only"] += 1
            elif b and not a:
                bucket["birdnet_only"] += 1
                if len(birdnet_only_clips) < 200:  # cap payload
                    birdnet_only_clips.append(
                        {
                            "audio_motion_event_id": src,
                            "timestamp": evt_ts.isoformat(),
                            "audio_clip_path": evt["audio_clip_path"],
                            "channel": evt["channel"],
                        }
                    )
            else:
                bucket["neither"] += 1

        daily_counts = [
            {
                "date": day,
                **counts,
            }
            for day, counts in sorted(daily.items())
        ]

        birdnet_caught_count = sum(d["both"] + d["birdnet_only"] for d in daily_counts)
        audio_events_caught_count = sum(
            d["both"] + d["audio_events_only"] for d in daily_counts
        )

        parity_ratio: Optional[float] = None
        if birdnet_caught_count > 0:
            parity_ratio = audio_events_caught_count / birdnet_caught_count

        ready_to_gate = parity_ratio is not None and parity_ratio >= 1.0

        return {
            "start_date": start_dt.date().isoformat(),
            "end_date": end_dt.date().isoformat(),
            "daily_counts": daily_counts,
            "summary": {
                "audio_motion_count": sum(d["audio_motion_count"] for d in daily_counts),
                "birdnet_caught_count": birdnet_caught_count,
                "audio_events_caught_count": audio_events_caught_count,
                "both_count": sum(d["both"] for d in daily_counts),
                "audio_events_only_count": sum(
                    d["audio_events_only"] for d in daily_counts
                ),
                "birdnet_only_count": sum(d["birdnet_only"] for d in daily_counts),
                "neither_count": sum(d["neither"] for d in daily_counts),
                "parity_ratio": parity_ratio,
                "ready_to_gate": ready_to_gate,
            },
            "birdnet_only_clips": birdnet_only_clips,
        }
    except HTTPException:
        # Bad start_date/end_date -> resolve_date_range raised a 400; let it
        # through instead of the bare ``except`` re-wrapping it as a 500.
        raise
    except Exception as e:
        logger.error("Failed to compute audio-events bird correlation", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to compute audio-events bird correlation: {e}",
        )


@router.get("/data/crows/stats")
def get_crow_stats(
    days: Optional[int] = Query(
        # No ge/le validation: the historical endpoints accepted any int (0/absent
        # -> the default window), so bounds here would 422 previously-valid calls.
        None,
        description="Rolling window size in days (0/absent = default window).",
    ),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    call_types: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    tz: Optional[str] = None,
    # No ge/le validation on page/page_size: paginate() clamps server-side
    # (page floor 1, page_size to [1, 1000]) exactly as the historical inline
    # blocks did — request-level bounds would 422 previously-accepted values.
    page: Optional[int] = Query(None, description="1-indexed page number."),
    page_size: Optional[int] = Query(
        None, description="Rows per page. Required with page. Clamped to 1000."
    ),
    response: Response = None,  # type: ignore[assignment]
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
        db = get_detection_db()

        start_dt, end_dt = resolve_date_range(days, start_date, end_date, default_days=7)

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

        rows = db.query_rows(
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

        for row in rows:
            metadata = _row_metadata(row)
            attributes = metadata.get("attributes", {})
            call_type = metadata.get("call_type") or "unknown"

            # Always track the full distribution so the frontend dropdown can
            # list every call_type present in the date range.
            all_call_type_counts[call_type] += 1

            if call_types_allow is not None and call_type.lower() not in call_types_allow:
                continue

            ts = _row_ts(row)
            if apply_time_window and not timestamp_in_window(
                ts, start_hhmm, end_hhmm, tz
            ):
                continue

            hour = ts.hour
            hourly_counts[hour] += 1
            daily_counts[ts.date().isoformat()] += 1

            age = attributes.get("age", "unknown") if attributes else "unknown"
            age_counts[age] += 1

            call_type_counts[call_type] += 1

            intent = attributes.get("intent", "unknown") if attributes else "unknown"
            if intent != "unknown":
                intent_counts[intent] += 1

            # Resolve channel from metadata if not in main field
            channel_val = row["channel"]
            if channel_val is None and metadata:
                channel_val = metadata.get("channel_id") or metadata.get("channel")

            age = attributes.get("age") if attributes else None
            context_val = _row_context_dump(row)
            detection_list.append(
                {
                    "timestamp": ts.isoformat(),
                    "confidence": row["confidence"],
                    "call_type": call_type,
                    "audio_clip_path": row["audio_clip_path"],
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
        scatter_sample = [
            {
                "timestamp": r["timestamp"],
                "call_type": r["call_type"],
                "confidence": r["confidence"],
            }
            for r in even_sample(sorted_asc)
        ]

        # Sort by timestamp descending (most-recent first) for the table
        detection_list.sort(key=lambda x: x["timestamp"], reverse=True)
        total_count = len(detection_list)

        # Pagination: opt-in via page+page_size. Otherwise preserve legacy 2000-row cap.
        paged_response: Dict[str, Any] = {}
        if isinstance(page, int) and isinstance(page_size, int):
            detection_list, p, ps, total_pages = paginate(
                detection_list, page, page_size
            )
            paged_response = {
                "page": p,
                "page_size": ps,
                "total_pages": total_pages,
            }
        else:
            detection_list = detection_list[:2000]

        result = {
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
        result.update(paged_response)
        # 10s browser cache — matches the sibling history endpoints
        # (/data/birds/history, /data/audio-events/history). Pages
        # poll /data/crows/stats every 30s, so every other poll lands
        # in cache without touching uvicorn.
        if response is not None:
            set_cache_control(response, max_age=10)
        return result
    except HTTPException:
        # Bad start_date/end_date -> resolve_date_range raised a 400; let it
        # through instead of the bare ``except`` re-wrapping it as a 500.
        raise
    except Exception as e:
        logger.error("Failed to fetch crow stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch crow stats: {e}")


@router.get("/data/audio/history")
def get_audio_history(
    days: Optional[int] = Query(
        # No ge/le validation: the historical endpoints accepted any int (0/absent
        # -> the default window), so bounds here would 422 previously-valid calls.
        None,
        description="Rolling window size in days (0/absent = default window).",
    ),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user: User = Depends(current_active_user),
):
    """Get audio motion detection history from the database."""
    try:
        db = get_detection_db()

        # NB: this endpoint's rolling default is 1 day (not 7 like the others).
        start_time, end_time = resolve_date_range(
            days, start_date, end_date, default_days=1
        )

        rows = db.query_rows(
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
        for row in rows:
            ts = _row_ts(row)
            hourly_counts[ts.hour] = hourly_counts.get(ts.hour, 0) + 1
            metadata = _row_metadata(row)
            channel_id = metadata.get("channel_id") or str(row["channel"] or "unknown")
            channel_counts[channel_id] = channel_counts.get(channel_id, 0) + 1
            context_val = _row_context_dump(row)
            results.append(
                {
                    "timestamp": ts.isoformat(),
                    "channel_id": channel_id,
                    "channel": row["channel"],
                    "duration_seconds": metadata.get("duration_seconds"),
                    "peak_energy_db": metadata.get("peak_energy_db"),
                    "audio_clip_path": row["audio_clip_path"],
                    "context": context_val,
                    "source_event_id": row["source_event_id"],
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
    except HTTPException:
        # Bad start_date/end_date -> resolve_date_range raised a 400; let it
        # through instead of the bare ``except`` re-wrapping it as a 500.
        raise
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
def play_sound(request: PlaybackRequest, user: User = Depends(require_role("admin"))):
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
