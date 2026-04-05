"""Orpheus Dashboard - Wildlife Monitoring Status Interface

This is the diagnostic dashboard for the Orpheus wildlife monitoring system.
It provides real-time status of system health, hardware, and services.

Architecture:
- FastAPI backend serving JSON APIs + static HTML/JS frontend
- Browser fetches data via REST endpoints and renders UI
- Each endpoint provides specific system status information

Current Status: MVP - Basic system health only
Next: Hardware validation layer (cameras, audio, bluetooth)
"""

from collections import deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import psutil
import subprocess
import shutil
import os
import threading
import asyncio
from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel
from fastapi.responses import StreamingResponse
from orpheus_common.hardware.storage import get_storage_hardware_info
from orpheus_common.system.health import get_data_storage_usage
from orpheus_common.mqtt import MQTTClient
from orpheus_common.storage import (
    get_video_path,
    parse_timelapse_filename,
    tier_sort_key,
)
from orpheus_common.logging import setup_logging, get_logger
from orpheus_common.detection import DetectionDB
import concurrent.futures
from datetime import datetime, timedelta, timezone


if "OrpheusConfig" not in globals():
    # Import lazily so tests that patch orpheus_dashboard.main.OrpheusConfig survive reloads
    from orpheus_common import OrpheusConfig  # type: ignore


# Configure logging using centralized setup_logging
setup_logging("orpheus-dashboard", level="INFO")
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage MQTT client lifecycle."""
    global _mqtt_client

    # Startup
    try:
        _mqtt_client = MQTTClient(
            broker_host=config.mqtt.broker_host,
            broker_port=config.mqtt.broker_port,
            client_id="orpheus-dashboard",
            keepalive=config.mqtt.keepalive,
        )
        _mqtt_client.connect()
        _mqtt_client.subscribe(
            topic_pattern="orpheus/system/audio/health",
            callback=_on_audio_health_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/system/video/health",
            callback=_on_video_health_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/audio/motion/events",
            callback=_on_audio_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/video/motion/events",
            callback=_on_video_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/detection/bird/events",
            callback=_on_bird_detection_message,
        )
        _mqtt_client.subscribe(
            topic_pattern="orpheus/detection/crow/events",
            callback=_on_crow_detection_message,
        )
        logger.info(
            "Connected to MQTT and subscribed to audio/video health, "
            "detection, bird, and crow updates"
        )
    except Exception as e:
        logger.warning("Failed to connect to MQTT for audio updates", error=str(e))
        _mqtt_client = None

    yield

    # Shutdown
    if _mqtt_client:
        try:
            _mqtt_client.disconnect()
            logger.info("Disconnected from MQTT")
        except Exception as e:
            logger.error("Error disconnecting from MQTT", error=str(e))
        _mqtt_client = None


app = FastAPI(
    title="Orpheus Dashboard",
    description="Wildlife Monitoring Station Status Interface",
    version="0.1.0",
    lifespan=lifespan,
)

# Get configuration singleton
config = OrpheusConfig.get_instance()
logger.info("Dashboard using configuration", config_source=config.config_source())

# Get camera registry from config
cameras = config.camera_registry()

# Cache for audio health status from MQTT
_audio_health_cache: Optional[Dict[str, Any]] = None
_audio_health_lock = threading.Lock()

# Cache for video health status from MQTT
_video_health_cache: Optional[Dict[str, Any]] = None
_video_health_lock = threading.Lock()

# Cache for audio motion detections
# Store last 20 detections total across all channels
_audio_detections_cache: deque = deque(maxlen=20)
# Store last detection per channel for quick summary
_audio_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_audio_detections_lock = threading.Lock()

# Cache for video motion detections
# Store last 20 detections total across all cameras
_video_detections_cache: deque = deque(maxlen=20)
# Store last detection per camera for quick summary
_video_detections_by_camera: Dict[str, Dict[str, Any]] = {}
_video_detections_lock = threading.Lock()

# Cache for bird detections
# Store last 50 detections total across all channels
_bird_detections_cache: deque = deque(maxlen=50)
# Store last detection per channel for quick summary
_bird_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_bird_detections_lock = threading.Lock()

# Cache for crow analysis detections
# Store last 50 crow analyses total across all channels
_crow_detections_cache: deque = deque(maxlen=50)
# Store last detection per channel for quick summary
_crow_detections_by_channel: Dict[str, Dict[str, Any]] = {}
_crow_detections_lock = threading.Lock()

# MQTT client for receiving audio/video health updates
_mqtt_client: Optional[MQTTClient] = None

# Determine absolute path to static directory (package-relative)
# This ensures tests running from different directories can still find static files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Mount static files (HTML, JS, CSS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _on_audio_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle audio health status messages from MQTT."""
    global _audio_health_cache
    with _audio_health_lock:
        _audio_health_cache = payload
        logger.info(
            "Updated audio health cache",
            running=payload.get("running"),
            channel_count=len(payload.get("channels", [])),
            xruns=payload.get("xrun", {}).get("total", 0),
        )


def _on_video_health_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle video health status messages from MQTT."""
    global _video_health_cache
    with _video_health_lock:
        _video_health_cache = payload
        logger.info(
            "Updated video health cache: running=%s, cameras=%d",
            payload.get("running"),
            len(payload.get("cameras", [])),
        )


def _on_audio_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle audio motion detection messages from MQTT."""
    with _audio_detections_lock:
        # Add to the global deque (maintains max 20)
        _audio_detections_cache.append(payload)

        # Update per-channel last detection
        channel_id = payload.get("channel_id", "unknown")
        _audio_detections_by_channel[channel_id] = payload

        logger.info(
            "Audio detection: channel=%s, duration=%.2fs, peak=%.1fdB",
            channel_id,
            payload.get("duration_seconds", 0),
            payload.get("peak_energy_db", 0),
        )


