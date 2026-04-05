"""
Amcrest IP camera implementation.

Supports Amcrest IP5M-B1186EW-AI-V3 and compatible models with HTTP API
and RTSP streaming capabilities.
"""

import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

import requests
from requests.auth import HTTPDigestAuth

from orpheus_common.hardware.base import Camera
from orpheus_common.logging import get_logger

logger = get_logger(__name__)


class AmcrestCamera(Camera):
    """
    Amcrest camera implementation with HTTP API and RTSP support.

    Features:
    - Network connectivity checks via ping
    - HTTP API validation
    - Snapshot capture with caching
    - RTSP stream validation
    - System information retrieval
    """

    _snapshot_cache = {}  # {camera_name: {"data": bytes, "timestamp": float, "size": int}}

    def __init__(
        self,
        name: str,
        host: str,
        model: str,
        username: str,
        password: str,
        snapshots: Optional[Any] = None,
        timelapses: Optional[Any] = None,
        enabled: bool = True,
    ):
        """
        Initialize Amcrest camera instance.

        Args:
            name: Camera identifier (e.g., "north", "south")
            host: Hostname or IP address
            model: Camera model number
            username: Authentication username
            password: Authentication password
            snapshots: Optional SnapshotConfig for periodic snapshot capture
            timelapses: Optional list of TimelapseConfig for timelapse generation
            enabled: Whether the camera is enabled (default True)
        """
        super().__init__(name, host, model, username, password, snapshots, timelapses, enabled)

    def check_network(self) -> dict[str, Any]:
        """Ping camera to check network connectivity."""
        try:
            start_time = time.time()

            # Platform-specific ping arguments
            if sys.platform == "darwin":
                # macOS: -t is timeout in seconds
                cmd = ["ping", "-c", "1", "-t", "2", self.host]
            else:
                # Linux: -W is timeout in seconds
                ping_cmd = shutil.which("ping") or "/bin/ping" or "/usr/bin/ping"
                cmd = [ping_cmd, "-c", "1", "-W", "2", self.host]

            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2.1,
                check=True,
            )
            latency = (time.time() - start_time) * 1000
            return {"ok": True, "latency_ms": round(latency, 2), "error": None}

        except subprocess.TimeoutExpired:
            logger.warning("Network check timed out", camera_name=self.name, host=self.host)
            return {"ok": False, "latency_ms": 0, "error": "Timeout"}
        except subprocess.CalledProcessError as e:
            logger.warning(
                f"Network check failed for {self.name} ({self.host}): Ping returned {e.returncode}"
            )
            return {"ok": False, "latency_ms": 0, "error": "Host unreachable"}
        except Exception as e:
            logger.error("Network check error", camera_name=self.name, host=self.host, error=str(e))
            return {"ok": False, "latency_ms": 0, "error": str(e)}

    def check_http_api(self) -> dict[str, Any]:
        """Check if HTTP API is accessible."""
        url = f"http://{self.host}/cgi-bin/magicBox.cgi?action=getSystemInfo"
        try:
            start_time = time.time()
            response = requests.get(
                url, auth=HTTPDigestAuth(self.username, self.password), timeout=3
            )
            response.raise_for_status()
            latency = (time.time() - start_time) * 1000
            return {"ok": True, "response_time_ms": round(latency, 2), "error": None}
        except Exception as e:
            logger.error("HTTP API check failed", camera_name=self.name, error=str(e))
            return {"ok": False, "response_time_ms": 0, "error": str(e)}

    def capture_snapshot(self) -> dict[str, Any]:
        """Capture and cache a snapshot image."""
        # Check cache (5 second TTL)
        cache = self._snapshot_cache.get(self.name)
        if cache and (time.time() - cache["timestamp"] < 5):
            return {
                "ok": True,
                "size_bytes": cache["size"],
                "cached_at": datetime.fromtimestamp(cache["timestamp"], tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z"),
                "image_data": cache["data"],
                "error": None,
            }

        url = f"http://{self.host}/cgi-bin/snapshot.cgi"
        try:
            response = requests.get(
                url, auth=HTTPDigestAuth(self.username, self.password), timeout=3
            )
            response.raise_for_status()
            data = response.content

            # Validate JPEG (starts with FF D8)
            if not data.startswith(b"\xff\xd8"):
                return {
                    "ok": False,
                    "size_bytes": len(data),
                    "cached_at": "",
                    "image_data": None,
                    "error": "Invalid JPEG header",
                }

            # Check minimum size (10KB)
            if len(data) < 10 * 1024:
                return {
                    "ok": False,
                    "size_bytes": len(data),
                    "cached_at": "",
                    "image_data": None,
                    "error": "Image too small",
                }

            # Update cache
            self._snapshot_cache[self.name] = {
                "data": data,
                "timestamp": time.time(),
                "size": len(data),
            }

            return {
                "ok": True,
                "size_bytes": len(data),
                "cached_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "image_data": data,
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "size_bytes": 0,
                "cached_at": "",
                "image_data": None,
                "error": str(e),
            }

    def check_rtsp_stream(self) -> dict[str, Any]:
        """Verify RTSP stream is accessible."""
        rtsp_url = (
            f"rtsp://{self.username}:{self.password}@{self.host}:554/"
            f"cam/realmonitor?channel=1&subtype=0"
        )

        try:
            start_time = time.time()

            # Find ffprobe executable
            ffprobe_cmd = shutil.which("ffprobe") or "/usr/bin/ffprobe"

            # Use ffprobe to check stream
            cmd = [
                ffprobe_cmd,
                "-v",
                "error",
                "-rtsp_transport",
                "tcp",
                "-i",
                rtsp_url,
                "-show_format",
            ]

            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=True,
            )

            latency = (time.time() - start_time) * 1000
            return {"ok": True, "connection_time_ms": round(latency, 2), "error": None}

        except subprocess.TimeoutExpired:
            logger.warning("RTSP check timed out", camera_name=self.name)
            return {"ok": False, "connection_time_ms": 0, "error": "Timeout"}
        except subprocess.CalledProcessError:
            logger.warning("RTSP check failed (stream unreachable)", camera_name=self.name)
            return {"ok": False, "connection_time_ms": 0, "error": "Stream unreachable"}
        except FileNotFoundError:
            logger.error("ffprobe not found - RTSP check failed")
            return {"ok": False, "connection_time_ms": 0, "error": "ffprobe not found"}
        except Exception as e:
            logger.error("RTSP check error", camera_name=self.name, error=str(e))
            return {"ok": False, "connection_time_ms": 0, "error": str(e)}

    def get_system_info(self) -> dict[str, Any]:
        """Get camera system information."""
        url = f"http://{self.host}/cgi-bin/magicBox.cgi?action=getSystemInfo"
        try:
            response = requests.get(
                url, auth=HTTPDigestAuth(self.username, self.password), timeout=3
            )
            response.raise_for_status()

            # Parse response (key=value lines)
            info = {}
            for line in response.text.splitlines():
                if "=" in line:
                    key, value = line.split("=", 1)
                    info[key.strip()] = value.strip()

            return {
                "ok": True,
                "firmware_version": info.get("appVersion", "Unknown"),
                "serial_number": info.get("serialNumber", "Unknown"),
                "uptime_seconds": 0,  # Amcrest doesn't easily give uptime
                "error": None,
            }
        except Exception as e:
            return {
                "ok": False,
                "firmware_version": "",
                "serial_number": "",
                "uptime_seconds": 0,
                "error": str(e),
            }

    def get_rtsp_url(self, channel: int = 1, subtype: int = 0) -> str:
        """
        Get RTSP stream URL for this camera.

        Args:
            channel: Camera channel (default 1)
            subtype: Stream subtype - 0=main, 1=sub (default 0)

        Returns:
            Complete RTSP URL
        """
        return (
            f"rtsp://{self.username}:{self.password}@{self.host}:554/"
            f"cam/realmonitor?channel={channel}&subtype={subtype}"
        )
