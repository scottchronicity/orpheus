"""GPU telemetry for /api/health: utilization, temperature and memory.

Read from the kernel's own files. A Jetson's GPU has no memory of its own: it
shares system RAM with the CPU, so memory is reported as that shared pool plus
what the PANNs worker's CUDA allocator holds (from the worker's own heartbeat),
never as dedicated VRAM. A host without these files reports
``available: false``.

Utilization is an average, not one reading: nvgpu's load counter is either
idle or close to 100% while a PANNs clip runs, so a single read shows 0 or
100 at random. A daemon thread reads it four times a second and the health check
reports the mean of the last 10 seconds (what tegrastats shows over its
interval).
"""

from __future__ import annotations

import collections
import glob
import os
import threading
import time
from typing import Any, Deque, Dict, Optional

# nvgpu's load, in tenths of a percent (what tegrastats shows as GR3D).
LOAD_PATHS = ("/sys/devices/gpu.0/load", "/sys/devices/platform/gpu.0/load")
THERMAL_ZONES = "/sys/class/thermal/thermal_zone*"
MIB = 1024 * 1024
SAMPLE_INTERVAL_SECONDS = 0.25
WINDOW_SECONDS = 10


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as fh:
            return fh.read().strip()
    except OSError:
        return None


def read_utilization(root: str = "") -> Optional[float]:
    """One instantaneous reading of the GPU load counter (percent)."""
    for path in LOAD_PATHS:
        raw = _read(root + path)
        if raw is not None and raw.isdigit():
            return round(min(int(raw), 1000) / 10, 1)
    return None


class UtilizationSampler:
    """Rolling mean of the GPU load counter, sampled by one daemon thread."""

    def __init__(self, root: str = "", interval: float = SAMPLE_INTERVAL_SECONDS,
                 window: float = WINDOW_SECONDS) -> None:
        self._root = root
        self._interval = interval
        self._samples: Deque[float] = collections.deque(maxlen=max(1, int(window / interval)))
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _run(self) -> None:
        while True:
            value = read_utilization(self._root)
            if value is not None:
                with self._lock:
                    self._samples.append(value)
            time.sleep(self._interval)

    def mean(self) -> Optional[float]:
        """The window's mean; starts sampling on first use. None without a GPU."""
        with self._lock:
            if self._thread is None:
                if read_utilization(self._root) is None:
                    return None
                self._thread = threading.Thread(
                    target=self._run, name="gpu-utilization", daemon=True
                )
                self._thread.start()
            samples = list(self._samples)
        if not samples:
            return read_utilization(self._root)
        return round(sum(samples) / len(samples), 1)


_sampler = UtilizationSampler()


def average_utilization() -> Optional[float]:
    return _sampler.mean()


def read_temperature(root: str = "") -> Optional[float]:
    for zone in sorted(glob.glob(root + THERMAL_ZONES)):
        kind = (_read(os.path.join(zone, "type")) or "").lower()
        if kind.startswith("gpu"):
            raw = _read(os.path.join(zone, "temp"))
            if raw is not None and raw.lstrip("-").isdigit():
                return round(int(raw) / 1000, 1)
    return None


def inference_memory(audio_events_health: Optional[Dict[str, Any]]) -> Dict[str, Optional[int]]:
    """CUDA memory the PANNs worker holds, from its last fresh heartbeat."""
    empty = {"inference_reserved_bytes": None, "inference_allocated_bytes": None}
    health = audio_events_health or {}
    if health.get("stale") or health.get("backend") != "gpu_worker":
        return empty
    runtime = (health.get("worker") or {}).get("runtime") or {}
    reserved, allocated = runtime.get("cuda_reserved_mib"), runtime.get("cuda_allocated_mib")
    if not isinstance(reserved, (int, float)):
        return empty
    return {
        "inference_reserved_bytes": int(reserved * MIB),
        "inference_allocated_bytes": (
            int(allocated * MIB) if isinstance(allocated, (int, float)) else None
        ),
    }


def gpu_info(
    total_bytes: int,
    available_bytes: int,
    audio_events_health: Optional[Dict[str, Any]],
    floor_mib: Optional[int],
    utilization: Optional[float],
    root: str = "",
) -> Dict[str, Any]:
    temperature = read_temperature(root)
    if utilization is None and temperature is None:
        return {"available": False}
    return {
        "available": True,
        "utilization_percent": utilization,
        "utilization_window_seconds": WINDOW_SECONDS,
        "temperature_c": temperature,
        "memory": {
            "shared": True,
            "total_bytes": total_bytes,
            "available_bytes": available_bytes,
            "inference_floor_bytes": int(floor_mib * MIB) if floor_mib else None,
            **inference_memory(audio_events_health),
        },
    }