def _on_video_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle video motion detection messages from MQTT."""
    with _video_detections_lock:
        # Add to the global deque (maintains max 20)
        _video_detections_cache.append(payload)

        # Update per-camera last detection
        camera_id = payload.get("camera_id", "unknown")
        _video_detections_by_camera[camera_id] = payload

        logger.info(
            "Video detection: camera=%s, duration=%.2fs, peak_motion=%.1f%%",
            camera_id,
            payload.get("duration_seconds", 0),
            payload.get("peak_motion_value", 0),
        )


def _on_bird_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle bird detection messages from MQTT."""
    try:
        with _bird_detections_lock:
            # Add to the global deque (maintains max 50)
            _bird_detections_cache.append(payload)

            # Update per-channel last detection
            channel_id = payload.get("channel_id", "unknown")
            _bird_detections_by_channel[channel_id] = payload

            # Count detections
            num_detections = len(payload.get("detections", []))
            species_list = ", ".join(
                [
                    d.get("species_common", "Unknown")
                    for d in payload.get("detections", [])
                ]
            )

            logger.info(
                "Bird detection: channel=%s, event_id=%s, species=[%s], count=%d",
                channel_id,
                payload.get("event_id", "unknown"),
                species_list,
                num_detections,
            )
    except Exception as e:
        logger.error(
            "Failed to process bird detection message: topic=%s, error=%s",
            topic,
            str(e),
            exc_info=True,
        )


def _on_crow_detection_message(topic: str, payload: Dict[str, Any]) -> None:
    """Handle crow detection messages from MQTT."""
    try:
        with _crow_detections_lock:
            # Add to the global deque (maintains max 50)
            _crow_detections_cache.append(payload)

            # Update per-channel last detection
            channel_id = payload.get("channel_id", "unknown")
            _crow_detections_by_channel[channel_id] = payload

            # Extract detection info from the correct format
            detection = payload.get("detection", {})
            species = detection.get("species", "unknown")
            call_type = detection.get("call_type", "unknown")
            quality_score = detection.get("quality_score", 0.0)
            attributes = detection.get("attributes", {})

            logger.info(
                "Crow detection: channel=%s, event_id=%s, species=%s, call_type=%s, quality=%.2f, attributes=%s",
                channel_id,
                payload.get("event_id", "unknown"),
                species,
                call_type,
                quality_score,
                attributes,
            )
    except Exception as e:
        logger.error(
            "Failed to process crow detection message: topic=%s, error=%s",
            topic,
            str(e),
            exc_info=True,
        )


class HealthResponse(BaseModel):
    """System health metrics"""

    status: str
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    uptime_seconds: int


class ServiceStatus(BaseModel):
    """Individual service status"""

    name: str
    status: str  # "running", "stopped", "unknown"
    reason: str


class ServicesResponse(BaseModel):
    """All services status"""

    services: List[ServiceStatus]


@app.get("/")
async def root():
    """Serve the main dashboard HTML page"""
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/bird-insights")
async def bird_insights():
    """Serve the bird insights visualization page"""
    return FileResponse(os.path.join(STATIC_DIR, "bird-insights.html"))


@app.get("/crow-insights")
async def crow_insights():
    """Serve the crow insights visualization page"""
    return FileResponse(os.path.join(STATIC_DIR, "crow-insights.html"))


@app.get("/api/config")
def get_config():
    """Get frontend configuration."""
    return {"poll_interval": config.dashboard_poll_interval()}


@app.get("/api/health", response_model=HealthResponse)
def get_health():
    """
    Get current system health metrics.

    This actually works - uses psutil to read real system stats.
    Returns CPU, memory, disk usage and system uptime.
    """
    import time

    boot_time = psutil.boot_time()
    uptime = int(time.time() - boot_time)

    return HealthResponse(
        status="ok",
        cpu_percent=round(psutil.cpu_percent(interval=1), 1),
        memory_percent=round(psutil.virtual_memory().percent, 1),
        disk_percent=round(psutil.disk_usage("/").percent, 1),
        uptime_seconds=uptime,
    )


@app.get("/api/system/storage/data")
def get_storage_data():
    """Get storage usage for the external data drive."""
    return get_data_storage_usage()


@app.get("/api/services/status", response_model=ServicesResponse)
def get_services_status():
    """
    Get status of all Orpheus services.
    Queries systemctl for actual status.
    """
    service_names = config.dashboard_services()

    services_status = []

    # Find systemctl executable
    # The systemd service definition restricts PATH, so we might need to find it explicitly
    systemctl_path = shutil.which("systemctl")
    logger.info("Locating systemctl", systemctl_path=systemctl_path)

    if not systemctl_path:
        for path in ["/bin/systemctl", "/usr/bin/systemctl"]:
            if os.path.exists(path):
                systemctl_path = path
                logger.info(
                    "Found systemctl at fallback path", systemctl_path=systemctl_path
                )
                break
            else:
                logger.debug("Checked fallback path: not found", path=path)

    if not systemctl_path:
        logger.warning("systemctl executable not found in PATH or fallback locations")

    for name in service_names:
        if not systemctl_path:
            # Handle local dev environment where systemctl is missing
            if name == "orpheus-dashboard":
                status = "running"
                reason = "Running in local dev mode (systemctl not found)"
            else:
                status = "unknown"
                reason = "Systemctl not available (checked PATH, /bin, /usr/bin)"

            services_status.append(
                ServiceStatus(name=name, status=status, reason=reason)
            )
            continue

        try:
            logger.debug("Checking service", service_name=name)
            result = subprocess.run(
                [systemctl_path, "is-active", f"{name}.service"],
                capture_output=True,
                text=True,
                timeout=2,
            )

            logger.debug(
                f"Service {name} return code: {result.returncode}, stdout: {result.stdout.strip()}"
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


@app.get("/api/services/{service_name}/logs/tail")
async def stream_service_logs(service_name: str):
    """Stream logs for a specific service using journalctl."""

    async def log_generator():
        """Yields log lines from journalctl, handling stdout and stderr concurrently."""

        service_allowlist = config.dashboard_services()

        if service_name not in service_allowlist:
            error_msg = f"Error: Invalid service name '{service_name}'. Must be one of {service_allowlist}"

            logger.error("Invalid service name provided", service_name=service_name)

            yield error_msg.encode("utf-8")

            return

        sudo_path = shutil.which("sudo") or "/usr/bin/sudo"

        journalctl_path = shutil.which("journalctl") or "/usr/bin/journalctl"

        command = [
            sudo_path,
            "-n",  # Non-interactive mode for sudo
            journalctl_path,
            "-u",
            f"{service_name}.service",
            "-f",
            "-n",
            "100",
            "--no-pager",
        ]

        logger.info("Streaming logs", command=" ".join(command))

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        except FileNotFoundError:
            logger.error("Could not find command", command=command[0])

            yield f"Error: Could not execute '{command[0]}'. File not found.".encode(
                "utf-8"
            )

            return

        # Queue to merge stdout and stderr

        queue = asyncio.Queue()

        async def stream_reader(stream, stream_name):
            """Reads from a stream and puts lines into the queue."""

            if not stream:
                await queue.put((stream_name, None))

                return

            while True:
                line = await stream.readline()

                if not line:
                    break

                await queue.put((stream_name, line))

            # Signal that this stream is done

            await queue.put((stream_name, None))

        # Start concurrent readers

        stdout_task = asyncio.create_task(stream_reader(process.stdout, "stdout"))

        stderr_task = asyncio.create_task(stream_reader(process.stderr, "stderr"))

        finished_streams = 0

        try:
            while finished_streams < 2:
                stream_name, line = await queue.get()

                if line is None:
                    finished_streams += 1

                    continue

                if stream_name == "stderr":
                    logger.warning(
                        "Log stream stderr",
                        service_name=service_name,
                        output=line.decode("utf-8").strip(),
                    )

                yield line

        except asyncio.CancelledError:
            logger.info("Log stream cancelled by client", service_name=service_name)

        finally:
            # Clean up reader tasks

            stdout_task.cancel()

            stderr_task.cancel()

            # Terminate the process

            if process.returncode is None:
                try:
                    process.terminate()

                    await process.wait()

                    logger.info(
                        "Terminated log stream process", service_name=service_name
                    )

                except ProcessLookupError:
                    pass  # Process already finished

            logger.info("Log streaming finished", service_name=service_name)

    return StreamingResponse(log_generator(), media_type="text/plain")


@app.get("/api/cameras")
def get_cameras():
    """Get status of all configured cameras."""
    # Run checks in parallel to avoid blocking and reduce total latency
    # Use configured poll interval for cache TTL (converted to seconds)
    ttl = config.dashboard_poll_interval() / 1000.0
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = list(
            executor.map(lambda c: c.get_health_status(ttl_seconds=ttl), cameras)
        )
    return results


@app.get("/api/cameras/{camera_name}/snapshot")
def get_camera_snapshot(camera_name: str):
    """Get cached snapshot from specific camera."""
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


@app.get("/api/hardware/storage")
def get_storage_hardware():
    """Get hardware status of storage devices."""
    return get_storage_hardware_info()


@app.get("/api/diagnostics/audio")
def get_audio_diagnostics():
    """
    Get audio system health diagnostics.

    Returns real-time status of audio hardware from the audio agent via MQTT.
    The audio agent publishes health updates every 5 seconds which are cached here.

    Gracefully handles if audio system isn't running or MQTT is unavailable.
    """
    global _audio_health_cache

    try:
        with _audio_health_lock:
            if _audio_health_cache:
                # Return cached data from MQTT
                return _audio_health_cache
            else:
                # No data received yet from MQTT
                return {
                    "running": False,
                    "message": "Waiting for audio health data from agent (via MQTT)",
                    "xrun": {"total": 0},
                    "channels": [],
                    "hardware": {},
                    "timing": {},
                    "system": {},
                }
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


@app.get("/api/diagnostics/video")
def get_video_diagnostics():
    """
    Get video system health diagnostics.

    Returns real-time status of video hardware from the video agent via MQTT.
    The video agent publishes health updates every 5 seconds which are cached here.

    Gracefully handles if video system isn't running or MQTT is unavailable.
    """
    global _video_health_cache

    try:
        with _video_health_lock:
            if _video_health_cache:
                # Return cached data from MQTT
                return _video_health_cache
            else:
                # No data received yet from MQTT, fall back to detection-based status
                with _video_detections_lock:
                    # Get list of cameras that have sent detections
                    active_cameras = list(_video_detections_by_camera.keys())

                    # Build camera status list
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

                        # Track most recent detection
                        # ISO 8601 timestamps are lexicographically comparable when properly formatted
                        if timestamp and (
                            not last_detection_time or timestamp > last_detection_time
                        ):
                            last_detection_time = timestamp

                    # Check MQTT connection
                    mqtt_connected = (
                        _mqtt_client is not None and _mqtt_client.is_connected
                    )

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


@app.get("/api/diagnostics/audio/detections")
def get_audio_detections():
    """
    Get recent audio motion detections from all channels.

    Returns:
    - summary: Per-channel last detection (for quick status cards)
    - history: Last 20 detections across all channels (most recent first)
    - mqtt_connected: Whether MQTT is connected

    Gracefully handles if no detections have been received yet.
    """
    try:
        with _audio_detections_lock:
            # Build per-channel summary (channels 1-4)
            summary = {}
            for channel_id in ["1", "2", "3", "4"]:
                if channel_id in _audio_detections_by_channel:
                    summary[channel_id] = _audio_detections_by_channel[channel_id]
                else:
                    summary[channel_id] = None

            # Get history as list (most recent first)
            history = list(reversed(_audio_detections_cache))

            # Check MQTT connection status
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


@app.get("/api/diagnostics/video/detections")
def get_video_detections():
    """
    Get recent video motion detections from all cameras.

    Returns:
    - summary: Per-camera last detection (for quick status cards)
    - history: Last 20 detections across all cameras (most recent first)
    - mqtt_connected: Whether MQTT is connected

    Gracefully handles if no detections have been received yet.
    """
    try:
        with _video_detections_lock:
            # Build per-camera summary (orpheus-eye-1 through orpheus-eye-4)
            summary = {}
            for camera_id in [
                "orpheus-eye-1",
                "orpheus-eye-2",
                "orpheus-eye-3",
                "orpheus-eye-4",
            ]:
                if camera_id in _video_detections_by_camera:
                    summary[camera_id] = _video_detections_by_camera[camera_id]
                else:
                    summary[camera_id] = None

            # Get history as list (most recent first)
            history = list(reversed(_video_detections_cache))

            # Check MQTT connection status
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


@app.get("/api/diagnostics/video/clips/{camera_id}")
def get_video_clips(camera_id: str):
    """
    Get list of available video clips for a specific camera.

    Returns clip metadata including filename, timestamp, and size.
    Clips are stored in /mnt/data/video/motion/{camera_id}/
    """
    try:
        video_path = get_video_path(category="video_motion")
        camera_path = video_path / camera_id

        if not camera_path.exists():
            return {"clips": [], "error": None}

        clips = []
        for clip_file in sorted(camera_path.glob("*.mp4"), reverse=True)[
            :50
        ]:  # Last 50 clips
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
                logger.warning("Failed to stat clip", clip_file=clip_file, error=str(e))

        return {"clips": clips, "error": None}
    except Exception as e:
        logger.error(
            "Failed to get video clips for camera", camera_id=camera_id, error=str(e)
        )
        return {"clips": [], "error": str(e)}


@app.get("/api/diagnostics/video/snapshots/status")
def get_snapshot_timelapse_status():
    """
    Get snapshot and timelapse status for all cameras.

    Returns status information for cameras with snapshot/timelapse configuration:
    - last_snapshot_time: ISO timestamp of most recent snapshot
    - snapshot_count: Number of snapshots today
    - last_timelapse_time: ISO timestamp of most recent timelapse
    - timelapse_count: Number of timelapses today
    - config: Snapshot and timelapse configuration for each camera
    """
    try:
        from pathlib import Path

        storage_base = Path(config.storage.base_path)
        snapshot_base = storage_base / "video" / "snapshots"
        timelapse_base = storage_base / "video" / "timelapses"

        # Get today's date in YYYY.MM.DD format
        today_str = datetime.now(timezone.utc).strftime("%Y.%m.%d")
        today_snapshot_dir = snapshot_base / today_str
        today_timelapse_dir = timelapse_base / today_str

        results = []

        for camera in cameras:
            camera_status = {
                "camera_name": camera.name,
                "enabled": camera.enabled,
                "snapshots_configured": camera.snapshots is not None,
                "timelapses_configured": camera.timelapses is not None
                and len(camera.timelapses) > 0,
                "last_snapshot": None,
                "snapshot_count_today": 0,
                "last_timelapse": None,
                "timelapse_count_today": 0,
                "snapshot_config": None,
                "timelapse_config": None,
            }

            # Get snapshot info
            if camera.snapshots:
                camera_status["snapshot_config"] = {
                    "interval": camera.snapshots.interval
                }

                # Find snapshots for this camera
                if today_snapshot_dir.exists():
                    snapshot_pattern = f"*.{camera.name}.jpg"
                    snapshots = list(today_snapshot_dir.glob(snapshot_pattern))
                    camera_status["snapshot_count_today"] = len(snapshots)

                    if snapshots:
                        # Get most recent snapshot
                        latest_snapshot = max(
                            snapshots, key=lambda p: p.stat().st_mtime
                        )
                        camera_status["last_snapshot"] = datetime.fromtimestamp(
                            latest_snapshot.stat().st_mtime, tz=timezone.utc
                        ).isoformat()

            # Get timelapse info
            if camera.timelapses:
                camera_status["timelapse_config"] = [
                    {
                        "label": getattr(tl, "label", ""),
                        "start_time": tl.start_time,
                        "lookback_window": tl.lookback_window,
                        "sampling_interval": tl.sampling_interval,
                        "retention_days": tl.retention_days,
                        "clip_duration": tl.clip_duration,
                        "timezone": getattr(tl, "timezone", "UTC"),
                    }
                    for tl in camera.timelapses
                ]

                # Find timelapses for this camera (match any .mp4 containing camera name)
                if today_timelapse_dir.exists():
                    timelapse_pattern = f"*{camera.name}*.mp4"
                    timelapses = list(today_timelapse_dir.glob(timelapse_pattern))
                    camera_status["timelapse_count_today"] = len(timelapses)

                    if timelapses:
                        # Get most recent timelapse
                        latest_timelapse = max(
                            timelapses, key=lambda p: p.stat().st_mtime
                        )
                        camera_status["last_timelapse"] = datetime.fromtimestamp(
                            latest_timelapse.stat().st_mtime, tz=timezone.utc
                        ).isoformat()

            results.append(camera_status)

        return {
            "cameras": results,
            "date": today_str,
            "snapshot_base_path": str(snapshot_base),
            "timelapse_base_path": str(timelapse_base),
        }
    except Exception as e:
        logger.error("Failed to get snapshot/timelapse status", error=str(e))
        return {
            "cameras": [],
            "error": str(e),
        }


@app.get("/api/video/snapshots/{camera_name}")
def get_camera_snapshots(camera_name: str, date: str = None, limit: int = 50):
    """
    Get list of snapshots for a specific camera.

    Args:
        camera_name: The camera name
        date: Optional date in YYYY.MM.DD format (defaults to today)
        limit: Maximum number of snapshots to return (default 50)

    Returns:
        List of snapshot metadata including filename, timestamp, and size.
    """
    try:
        from pathlib import Path

        # Validate camera name to prevent path traversal
        if ".." in camera_name or "/" in camera_name:
            raise HTTPException(status_code=400, detail="Invalid camera name")

        storage_base = Path(config.storage.base_path)

        # Use today's date if not specified
        if not date:
            date = datetime.now(timezone.utc).strftime("%Y.%m.%d")

        # Validate date format
        if not date or len(date) != 10 or date.count(".") != 2:
            raise HTTPException(
                status_code=400, detail="Invalid date format. Use YYYY.MM.DD"
            )

        snapshot_dir = storage_base / "video" / "snapshots" / date

        if not snapshot_dir.exists():
            return {"snapshots": [], "date": date, "camera": camera_name}

        # Find snapshots for this camera
        snapshot_pattern = f"*.{camera_name}.jpg"
        snapshots = []

        for snapshot_file in sorted(snapshot_dir.glob(snapshot_pattern), reverse=True)[
            :limit
        ]:
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
                        "download_url": f"/api/video/snapshots/{camera_name}/{date}/{snapshot_file.name}",
                    }
                )
            except Exception as e:
                logger.warning(
                    "Failed to stat snapshot", path=str(snapshot_file), error=str(e)
                )

        return {
            "snapshots": snapshots,
            "date": date,
            "camera": camera_name,
            "count": len(snapshots),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get snapshots", camera=camera_name, error=str(e))
        return {"snapshots": [], "error": str(e)}


@app.get("/api/video/snapshots/{camera_name}/{date}/{filename:path}")
def serve_snapshot_file(camera_name: str, date: str, filename: str):
    """
    Serve a snapshot image file.

    Args:
        camera_name: The camera name
        date: Date in YYYY.MM.DD format
        filename: The snapshot filename

    Returns:
        The JPEG image file
    """
    from pathlib import Path

    # Validate inputs to prevent path traversal
    if ".." in camera_name or "/" in camera_name:
        raise HTTPException(status_code=400, detail="Invalid camera name")
    if ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid date")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    storage_base = Path(config.storage.base_path).resolve()
    snapshots_base = (storage_base / "video" / "snapshots").resolve()
    snapshot_path = (snapshots_base / date / filename).resolve()

    # Security: Ensure resolved path is within the allowed directory (prevents symlink attacks)
    # Use is_relative_to() for robust path containment check (Python 3.9+)
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


@app.get("/api/video/timelapses/{camera_name}")
def get_camera_timelapses(camera_name: str, date: str = None, limit: int = 50):
    """
    Get list of timelapse videos for a specific camera.

    Args:
        camera_name: The camera name
        date: Optional date in YYYY.MM.DD format (defaults to all recent)
        limit: Maximum number of timelapses to return (default 50)

    Returns:
        List of timelapse metadata including filename, timestamp, size, and parsed metadata.
        Results are grouped by tier (24h, 1h, 30m, 10m) then sorted by time within each tier.
    """
    try:
        from pathlib import Path

        # Validate camera name to prevent path traversal
        if ".." in camera_name or "/" in camera_name:
            raise HTTPException(status_code=400, detail="Invalid camera name")

        storage_base = Path(config.storage.base_path)
        timelapse_base = storage_base / "video" / "timelapses"

        if not timelapse_base.exists():
            return {"timelapses": [], "camera": camera_name}

        timelapses = []

        # If date specified, only search that date
        if date:
            date_dirs = (
                [timelapse_base / date] if (timelapse_base / date).exists() else []
            )
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

            for timelapse_file in sorted(
                date_dir.glob(timelapse_pattern), reverse=True
            ):
                if len(timelapses) >= limit:
                    break

                try:
                    stat = timelapse_file.stat()

                    # Parse filename to extract metadata
                    parsed = parse_timelapse_filename(timelapse_file.name)

                    timelapse_info = {
                        "filename": timelapse_file.name,
                        "date": date_str,
                        "camera": camera_name,
                        "size_bytes": stat.st_size,
                        "size_mb": round(stat.st_size / (1024 * 1024), 2),
                        "modified_time": stat.st_mtime,
                        "timestamp_iso": datetime.fromtimestamp(
                            stat.st_mtime, tz=timezone.utc
                        ).isoformat(),
                        "download_url": f"/api/video/timelapses/{camera_name}/{date_str}/{timelapse_file.name}",
                        # Parsed metadata (may be None for legacy format)
                        "label": parsed.label if parsed else None,
                        "tier": parsed.tier if parsed else None,
                        "tier_display": parsed.tier_display if parsed else None,
                        "lookback": parsed.lookback if parsed else None,
                    }
                    timelapses.append(timelapse_info)
                except Exception as e:
                    logger.warning(
                        "Failed to stat timelapse",
                        path=str(timelapse_file),
                        error=str(e),
                    )

            if len(timelapses) >= limit:
                break

        # Sort by tier (24h first, then 1h, 30m, 10m) then by time within each tier
        def sort_key(tl):
            tier = tl.get("tier") or "tlX"
            # Sort by tier first, then by timestamp descending
            return (tier_sort_key(tier), -tl.get("modified_time", 0))

        timelapses.sort(key=sort_key)

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


@app.get("/api/video/timelapses/{camera_name}/{date}/{filename:path}")
def serve_timelapse_file(camera_name: str, date: str, filename: str):
    """
    Serve a timelapse video file.

    Args:
        camera_name: The camera name
        date: Date in YYYY.MM.DD format
        filename: The timelapse filename

    Returns:
        The MP4 video file
    """
    from pathlib import Path

    # Validate inputs to prevent path traversal
    if ".." in camera_name or "/" in camera_name:
        raise HTTPException(status_code=400, detail="Invalid camera name")
    if ".." in date or "/" in date:
        raise HTTPException(status_code=400, detail="Invalid date")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    storage_base = Path(config.storage.base_path).resolve()
    timelapses_base = (storage_base / "video" / "timelapses").resolve()
    timelapse_path = (timelapses_base / date / filename).resolve()

    # Security: Ensure resolved path is within the allowed directory (prevents symlink attacks)
    # Use relative_to() for robust path containment check (Python 3.9+)
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


@app.get("/api/diagnostics/bird/detections")
def get_bird_detections():
    """
    Get recent bird detections from all channels.

    Returns:
    - summary: Per-channel last detection (for quick status cards)
    - history: Last 50 detections across all channels (most recent first)
    - mqtt_connected: Whether MQTT is connected

    Gracefully handles if no detections have been received yet.
    """
    try:
        with _bird_detections_lock:
            # Build per-channel summary (channels 1-4), mapping audio_clip_path to clip_path for frontend compatibility
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

            # Get history as list (most recent first), mapping audio_clip_path to clip_path
            history = []
            for det in reversed(_bird_detections_cache):
                det = dict(det)
                if "audio_clip_path" in det:
                    det["clip_path"] = det["audio_clip_path"]
                history.append(det)

            # Check MQTT connection status
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


@app.get("/api/diagnostics/crow/detections")
def get_crow_detections():
    """
    Get recent crow analysis results from all channels.

    Returns:
    - summary: Per-channel last crow analysis (for quick status cards)
    - history: Last 50 crow analyses across all channels (most recent first)
    - mqtt_connected: Whether MQTT is connected

    Gracefully handles if no analyses have been received yet.
    """
    try:
        with _crow_detections_lock:
            # Build per-channel summary (channels 1-4)
            summary = {}
            for channel_id in ["1", "2", "3", "4"]:
                if channel_id in _crow_detections_by_channel:
                    summary[channel_id] = _crow_detections_by_channel[channel_id]
                else:
                    summary[channel_id] = None

            # Get history as list (most recent first)
            history = list(reversed(_crow_detections_cache))

            # Check MQTT connection status
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


@app.get("/api/audio/clips/{channel_id}/{filename:path}")
def get_audio_clip(channel_id: str, filename: str):
    """
    Serve an audio clip file from the audio_motion storage directory.

    Args:
        channel_id: The channel ID (1-4)
        filename: The clip filename (e.g., 20251201T211427.340286Z.flac)

    Returns:
        The audio file with appropriate content type
    """
    # Validate channel_id to prevent path traversal
    if channel_id not in ["1", "2", "3", "4"]:
        raise HTTPException(status_code=400, detail="Invalid channel ID")

    # Validate filename to prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Build the full path to the clip
    # Clips are stored at: /data/orpheus/audio/audio_motion/<channel>/<filename>
    data_root = os.environ.get("ORPHEUS_DATA_ROOT", "/data/orpheus")
    clip_path = os.path.join(data_root, "audio", "audio_motion", channel_id, filename)

    if not os.path.exists(clip_path):
        raise HTTPException(status_code=404, detail="Clip not found")

    # Determine content type based on file extension
    if filename.endswith(".flac"):
        media_type = "audio/flac"
    elif filename.endswith(".wav"):
        media_type = "audio/wav"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        clip_path,
        media_type=media_type,
        filename=filename,
    )


@app.get("/api/video/clips/{camera_id}/{filename:path}")
def get_video_clip(camera_id: str, filename: str):
    """
    Serve a video clip file from the video_motion storage directory.

    Args:
        camera_id: The camera ID (e.g., "orpheus-eye-1")
        filename: The clip filename (e.g., 20251201T211427.340286Z.mp4)

    Returns:
        The video file with appropriate content type
    """
    # Validate camera_id to prevent path traversal
    valid_cameras = ["orpheus-eye-1", "orpheus-eye-2", "orpheus-eye-3", "orpheus-eye-4"]
    if camera_id not in valid_cameras:
        raise HTTPException(status_code=400, detail="Invalid camera ID")

    # Validate filename to prevent path traversal
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Build the full path to the clip using storage helper
    video_path = get_video_path(category="video_motion")
    clip_path = video_path / camera_id / filename

    if not clip_path.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    # Determine content type based on file extension
    if filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".avi"):
        media_type = "video/x-msvideo"
    else:
        media_type = "application/octet-stream"

    return FileResponse(
        str(clip_path),
        media_type=media_type,
        filename=filename,
    )


@app.get("/api/debug/config")
def get_debug_config():
    """Get runtime configuration for debugging (shows actual config that agents use)."""
    # Use the enhanced get_debug_safe_values which now includes runtime defaults
    debug_values = config.get_debug_safe_values()

    # Update the config.source to indicate it includes runtime defaults
    if (
        "orpheus_config" in debug_values
        and "config.source" in debug_values["orpheus_config"]
    ):
        debug_values["orpheus_config"]["config.source"] = (
            f"Runtime config (YAML + defaults + env overrides) from {config.config_source()}"
        )

    return debug_values


# ===== Audio Playback API =====


class PlaybackRequest(BaseModel):
    """Audio playback request model."""

    sound_name: str
    repeat_count: int = 1
    pause_between: float = 0.0


class PlaybackResponse(BaseModel):
    """Audio playback response model."""

    success: bool
    message: str


@app.get("/api/audio/playback/sounds")
def get_available_sounds():
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


# ===== Data Visualization API Endpoints =====

# Non-bird sounds to filter out (BirdNET noise classifications)
NON_BIRD_SOUNDS = {
    "Human whistle",
    "Human vocal",
    "Human non-vocal",
    "Siren",
    "Fireworks",
    "Engine",
    "Dog",
    "Power tools",
    "Car horn",
    "Alarm",
    # Add lowercase versions for case-insensitive matching
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


@app.get("/api/data/birds/history")
def get_bird_history(days: int = None, start_date: str = None, end_date: str = None):
    """
    Get bird detection history for scatter plot visualization.

    Returns detections with timestamp, confidence, and species.
    Used for Time vs. Confidence scatter plot, color-coded by species.

    Filters out non-bird sounds like human voices, sirens, engines, etc.

    Args:
        days: Number of days to look back (default: 7, ignored if start_date provided)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        List of detection records with timestamp, species, and confidence
    """
    try:
        db = DetectionDB()

        # Parse date range
        if start_date:
            start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_time = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_time = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_time = datetime.now(timezone.utc) - timedelta(days=days)
            end_time = datetime.now(timezone.utc)

        # Query all bird detections in the time range
        detections = db.query(
            detection_type="species.detected",
            start_time=start_time,
            end_time=end_time,
            limit=100000,  # Match crow endpoint limit
        )

        # Format data for frontend charting, filtering out non-bird sounds
        results = []
        filtered_count = 0
        for det in detections:
            species_common = det.species_common or det.species_code or ""
            species_code = det.species_code or ""

            # Skip non-bird sounds
            if species_common in NON_BIRD_SOUNDS or species_code in NON_BIRD_SOUNDS:
                filtered_count += 1
                continue

            results.append(
                {
                    "timestamp": det.timestamp.isoformat(),
                    "species_code": det.species_code,
                    "species_common": det.species_common or det.species_code,
                    "confidence": det.confidence,
                    "channel": det.channel,
                }
            )

        logger.info(
            "Bird history query complete",
            total_detections=len(detections),
            birds_returned=len(results),
            non_bird_filtered=filtered_count,
            start_date=start_time.date().isoformat(),
            end_date=end_time.date().isoformat(),
        )

        return {
            "detections": results,
            "count": len(results),
            "filtered_count": filtered_count,
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch bird history", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch bird history: {e}"
        )


@app.get("/api/data/birds/daily")
def get_bird_daily_counts(
    days: int = None, start_date: str = None, end_date: str = None
):
    """
    Get daily bird detection counts for histogram visualization.

    Returns daily counts grouped by species.
    Used for stacked histogram showing sightings per day.

    Filters out non-bird sounds like human voices, sirens, engines, etc.

    Args:
        days: Number of days to look back (default: 7, ignored if start_date provided)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        Daily counts grouped by date and species
    """
    try:
        db = DetectionDB()

        # Parse date range
        if start_date:
            start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_time = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_time = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_time = datetime.now(timezone.utc) - timedelta(days=days)
            end_time = datetime.now(timezone.utc)

        # Query all bird detections in the time range
        detections = db.query(
            detection_type="species.detected",
            start_time=start_time,
            end_time=end_time,
            limit=100000,  # Higher limit for aggregation
        )

        # Group by date and species, filtering out non-bird sounds
        from collections import defaultdict

        daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        filtered_count = 0

        for det in detections:
            species = det.species_common or det.species_code or "Unknown"

            # Skip non-bird sounds
            if species in NON_BIRD_SOUNDS:
                filtered_count += 1
                continue

            # Extract date (YYYY-MM-DD) from timestamp
            date_str = det.timestamp.date().isoformat()
            daily_counts[date_str][species] += 1

        # Convert to list format for frontend
        results = []
        for date_str in sorted(daily_counts.keys()):
            date_data = {"date": date_str}
            date_data.update(daily_counts[date_str])
            results.append(date_data)

        # Get list of all species for the legend
        all_species = set()
        for date_data in daily_counts.values():
            all_species.update(date_data.keys())

        logger.info(
            "Bird daily counts query complete",
            total_detections=len(detections),
            non_bird_filtered=filtered_count,
            unique_species=len(all_species),
            start_date=start_time.date().isoformat(),
            end_date=end_time.date().isoformat(),
        )

        return {
            "daily_counts": results,
            "species": sorted(all_species),
            "filtered_count": filtered_count,
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch bird daily counts", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch bird daily counts: {e}"
        )


@app.get("/api/data/non-birds/daily")
def get_non_bird_daily_counts(
    days: int = None, start_date: str = None, end_date: str = None
):
    """
    Get daily non-bird sound detection counts for histogram visualization.

    Returns daily counts of non-bird sounds (human activity, sirens, vehicles, etc.)
    that were filtered from bird detection data.

    Args:
        days: Number of days to look back (default: 7, ignored if start_date provided)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        Daily counts grouped by date and sound type
    """
    try:
        db = DetectionDB()

        # Parse date range
        if start_date:
            start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_time = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_time = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_time = datetime.now(timezone.utc) - timedelta(days=days)
            end_time = datetime.now(timezone.utc)

        # Query all detections in the time range
        detections = db.query(
            detection_type="species.detected",
            start_time=start_time,
            end_time=end_time,
            limit=100000,
        )

        # Group by date and non-bird sound type
        from collections import defaultdict

        daily_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for det in detections:
            species = det.species_common or det.species_code or "Unknown"

            # Only include non-bird sounds
            if species not in NON_BIRD_SOUNDS:
                continue

            # Extract date (YYYY-MM-DD) from timestamp
            date_str = det.timestamp.date().isoformat()
            daily_counts[date_str][species] += 1

        # Convert to list format for frontend
        results = []
        for date_str in sorted(daily_counts.keys()):
            date_data = {"date": date_str}
            date_data.update(daily_counts[date_str])
            results.append(date_data)

        # Get list of all sound types for the legend
        all_sounds = set()
        for date_data in daily_counts.values():
            all_sounds.update(date_data.keys())

        logger.info(
            "Non-bird daily counts query complete",
            total_non_bird_detections=sum(
                sum(d.values()) for d in daily_counts.values()
            ),
            unique_sound_types=len(all_sounds),
            start_date=start_time.date().isoformat(),
            end_date=end_time.date().isoformat(),
        )

        return {
            "daily_counts": results,
            "sound_types": sorted(all_sounds),
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch non-bird daily counts", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch non-bird daily counts: {e}"
        )


@app.get("/api/data/crows/stats")
def get_crow_stats(days: int = None, start_date: str = None, end_date: str = None):
    """
    Get crow detection statistics for dashboard visualization.

    Returns aggregated statistics including:
    - Age distribution (adult/juvenile counts)
    - Hourly activity patterns
    - Intent classifications (if available)
    - Call type distribution

    Args:
        days: Number of days to look back (default: 7, ignored if start_date provided)
        start_date: Start date in YYYY-MM-DD format (optional)
        end_date: End date in YYYY-MM-DD format (optional, defaults to today)

    Returns:
        Aggregated crow statistics
    """
    try:
        db = DetectionDB()

        # Parse date range
        if start_date:
            start_time = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
            if end_date:
                end_time = datetime.fromisoformat(end_date).replace(
                    hour=23, minute=59, second=59, tzinfo=timezone.utc
                )
            else:
                end_time = datetime.now(timezone.utc)
        else:
            days = days or 7
            start_time = datetime.now(timezone.utc) - timedelta(days=days)
            end_time = datetime.now(timezone.utc)

        # Query all crow detections (detection_type="crow" from crow detection agent)
        detections = db.query(
            detection_type="crow",
            start_time=start_time,
            end_time=end_time,
            limit=100000,
        )

        # Initialize counters
        from collections import defaultdict

        age_counts: Dict[str, int] = defaultdict(int)
        hourly_counts: Dict[int, int] = defaultdict(int)
        call_type_counts: Dict[str, int] = defaultdict(int)
        intent_counts: Dict[str, int] = defaultdict(int)

        # Aggregate statistics
        for det in detections:
            # Extract hour for time-of-day analysis
            hour = det.timestamp.hour
            hourly_counts[hour] += 1

            # Parse metadata for age, call_type, intent
            metadata = det.metadata or {}

            # Age distribution - check attributes dict inside metadata
            attributes = metadata.get("attributes", {})
            age = attributes.get("age", "unknown") if attributes else "unknown"
            age_counts[age] += 1

            # Call type - stored at metadata level
            call_type = metadata.get("call_type") or "unknown"
            call_type_counts[call_type] += 1

            # Intent (if available) - check in attributes
            intent = attributes.get("intent", "unknown") if attributes else "unknown"
            if intent != "unknown":
                intent_counts[intent] += 1

        # Format hourly data as list for charting
        hourly_data = [{"hour": h, "count": hourly_counts[h]} for h in range(24)]

        return {
            "total_detections": len(detections),
            "age_distribution": dict(age_counts),
            "hourly_activity": hourly_data,
            "call_types": dict(call_type_counts),
            "intents": dict(intent_counts),
            "start_date": start_time.date().isoformat(),
            "end_date": end_time.date().isoformat(),
        }
    except Exception as e:
        logger.error("Failed to fetch crow stats", error=str(e))
        raise HTTPException(status_code=500, detail=f"Failed to fetch crow stats: {e}")


@app.post("/api/audio/playback/play", response_model=PlaybackResponse)
def play_sound(request: PlaybackRequest):
    """Request playback of a sound."""
    if not _mqtt_client:
        raise HTTPException(
            status_code=503,
            detail="MQTT client not connected. Cannot send playback request.",
        )

    # Validate parameters
    if request.repeat_count < 1:
        raise HTTPException(status_code=400, detail="repeat_count must be >= 1")

    if request.pause_between < 0:
        raise HTTPException(status_code=400, detail="pause_between must be >= 0")

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
            f"Playback request sent: {request.sound_name}, "
            f"repeat={request.repeat_count}, pause={request.pause_between}s"
        )

        return PlaybackResponse(
            success=True,
            message=f"Playback request sent for '{request.sound_name}'",
        )

    except Exception as e:
        logger.exception("Failed to send playback request", error=str(e))
        raise HTTPException(
            status_code=500, detail=f"Failed to send playback request: {e}"
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8081)
